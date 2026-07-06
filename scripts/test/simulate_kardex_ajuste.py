#!/usr/bin/env python3
"""Simula ajuste inventario ERP: kardex cabecera (ajustesp/ajustesn) -> outbox kardex."""

from __future__ import annotations

import argparse

from _common import (
    add_common_args,
    apply_sinv_existencia_delta,
    connect_dict,
    format_kobs_ajuste,
    insert_kardex_header,
    maybe_flush,
    pick_product,
    read_sinv_costs,
    read_sinv_existencia,
    require_mysql,
    show_recent_outbox,
    resolve_simulation_fecha,
    test_suffix,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula ajuste inventario ERP (solo kardex cabecera, kobs Ajuste Nro:)"
    )
    add_common_args(parser)
    parser.add_argument(
        "--direccion",
        choices=("entrada", "salida"),
        default="entrada",
        help="entrada=ajustesp; salida=ajustesn",
    )
    args = parser.parse_args()

    mysql = require_mysql()
    conn = connect_dict(mysql)
    try:
        product = pick_product(conn, args.codigo, aleatorio=args.aleatorio)
        codigo = str(product["codigo"]).strip()
        qty = float(args.cantidad)
        if qty <= 0:
            qty = 1.0

        ajustesp = qty if args.direccion == "entrada" else 0.0
        ajustesn = qty if args.direccion == "salida" else 0.0
        suf = test_suffix()
        nro_ajuste = f"{int(suf):06d}"[:12]
        accion = "*Aumento" if args.direccion == "entrada" else "*Disminucion"
        fecha = resolve_simulation_fecha(args)
        kobs = format_kobs_ajuste(nro_ajuste, accion=accion)

        delta = ajustesp - ajustesn
        ex_antes = read_sinv_existencia(conn, codigo)
        costo, costopro = read_sinv_costs(conn, codigo)
        ex_despues = ex_antes + delta
        entradas = ajustesp
        salidas = ajustesn

        print(f"Product: {codigo} (sinv stock={ex_antes})")
        print(
            f"INSERT kardex: ajustesp={ajustesp} ajustesn={ajustesn} "
            f"kobs={kobs[:50]}..."
        )
        if not args.no_update_sinv and delta != 0:
            print(f"UPDATE sinv: stock += {delta}")

        if args.dry_run:
            return 0

        with conn.cursor() as cur:
            indice = insert_kardex_header(
                cur,
                codigo=codigo,
                fecha=fecha,
                ajustesp=ajustesp,
                ajustesn=ajustesn,
                existenciai=ex_antes,
                entradas=entradas,
                salidas=salidas,
                existenciaf=ex_despues,
                costo=costo,
                costopro=costopro,
                kobs=kobs,
                cajero="TEST",
            )
        if not args.no_update_sinv and delta != 0:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, delta)
            print(f"sinv.stock: {ex0} -> {ex1}")
        conn.commit()
        print(f"OK: ERP adjustment kardex indice={indice}.")
        show_recent_outbox(conn, "kardex")
    except Exception as ex:
        conn.rollback()
        print(f"Error: {ex}", file=__import__("sys").stderr)
        return 1
    finally:
        conn.close()

    maybe_flush(args.flush)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
