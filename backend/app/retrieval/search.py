"""Search the corpus: embed the query, run both legs and fuse their ranks in one query, rerank."""

from collections.abc import Sequence

from sqlalchemy import CTE, Integer, Select, cast, func, select, text, true
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import TextRanker, config
from app.core.llm.embed import EmbedInput, embed
from app.core.llm.errors import llm_retry
from app.ingestion.chunk.schemas import DocumentChunk
from app.retrieval.models import CHUNK_COLUMNS, SearchFilters, SearchRequest, SearchResult
from app.retrieval.rerank import rerank_results

EF_SEARCH_MAX = 1000
"""pgvector refuses a larger walk, so a pool that would ask for one is clamped, not rejected."""
BM25_K1 = 1.2
BM25_B = 0.75
"""The textbook constants: how fast repeats saturate, and how hard length is penalised."""
BM25_CITATION_WEIGHT = 4.0
"""What a term in the chunk's own citation counts for against one in its text, so the article
a query names beats a short chunk that merely mentions it. Invisible to the golden set at any
value, whose questions rarely carry a citation's words; set by the article 11 and 11a case.
The title's A weight earns no boost: a question word in a title cost 0.06 recall at 10."""


@llm_retry
async def _embed_query(query: str) -> list[float]:
    """Embed one query, retrying transient provider failures."""
    (vector,) = await embed([query], input_type=EmbedInput.QUERY)
    return vector


async def _tune_hnsw_walk(session: AsyncSession, candidates: int) -> None:
    """Let the HNSW walk resume past filtered and dead tuples until the candidate pool is met.

    strict_order because fusion scores rank position, which an approximate order makes
    meaningless; both settings are transaction-local, so neither leaks across the pool.
    """
    ef_search = min(candidates * config.EF_SEARCH_PER_CANDIDATE, EF_SEARCH_MAX)
    stmt = text(
        "SELECT set_config('hnsw.iterative_scan', 'strict_order', true),"
        " set_config('hnsw.ef_search', :ef_search, true)"
    ).bindparams(ef_search=str(ef_search))
    await session.execute(stmt)


def _filtered(stmt: Select, filters: SearchFilters) -> Select:
    """Narrow a candidate query before its limit, so the pool the fusion sees is honest."""
    if filters.celex is not None:
        stmt = stmt.where(DocumentChunk.celex == filters.celex)
    if filters.topic is not None:
        stmt = stmt.where(DocumentChunk.topic == filters.topic)
    return stmt


def _ranked(stmt: Select, order: Sequence, limit: int) -> Select:
    """A leg's top chunk ids, each carrying its 1-based position in that leg."""
    return (
        stmt.add_columns(func.row_number().over(order_by=order).label("rank"))
        .order_by(*order)
        .limit(limit)
    )


def _vector_candidates(embedding: Sequence[float], filters: SearchFilters, limit: int) -> Select:
    """Chunk ids nearest the query vector by cosine distance, closest first, each with
    its similarity: the one absolute measure of nearness the walk already computed."""
    distance = DocumentChunk.embedding.cosine_distance(embedding)
    order = (distance, DocumentChunk.id)
    stmt = select(DocumentChunk.id, (1 - distance).label("cosine_similarity")).where(
        DocumentChunk.embedding.is_not(None)
    )
    return _ranked(_filtered(stmt, filters), order, limit)


def _query_terms(query: str) -> CTE:
    """The query's lexemes, each quoted as tsquery syntax and counted across the corpus, put
    through the same stemming and stop words as the search vector so the two meet on equal
    terms. Read more than once, so Postgres materialises it and counts each term once."""
    lexemes = (
        func.unnest(func.to_tsvector("english", query))
        .table_valued("lexeme", "positions", "weights")
        .render_derived()
    )
    quoted = func.format("%L", lexemes.c.lexeme)
    matches = DocumentChunk.search_vector.bool_op("@@")(cast(quoted, TSQUERY))
    ndoc = select(func.count()).select_from(DocumentChunk).where(matches).scalar_subquery()
    return select(quoted.label("quoted"), ndoc.label("ndoc")).cte("terms")


def _ts_rank_candidates(query: str, filters: SearchFilters, limit: int) -> Select:
    """Chunk ids matching every term of the query, ordered by Postgres's own cover density."""
    tsquery = func.websearch_to_tsquery("english", query)
    order = (func.ts_rank_cd(DocumentChunk.search_vector, tsquery).desc(), DocumentChunk.id)
    stmt = select(DocumentChunk.id).where(DocumentChunk.search_vector.bool_op("@@")(tsquery))
    return _ranked(_filtered(stmt, filters), order, limit)


def _bm25_candidates(query: str, filters: SearchFilters, limit: int) -> Select:
    """Chunk ids matching any term of the query, ordered by BM25 over the search vector.

    Any term, since a question is not a conjunction and one word the corpus lacks must not
    empty the leg. A term's weight is its rarity across the corpus, its frequency in the
    chunk saturating, and the chunk's length in characters penalised, which holds recall as
    well as a token count does and needs no second unnest.
    """
    terms = _query_terms(query)
    any_term = select(cast(func.string_agg(terms.c.quoted, " | "), TSQUERY)).scalar_subquery()
    stats = (
        select(
            func.count().label("n"),
            func.avg(func.length(DocumentChunk.text)).label("avg_len"),
        )
        .select_from(DocumentChunk)
        .cte("stats")
    )
    lexemes = (
        func.unnest(DocumentChunk.search_vector)
        .table_valued("lexeme", "positions", "weights")
        .render_derived()
    )
    quoted = func.format("%L", lexemes.c.lexeme)
    positions = func.array_length(lexemes.c.positions, 1)
    in_citation = func.to_tsvector("english", DocumentChunk.citation).bool_op("@@")(
        cast(quoted, TSQUERY)
    )
    tf = positions + cast(in_citation, Integer) * (BM25_CITATION_WEIGHT - 1)
    hits = select(
        DocumentChunk.id,
        func.length(DocumentChunk.text).label("len"),
        quoted.label("quoted"),
        tf.label("tf"),
    ).join(lexemes, true())
    hits = hits.where(
        DocumentChunk.search_vector.bool_op("@@")(any_term),
        quoted.in_(select(terms.c.quoted)),
    )
    hits = _filtered(hits, filters).cte("hits")
    idf = func.ln((stats.c.n - terms.c.ndoc + 0.5) / (terms.c.ndoc + 0.5) + 1)
    saturated = (hits.c.tf * (BM25_K1 + 1)) / (
        hits.c.tf + BM25_K1 * (1 - BM25_B + BM25_B * hits.c.len / stats.c.avg_len)
    )
    scored = (
        select(hits.c.id, func.sum(idf * saturated).label("bm25"))
        .select_from(hits.join(terms, hits.c.quoted == terms.c.quoted).join(stats, true()))
        .group_by(hits.c.id)
        .subquery("scored")
    )
    order = (scored.c.bm25.desc(), scored.c.id)
    return _ranked(select(scored.c.id), order, limit)


def _text_candidates(query: str, filters: SearchFilters, limit: int) -> Select:
    """Chunk ids whose search vector matches the query, best-ranked first."""
    if config.TEXT_RANKER is TextRanker.BM25:
        return _bm25_candidates(query, filters, limit)
    return _ts_rank_candidates(query, filters, limit)


async def hybrid_search(
    session: AsyncSession,
    *,
    query: str,
    embedding: Sequence[float],
    filters: SearchFilters,
    limit: int,
    candidates: int,
    rrf_k: int,
) -> tuple[SearchResult, ...]:
    """The corpus's best answers, both legs fused by 1/(rrf_k + rank) in one round trip.

    A full outer join keeps chunks only one leg found, whose missing term contributes nothing.
    """
    await _tune_hnsw_walk(session, candidates)
    by_vector = _vector_candidates(embedding, filters, candidates).cte("by_vector")
    by_text = _text_candidates(query, filters, candidates).cte("by_text")
    rrf_score = (
        func.coalesce(1.0 / (rrf_k + by_vector.c.rank), 0.0)
        + func.coalesce(1.0 / (rrf_k + by_text.c.rank), 0.0)
    ).label("rrf_score")
    joined = by_vector.join(by_text, by_vector.c.id == by_text.c.id, full=True).join(
        DocumentChunk, DocumentChunk.id == func.coalesce(by_vector.c.id, by_text.c.id)
    )
    stmt = (
        select(
            *CHUNK_COLUMNS,
            rrf_score,
            by_vector.c.rank.label("vector_rank"),
            by_text.c.rank.label("text_rank"),
            by_vector.c.cosine_similarity,
        )
        .select_from(joined)
        .order_by(rrf_score.desc(), DocumentChunk.id)
        .limit(limit)
    )
    rows = await session.execute(stmt)
    return tuple(SearchResult.model_validate(row) for row in rows)


async def search(session: AsyncSession, request: SearchRequest) -> tuple[SearchResult, ...]:
    """The corpus's best answers to a query, fused across both legs and reranked."""
    limit = request.limit or config.SEARCH_DEFAULT_LIMIT
    embedding = await _embed_query(request.query)
    pool = max(limit, config.RERANK_POOL) if config.RERANK_ENABLED else limit
    results = await hybrid_search(
        session,
        query=request.query,
        embedding=embedding,
        filters=request.filters,
        limit=pool,
        candidates=config.SEARCH_CANDIDATES,
        rrf_k=config.RRF_K,
    )
    if config.RERANK_ENABLED:
        results = await rerank_results(request.query, results, limit=limit)
    return results
