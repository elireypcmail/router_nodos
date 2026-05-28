from fastapi import APIRouter, Depends

from config import settings
from db_mysql import mysql_db_health_status
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(_: None = Depends(verify_bearer)):
    db = mysql_db_health_status()
    # Sin MySQL en .env el nodo sigue operativo (sync SQLite); con MySQL caído -> degradado.
    status = "ok" if db in ("ok", "simulated") else "degraded"
    return {
        "status": status,
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "vpn_ip": settings.nodo_vpn_ip,
        "db": db,
    }
