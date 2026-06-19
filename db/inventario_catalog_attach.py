"""Enriquece filas sinv con categoría (catego) y proveedor (sprv)."""

from __future__ import annotations

from db.cursor_row import cursor_row_as_dict

CATEGO_LOOKUP_COLUMNS = ("ccate", "ncate")
SPRV_LOOKUP_COLUMNS = ("cod_prv", "nom_prv")


def _batch_lookup(
    cur,
    table: str,
    key_col: str,
    value_cols: tuple[str, ...],
    keys: set[str],
) -> dict[str, dict]:
    if not keys:
        return {}
    placeholders = ", ".join(["%s"] * len(keys))
    cols = ", ".join(value_cols)
    cur.execute(
        f"""
        SELECT {cols}
        FROM {table}
        WHERE {key_col} IN ({placeholders})
        """,
        tuple(keys),
    )
    by_key: dict[str, dict] = {}
    for raw in cur.fetchall() or []:
        row = cursor_row_as_dict(raw, value_cols)
        if not row:
            continue
        by_key[str(row[key_col]).strip()] = row
    return by_key


def attach_category_provider_to_items(cur, rows: list[dict]) -> None:
    """Añade categoria_* y proveedor_* resueltos desde catego/sprv."""
    category_codes = {
        str(row.get("ccate") or "").strip()
        for row in rows
        if str(row.get("ccate") or "").strip()
    }
    provider_codes = {
        str(row.get("cod_prv") or "").strip()
        for row in rows
        if str(row.get("cod_prv") or "").strip()
    }

    by_category = _batch_lookup(
        cur, "catego", "ccate", CATEGO_LOOKUP_COLUMNS, category_codes
    )
    by_provider = _batch_lookup(
        cur, "sprv", "cod_prv", SPRV_LOOKUP_COLUMNS, provider_codes
    )

    for row in rows:
        ccate = str(row.get("ccate") or "").strip()
        if ccate and ccate in by_category:
            cat = by_category[ccate]
            row["categoria_ccate"] = str(cat["ccate"]).strip()
            row["categoria_ncate"] = str(cat["ncate"]).strip()
        elif ccate:
            row["categoria_ccate"] = ccate
            row["categoria_ncate"] = None
        else:
            row["categoria_ccate"] = None
            row["categoria_ncate"] = None

        cod_prv = str(row.get("cod_prv") or "").strip()
        if cod_prv and cod_prv in by_provider:
            prv = by_provider[cod_prv]
            row["proveedor_cod_prv"] = str(prv["cod_prv"]).strip()
            row["proveedor_nom_prv"] = str(prv["nom_prv"]).strip()
        elif cod_prv:
            row["proveedor_cod_prv"] = cod_prv
            row["proveedor_nom_prv"] = None
        else:
            row["proveedor_cod_prv"] = None
            row["proveedor_nom_prv"] = None
