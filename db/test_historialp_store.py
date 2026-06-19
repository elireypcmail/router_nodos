"""Tests historialp_store y partner_request_context (sin MySQL)."""

import unittest
from unittest.mock import MagicMock

from core.partner_request_context import (
    PartnerRequestContext,
    bind_partner_request_context,
    historialp_usuario_from_context,
    reset_partner_request_context,
)
from db.historialp_store import (
    log_precio_referencial_changes,
    precio1_bs_changed,
    precio1_usd_changed,
)


class TestHistorialpPriceChange(unittest.TestCase):
    def test_precio1_bs_unchanged_after_rounding(self):
        self.assertFalse(precio1_bs_changed(10.00, 10.00))
        self.assertTrue(precio1_bs_changed(10.00, 10.01))

    def test_precio1_usd_unchanged_after_rounding(self):
        self.assertFalse(precio1_usd_changed(2.8750001, 2.8750004))
        self.assertTrue(precio1_usd_changed(2.875000, 2.875001))


class TestHistorialpUsuario(unittest.TestCase):
    def test_usuario_from_partner_context(self):
        token = bind_partner_request_context(
            PartnerRequestContext(
                key_id="7f3a2b1c-e89b-12d3-a456-426614174000",
                key_label="integracion-erp",
            )
        )
        try:
            self.assertEqual(
                historialp_usuario_from_context(),
                "Usuario Activo: integracion-erp (7f3a2b1c-e89b-12d3-a456-426614174000)",
            )
        finally:
            reset_partner_request_context(token)

    def test_usuario_fallback_without_context(self):
        token = bind_partner_request_context(None)
        try:
            self.assertEqual(
                historialp_usuario_from_context(),
                "Usuario Activo: API Multishop",
            )
        finally:
            reset_partner_request_context(token)


class TestHistorialpLogging(unittest.TestCase):
    def test_skips_insert_when_prices_unchanged(self):
        cur = MagicMock()
        log_precio_referencial_changes(
            cur,
            "FF00009",
            old_precio1_bs=100.0,
            new_precio1_bs=100.0,
            old_precio1_usd=20.0,
            new_precio1_usd=20.0,
            usuario="Usuario Activo: test",
        )
        cur.execute.assert_not_called()

    def test_inserts_only_changed_price_types(self):
        cur = MagicMock()
        log_precio_referencial_changes(
            cur,
            "FF00009",
            old_precio1_bs=100.0,
            new_precio1_bs=101.0,
            old_precio1_usd=20.0,
            new_precio1_usd=20.0,
            usuario="Usuario Activo: test",
        )
        inserts = [
            call
            for call in cur.execute.call_args_list
            if "INSERT INTO historialp" in str(call[0][0])
        ]
        self.assertEqual(len(inserts), 1)
        args = inserts[0][0][1]
        self.assertEqual(args[0], "FF00009")
        self.assertEqual(args[1], "Precio1Bs")
        self.assertEqual(args[2], 100.0)


if __name__ == "__main__":
    unittest.main()
