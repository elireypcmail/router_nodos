"""Utilidades compartidas para pull con warnings."""

from __future__ import annotations

from typing import Any, Callable

from db_mysql import MySqlClient


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def fetch_codes_existing(
    mysql: MySqlClient,
    table: str,
    column: str,
    codes: list[str],
) -> set[str]:
    codes = [c.strip() for c in codes if str(c or "").strip()]
    if not codes:
        return set()

    def load() -> set[str]:
        conn = mysql.connect()
        found: set[str] = set()
        try:
            cur = conn.cursor()
            for chunk in chunked(codes, 400):
                placeholders = ", ".join(["%s"] * len(chunk))
                cur.execute(
                    f"SELECT {column} FROM {table} WHERE {column} IN ({placeholders})",
                    tuple(chunk),
                )
                for (code,) in cur.fetchall() or []:
                    if code is not None:
                        found.add(str(code).strip())
        finally:
            conn.close()
        return found

    return load()


def run_pull_with_compare(
    *,
    mysql: MySqlClient,
    hub_items: list[dict],
    code_key: str,
    fetch_local: Callable[[list[str]], dict[str, dict[str, Any]]],
    snapshots_equal: Callable[[dict, dict], bool],
    diff_fields_fn: Callable[[dict, dict], list[str]],
    insert_row: Callable[[Any, dict], None],
) -> tuple[int, int, int, list[dict], int]:
    """
    Returns: inserted, unchanged, conflicts_count, conflict_reports, skipped
    """
    hub_by_code: dict[str, dict] = {}
    skipped = 0
    for it in hub_items:
        if not isinstance(it, dict):
            skipped += 1
            continue
        code = str(it.get(code_key) or "").strip()
        if not code:
            skipped += 1
            continue
        hub_by_code[code] = it

    def process():
        local = fetch_local(list(hub_by_code.keys()))
        to_insert: list[dict] = []
        conflicts: list[dict] = []
        unchanged = 0

        for code, hub_row in hub_by_code.items():
            node_row = local.get(code)
            if node_row is None:
                to_insert.append(hub_row)
                continue
            if snapshots_equal(hub_row, node_row):
                unchanged += 1
                continue
            conflicts.append(
                {
                    "codigo": code,
                    "hubSnapshot": hub_row,
                    "nodeSnapshot": node_row,
                    "diffFields": diff_fields_fn(hub_row, node_row),
                }
            )

        inserted = 0
        if to_insert:
            conn = mysql.connect()
            try:
                cur = conn.cursor()
                for row in to_insert:
                    insert_row(cur, row)
                    inserted += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return inserted, unchanged, conflicts

    inserted, unchanged, conflicts = process()
    return inserted, unchanged, len(conflicts), conflicts, skipped
