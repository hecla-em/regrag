"""The API key a service caller presents, as a route dependency."""

import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import APIKeyHeader

from app.core.config import config
from app.core.exceptions import UnauthorizedError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_analytics_key(api_key: Annotated[str | None, Depends(api_key_header)]) -> None:
    """Refuse the request unless it carries ANALYTICS_API_KEY. With no key set, refuse every one."""
    expected = config.ANALYTICS_API_KEY.get_secret_value()
    if (
        not expected
        or not api_key
        or not secrets.compare_digest(api_key.encode(), expected.encode())
    ):
        raise UnauthorizedError()
