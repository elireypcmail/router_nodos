"""Tests sin MySQL: precio desde costopro + pg programado + IVA."""

import unittest

from db.product_price_formula import price_from_costopro_pg_and_tax, price_ui_round_bs
from db.sinv_price_from_cost import (
    price_from_costopro_and_pg,
    recalc_programmed_prices_from_row,
)


class TestSinvPriceFromCost(unittest.TestCase):
    def test_margin_formula_without_tax(self):
        self.assertEqual(
            price_from_costopro_pg_and_tax(30.46, 20.0525, tax_pct=0),
            38.10,
        )

    def test_margin_formula_with_iva(self):
        # costopro=2.30, pg1=20, porvg=16 → base=2.875, final=3.335
        base = 2.30 / (1 - 20 / 100)
        self.assertAlmostEqual(base, 2.875, places=3)
        self.assertEqual(
            price_from_costopro_pg_and_tax(2.30, 20, tax_pct=16),
            round(2.875 * 1.16, 2),
        )

    def test_pg_zero_skips_list(self):
        row = {"pg1": 0, "pg2": 15.0, "porvg": 0, "precio1": 100, "precio2": 0}
        out = recalc_programmed_prices_from_row(row, costopro=10.0)
        self.assertNotIn("precio1", out)
        self.assertIn("precio2", out)
        self.assertEqual(out["precio2"], price_from_costopro_and_pg(10.0, 15.0))

    def test_invalid_pg_returns_none(self):
        self.assertIsNone(price_from_costopro_and_pg(10, 0))
        self.assertIsNone(price_from_costopro_and_pg(0, 20))
        self.assertIsNone(price_from_costopro_and_pg(10, 100))


if __name__ == "__main__":
    unittest.main()
