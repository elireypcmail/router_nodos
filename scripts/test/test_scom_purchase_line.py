"""Tests build_scom_purchase_line (sin MySQL)."""

import unittest

from scom_purchase_line import DEFAULT_SCOM_FACTOR, build_scom_purchase_line


class TestBuildScomPurchaseLine(unittest.TestCase):
    def test_exento_sin_iva_y_factor_default(self) -> None:
        sinv = {
            "porvg": 0,
            "pg1": 25.0,
            "precio1": 50.0,
            "costo": 10.0,
            "costopro": 10.0,
        }
        line = build_scom_purchase_line(
            sinv,
            cantidad=1.0,
            costo_unitario=100.0,
            costo_antes=10.0,
            costopro_antes=10.0,
            existencia_antes=5.0,
            factor=DEFAULT_SCOM_FACTOR,
        )
        self.assertEqual(line["exento"], 100.0)
        self.assertEqual(line["base1"], 0.0)
        self.assertEqual(line["iva1"], 0.0)
        self.assertEqual(line["factor"], DEFAULT_SCOM_FACTOR)
        self.assertAlmostEqual(line["costodiv"], 100.0 / 400.0)
        self.assertAlmostEqual(line["nuevocosto"], 100.0)
        self.assertAlmostEqual(line["costopro"], 25.0)  # CPP ponderado

    def test_iva_desde_porvg(self) -> None:
        sinv = {"porvg": 16.0, "pg1": 0, "precio1": 0}
        line = build_scom_purchase_line(
            sinv,
            cantidad=6.0,
            costo_unitario=1462.61,
            costo_antes=1000.0,
            costopro_antes=1000.0,
            existencia_antes=0.0,
            factor=400.0,
        )
        self.assertEqual(line["exento"], 0.0)
        self.assertAlmostEqual(line["subtotal2"], 8775.66)
        self.assertAlmostEqual(line["base1"], 8775.66)
        self.assertAlmostEqual(line["iva1"], 1404.1056)

    def test_nprecio_desde_pg_y_cpp(self) -> None:
        sinv = {"porvg": 0, "pg1": 23.48, "precio1": 7095.60, "costopro": 4000.0}
        line = build_scom_purchase_line(
            sinv,
            cantidad=1.0,
            costo_unitario=5429.69,
            costo_antes=4000.0,
            costopro_antes=4000.0,
            existencia_antes=0.0,
            factor=510.7873,
        )
        self.assertAlmostEqual(line["costopro"], 5429.69)
        self.assertAlmostEqual(line["nprecio1"], 7095.60, places=0)
        self.assertAlmostEqual(line["costodiv"], 10.630041, places=2)


if __name__ == "__main__":
    unittest.main()
