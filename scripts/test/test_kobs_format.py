"""Tests de formato kobs ERP en simuladores (sin MySQL)."""

import unittest
from datetime import datetime

from _common import (
    erp_bs_amount_label,
    format_kobs_ajuste,
    format_kobs_compra,
    format_kobs_devolucion_compra,
    format_kobs_venta,
)


class TestKobsFormat(unittest.TestCase):
    def setUp(self) -> None:
        self.when = datetime(2026, 7, 8, 12, 37, 6)

    def test_compra(self):
        kobs = format_kobs_compra(
            "08072",
            "102",
            "COMPAÑIA ANONIMA MAFARTA (C.A. MAFARTA)",
            ind="99825",
            operador="ELIAS",
            when=self.when,
        )
        self.assertIn("Compra#: 08072 Proveedor: 102 COMPAÑIA ANONIMA MAFARTA", kobs)
        self.assertIn("Ind: 99825", kobs)
        self.assertIn("12:37:06 p. m.", kobs)
        self.assertIn("Relizado por: ELIAS", kobs)

    def test_venta_con_precios(self):
        kobs = format_kobs_venta(
            "1000052880",
            cliente="V25497333 LUIS CARLOS",
            precio_bs=2872.75,
            precio_usd=4.188034,
            tasa_usd=685.9426,
            when=self.when,
        )
        self.assertIn("Vta#: 1000052880 Cliente: V25497333 LUIS CARLOS", kobs)
        self.assertIn("Precio de Venta Bs.: 2.872,75", kobs)
        self.assertIn("USD: 4,188034", kobs)
        self.assertIn("Tasa USD: 685,942600", kobs)

    def test_ajuste(self):
        kobs = format_kobs_ajuste(
            "5032",
            accion="*Aumentar*",
            operador="ELIAS",
            when=self.when,
        )
        self.assertIn("Ajuste Nro: 0000005032", kobs)
        self.assertIn("08/07/2026", kobs)
        self.assertIn("Accion:  *Aumentar*", kobs)
        self.assertIn("Deposito Afectado:", kobs)
        self.assertIn("Motivo:", kobs)

    def test_devolucion_compra(self):
        kobs = format_kobs_devolucion_compra(
            "08072026",
            "102",
            operador="ELIAS",
            when=datetime(2026, 7, 8, 12, 47, 38),
        )
        self.assertEqual(
            kobs,
            "Dev.Compra#: 08072026 Proveedor: 102 12:47:38 p. m.  Relizado por: ELIAS",
        )

    def test_bs_amount_label(self):
        self.assertEqual(erp_bs_amount_label(147.4), "147,40")
        self.assertEqual(erp_bs_amount_label(2872.75), "2.872,75")


if __name__ == "__main__":
    unittest.main()
