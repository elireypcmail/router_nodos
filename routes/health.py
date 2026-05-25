from fastapi import APIRouter, Depends

from config import settings
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(_: None = Depends(verify_bearer)):
    return {
        "status": "ok",
        "nodo_id": settings.nodo_id,
        "nombre": settings.nodo_nombre,
        "vpn_ip": settings.nodo_vpn_ip,
    }
