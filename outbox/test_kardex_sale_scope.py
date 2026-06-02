"""Tests de alcance kardex → índice diariovi (sin MySQL)."""

import unittest

from sync.jobs.kardex_sale_scope import build_sale_erp_scoped_to_kardex_exists


class _FakeColCache:
    def __init__(self, tables: dict[str, set[str]]) -> None:
        self._tables = tables

    def columns(self, _cur: object, table: str) -> set[str]:
        return self._tables.get(table, set())


class TestKardexSaleScope(unittest.TestCase):
    def test_exists_sql_uses_kardex_ventas_filter(self) -> None:
        cache = _FakeColCache(
            {
                "kardex": {"codigo", "numero", "ventas", "contador", "fecha"},
                "diariovi": {"codigo", "numero", "cantidad", "contador", "fecha"},
            }
        )
        k_where = ["IFNULL(k.ventas, 0) <> 0", "TRIM(k.codigo) = %s"]
        k_params = ["FF23834"]
        sql, params = build_sale_erp_scoped_to_kardex_exists(
            "diariovi",
            object(),
            cache,
            k_where,
            k_params,
        )
        self.assertIn("EXISTS", sql)
        self.assertIn("IFNULL(k.ventas, 0) <> 0", sql)
        self.assertIn("TRIM(k.codigo) = %s", sql)
        self.assertEqual(params, ("FF23834",))


if __name__ == "__main__":
    unittest.main()
