"""Tests movement_enrich / erp_fetch (sin MySQL)."""

from unittest.mock import MagicMock, patch

from outbox.erp_fetch import parse_sale_keys
from outbox.movement_enrich import enrich_kardex_adjustment_row, enrich_movement_row, enrich_sale_row


def test_parse_sale_keys():
    row = {"numero": "0200229381", "codigo": "FF09748", "contador": 122695}
    pk = {"ccaja": "02"}
    assert parse_sale_keys(row, pk) == ("0200229381", "FF09748", 122695, "02")


@patch("outbox.movement_enrich.fetch_lotes_aggregated", return_value=([], 0.0))
@patch("outbox.movement_enrich.fetch_detalle_lotes", return_value=[])
@patch("outbox.movement_enrich.fetch_detallepr_row", return_value={"precio1": 1})
@patch("outbox.movement_enrich.fetch_scom_line", return_value={"subtotal2": 100})
@patch("outbox.movement_enrich.fetch_sinv_row", return_value={"codigo": "FF1"})
def test_enrich_purchase_row(*_mocks):
    row = {"codigo": "FF1", "compras": 2, "numdoc": "N1"}
    out = enrich_movement_row("kardex", row, None, MagicMock())
    assert out["scom"]["subtotal2"] == 100
    assert out["sinv"]["codigo"] == "FF1"
    assert out["detallepr"]["precio1"] == 1


@patch("outbox.movement_enrich.fetch_lotes_aggregated", return_value=([{"calidad": "01"}], 5.0))
@patch("outbox.movement_enrich.fetch_detalle_lotes", return_value=[{"cubica": "01"}])
@patch("outbox.movement_enrich.fetch_detallepr_row", return_value={"precio1": 0.5})
@patch("outbox.movement_enrich.fetch_sinv_row", return_value={"codigo": "FF09748"})
@patch("outbox.movement_enrich.fetch_diariovi_line")
def test_enrich_sale_row(mock_diariovi, *_mocks):
    mock_diariovi.return_value = {"subtotal2": 3111.35}
    out = enrich_sale_row(
        {"numero": "0200229381", "codigo": "FF09748", "contador": 122695},
        {"ccaja": "02"},
        MagicMock(),
    )
    assert out["diariovi"]["subtotal2"] == 3111.35
    assert out["sinv"]["codigo"] == "FF09748"
    assert out["detallepr"]["precio1"] == 0.5
    assert out["lotes"][0]["calidad"] == "01"


@patch("outbox.movement_enrich.fetch_lotes_aggregated", return_value=([], 0.0))
@patch("outbox.movement_enrich.fetch_detalle_lotes", return_value=[])
@patch("outbox.movement_enrich.fetch_detallepr_row", return_value={"costo": 0.2})
@patch("outbox.movement_enrich.fetch_sinv_row", return_value={"existencia": 3})
def test_enrich_kardex_solo_sinv(mock_sinv, *_mocks):
    out = enrich_kardex_adjustment_row({"codigo": "FF1", "ajustesp": 2}, MagicMock())
    assert out["sinv"]["existencia"] == 3
    assert out["detallepr"]["costo"] == 0.2
    mock_sinv.assert_called_once()
