"""Parseo de kardex.kobs (texto ERP) para outbox / webhooks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from core.store_datetime import store_timezone

# Normaliza "a. m." / "a.m." / NBSP / "AM".
_AMPM_RE = re.compile(r"([ap])\.?\s*m\.?", re.IGNORECASE)

# Acepta "10:28:19 p. m." y también "10:28:19p. m." (sin espacio).
_TIME_RE = re.compile(
    r"(?:Hora:\s*)?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*"
    r"([ap]\.?\s*m\.?)",
    re.IGNORECASE,
)

_PROVEEDOR_RE = re.compile(r"Proveedor:\s*(\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedKobs:
    provider_code: str | None
    local_time: time | None
    local_time_raw: str | None


def _normalize_kobs(kobs: str) -> str:
    # ERP a veces usa NBSP entre a. y m.
    return (
        kobs.replace("\xa0", " ")
        .replace("\u202f", " ")
        .strip()
    )


def parse_kobs_time(kobs: str) -> tuple[time | None, str | None]:
    text = _normalize_kobs(kobs)
    if not text:
        return None, None
    match = _TIME_RE.search(text)
    if not match:
        return None, None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    ampm = _AMPM_RE.sub(r"\1m", match.group(4).lower().replace(" ", ""))
    if hour < 1 or hour > 12 or minute > 59 or second > 59:
        return None, match.group(0).strip()
    if ampm.startswith("p") and hour != 12:
        hour += 12
    elif ampm.startswith("a") and hour == 12:
        hour = 0
    return time(hour, minute, second), match.group(0).strip()


def parse_hora_column(value: object) -> time | None:
    """Fallback: columna kardex.hora (p. ej. '1:21' o '13:05:00')."""
    raw = str(value or "").strip()
    if not raw:
        return None
    parts = raw.replace(".", ":").split(":")
    try:
        if len(parts) == 1:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        if hour > 23 or minute > 59 or second > 59:
            return None
        return time(hour, minute, second)
    except (TypeError, ValueError):
        return None


def parse_provider_code(kobs: str) -> str | None:
    text = _normalize_kobs(kobs)
    if not text:
        return None
    match = _PROVEEDOR_RE.search(text)
    if not match:
        return None
    code = match.group(1).strip()
    return code or None


def parse_kobs(kobs: object) -> ParsedKobs:
    text = _normalize_kobs(str(kobs or ""))
    if not text:
        return ParsedKobs(None, None, None)
    provider = parse_provider_code(text)
    local_time, raw = parse_kobs_time(text)
    return ParsedKobs(provider, local_time, raw)


def parse_fecha_value(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def build_movement_timestamp(
    fecha: object,
    local_time: time | None,
    *,
    tz: timezone | None = None,
) -> str | None:
    """fecha kardex + hora local del nodo → ISO UTC (`…Z`)."""
    day = parse_fecha_value(fecha)
    if day is None:
        return None
    wall = local_time or time(0, 0, 0)
    resolved = tz if tz is not None else store_timezone()
    local_dt = datetime(
        day.year,
        day.month,
        day.day,
        wall.hour,
        wall.minute,
        wall.second,
        tzinfo=resolved,
    )
    return local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def kobs_parsed_dict(parsed: ParsedKobs) -> dict[str, Any]:
    local_iso = None
    if parsed.local_time is not None:
        local_iso = parsed.local_time.strftime("%H:%M:%S")
    return {
        "provider_code": parsed.provider_code,
        "local_time": local_iso,
        "local_time_raw": parsed.local_time_raw,
    }
