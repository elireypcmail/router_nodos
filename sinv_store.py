"""Upsert de inventario (sinv) alineado con hub product-sync-item y resumen/sinv.txt."""

from __future__ import annotations

from datetime import date, datetime
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

# Columnas sinv derivadas al aplicar catálogo del hub (no comparan en pull de maestros).
SINV_LOCAL_FIELDS = ("corigen", "fcrea", "descontinuador")
SINV_PULL_FETCH_FIELDS = SINV_HUB_FIELDS + SINV_LOCAL_FIELDS

SINV_DESCONTINUADOR_FROM_HUB = "N/A"
SINV_CORIGEN_MAX_LEN = 15

# Metadatos de sync push/pull que no son columnas sinv.
SINV_SYNC_META_KEYS = frozenset(
    {"action", "lotes", "existencia", "costo", "costopro", "costoant"}
)

# Solo corigen se actualiza en ON DUPLICATE KEY UPDATE (fcrea/descontinuador: insert).
SINV_UPDATE_LOCAL_FIELDS = ("corigen",)
SINV_INSERT_ONLY_LOCAL_FIELDS = frozenset({"fcrea", "descontinuador"})


def _parse_hub_fcrea(raw_row: dict) -> str | None:
    """Map hub fcrea/createdAt to YYYY-MM-DD for sinv.fcrea."""
    for key in ("fcrea", "createdAt", "created_at"):
        val = raw_row.get(key)
        if val is None:
            continue
        if isinstance(val, date) and not isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, datetime):
            return val.date().isoformat()
        text = str(val).strip()
        if not text:
            continue
        if "T" in text:
            return text.split("T", 1)[0]
        if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
            return text[:10]
        return text
    return None


def _effective_barra(row: dict[str, Any]) -> str:
    """Código de barras; si viene vacío, usa codigo."""
    codigo = str(row.get("codigo") or "").strip()
    barra = str(row.get("barra") or "").strip()
    return barra or codigo


def enrich_sinv_from_hub(normalized: dict[str, Any], raw_row: dict) -> dict[str, Any]:
    """Deriva barra (fallback codigo), corigen (= barra efectiva), fcrea y descontinuador."""
    out = dict(normalized)
    codigo = str(out.get("codigo") or "").strip()
    barra = _effective_barra(out)
    if barra and not str(out.get("barra") or "").strip():
        out["barra"] = barra
    if barra:
        out["corigen"] = barra[:SINV_CORIGEN_MAX_LEN]
    elif codigo:
        out["corigen"] = codigo[:SINV_CORIGEN_MAX_LEN]
    out["descontinuador"] = SINV_DESCONTINUADOR_FROM_HUB
    fcrea = _parse_hub_fcrea(raw_row)
    if fcrea:
        out["fcrea"] = fcrea
    return out


def _hub_row_has_activo(raw_row: dict) -> bool:
    if "activo" not in raw_row:
        return False
    val = raw_row.get("activo")
    if val is None:
        return False
    return str(val).strip() != ""


def prepare_sinv_upsert(row: dict) -> dict[str, Any]:
    """Normalize hub/PGMQ row to sinv snapshot plus derived local fields."""
    from sinv_compare import normalize_sinv_snapshot

    clean = {k: v for k, v in row.items() if k not in SINV_SYNC_META_KEYS}
    has_activo = _hub_row_has_activo(clean)
    normalized = normalize_sinv_snapshot(clean)
    if not has_activo:
        normalized["activo"] = 1
    return enrich_sinv_from_hub(normalized, clean)


def augment_sinv_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Completa barra (fallback codigo) y corigen acorde."""
    codigo = str(patch.get("codigo") or "").strip()
    barra = _effective_barra(patch)
    if barra and not str(patch.get("barra") or "").strip():
        patch["barra"] = barra
    effective = barra or codigo
    if effective:
        patch["corigen"] = effective[:SINV_CORIGEN_MAX_LEN]
    return patch


def sinv_local_empty_patch(
    hub_prepared: dict[str, Any], node_row: dict
) -> dict[str, Any] | None:
    """
    Rellena corigen/fcrea/descontinuador vacíos en tienda cuando el maestro hub coincide.
    hub_prepared debe venir de prepare_sinv_upsert().
    """
    codigo = str(hub_prepared.get("codigo") or "").strip()
    if not codigo:
        return None

    patch: dict[str, Any] = {"codigo": codigo}
    changed = False

    barra = _effective_barra(hub_prepared)
    local_barra = str(node_row.get("barra") or "").strip()
    if not local_barra and barra:
        patch["barra"] = barra
        changed = True

    local_corigen = str(node_row.get("corigen") or "").strip()
    hub_corigen = (barra or codigo)[:SINV_CORIGEN_MAX_LEN]
    if not local_corigen and hub_corigen:
        patch["corigen"] = hub_corigen
        changed = True

    local_fcrea = node_row.get("fcrea")
    hub_fcrea = hub_prepared.get("fcrea")
    if (
        (local_fcrea is None or str(local_fcrea).strip() == "")
        and hub_fcrea
        and str(hub_fcrea).strip()
    ):
        patch["fcrea"] = str(hub_fcrea).strip()[:10]
        changed = True

    local_desc = str(node_row.get("descontinuador") or "").strip()
    if not local_desc:
        patch["descontinuador"] = SINV_DESCONTINUADOR_FROM_HUB
        changed = True

    return patch if changed else None


def _value_for_column(normalized: dict[str, Any], key: str, raw_row: dict) -> Any:
    if key in {"recipe", "cfrio", "activo"}:
        return normalized.get(key, 0)
    if key == "existencia":
        raw = raw_row.get("existencia")
        if raw is None:
            return 0
        return raw
    if key in {"precio1", "pg1", "stockmin", "stockmax", "porvg"}:
        return normalized.get(key, 0)
    if key == "fcrea":
        val = normalized.get("fcrea")
        return val if val else None
    return normalized.get(key, "")


def upsert_sinv(
    cur,
    row: dict,
    *,
    patch_keys: set[str] | None = None,
) -> None:
    """
    INSERT o UPDATE por codigo (UNIQUE codigo_2).

    patch_keys: en ON DUPLICATE KEY UPDATE solo toca esas columnas (p. ej. barra).
    INSERT siempre escribe el snapshot completo normalizado + campos locales.
    """
    normalized = prepare_sinv_upsert(row)
    codigo = str(normalized.get("codigo") or "").strip()
    if not codigo:
        raise ValueError("inventory row requires codigo")

    insert_fields = list(SINV_UPDATE_FIELDS)
    for key in SINV_LOCAL_FIELDS:
        val = normalized.get(key)
        if val is not None and str(val).strip() != "":
            insert_fields.append(key)
    if row.get("existencia") is not None and "existencia" not in insert_fields:
        insert_fields.append("existencia")

    if patch_keys is not None:
        allowed = {k for k in patch_keys if k in insert_fields}
        update_fields = [k for k in insert_fields if k in allowed]
        if not update_fields:
            update_fields = insert_fields
    else:
        update_fields = list(SINV_UPDATE_FIELDS)
        for key in SINV_UPDATE_LOCAL_FIELDS:
            if key in insert_fields and key not in update_fields:
                update_fields.append(key)

    insert_cols = ["codigo", *insert_fields]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    update_clause = ", ".join(f"{c} = VALUES({c})" for c in update_fields)

    values: list[Any] = [codigo]
    for key in insert_fields:
        values.append(_value_for_column(normalized, key, row))

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
