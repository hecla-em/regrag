"""Read-only analytics for hecla-admin, on the private-network port only, behind the
analytics key and out of the public OpenAPI schema: the chat ledger's measures, and the
stored eval runs."""

from fastapi import APIRouter, Depends

from app.analytics.chat.router import router as chat_router
from app.analytics.evals.router import router as evals_router
from app.core.security import require_private_network, verify_analytics_key

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_private_network), Depends(verify_analytics_key)],
    include_in_schema=False,
)
router.include_router(chat_router)
router.include_router(evals_router)
