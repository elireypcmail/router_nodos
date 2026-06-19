"""Códigos alternos de producto (tabla calternos: cpadre, chijo, id autoincrement)."""

from __future__ import annotations

from typing import Any

from db.inventario_identifier_conflict import find_identifier_conflicts

CHIJO_MAX_LEN = 30


def normalize_codigos_alternos(values: list[str] | None) -> list[str]:
    """Normaliza, deduplica y valida códigos alternos (orden de primera aparición)."""
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        code = str(raw or "").strip()
        if not code:
            continue
        if len(code) > CHIJO_MAX_LEN:
            raise ValueError(f"codigo alterno too long (max {CHIJO_MAX_LEN}): {code[:20]}")
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def fetch_codigos_alternos(cur, cpadre: str) -> list[str]:
    cur.execute(
        """
        SELECT chijo
        FROM calternos
        WHERE cpadre = %s
        ORDER BY id ASC
        """,
        (cpadre.strip(),),
    )
    rows = cur.fetchall() or []
    return [str(row[0] if isinstance(row, (list, tuple)) else row.get("chijo") or "") for row in rows]


def fetch_codigos_alternos_by_padres(cur, cpadres: list[str]) -> dict[str, list[str]]:
    codes = [c.strip() for c in cpadres if c and str(c).strip()]
    if not codes:
        return {}
    placeholders = ", ".join(["%s"] * len(codes))
    cur.execute(
        f"""
        SELECT cpadre, chijo
        FROM calternos
        WHERE cpadre IN ({placeholders})
        ORDER BY cpadre ASC, id ASC
        """,
        tuple(codes),
    )
    rows = cur.fetchall() or []
    out: dict[str, list[str]] = {c: [] for c in codes}
    for row in rows:
        if isinstance(row, dict):
            padre = str(row.get("cpadre") or "")
            chijo = str(row.get("chijo") or "")
        else:
            padre = str(row[0] or "")
            chijo = str(row[1] or "")
        if padre in out and chijo:
            out[padre].append(chijo)
    return out


def insert_codigos_alternos(cur, cpadre: str, chijos: list[str]) -> list[str]:
    """Inserta códigos alternos; devuelve la lista insertada. Omite duplicados ya ligados al mismo padre."""
    parent = cpadre.strip()
    if not parent:
        raise ValueError("cpadre is required")
    normalized = normalize_codigos_alternos(chijos)
    if not normalized:
        return []

    existing = set(fetch_codigos_alternos(cur, parent))
    inserted: list[str] = []
    for chijo in normalized:
        if chijo == parent:
            raise ValueError(f"codigo alterno cannot equal product code: {chijo}")
        conflicts = find_identifier_conflicts(cur, [chijo], exclude_codigo=parent)
        if conflicts:
            raise ValueError(conflicts[0].message())
        if chijo in existing:
            continue
        cur.execute(
            "INSERT INTO calternos (cpadre, chijo) VALUES (%s, %s)",
            (parent, chijo),
        )
        existing.add(chijo)
        inserted.append(chijo)
    return inserted


def replace_codigos_alternos(cur, cpadre: str, chijos: list[str]) -> list[str]:
    """Reemplaza todos los alternos del producto."""
    parent = cpadre.strip()
    if not parent:
        raise ValueError("cpadre is required")
    cur.execute("DELETE FROM calternos WHERE cpadre = %s", (parent,))
    return insert_codigos_alternos(cur, parent, chijos)


def attach_codigos_alternos_to_items(cur, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    by_padre = fetch_codigos_alternos_by_padres(
        cur,
        [str(row.get("codigo") or "") for row in items],
    )
    for row in items:
        codigo = str(row.get("codigo") or "")
        row["codigos_alternos"] = by_padre.get(codigo, [])
