"""Tests detallepr_store (mapeo divisa sin MySQL)."""

import unittest

from db.detallepr_store import (
    DETALLEPR_DIVISA_COST_FIELDS,
    DETALLEPR_DIVISA_PG_FIELDS,
    DETALLEPR_DIVISA_PRICE_FIELDS,
    _default_divisa_fields,
    _detallepr_row_to_divisa_fields,
)


class TestDetalleprStore(unittest.TestCase):
    def test_default_divisa_fields(self):
        defaults = _default_divisa_fields()
        for key in (
            *DETALLEPR_DIVISA_PRICE_FIELDS,
            *DETALLEPR_DIVISA_PG_FIELDS,
            *DETALLEPR_DIVISA_COST_FIELDS,
        ):
            self.assertIn(key, defaults)
            self.assertEqual(defaults[key], 0.0)

    def test_row_to_divisa_fields(self):
        mapped = _detallepr_row_to_divisa_fields(
            {
                "precio1": 10.5,
                "precio2": 11,
                "precio3": 0,
                "precio4": 12.25,
                "pg1": 70.25,
                "pg2": 5,
                "pg3": 0,
                "pg4": 8,
                "costo": 1.2,
                "costopro": 0.95,
                "costoant": 1.1,
            }
        )
        self.assertEqual(mapped["precio1div"], 10.5)
        self.assertEqual(mapped["precio4div"], 12.25)
        self.assertEqual(mapped["pg1div"], 70.25)
        self.assertEqual(mapped["pg4div"], 8.0)
        self.assertEqual(mapped["costodiv"], 1.2)
        self.assertEqual(mapped["costoprodiv"], 0.95)
        self.assertEqual(mapped["costoantdiv"], 1.1)


if __name__ == "__main__":
    unittest.main()
