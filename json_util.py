"""Valores JSON-serializables para httpx/FastAPI (filas MySQL)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value
