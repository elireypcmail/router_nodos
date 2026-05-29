"""Valores JSON-serializables para httpx/FastAPI (filas MySQL)."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger("multishop.json")

# Controles ASCII literales (ERP en descrip/kobs); no afecta secuencias ya escapadas \\n.
_INVALID_JSON_CONTROL_RE = re.compile(r"[\x00-\x1f]")


def sanitize_json_text(text: str) -> str:
    """Convierte controles literales en escapes JSON o espacio."""

    def repl(match: re.Match[str]) -> str:
        ch = match.group(0)
        if ch == "\t":
            return "\\t"
        if ch == "\n":
            return "\\n"
        if ch == "\r":
            return "\\r"
        return " "

    return _INVALID_JSON_CONTROL_RE.sub(repl, text)


def loads_outbox_json(raw: str, *, context: str = "") -> Any:
    """Parsea pk_json/row_json del outbox; repara texto ERP con tab/saltos sin escapar."""

    try:
        return json.loads(raw)
    except json.JSONDecodeError as first_exc:
        if "control character" not in str(first_exc).lower():
            raise
        repaired = sanitize_json_text(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise first_exc from None
        logger.warning(
            "Outbox JSON reparado (%s): %s",
            context or "sync_outbox",
            first_exc.msg,
        )
        return data


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
