"""Tests fórmulas precio/margen (sin MySQL)."""

import unittest

from db.product_price_formula import (
    pg_from_costopro_and_price_ex_tax,
    price_ex_tax_from_inc_tax,
    price_from_costopro_pg_and_tax,
    price_inc_tax_from_ex_tax,
    price_ui_round_bs,
)


class TestProductPriceFormulaInverse(unittest.TestCase):
    def test_pg_inverse_round_trip(self):
        cpp = 30.46
        pg = 20.0525
        psi = price_from_costopro_pg_and_tax(cpp, pg, tax_pct=0)
        self.assertIsNotNone(psi)
        back = pg_from_costopro_and_price_ex_tax(cpp, float(psi))
        self.assertIsNotNone(back)
        self.assertAlmostEqual(back, pg, places=3)

    def test_pg_invalid_when_price_at_or_below_cpp(self):
        self.assertIsNone(pg_from_costopro_and_price_ex_tax(10.0, 10.0))
        self.assertIsNone(pg_from_costopro_and_price_ex_tax(10.0, 5.0))

    def test_price_inc_tax_from_ex_tax_with_iva(self):
        self.assertEqual(
            price_inc_tax_from_ex_tax(100.0, 16.0, round_fn=price_ui_round_bs),
            116.0,
        )

    def test_price_ex_tax_from_inc_tax_with_iva(self):
        self.assertEqual(
            price_ex_tax_from_inc_tax(116.0, 16.0, round_fn=price_ui_round_bs),
            100.0,
        )

    def test_tax_round_trip(self):
        psi = price_ui_round_bs(45.625)
        pci = price_inc_tax_from_ex_tax(psi, 16.0, round_fn=price_ui_round_bs)
        self.assertIsNotNone(pci)
        back = price_ex_tax_from_inc_tax(float(pci), 16.0, round_fn=price_ui_round_bs)
        self.assertEqual(back, psi)


if __name__ == "__main__":
    unittest.main()
