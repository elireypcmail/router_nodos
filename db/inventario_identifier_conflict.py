"""Unicidad cruzada de SKU, código de barras y alternos entre productos."""

from __future__ import annotations

from dataclasses import dataclass

from db.cursor_row import cursor_row_as_dict


@dataclass(frozen=True)
class IdentifierConflict:
    identifier: str
    kind: str
    owner_codigo: str

    def message(self) -> str:
        return (
            f"Identifier {self.identifier!r} already used as {self.kind} "
            f"of product {self.owner_codigo!r}"
        )


def collect_product_identifiers(
    codigo: str,
    barra: str | None,
    alternos: list[str] | None,
) -> list[str]:
    """SKU, barra efectiva (barra o codigo si vacía) y alternos, sin duplicados."""
    parent = (codigo or "").strip()
    eff_barra = (barra or "").strip() or parent
    out: list[str] = []
    seen: set[str] = set()
    for raw in [parent, eff_barra, *(alternos or [])]:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _row_field(raw: object, columns: tuple[str, ...], index: int) -> str:
    row = cursor_row_as_dict(raw, columns)
    if not row:
        return ""
    return str(row.get(columns[index]) or "").strip()


def find_identifier_conflicts(
    cur,
    identifiers: list[str],
    *,
    exclude_codigo: str,
) -> list[IdentifierConflict]:
    """Devuelve conflictos con otros productos (orden de `identifiers`)."""
    if not identifiers:
        return []

    exclude = (exclude_codigo or "").strip()
    id_set = set(identifiers)
    by_ident: dict[str, IdentifierConflict] = {}
    placeholders = ", ".join(["%s"] * len(identifiers))
    params = tuple(identifiers)

    cur.execute(
        f"SELECT codigo FROM sinv WHERE codigo IN ({placeholders})",
        params,
    )
    for raw in cur.fetchall() or []:
        owner = _row_field(raw, ("codigo",), 0)
        if not owner or owner not in id_set or owner == exclude:
            continue
        by_ident.setdefault(owner, IdentifierConflict(owner, "sku", owner))

    cur.execute(
        f"""
        SELECT codigo, barra FROM sinv
        WHERE barra IN ({placeholders})
          AND TRIM(COALESCE(barra, '')) <> ''
        """,
        params,
    )
    for raw in cur.fetchall() or []:
        owner = _row_field(raw, ("codigo", "barra"), 0)
        barra = _row_field(raw, ("codigo", "barra"), 1)
        if not barra or barra not in id_set or owner == exclude:
            continue
        by_ident.setdefault(barra, IdentifierConflict(barra, "barcode", owner))

    cur.execute(
        f"SELECT chijo, cpadre FROM calternos WHERE chijo IN ({placeholders})",
        params,
    )
    for raw in cur.fetchall() or []:
        chijo = _row_field(raw, ("chijo", "cpadre"), 0)
        cpadre = _row_field(raw, ("chijo", "cpadre"), 1)
        if not chijo or chijo not in id_set or cpadre == exclude:
            continue
        by_ident.setdefault(
            chijo,
            IdentifierConflict(chijo, "alternate code", cpadre),
        )

    return [by_ident[i] for i in identifiers if i in by_ident]


def assert_product_identifiers_available(
    cur,
    codigo: str,
    barra: str | None,
    alternos: list[str] | None,
    *,
    exclude_codigo: str | None = None,
) -> None:
    """Lanza ValueError si algún identificador ya existe en otro producto."""
    parent = (codigo or "").strip()
    if not parent:
        raise ValueError("codigo is required")
    exclude = (exclude_codigo or parent).strip()
    identifiers = collect_product_identifiers(parent, barra, alternos)
    conflicts = find_identifier_conflicts(cur, identifiers, exclude_codigo=exclude)
    if conflicts:
        raise ValueError(conflicts[0].message())
