"""Tests de match kardex → línea venta (sin MySQL)."""

import unittest

from outbox.sale_erp_index import (
    SaleErpLineIndex,
    _index_row,
    _kardex_ventas_numero_subquery,
    lookup_sale_line_in_index,
)


class TestSaleErpMatch(unittest.TestCase):
    def test_match_prefers_numero_cantidad_over_contador(self):
        index = SaleErpLineIndex()
        _index_row(
            index,
            {
                "codigo": "FF23834",
                "numero": "1000052872",
                "cantidad": 2,
                "contador": 999,
                "precio1": 100.0,
                "subtotal2": 200.0,
            },
        )
        _index_row(
            index,
            {
                "codigo": "FF23834",
                "numero": "1000052872",
                "cantidad": 5,
                "contador": 226886,
                "costo": 25570.72,
                "subtotal2": 127853.6,
            },
        )
        payload = {
            "codigo": "FF23834",
            "numero": "1000052872",
            "cantidad": 2,
            "contador": 226886,
        }
        row = lookup_sale_line_in_index(index, payload)
        self.assertIsNotNone(row)
        self.assertEqual(float(row["precio1"]), 100.0)

    def test_kardex_numero_subquery_uses_distinct_numero(self) -> None:
        sql = _kardex_ventas_numero_subquery(["IFNULL(ventas, 0) <> 0"])
        self.assertIn("DISTINCT TRIM(numero)", sql)
        self.assertNotIn("DISTINCT TRIM(codigo)", sql)
        self.assertIn("TRIM(numero) <> ''", sql)


if __name__ == "__main__":
    unittest.main()
