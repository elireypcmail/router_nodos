"""Tests movement_enrich / erp_fetch (sin MySQL)."""

from unittest.mock import MagicMock, patch

from outbox.erp_fetch import parse_sale_keys
from outbox.movement_enrich import enrich_kardex_adjustment_row, enrich_movement_row, enrich_sale_row


def test_parse_sale_keys():
    row = {"numero": "0200229381", "codigo": "FF09748", "contador": 122695}
    pk = {"ccaja": "02"}
    assert parse_sale_keys(row, pk) == ("0200229381", "FF09748", 122695, "02")


@patch("outbox.movement_enrich.fetch_scli_row", return_value=None)
@patch("outbox.movement_enrich.fetch_sprv_row", return_value={"cod_prv": "101", "nom_prv": "NENA"})
@patch("outbox.movement_enrich.fetch_kardex_obs", return_value=None)
@patch("outbox.movement_enrich.fetch_lotes_aggregated", return_value=([], 0.0))
@patch("outbox.movement_enrich.fetch_detalle_lotes", return_value=[])
@patch("outbox.movement_enrich.fetch_detallepr_row", return_value={"precio1": 1})
@patch("outbox.movement_enrich.fetch_scom_line", return_value={"subtotal2": 100})
@patch("outbox.movement_enrich.fetch_sinv_row", return_value={"codigo": "FF1"})
def test_enrich_purchase_row(*_mocks):
    row = {
        "codigo": "FF1",
        "compras": 2,
        "numdoc": "N1",
        "fecha": "2025-12-01",
        "kobs": (
            "Compra#: 41816037 Proveedor: 101 DROGUERIA NENA C.A. Ind: 09124672 "
            "07:10:23 a. m.  Relizado por: PORTIZ"
        ),
    }
    out = enrich_movement_row("kardex", row, None, MagicMock())
    assert out["scom"]["subtotal2"] == 100
    assert out["sinv"]["codigo"] == "FF1"
    assert out["detallepr"]["precio1"] == 1
    assert out["kobs_parsed"]["provider_code"] == "101"
    assert out["kobs_parsed"]["local_time"] == "07:10:23"
    assert out["movement_timestamp"] == "2025-12-01T11:10:23.000Z"
    assert out["sprv"]["cod_prv"] == "101"
    assert out["scli"] is None
    assert out["cash_register_code"] is None


@patch(
    "outbox.movement_enrich.fetch_scli_row",
    return_value={"cod_cli": "V27567145", "nom_cli": "ALFREDO JIMENEZ"},
)
@patch("outbox.movement_enrich.fetch_sprv_row", return_value=None)
@patch("outbox.movement_enrich.fetch_kardex_obs", return_value=None)
@patch("outbox.movement_enrich.fetch_lotes_aggregated", return_value=([{"calidad": "01"}], 5.0))
@patch("outbox.movement_enrich.fetch_detalle_lotes", return_value=[{"cubica": "01"}])
@patch("outbox.movement_enrich.fetch_detallepr_row", return_value={"precio1": 0.5})
@patch("outbox.movement_enrich.fetch_sinv_row", return_value={"codigo": "FF09748"})
@patch("outbox.movement_enrich.fetch_diariov_by_ccaja", return_value={"nordene": "a1b2c3d4e5f678", "ccaja": "02"})
@patch("outbox.movement_enrich.fetch_diariovi_line")
def test_enrich_sale_row(mock_diariovi, *_mocks):
    mock_diariovi.return_value = {"subtotal2": 3111.35, "ccaja": "02"}
    out = enrich_sale_row(
        {
            "numero": "0200229381",
            "codigo": "FF09748",
            "contador": 122695,
            "fecha": "2025-12-01",
            "kobs": (
                "Vta#: 0100237670 Cliente: V27567145 ALFREDO JIMENEZ Caja:01 "
                "Hora:1:21:00 a. m.  Atendido por: YJAIMES"
            ),
        },
        {"ccaja": "02"},
        MagicMock(),
    )
    assert out["diariovi"]["subtotal2"] == 3111.35
    assert out["diariov"]["nordene"] == "a1b2c3d4e5f678"
    assert out["sinv"]["codigo"] == "FF09748"
    assert out["detallepr"]["precio1"] == 0.5
    assert out["lotes"][0]["calidad"] == "01"
    assert out["movement_timestamp"] == "2025-12-01T05:21:00.000Z"
    assert out["sprv"] is None
    assert out["kobs_parsed"]["client_code"] == "V27567145"
    assert out["kobs_parsed"]["cash_register_code"] == "01"
    assert out["cash_register_code"] == "01"
    assert out["scli"]["cod_cli"] == "V27567145"


@patch("outbox.movement_enrich.fetch_scli_row", return_value=None)
@patch("outbox.movement_enrich.fetch_sprv_row", return_value=None)
@patch("outbox.movement_enrich.fetch_kardex_obs", return_value=None)
@patch("outbox.movement_enrich.fetch_lotes_aggregated", return_value=([], 0.0))
@patch("outbox.movement_enrich.fetch_detalle_lotes", return_value=[])
@patch("outbox.movement_enrich.fetch_detallepr_row", return_value={"costo": 0.2})
@patch("outbox.movement_enrich.fetch_sinv_row", return_value={"existencia": 3})
def test_enrich_kardex_solo_sinv(mock_sinv, *_mocks):
    out = enrich_kardex_adjustment_row(
        {"codigo": "FF1", "ajustesp": 2, "fecha": "2025-12-01"},
        MagicMock(),
    )
    assert out["sinv"]["existencia"] == 3
    assert out["detallepr"]["costo"] == 0.2
    assert out["movement_timestamp"] == "2025-12-01T04:00:00.000Z"
    mock_sinv.assert_called_once()
