"""Tests parseo kobs / movement_timestamp (sin MySQL)."""

from datetime import time

from outbox.kobs_parse import (
    build_movement_timestamp,
    parse_client_code,
    parse_cash_register_code,
    parse_hora_column,
    parse_kobs,
    parse_kobs_time,
    parse_provider_code,
)


COMPRA = (
    "Compra#: 41816037 Proveedor: 101 DROGUERIA NENA C.A. Ind: 09124672 "
    "07:10:23 a. m.  Relizado por: PORTIZ"
)
VENTA = (
    "Vta#: 0100237670 Cliente: V27567145 ALFREDO JIMENEZ Caja:01 "
    "Hora:1:21:00 a. m.  Atendido por: YJAIMES / Precio de Venta Bs.: 147,40"
)
AJUSTE = (
    "Ajuste Nro: 0000004729 de Fecha 01/12/2025 - Hora: 04:07:29 p. m.  "
    "Accion:  *Aumentar*  Relizado por: PORTIZ"
)
TRASLADO = (
    "Traslado Externo Nro: 0000000100 de Fecha 01/12/2025 - Hora: 10:46:42 a. m.  "
    "Accion:  *Disminuir*"
)
DEVOC = "Dev.Compra#: 15637821 Proveedor: 101 10:57:51 a. m.  Relizado por: PORTIZ"
DEVOV = "MULTISHOP-TEST-DEV-DEVOV"


def test_parse_provider_compra_devoc():
    assert parse_provider_code(COMPRA) == "101"
    assert parse_provider_code(DEVOC) == "101"
    assert parse_provider_code(VENTA) is None
    assert parse_provider_code(DEVOV) is None


def test_parse_client_and_caja_venta():
    assert parse_client_code(VENTA) == "V27567145"
    assert parse_cash_register_code(VENTA) == "01"
    assert parse_client_code(COMPRA) is None
    assert parse_cash_register_code(COMPRA) is None
    assert parse_client_code("Cliente: V112618313 Caja:01") == "V112618313"
    assert parse_cash_register_code("Cliente: V112618313 Caja:01") == "01"


def test_parse_times_from_samples():
    assert parse_kobs_time(COMPRA)[0] == time(7, 10, 23)
    assert parse_kobs_time(VENTA)[0] == time(1, 21, 0)
    assert parse_kobs_time(AJUSTE)[0] == time(16, 7, 29)
    assert parse_kobs_time(TRASLADO)[0] == time(10, 46, 42)
    assert parse_kobs_time(DEVOC)[0] == time(10, 57, 51)
    assert parse_kobs_time(DEVOV)[0] is None


def test_parse_hora_column_fallback():
    assert parse_hora_column("1:21") == time(1, 21, 0)
    assert parse_hora_column("13:05:09") == time(13, 5, 9)


def test_movement_timestamp_caracas_to_utc():
    # 07:10:23 America/Caracas (−4) → 11:10:23Z
    assert (
        build_movement_timestamp("2025-12-01", time(7, 10, 23))
        == "2025-12-01T11:10:23.000Z"
    )
    # sin hora → medianoche local
    assert (
        build_movement_timestamp("2025-12-01", None) == "2025-12-01T04:00:00.000Z"
    )


def test_parse_kobs_bundle():
    p = parse_kobs(COMPRA)
    assert p.provider_code == "101"
    assert p.client_code is None
    assert p.cash_register_code is None
    assert p.local_time == time(7, 10, 23)

    v = parse_kobs(VENTA)
    assert v.provider_code is None
    assert v.client_code == "V27567145"
    assert v.cash_register_code == "01"
    assert v.local_time == time(1, 21, 0)
