"""UUID v7 para correlación de eventos outbox."""

from __future__ import annotations

import re
import uuid

try:
    from uuid6 import uuid7 as _uuid7
except ImportError:  # pragma: no cover
    _uuid7 = None  # type: ignore[assignment]

_UUID_V7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def generate_uuid_v7() -> str:
    if _uuid7 is not None:
        return str(_uuid7())
    return str(uuid.uuid4())
