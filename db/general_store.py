"""Laboratorios (tabla general): cgeneral, ngeneral, id."""

from __future__ import annotations

from db.cursor_row import cursor_row_as_dict

GENERAL_LAB_COLUMNS = ("cgeneral", "ngeneral")


def fetch_laboratorio_by_code(cur, cgeneral: str) -> dict | None:
    code = (cgeneral or "").strip()
    if not code:
        return None
    cur.execute(
        """
        SELECT cgeneral, ngeneral
        FROM general
        WHERE cgeneral = %s
        LIMIT 1
        """,
        (code,),
    )
    return cursor_row_as_dict(cur.fetchone(), GENERAL_LAB_COLUMNS)


def fetch_laboratorio_by_name(cur, ngeneral: str) -> dict | None:
    name = (ngeneral or "").strip()
    if not name:
        return None
    cur.execute(
        """
        SELECT cgeneral, ngeneral
        FROM general
        WHERE ngeneral = %s
        LIMIT 1
        """,
        (name,),
    )
    return cursor_row_as_dict(cur.fetchone(), GENERAL_LAB_COLUMNS)


def resolve_laboratorio_codigo_to_sinv(cur, laboratorio_codigo: str) -> str:
    """Devuelve ngeneral para guardar en sinv.cgeneral."""
    row = fetch_laboratorio_by_code(cur, laboratorio_codigo)
    if row is None:
        raise ValueError("Invalid laboratorio_codigo")
    return str(row["ngeneral"]).strip()


def attach_laboratory_to_items(cur, rows: list[dict]) -> None:
    """Enriquece filas sinv con laboratorio_cgeneral y laboratorio_ngeneral."""
    names = {
        str(row.get("cgeneral") or "").strip()
        for row in rows
        if str(row.get("cgeneral") or "").strip()
    }
    by_name: dict[str, dict] = {}
    if names:
        placeholders = ", ".join(["%s"] * len(names))
        cur.execute(
            f"""
            SELECT cgeneral, ngeneral
            FROM general
            WHERE ngeneral IN ({placeholders})
            """,
            tuple(names),
        )
        for raw in cur.fetchall() or []:
            row = cursor_row_as_dict(raw, GENERAL_LAB_COLUMNS)
            if not row:
                continue
            by_name[str(row["ngeneral"]).strip()] = row

    for row in rows:
        stored = str(row.get("cgeneral") or "").strip()
        if stored and stored in by_name:
            lab = by_name[stored]
            row["laboratorio_cgeneral"] = str(lab["cgeneral"]).strip()
            row["laboratorio_ngeneral"] = str(lab["ngeneral"]).strip()
        elif stored:
            row["laboratorio_cgeneral"] = None
            row["laboratorio_ngeneral"] = stored
        else:
            row["laboratorio_cgeneral"] = None
            row["laboratorio_ngeneral"] = None
