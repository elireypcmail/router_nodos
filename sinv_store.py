"""Upsert de inventario (sinv) alineado con hub product-sync-item y resumen/sinv.txt."""

from __future__ import annotations

from typing import Any

# Campos que envía el hub en PGMQ (sin existencia: la tienda la mantiene local).
SINV_HUB_FIELDS = (
    "codigo",
    "descrip",
    "ccate",
    "cod_prv",
    "precio1",
    "pg1",
    "barra",
    "referencia",
    "componente",
    "stockmin",
    "stockmax",
    "recipe",
    "cfrio",
    "activo",
    "porvg",
)

SINV_UPDATE_FIELDS = tuple(f for f in SINV_HUB_FIELDS if f != "codigo")


def _str_field(row: dict, key: str, default: str = "") -> str:
    raw = row.get(key)
    if raw is None:
        return default
    return str(raw).strip()


def _num_field(row: dict, key: str, default: float | int | None = None):
    if key not in row or row.get(key) is None:
        return default
    return row.get(key)


def upsert_sinv(cur, row: dict) -> None:
    """
    INSERT o UPDATE por codigo (UNIQUE codigo_2).
    No pisa existencia en UPDATE salvo que venga explícita en row (API local).
    """
    codigo = _str_field(row, "codigo")
    if not codigo:
        raise ValueError("inventario requiere codigo")

    update_fields = list(SINV_UPDATE_FIELDS)
    if row.get("existencia") is not None:
        update_fields.append("existencia")

    insert_cols = ["codigo", *update_fields]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    update_clause = ", ".join(f"{c} = VALUES({c})" for c in update_fields)

    values: list[Any] = [codigo]
    for key in update_fields:
        if key in {"recipe", "cfrio", "activo"}:
            values.append(_num_field(row, key, 0))
        elif key == "existencia":
            values.append(_num_field(row, key, 0))
        elif key in {"precio1", "pg1", "stockmin", "stockmax", "porvg"}:
            values.append(_num_field(row, key, 0))
        else:
            values.append(_str_field(row, key))

    cur.execute(
        f"""
        INSERT INTO sinv ({col_list})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {update_clause}
        """,
        tuple(values),
    )


def delete_sinv(cur, codigo: str) -> int:
    cur.execute("DELETE FROM sinv WHERE codigo = %s", (codigo.strip(),))
    return int(cur.rowcount or 0)
