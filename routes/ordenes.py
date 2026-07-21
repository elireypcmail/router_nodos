"""Preventas / órdenes por facturar (sin kardex ni descuento de stock)."""

from __future__ import annotations

from typing import Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from core.config import settings
from db.mysql import MySqlClient
from db.ordenes_store import (
    OrdenCustomerInput,
    OrdenLineInput,
    OrdenPaymentInput,
    OrdenesStoreError,
    create_orden,
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
    use_sinv_precio1: bool = False
    enforce_min_precio1: bool = False


def _create_orden_sync(body: OrdenCreateRequest) -> dict:
    mysql = MySqlClient()
    if not mysql.is_configured():
        raise RuntimeError("Node MySQL not configured (set MYSQL_* in env.txt/.env)")

    conn = mysql.connect()
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
