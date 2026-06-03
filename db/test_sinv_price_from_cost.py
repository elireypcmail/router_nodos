"""Tests sin MySQL: precio desde costopro + pg programado."""

import unittest

from db.sinv_price_from_cost import (
    price_from_costopro_and_pg,
    recalc_programmed_prices_from_row,
)


class TestSinvPriceFromCost(unittest.TestCase):
    def test_margin_formula_matches_erp_sample(self):
        # F13353 en sistema-20260531.sql
        self.assertEqual(price_from_costopro_and_pg(30.46, 20.0525), 38.10)
        # FF10727
        self.assertEqual(price_from_costopro_and_pg(372.45, 81.9272), 2060.83)

    def test_pg_zero_skips_list(self):
        row = {"pg1": 0, "pg2": 15.0, "precio1": 100, "precio2": 0}
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
