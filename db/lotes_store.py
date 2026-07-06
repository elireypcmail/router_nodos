"""Consultas agregadas de lotes (tabla detalle)."""

from __future__ import annotations


def lotes_where(codigo: str) -> tuple[str, list]:
    c = (codigo or "").strip()
    where_parts = ["disponible = 'S'"]
    params: list = []
    if c:
        where_parts.append("codigo = %s")
        params.append(c)
    return "WHERE " + " AND ".join(where_parts), params


_LOTES_SELECT = """
SELECT
  codigo,
  calidad,
  MIN(vence) AS vence,
  SUM(existencia) AS existencia,
  MAX(costo) AS costo,
  MAX(costopro) AS costopro,
  MAX(costopr) AS costopr,
  MAX(costopropr) AS costopropr
FROM detalle
{where_sql}
GROUP BY codigo, calidad
ORDER BY codigo ASC, calidad ASC
"""


def count_lotes_groups(cur, where_sql: str, params: list) -> int:
    cur.execute(
        f"""
        SELECT COUNT(*) AS cnt
        FROM (
          SELECT codigo, calidad
          FROM detalle
          {where_sql}
          GROUP BY codigo, calidad
        ) AS grouped
        """,
        params,
    )
    total_row = cur.fetchone() or {}
    return int(total_row.get("cnt") or 0)


def fetch_lotes_groups(
    cur,
    where_sql: str,
    params: list,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict]:
    sql = _LOTES_SELECT.format(where_sql=where_sql)
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        cur.execute(sql, (*params, int(limit), int(offset or 0)))
    else:
        cur.execute(sql, params)
    return list(cur.fetchall() or [])
