"""Suprimir sync_outbox en escrituras originadas en el hub (evita eco catalog-push)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

# Variable de sesión MySQL leída por trg_{sinv,sprv,catego}_* en mysql_outbox_triggers.sql
SKIP_OUTBOX_VAR = "@ms_skip_outbox"


def hub_origin_write_begin(cur: Any) -> None:
    cur.execute(f"SET {SKIP_OUTBOX_VAR} = IFNULL({SKIP_OUTBOX_VAR}, 0) + 1")


def hub_origin_write_end(cur: Any) -> None:
    cur.execute(f"SET {SKIP_OUTBOX_VAR} = IFNULL({SKIP_OUTBOX_VAR}, 0) - 1")


@contextmanager
def hub_origin_write(cur: Any) -> Iterator[None]:
    """Misma conexión que el INSERT/UPDATE; anidable (contador)."""
    hub_origin_write_begin(cur)
    try:
        yield
    finally:
        hub_origin_write_end(cur)
