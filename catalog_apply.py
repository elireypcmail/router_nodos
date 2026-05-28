"""Aplicar filas de catálogo del hub en MySQL local."""

from __future__ import annotations

import logging

from sprv_store import upsert_sprv
from sinv_store import upsert_sinv

logger = logging.getLogger("multishop.sync_apply")


def apply_categoria_row(cur, it: dict) -> None:
    ccate = str(it.get("ccate") or "").strip()
    ncate = str(it.get("ncate") or "").strip()
    if not ccate or not ncate:
        raise ValueError("categoría incompleta")
    cur.execute(
        """
        INSERT INTO catego (ccate, ncate, pganancia, pdescu)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          ncate = VALUES(ncate),
          pganancia = VALUES(pganancia),
          pdescu = VALUES(pdescu)
        """,
        (ccate, ncate, it.get("pganancia"), it.get("pdescu")),
    )


def apply_proveedor_row(cur, it: dict) -> None:
    upsert_sprv(cur, it)


def apply_inventario_row(cur, it: dict) -> None:
    upsert_sinv(cur, it)


def apply_inventario_dependency_rows(
    cur,
    *,
    categoria_row: dict | None,
    proveedor_row: dict | None,
) -> None:
    """Upsert de categoría/proveedor del hub en la misma transacción que sinv."""
    if categoria_row and isinstance(categoria_row, dict):
        logger.info(
            "[apply-from-hub] inventario deps: aplicando categoría ccate=%s",
            str(categoria_row.get("ccate") or "").strip(),
        )
        apply_categoria_row(cur, categoria_row)
    if proveedor_row and isinstance(proveedor_row, dict):
        logger.info(
            "[apply-from-hub] inventario deps: aplicando proveedor cod_prv=%s",
            str(proveedor_row.get("cod_prv") or "").strip(),
        )
        apply_proveedor_row(cur, proveedor_row)


def assert_inventario_dependencies(cur, row: dict) -> None:
    ccate = str(row.get("ccate") or "").strip()
    cod_prv = str(row.get("cod_prv") or "").strip()
    codigo = str(row.get("codigo") or "").strip()
    if ccate:
        cur.execute("SELECT 1 FROM catego WHERE ccate = %s LIMIT 1", (ccate,))
        if not cur.fetchone():
            logger.warning(
                "[apply-from-hub] dependencia faltante: categoría %s (producto %s)",
                ccate,
                codigo or "?",
            )
            raise ValueError(f"categoría {ccate} no existe en la tienda")
    if cod_prv:
        cur.execute("SELECT 1 FROM sprv WHERE cod_prv = %s LIMIT 1", (cod_prv,))
        if not cur.fetchone():
            logger.warning(
                "[apply-from-hub] dependencia faltante: proveedor %s (producto %s)",
                cod_prv,
                codigo or "?",
            )
            raise ValueError(f"proveedor {cod_prv} no existe en la tienda")
