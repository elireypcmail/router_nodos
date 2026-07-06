from fastapi import APIRouter, Depends

from db.mysql import MySqlClient
from middleware.auth import verify_bearer
from outbox.mysql import OutboxRepository

router = APIRouter(prefix="/api/sync/outbox", tags=["sync-outbox"])


@router.get("/status")
async def outbox_status(_: None = Depends(verify_bearer)):
    mysql = MySqlClient()
    if not mysql.is_configured():
        return {
            "configured": False,
            "stats": {},
            "recent_pending": [],
            "recent_failed": [],
        }
    repo = OutboxRepository(mysql)
    repo.ensure_schema()
    return {
        "configured": True,
        "stats": repo.stats(),
        "recent_pending": repo.recent("pending", limit=15),
        "recent_failed": repo.recent("failed", limit=15),
    }
