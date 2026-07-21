"""Timezone de la tienda para simuladores / timestamps locales."""

from __future__ import annotations

import logging
import os
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("multishop.store_datetime")

# Venezuela sin DST desde 2016; fallback si falta tzdata.
_CARACAS_FALLBACK = timezone(timedelta(hours=-4))
_FIXED_TZ_FALLBACK: dict[str, timezone] = {
    "America/Caracas": _CARACAS_FALLBACK,
}


def store_timezone() -> ZoneInfo | timezone:
    tz_name = (os.environ.get("NODO_STORE_TZ") or "America/Caracas").strip()
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ModuleNotFoundError):
        fallback = _FIXED_TZ_FALLBACK.get(tz_name)
        if fallback is not None:
            logger.warning(
                "Zona IANA %s no disponible (pip install tzdata); "
                "usando offset fijo UTC-4",
                tz_name,
            )
            return fallback
        raise
