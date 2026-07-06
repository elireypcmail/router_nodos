"""Tests erp_compra_effects (sin MySQL)."""

import unittest

from erp_compra_effects import (
    bs_to_usd,
    format_historial_modulo_compra,
    format_historial_usuario_erp,
)


class TestErpCompraEffects(unittest.TestCase):
    def test_bs_to_usd(self) -> None:
        self.assertAlmostEqual(bs_to_usd(150.0, 60.0), 2.5)
        self.assertIsNone(bs_to_usd(150.0, 0.0))

    def test_modulo_compra(self) -> None:
        text = format_historial_modulo_compra(
            "39870215",
            "101",
            "DROGUERIA NENA C.A.",
        )
        self.assertIn("Compra#: 39870215", text)
        self.assertIn("101 DROGUERIA NENA C.A.", text)

    def test_usuario_erp(self) -> None:
        self.assertEqual(
            format_historial_usuario_erp("PORTIZ"),
            "Usuario Activo: PORTIZ",
        )


if __name__ == "__main__":
    unittest.main()
