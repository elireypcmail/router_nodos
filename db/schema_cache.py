"""Caché de columnas MySQL (SHOW COLUMNS) para evitar N consultas de metadatos."""

from __future__ import annotations

from typing import Any


class TableColumnCache:
    def __init__(self) -> None:
        self._columns: dict[str, set[str]] = {}

    def columns(self, cur: Any, table: str) -> set[str]:
        key = str(table or "").strip().lower()
        if key in self._columns:
            return self._columns[key]
        cur.execute(f"SHOW COLUMNS FROM `{key}`")
        cols: set[str] = set()
        for row in cur.fetchall() or []:
            if not isinstance(row, dict):
                continue
            field = str(row.get("Field") or "").strip().lower()
            if field:
                cols.add(field)
        self._columns[key] = cols
        return cols

    def has_column(self, cur: Any, table: str, column: str) -> bool:
        return str(column or "").strip().lower() in self.columns(cur, table)
