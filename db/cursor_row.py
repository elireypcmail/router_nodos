"""Normaliza filas de cursor MySQL (dict o tupla) a dict."""

from __future__ import annotations

from typing import Any, Sequence


def cursor_row_as_dict(
    row: Any,
    columns: Sequence[str],
) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, (list, tuple)):
        return {
            col: row[i]
            for i, col in enumerate(columns)
            if i < len(row)
        }
    return None
