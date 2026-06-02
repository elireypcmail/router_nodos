"""Tipos compartidos para sync transaccional (marca vive en el hub)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TransactionWatermark:
    fecha: str
    contador: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"fecha": self.fecha}
        if self.contador is not None:
            out["contador"] = self.contador
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TransactionWatermark | None:
        if not raw or not isinstance(raw, dict):
            return None
        fecha = str(raw.get("fecha") or "").strip()[:10]
        if not fecha:
            return None
        cont_raw = raw.get("contador")
        contador = (
            int(cont_raw)
            if cont_raw is not None and str(cont_raw).strip() != ""
            else None
        )
        return cls(fecha=fecha, contador=contador)


def parse_since_query(
    since_fecha: str | None,
    since_contador: int | None = None,
) -> TransactionWatermark | None:
    fecha = str(since_fecha or "").strip()[:10]
    if not fecha:
        return None
    return TransactionWatermark(fecha=fecha, contador=since_contador)


def max_watermark_from_rows(rows: list[dict[str, Any]]) -> TransactionWatermark | None:
    best: TransactionWatermark | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        fecha = str(row.get("fecha") or "").strip()[:10]
        if not fecha:
            continue
        cont_raw = row.get("contador")
        if cont_raw is None or str(cont_raw).strip() == "":
            cont_raw = row.get("indice")
        contador: int | None
        try:
            contador = (
                int(cont_raw)
                if cont_raw is not None and str(cont_raw).strip() != ""
                else None
            )
        except (TypeError, ValueError):
            contador = None
        candidate = TransactionWatermark(fecha=fecha, contador=contador)
        if best is None or _watermark_gt(candidate, best):
            best = candidate
    return best


def merge_watermark(
    current: TransactionWatermark | None,
    rows: list[dict[str, Any]],
) -> TransactionWatermark | None:
    candidate = max_watermark_from_rows(rows)
    if candidate is None:
        return current
    if current is None:
        return candidate
    return candidate if _watermark_gt(candidate, current) else current


def _watermark_gt(a: TransactionWatermark, b: TransactionWatermark) -> bool:
    if a.fecha > b.fecha:
        return True
    if a.fecha < b.fecha:
        return False
    a_cont = a.contador if a.contador is not None else -1
    b_cont = b.contador if b.contador is not None else -1
    return a_cont > b_cont
