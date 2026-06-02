"""Tests de claves kardex → lookup diariovi (sin MySQL)."""

import unittest

from sync.jobs.kardex_sale_scope import KardexSaleLookupKeys


class TestKardexSaleLookupKeys(unittest.TestCase):
    def test_add_row_collects_numero_contador(self) -> None:
        keys = KardexSaleLookupKeys()
        keys.add_row(
            {
                "codigo": "FF23834",
                "numero": "1000052872",
                "ventas": 2,
                "contador": 226886,
                "fecha": "2026-05-30",
            }
        )
        self.assertIn(("FF23834", "1000052872"), keys.by_numero)
        self.assertIn(("FF23834", 226886), keys.by_contador)


if __name__ == "__main__":
    unittest.main()
