"""Digest SHA-256 del snapshot de catálogo enviado al hub (evita push repetido)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from catalog_compare import normalize_catego_snapshot, normalize_sprv_snapshot
from db_mysql import MySqlClient
from sinv_compare import normalize_sinv_snapshot

CATALOG_TABLES = frozenset({"catego", "sprv", "sinv"})


def catalog_entity_key(table_name: str, item: dict[str, Any]) -> str | None:
    table = str(table_name or "").strip().lower()
    if table == "catego":
        code = str(item.get("ccate") or "").strip()
    elif table == "sprv":
        code = str(item.get("cod_prv") or "").strip()
    elif table == "sinv":
        code = str(item.get("codigo") or "").strip()
    else:
        return None
    if not code:
        return None
    return f"{table}:{code}"


def _normalize_lote_line(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "lote": str(raw.get("lote") or "").strip(),
        "cubica": str(raw.get("cubica") or "").strip(),
        "vence": str(raw.get("vence") or "").strip() if raw.get("vence") else None,
        "existencia": float(raw.get("existencia") or 0),
        "costo": float(raw.get("costo") or 0),
        "costopro": float(raw.get("costopro") or 0),
    }


def catalog_push_digest_payload(table_name: str, item: dict[str, Any]) -> dict[str, Any]:
    """Snapshot canónico para hash (alineado con comparadores push/pull)."""
    table = str(table_name or "").strip().lower()
    if table == "catego":
        return {"master": normalize_catego_snapshot(item)}
    if table == "sprv":
        return {"master": normalize_sprv_snapshot(item)}
    if table == "sinv":
        lotes_raw = item.get("lotes")
        lotes: list[dict[str, Any]] = []
        if isinstance(lotes_raw, list):
            for row in lotes_raw:
                if isinstance(row, dict):
                    lotes.append(_normalize_lote_line(row))
        lotes.sort(
            key=lambda r: (r["cubica"], r["lote"], r["vence"] or ""),
        )
        master = normalize_sinv_snapshot(item)
        extra = {
            "existencia": float(item.get("existencia") or 0),
            "costo": float(item.get("costo") or 0),
            "costopro": float(item.get("costopro") or 0),
        }
        return {"master": master, "extra": extra, "lotes": lotes}
    raise ValueError(f"unsupported catalog table: {table_name}")


def compute_catalog_push_digest(table_name: str, item: dict[str, Any]) -> str:
    canonical = catalog_push_digest_payload(table_name, item)
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CatalogPushDigestStore:
    def __init__(self, mysql: MySqlClient, table_name: str = "catalog_push_digest"):
        self._mysql = mysql
        self._table = table_name

    def ensure_schema(self) -> None:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                  entity_key VARCHAR(80) NOT NULL,
                  table_name VARCHAR(16) NOT NULL,
                  digest CHAR(64) NOT NULL,
                  updated_at DATETIME(3) NOT NULL,
                  PRIMARY KEY (entity_key),
                  KEY idx_table_updated (table_name, updated_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
                """
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_digest(self, entity_key: str) -> str | None:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                f"SELECT digest FROM {self._table} WHERE entity_key = %s LIMIT 1",
                (entity_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return str(row.get("digest") or "").strip() or None
        finally:
            conn.close()

    def save_digest(self, entity_key: str, table_name: str, digest: str) -> None:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {self._table}(entity_key, table_name, digest, updated_at)
                VALUES (%s, %s, %s, NOW(3))
                ON DUPLICATE KEY UPDATE
                  table_name = VALUES(table_name),
                  digest = VALUES(digest),
                  updated_at = VALUES(updated_at)
                """,
                (entity_key, table_name, digest),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_digest(self, entity_key: str) -> None:
        conn = self._mysql.connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"DELETE FROM {self._table} WHERE entity_key = %s",
                (entity_key,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
