"""Tests inventario_identifier_conflict (sin MySQL)."""

import unittest

from db.inventario_identifier_conflict import collect_product_identifiers


class TestCollectProductIdentifiers(unittest.TestCase):
    def test_sku_and_effective_barra_when_empty(self):
        self.assertEqual(
            collect_product_identifiers("FF1", "", []),
            ["FF1"],
        )

    def test_sku_barra_and_alternos_deduped(self):
        self.assertEqual(
            collect_product_identifiers(
                "FF1",
                "7591196006240",
                ["7591196006240", " 7592637005099 ", "7592637005099"],
            ),
            ["FF1", "7591196006240", "7592637005099"],
        )

    def test_barra_defaults_to_codigo_when_blank(self):
        self.assertEqual(
            collect_product_identifiers("FF1", "   ", ["ALT1"]),
            ["FF1", "ALT1"],
        )


if __name__ == "__main__":
    unittest.main()
