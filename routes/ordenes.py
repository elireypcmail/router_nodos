"""Preventas / órdenes por facturar (sin kardex ni descuento de stock)."""

from __future__ import annotations

from typing import Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from core.config import settings
from db.mysql import MySqlClient
from db.ordenes_store import (
    OrdenCustomerInput,
    OrdenLineInput,
    OrdenPaymentInput,
    OrdenesStoreError,
    create_orden,
    get_orden_by_nordene,
    list_ordenes,
)
from middleware.auth import verify_bearer

router = APIRouter(prefix="/api", tags=["ordenes"])

# Cédula o RIF: una letra + dígitos (ej. V21135632, J123456789).
DOCUMENT_ID_PATTERN = r"^[A-Za-z]\d+$"


class OrdenCustomerRequest(BaseModel):
    document_id: str = Field(min_length=2, max_length=30, pattern=DOCUMENT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=240)
    phone: str = Field(min_length=1, max_length=80)
    address_line1: str = Field(default="", max_length=200)
    address_line2: str = Field(default="", max_length=200)
    address_line3: str = Field(default="", max_length=200)


class OrdenItemRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    quantity: float = Field(gt=0)
    unit_price: float | None = Field(default=None, gt=0)


class OrdenPaymentRequest(BaseModel):
    method: Literal["card", "deposit"]
    amount: float = Field(gt=0)
    bank_code: str = Field(min_length=1, max_length=10)
    card_number: str | None = Field(default=None, max_length=15)
    holder_name: str | None = Field(default=None, max_length=200)
    confirmation_number: str | None = Field(default=None, max_length=15)
    operation_type: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _require_method_fields(self) -> OrdenPaymentRequest:
        if self.method == "card" and not (self.card_number or "").strip():
            raise ValueError("card_number is required when method=card")
        if self.method == "deposit" and not (self.confirmation_number or "").strip():
            raise ValueError("confirmation_number is required when method=deposit")
        return self


class OrdenCreateRequest(BaseModel):
    customer: OrdenCustomerRequest
    items: list[OrdenItemRequest] = Field(min_length=1)
    payments: list[OrdenPaymentRequest] = Field(min_length=1)
    # Inyectados por el hub desde parámetros de sistema (Postgres)
    deposito_ncuenta: str = Field(default="", max_length=25)
    tarjeta_npunto: str = Field(min_length=1, max_length=2)
    cod_ven: str = Field(min_length=1, max_length=10)
    cajero_ccaja: str = Field(min_length=1, max_length=10)
    use_sinv_precio1: bool = False
    enforce_min_precio1: bool = False


def _mysql_conn():
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")
    return mysql.connect()


def _create_orden_sync(body: OrdenCreateRequest) -> dict:
    conn = _mysql_conn()
    try:
        result = create_orden(
            conn,
            customer=OrdenCustomerInput(
                document_id=body.customer.document_id,
                name=body.customer.name,
                phone=body.customer.phone,
                address_line1=body.customer.address_line1,
                address_line2=body.customer.address_line2,
                address_line3=body.customer.address_line3,
            ),
            items=[
                OrdenLineInput(
                    sku=item.sku,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                for item in body.items
            ],
            payments=[
                OrdenPaymentInput(
                    method=pay.method,
                    amount=pay.amount,
                    bank_code=pay.bank_code,
                    card_number=pay.card_number,
                    holder_name=pay.holder_name,
                    confirmation_number=pay.confirmation_number,
                    operation_type=pay.operation_type,
                )
                for pay in body.payments
            ],
            deposito_ncuenta=body.deposito_ncuenta,
            tarjeta_npunto=body.tarjeta_npunto,
            cod_ven=body.cod_ven,
            cajero_ccaja=body.cajero_ccaja,
            use_sinv_precio1=body.use_sinv_precio1,
            enforce_min_precio1=body.enforce_min_precio1,
        )
        conn.commit()
        return {
            "nodo_id": settings.nodo_id,
            "nombre": settings.nodo_nombre,
            **result,
        }
    except OrdenesStoreError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _list_ordenes_sync(
    search: str,
    fecha_desde: str,
    fecha_hasta: str,
    status: str,
    page: int,
    limit: int,
) -> dict:
    conn = _mysql_conn()
    try:
        items, total = list_ordenes(
            conn,
            search=search,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            status=status,
            page=page,
            limit=limit,
        )
        total_pages = 0 if total == 0 else (total + limit - 1) // limit
        return {
            "search": search,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "status": status,
            "nodo_id": settings.nodo_id,
            "nombre": settings.nodo_nombre,
            "items": items,
            "page": page,
            "limit": limit,
            "total": total,
            "totalPages": total_pages,
            "message": "ok",
        }
    finally:
        conn.close()


def _get_orden_sync(nordene: str) -> dict:
    conn = _mysql_conn()
    try:
        result = get_orden_by_nordene(conn, nordene)
        if result is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return {
            "nodo_id": settings.nodo_id,
            "nombre": settings.nodo_nombre,
            **result,
        }
    finally:
        conn.close()


@router.get("/ordenes")
async def list_ordenes_route(
    search: str = Query("", description="Match orderId, customer or invoice number"),
    fecha_desde: str = Query("", description="Start date (YYYY-MM-DD)"),
    fecha_hasta: str = Query("", description="End date (YYYY-MM-DD)"),
    status: str = Query(
        "",
        description="Filter: pending | confirmed",
    ),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(50, ge=1, le=500, description="Rows per page"),
    _: None = Depends(verify_bearer),
):
    status_norm = (status or "").strip().lower()
    if status_norm and status_norm not in ("pending", "confirmed"):
        raise HTTPException(
            status_code=422,
            detail="status must be pending or confirmed",
        )
    try:
        return await anyio.to_thread.run_sync(
            lambda: _list_ordenes_sync(
                search, fecha_desde, fecha_hasta, status_norm, page, limit
            )
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/ordenes/{nordene}")
async def get_orden_route(
    nordene: str,
    _: None = Depends(verify_bearer),
):
    try:
        return await anyio.to_thread.run_sync(_get_orden_sync, nordene)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/ordenes")
async def create_orden_route(
    body: OrdenCreateRequest,
    _: None = Depends(verify_bearer),
):
    try:
        return await anyio.to_thread.run_sync(_create_orden_sync, body)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
