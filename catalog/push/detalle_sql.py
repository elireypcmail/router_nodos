"""Fragmentos SQL de detalle para push catálogo (sin imports de hub — evita ciclos)."""

DETALLE_PUSH_FIELDS = (
    "codigod",
    "lote",
    "cubica",
    "nubica",
    "existencia",
    "vence",
    "elabora",
    "calidad",
    "costo",
    "costopro",
)

_detalle_cols = ", ".join(f"d.{c}" for c in DETALLE_PUSH_FIELDS if c != "nubica")
DETALLE_PUSH_SELECT = f"{_detalle_cols}, u.nubica"

DETALLE_PUSH_FROM = """
FROM detalle d
LEFT JOIN ubica u ON d.cubica = u.cubica
"""
