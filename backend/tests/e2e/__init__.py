"""E2E launcher package: its own database and Redis index, pinned before the app loads config."""

import os

os.environ["DB_NAME"] = "regrag_e2e"
os.environ["REDIS_URL"] = "redis://localhost:6379/2"
"""Apart from the suite's, so a pytest run and a Playwright run never clear each other's rows."""
