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


def validate_laboratorio_codigo(cur, laboratorio_codigo: str) -> str:
    """Valida que el código exista en general y devuelve cgeneral para sinv.cgeneral."""
    code = (laboratorio_codigo or "").strip()
    row = fetch_laboratorio_by_code(cur, code)
    if row is None:
        raise ValueError("Invalid laboratorio_codigo")
    return str(row["cgeneral"]).strip()


def attach_laboratory_to_items(cur, rows: list[dict]) -> None:
    """Enriquece filas sinv con laboratorio (objeto o null)."""
    codes = {
        str(row.get("cgeneral") or "").strip()
        for row in rows
        if str(row.get("cgeneral") or "").strip()
    }
    by_code: dict[str, dict] = {}
    if codes:
        placeholders = ", ".join(["%s"] * len(codes))
        cur.execute(
            f"""
            SELECT cgeneral, ngeneral
            FROM general
            WHERE cgeneral IN ({placeholders})
            """,
            tuple(codes),
        )
        for raw in cur.fetchall() or []:
            row = cursor_row_as_dict(raw, GENERAL_LAB_COLUMNS)
            if not row:
                continue
            by_code[str(row["cgeneral"]).strip()] = dict(row)

    for row in rows:
        stored = str(row.get("cgeneral") or "").strip()
        if not stored:
            row["laboratorio"] = None
        elif stored in by_code:
            row["laboratorio"] = by_code[stored]
        else:
            row["laboratorio"] = {"cgeneral": stored}
