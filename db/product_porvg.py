"""Alícuota IVA (sinv.porvg) permitida al crear producto."""

from __future__ import annotations

ALLOWED_PORVG = frozenset({0.0, 8.0, 16.0, 31.0})


def validate_porvg(value: float | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if parsed not in ALLOWED_PORVG:
        raise ValueError("porvg must be one of 0, 8, 16, 31")
    return parsed
