"""Enriquece filas sinv con categoría (catego) y proveedor (sprv)."""

from __future__ import annotations

from db.cursor_row import cursor_row_as_dict

CATEGO_LOOKUP_COLUMNS = ("ccate", "ncate", "pganancia", "pdescu")
SPRV_LOOKUP_COLUMNS = (
    "cod_prv",
    "nom_prv",
    "rif_prv",
    "dir1_prv",
    "dir2_prv",
    "dir3_prv",
    "tel_prv",
    "email1_prv",
    "email2_prv",
    "rep_prv",
    "especial",
    "numcuenta",
)


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
        by_key[str(row[key_col]).strip()] = dict(row)
    return by_key


def attach_category_provider_to_items(cur, rows: list[dict]) -> None:
    """Añade categoria y proveedor como objetos completos desde catego/sprv."""
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
            row["categoria"] = by_category[ccate]
        elif ccate:
            row["categoria"] = {"ccate": ccate}
        else:
            row["categoria"] = None

        cod_prv = str(row.get("cod_prv") or "").strip()
        if cod_prv and cod_prv in by_provider:
            row["proveedor"] = by_provider[cod_prv]
        elif cod_prv:
            row["proveedor"] = {"cod_prv": cod_prv}
        else:
            row["proveedor"] = None
