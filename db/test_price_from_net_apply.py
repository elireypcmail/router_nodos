"""Tests price_from_net_apply (modo y validaciones sin MySQL)."""

import unittest
from unittest.mock import MagicMock, patch

from db.price_from_net_apply import (
    PriceFromNetError,
    _resolve_mode,
    _validate_cpp_vs_price,
    apply_price_from_net,
)


class TestPriceFromNetMode(unittest.TestCase):
    def test_resolve_modes(self):
        self.assertEqual(
            _resolve_mode(price_ex_tax_usd=1.0, porvg_request=16.0),
            "completo",
        )
        self.assertEqual(
            _resolve_mode(price_ex_tax_usd=1.0, porvg_request=None),
            "solo_precio",
        )
        self.assertEqual(
            _resolve_mode(price_ex_tax_usd=None, porvg_request=8.0),
            "solo_impuesto",
        )

    def test_resolve_requires_one_field(self):
        with self.assertRaises(PriceFromNetError):
            _resolve_mode(price_ex_tax_usd=None, porvg_request=None)

    def test_cpp_vs_price_validation(self):
        with self.assertRaises(PriceFromNetError):
            _validate_cpp_vs_price(
                price_ex_tax_usd=0.78,
                price_ex_tax_bs=28.47,
                cpp_usd=0.80,
                cpp_bs=30.0,
            )


class TestApplyPriceFromNetSoloImpuesto(unittest.TestCase):
    @patch("db.price_from_net_apply.log_precio_referencial_changes")
    @patch("db.price_from_net_apply.ensure_detallepr_for_create")
    @patch("db.price_from_net_apply.fetch_detallepr_cost_row")
    @patch("db.price_from_net_apply._fetch_sinv_pricing_row")
    def test_tax_only_updates_porvg_and_prices_not_pg(
        self,
        mock_sinv_fetch,
        mock_det_fetch,
        mock_ensure,
        mock_hist,
    ):
        mock_sinv_fetch.return_value = {
            "costopro": 219.04,
            "porvg": 16.0,
            "precio1": 52.925,
            "precio1div": 1.45,
            "pg1": 51.0,
            "pg1div": 37.0,
        }
        mock_det_fetch.return_value = {
            "costopro": 0.780726,
            "precio1": 1.45,
            "pg1": 37.0,
        }
        cur = MagicMock()

        out = apply_price_from_net(cur, "SKU1", porvg=8.0)

        self.assertEqual(out["modo"], "solo_impuesto")
        self.assertEqual(out["porvg"], 8.0)
        self.assertEqual(out["pg_bs"], 51.0)
        self.assertEqual(out["pg_usd"], 37.0)
        self.assertGreater(out["precio_con_iva_bs"], 0)
        update_sqls = [call[0][0] for call in cur.execute.call_args_list]
        sinv_update = next(sql for sql in update_sqls if "UPDATE sinv" in sql)
        self.assertIn("porvg", sinv_update)
        self.assertNotIn("pg1", sinv_update)
        mock_hist.assert_called_once()


if __name__ == "__main__":
    unittest.main()
