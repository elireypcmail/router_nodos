"""Tests del lote de precios (validación de request sin MySQL)."""

import unittest

from pydantic import ValidationError

from routes.inventario import PrecioLoteRequest


class TestPrecioLoteRequest(unittest.TestCase):
    def test_valid_body(self):
        body = PrecioLoteRequest.model_validate(
            {
                "tasa": 400,
                "items": [
                    {"codigo": "FF22470", "precio_con_iva_usd": 1.16},
                    {"codigo": "FF23813", "precio_con_iva_usd": 2.9},
                ],
            }
        )
        self.assertEqual(body.tasa, 400.0)
        self.assertEqual(len(body.items), 2)

    def test_rejects_empty_items(self):
        with self.assertRaises(ValidationError):
            PrecioLoteRequest.model_validate({"tasa": 400, "items": []})

    def test_rejects_missing_tasa(self):
        with self.assertRaises(ValidationError):
            PrecioLoteRequest.model_validate(
                {"items": [{"codigo": "A", "precio_con_iva_usd": 1.0}]}
            )

    def test_rejects_over_100_items(self):
        items = [
            {"codigo": f"SKU{i}", "precio_con_iva_usd": 1.0} for i in range(101)
        ]
        with self.assertRaises(ValidationError):
            PrecioLoteRequest.model_validate({"tasa": 400, "items": items})


if __name__ == "__main__":
    unittest.main()
