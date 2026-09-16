"""Test package: pin the environment and the database before any app import loads config."""

import os

os.environ["ENVIRONMENT"] = "test"
os.environ["DB_NAME"] = "regrag_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
"""Set here rather than in .env.example, which is also the template for .env.dev: naming the
test database and Redis index there would point a fresh dev checkout at the ones the suite
truncates."""
os.environ["RATE_LIMIT_ENABLED"] = "false"
"""Off suite-wide so no test's questions count against another's; limiter tests turn it on."""
