"""Application configuration loaded from environment variables."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

import certifi
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Environment(StrEnum):
    """Application environment."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


def load_environment() -> Environment:
    """Read $ENVIRONMENT, naming the accepted values when it holds something else."""
    name = os.environ.get("ENVIRONMENT", Environment.DEV)
    try:
        return Environment(name)
    except ValueError:
        accepted = ", ".join(Environment)
        raise ValueError(
            f"ENVIRONMENT={name!r} is not a valid environment; expected one of: {accepted}"
        ) from None


ENVIRONMENT: Environment = load_environment()
BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def get_env_file(env: Environment = ENVIRONMENT) -> Path:
    """Absolute, so the file is found whatever directory the process was started from."""
    name = ".env.example" if env == Environment.TEST else f".env.{env.value}"
    return BACKEND_ROOT / name


class BaseConfig(BaseSettings):
    """Base for the per-concern settings classes."""

    model_config = SettingsConfigDict(
        env_file=get_env_file(),
        env_ignore_empty=True,
        extra="ignore",
        validate_assignment=True,
    )


class AppConfig(BaseConfig):
    """Application configuration.

    BUILD_ID: which release is running, read from the image reference Fly sets on every
        machine, so it changes with each deploy and is shared by a release's machines.
    """

    ENVIRONMENT: Environment = ENVIRONMENT
    PROJECT_NAME: str = "RegRag"
    FRONTEND_URL: str = "http://localhost:5173"
    BUILD_ID: str = Field(default="local", validation_alias="FLY_IMAGE_REF")


class StorageBackend(StrEnum):
    """Where raw source documents are kept."""

    LOCAL = "local"
    R2 = "r2"


class StorageConfig(BaseConfig):
    """Which backend holds raw source documents, and where the local one keeps them."""

    STORAGE_BACKEND: StorageBackend = StorageBackend.LOCAL
    RAW_DATA_DIR: Path = PROJECT_ROOT / "data" / "raw"


class R2Config(BaseConfig):
    """Cloudflare R2 credentials, every field required so a half-configured bucket fails early."""

    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: str
    R2_SECRET_ACCESS_KEY: str
    R2_BUCKET: str

    @property
    def R2_ENDPOINT_URL(self) -> str:
        """The S3-compatible endpoint R2 serves this account's buckets on."""
        return f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


class SslMode(StrEnum):
    """libpq's sslmode values."""

    DISABLE = "disable"
    ALLOW = "allow"
    PREFER = "prefer"
    REQUIRE = "require"
    VERIFY_CA = "verify-ca"
    VERIFY_FULL = "verify-full"


def get_default_sslmode(env: Environment = ENVIRONMENT) -> SslMode | None:
    """Prod checks the server's certificate; the compose Postgres serves no TLS."""
    return SslMode.VERIFY_FULL if env is Environment.PROD else None


class PostgresConfig(BaseConfig):
    """PostgreSQL database configuration.

    DB_SSLMODE: how far the server's certificate is checked. Set it to verify-full in any
        env file that points DB_HOST at the prod database.
    """

    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASS: SecretStr = SecretStr("postgres")
    DB_NAME: str = "regrag"
    DB_SSLMODE: SslMode | None = get_default_sslmode()

    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 3
    DB_POOL_PRE_PING: bool = True
    DB_POOL_RECYCLE: int = 300
    DB_POOL_TIMEOUT: int = 30
    DB_CONNECT_TIMEOUT: int = 10
    DB_COMMAND_TIMEOUT: int = 30

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> URL:
        """What alembic and the app engine both connect with, its password masked when printed."""
        tls = {}
        if self.DB_SSLMODE:
            tls = {"sslmode": self.DB_SSLMODE.value, "sslrootcert": certifi.where()}
        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASS.get_secret_value(),
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
            query=tls,
        )

    @property
    def SQLALCHEMY_ENGINE_ARGS(self) -> dict[str, Any]:
        """Get SQLAlchemy engine arguments."""
        return {
            "pool_size": self.DB_POOL_SIZE,
            "max_overflow": self.DB_MAX_OVERFLOW,
            "pool_pre_ping": self.DB_POOL_PRE_PING,
            "pool_recycle": self.DB_POOL_RECYCLE,
            "pool_timeout": self.DB_POOL_TIMEOUT,
            "connect_args": {
                "connect_timeout": self.DB_CONNECT_TIMEOUT,
                "options": f"-c statement_timeout={self.DB_COMMAND_TIMEOUT * 1000}",
            },
        }


class RedisConfig(BaseConfig):
    """The Redis the rate limiter counts in, the compose service by default.

    REDIS_TIMEOUT: seconds to wait to connect or for a reply. A limiter check that waits
        longer than this lets the call through rather than hold it.
    """

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_TIMEOUT: float = Field(default=1.0, gt=0.0)


class RateLimitConfig(BaseConfig):
    """The chat rate limiter: an allowance per client id, and a ceiling per address behind it.

    RATE_LIMIT_ENABLED: the limiter's off switch. Tests switch it off.
    RATE_LIMIT_PER_CLIENT: questions one client id may ask inside the window, a burst
        of a few and then roughly one every 12s at the default.
    RATE_LIMIT_PER_IP: questions one address may ask inside the window, whatever ids it
        sends, so rotating ids buys nothing.
    RATE_LIMIT_WINDOW_SECONDS: the sliding window both limits count over.
    """

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_CLIENT: int = Field(default=5, ge=1)
    RATE_LIMIT_PER_IP: int = Field(default=20, ge=1)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)


EMBED_DIMENSIONS = 1024
"""Width of the document_chunks.embedding column: not a setting, changing it needs a migration."""


class ProviderConfig(BaseConfig):
    """One key per provider a model may name, under litellm's own variable names so the env
    file reads the same as it would for litellm itself. Empty is unset: the provider refuses
    the call.

    Every model the graph and the judge call is reached through OpenRouter, so a model swap
    stays a setting rather than an account. Voyage is named directly because OpenRouter
    serves no embedding or rerank endpoint."""

    VOYAGE_API_KEY: SecretStr = SecretStr("")
    OPENROUTER_API_KEY: SecretStr = SecretStr("")


class EmbeddingConfig(BaseConfig):
    """Voyage embedding configuration."""

    EMBED_MODEL: str = "voyage/voyage-4-lite"
    EMBED_TIMEOUT: int = 30


class ChatConfig(BaseConfig):
    """Chat model configuration for the chat graph.

    CHAT_MODEL: the model every node calls, at whichever provider it names; only the judge
        is set apart, so that a model does not grade its own habits.
    CHAT_TIMEOUT: seconds to wait for one model call, whichever node makes it.
    CHAT_MAX_TOKENS: the cap on one call's output.
    CHAT_SOURCES: search hits the answer draws on, each widened to its section.
    CHAT_CONTEXT_CHUNKS: the most chunks the widening may put in the prompt, a guardrail
        against a run of long articles rather than a target.
    CHAT_TEMPERATURE: at 0 the model takes its likeliest token every time, which is what an
        answer quoting law back wants. A model that refuses the parameter drops it instead.
    CHAT_THREAD_TURNS: the most answered turns a thread may hold, and so the history every
        follow-up call sees. The next question on a full thread is rejected.
    CHAT_DAILY_SPEND_CAP_USD: what the ledger may show spent over the last day before the
        next question is refused; a rolling day, so midnight brings no fresh budget. Must be
        positive: zero would refuse every question on an empty ledger, not switch the cap off.
    CHAT_CACHE_ENABLED: the answer cache's off switch, which serves a repeated first question
        without running the graph; tests switch it off.
    CHAT_CACHE_TTL_SECONDS: how long a cached answer is kept. A deploy, a changed setting or
        a moved corpus already retires every answer, so this bounds how long an answer is
        served over an unchanged corpus, and how long a dead key holds memory.
    CHAT_THINKING_ENABLED: whether the answer call reasons before it writes; the other nodes
        never do. Off by default to hold cost down, though on it lifted judged correctness 0.70
        to 0.86 and faithfulness 0.91 to 0.95 over two runs each, for about 2.7s and 30% more
        spend per answer (HEC-329). Anthropic requires a temperature of 1 while a model
        thinks, so CHAT_TEMPERATURE is ignored on this path. The budget is sent as
        Anthropic's own parameter, which litellm drops for any other provider rather than
        failing, so on a model that is not Anthropic's this setting does nothing at all.
    CHAT_THINKING_BUDGET: the most tokens the answer call may reason in, on top of
        CHAT_MAX_TOKENS; 1024 is Anthropic's floor, and 2048 scored no better.
    """

    CHAT_MODEL: str = "openrouter/google/gemini-2.5-flash"
    CHAT_TIMEOUT: int = 60
    CHAT_MAX_TOKENS: int = 2048
    CHAT_TEMPERATURE: float = Field(default=0.0, ge=0.0, le=1.0)
    CHAT_SOURCES: int = Field(default=5, ge=1)
    CHAT_CONTEXT_CHUNKS: int = Field(default=15, ge=1)
    CHAT_THREAD_TURNS: int = Field(default=5, ge=1)
    CHAT_DAILY_SPEND_CAP_USD: float = Field(default=5.0, gt=0.0)
    CHAT_CACHE_ENABLED: bool = True
    CHAT_CACHE_TTL_SECONDS: int = Field(default=7 * 24 * 3600, ge=1)
    CHAT_THINKING_ENABLED: bool = False
    CHAT_THINKING_BUDGET: int = Field(default=1024, ge=1024)


class AssessConfig(BaseConfig):
    """The assess ⇄ assess_tools loop, which grows the retrieved context before the answer.

    ASSESS_ENABLED: the loop's off switch; off, the graph answers from retrieval alone. On
        by default: it lifted expanded recall 0.84 to 0.93 and cited references 0.76 to 0.82
        for 2.1x the latency, the gain sitting in the multi-hop cases (RRG-98).
    ASSESS_MAX_ROUNDS: times assess may ask for tool calls before the answer is written. One
        reaches everything the context can address, since a block's `cites` line carries the
        address of what it points at.
    ASSESS_MAX_CALLS: the most tool calls one round may run; the rest are dropped.
    ASSESS_SEARCH_LIMIT: hits one search tool call brings back.
    ASSESS_FOLLOW_LIMIT: chunks one follow_reference call brings back, so a long division
        cannot spend the whole budget in a single call.
    ASSESS_EXTRA_CHUNKS: the most chunks the loop may add on top of retrieve's context; at 0
        it reads the context but never grows it.
    ASSESS_MAY_REFUSE: whether assess is offered the refuse tool; off, a question nothing
        bears on is declined by synthesize in its own words. On by default: it refused 2 of
        the 6 out-of-corpus cases that clear the gate and no in-corpus case (RRG-103).
    """

    ASSESS_ENABLED: bool = True
    ASSESS_MAX_ROUNDS: int = Field(default=1, ge=1)
    ASSESS_MAX_CALLS: int = Field(default=4, ge=1)
    ASSESS_SEARCH_LIMIT: int = Field(default=5, ge=1)
    ASSESS_FOLLOW_LIMIT: int = Field(default=5, ge=1)
    ASSESS_EXTRA_CHUNKS: int = Field(default=10, ge=0)
    ASSESS_MAY_REFUSE: bool = True


class DecomposeConfig(BaseConfig):
    """The decompose node, which splits a multi-part question into one search per part.

    DECOMPOSE_ENABLED: the node's off switch; off, retrieve searches the question as asked.
        Off by default: it moved multi_part recall 0.885 to 0.910, inside the ±0.07 noise,
        and wrongly split 2 single-part cases (RRG-73).
    DECOMPOSE_MAX_PARTS: the most queries a question may split into, surplus parts dropped.
        Each part searches CHAT_SOURCES hits, so keep the product under CHAT_CONTEXT_CHUNKS.
    """

    DECOMPOSE_ENABLED: bool = False
    DECOMPOSE_MAX_PARTS: int = Field(default=3, ge=2)


class IngestConfig(BaseConfig):
    """Ingestion tunables.

    TOPIC_BASE_ACTS: the act each topic is built from; its corpus is everything based on it.
    TOPIC_BASIS_ARTICLES: a pattern for the start of a legal basis, as CELLAR writes it, that
        narrows a topic to the acts adopted under those articles; a topic with none keeps every
        act. ETS keeps shipping: Articles 3ga-3gg and the 12(3-b) to 12(3-e) derogations, not
        Article 3g on aviation or 12(3b) on carbon capture.
    TOPIC_EXCLUDED_BASIS_ARTICLES: the same kind of pattern, for acts the corpus leaves out. ETS
        drops the lists of shipping companies adopted under Article 3gf(2), 2024/411 and any
        that replace it: 200k characters of names that crowd out the rules.
    CRAWL_DELAYS: seconds between requests per host; eur-lex publishes 10 in robots.txt.
    MAX_DROP_RATIO: fraction of the previous corpus that may vanish before discovery aborts.
    MIN_SUSPICIOUS_DROPS: dropped documents below this never abort, however small the corpus.
    MAX_CHARS: longest chunk emitted.
    EMBED_PAGE_SIZE: chunks the embed sweep reads per page.
    EMBED_CONCURRENCY: provider calls in flight at once; llm_retry absorbs the rate limits.
    MAX_FAILURE_CHARS: cut for a stored failure message, so one talkative provider cannot
        bloat the run row.
    """

    TOPIC_BASE_ACTS: dict[str, str] = {
        "fueleu": "32023R1805",
        "mrv": "32015R0757",
        "ets": "32003L0087",
    }
    TOPIC_BASIS_ARTICLES: dict[str, str] = {"ets": r"A03g[a-g]|A12P3-[b-e]"}
    TOPIC_EXCLUDED_BASIS_ARTICLES: dict[str, str] = {"ets": r"A03gfP2"}
    CRAWL_DELAYS: dict[str, float] = {"eur-lex.europa.eu": 10.0, "publications.europa.eu": 1.0}
    MAX_DROP_RATIO: float = 0.2
    MIN_SUSPICIOUS_DROPS: int = 3
    MAX_CHARS: int = 2000
    EMBED_PAGE_SIZE: int = 500
    EMBED_CONCURRENCY: int = 4
    MAX_FAILURE_CHARS: int = 500


class RetrievalConfig(BaseConfig):
    """Search tunables.

    SEARCH_CANDIDATES: per-leg candidate pool feeding Reciprocal Rank Fusion.
    SEARCH_DEFAULT_LIMIT: results returned when the caller does not say how many.
    EF_SEARCH_PER_CANDIDATE: how far the HNSW walk looks per candidate; pgvector caps the
        product at 1000.
    RRF_K: fusion damping; a result at some rank scores 1 / (RRF_K + rank).
    RERANK_ENABLED: the cross-encoder's off switch.
    RERANK_MODEL: which cross-encoder rescores the fused results.
    RERANK_TIMEOUT: seconds to wait for the cross-encoder.
    RERANK_POOL: fused results the cross-encoder rescores.
    EXPAND_SECTIONS: widens each hit to its whole section; off by default, as the tune
        showed it doubling context cost for no recall or citation gain.
    MIN_COSINE_SIMILARITY / MIN_RERANKER_RELEVANCE: the refusal gate's bars, cleared by the
        best hit per signal rather than by one hit on both. Set permissively, since the gate
        is for junk and a false refusal costs more than a wasted call.
    """

    SEARCH_CANDIDATES: int = Field(default=50, ge=1)
    SEARCH_DEFAULT_LIMIT: int = Field(default=10, ge=1)
    EF_SEARCH_PER_CANDIDATE: int = Field(default=4, ge=1)
    RRF_K: int = 60

    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "voyage/rerank-2.5"
    RERANK_TIMEOUT: int = 30
    RERANK_POOL: int = 30

    EXPAND_SECTIONS: bool = False

    MIN_COSINE_SIMILARITY: float = Field(default=0.30, ge=0.0)
    MIN_RERANKER_RELEVANCE: float = Field(default=0.45, ge=0.0)


class EvalConfig(BaseConfig):
    """Eval tunables.

    EVAL_DATASET_PATH: the golden dataset, authored cases versioned as JSON in the repo.
    EVAL_CACHE_DIR: where repeated runs replay their embed and rerank calls from. Not in
        RetrievalConfig, which a run records: a cache hit answers exactly as a miss would.
    """

    EVAL_DATASET_PATH: Path = BACKEND_ROOT / "app" / "evals" / "dataset" / "golden.json"
    EVAL_CACHE_DIR: Path = PROJECT_ROOT / "data" / "cache" / "evals"


class JudgeConfig(BaseConfig):
    """The eval judge: the model that reads an answer and grades it.

    EVAL_JUDGE_MODEL: a model other than the one that wrote the answer, so a model does not
        grade its own habits. Recorded on every run, since different judges do not compare.
    EVAL_JUDGE_TIMEOUT: seconds for one verdict, above the chat wait: the judge sits a tier
        up and writes a longer answer, so the chat value cuts it off.
    EVAL_JUDGE_MAX_TOKENS: the cap on one verdict, well above the answer's, since a verdict
        is critique first. One cut short parses as nothing and leaves the case unjudged.
    EVAL_JUDGE_CONCURRENCY: cases judged at once; llm_retry absorbs the rate limits.
    """

    EVAL_JUDGE_MODEL: str = "openrouter/anthropic/claude-sonnet-5"
    EVAL_JUDGE_TIMEOUT: int = 120
    EVAL_JUDGE_MAX_TOKENS: int = 8192
    EVAL_JUDGE_CONCURRENCY: int = 4


class Config(
    AppConfig,
    PostgresConfig,
    RedisConfig,
    RateLimitConfig,
    ProviderConfig,
    EmbeddingConfig,
    ChatConfig,
    AssessConfig,
    DecomposeConfig,
    IngestConfig,
    RetrievalConfig,
    StorageConfig,
    EvalConfig,
    JudgeConfig,
):
    """Combined configuration class for core app functionality."""


config = Config()


_CONFIG_SECTIONS = (
    AppConfig,
    PostgresConfig,
    RedisConfig,
    RateLimitConfig,
    ProviderConfig,
    EmbeddingConfig,
    ChatConfig,
    AssessConfig,
    DecomposeConfig,
    IngestConfig,
    RetrievalConfig,
    StorageConfig,
    EvalConfig,
    JudgeConfig,
)
EVAL_CONFIG_SECTIONS = (
    EmbeddingConfig,
    ChatConfig,
    AssessConfig,
    DecomposeConfig,
    RetrievalConfig,
    JudgeConfig,
)
ANSWER_CONFIG_SECTIONS = (
    EmbeddingConfig,
    ChatConfig,
    AssessConfig,
    DecomposeConfig,
    RetrievalConfig,
)


def get_config_snapshot(
    sections: tuple[type[BaseConfig], ...] | None = None,
) -> dict[str, Any]:
    """Return non-secret settings from the requested config sections."""
    sections = sections or _CONFIG_SECTIONS

    return {
        name: getattr(config, name)
        for section in sections
        for name, field in sorted(section.model_fields.items())
        if field.annotation is not SecretStr
    }
