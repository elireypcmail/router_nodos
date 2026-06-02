"""Ritmo de cancel/progreso en export gzip (evita costo por fila en Huey)."""

from __future__ import annotations

CATALOG_EXPORT_TICK_EVERY = 50


def should_tick_export_loop(
    *,
    written: int,
    total: int,
    every: int = CATALOG_EXPORT_TICK_EVERY,
) -> bool:
    """True en primera fila, cada ``every`` filas y en la última."""
    if written <= 0:
        return False
    if written == 1:
        return True
    if total > 0 and written >= total:
        return True
    return every > 0 and written % every == 0
