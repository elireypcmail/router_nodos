#!/usr/bin/env python3
"""INSERT en kardex con devolución a proveedor (devoc) -> outbox kardex -> hub."""

from __future__ import annotations

import argparse

from _common import (
    add_common_args,
    apply_sinv_existencia_delta,
    connect_dict,
    erp_devolucion_numero,
    format_kobs_devolucion_compra,
    insert_kardex_header,
    lookup_provider,
    maybe_flush,
    next_kardex_contador,
    pick_product,
    read_sinv_costs,
    read_sinv_existencia,
    require_mysql,
    resolve_movimiento_datetime,
    show_recent_outbox,
    test_suffix,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula kardex con devolución a proveedor (sin compras/ventas en la fila)"
    )
    add_common_args(parser)
    parser.add_argument(
        "--tipo",
        choices=("devoc",),
        default="devoc",
        help="devoc=devolución a proveedor (salida). Dev. cliente: ventas negativas en kardex.",
    )
    parser.add_argument(
        "--cod-prv",
        default=None,
        help="Código proveedor en kobs (default: sinv.cod_prv)",
    )
    parser.add_argument(
        "--operador",
        default="SUPERVISOR",
        help="Usuario ERP en kobs (default: SUPERVISOR)",
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

        devov = qty if args.tipo == "devov" else 0.0
        devoc = qty if args.tipo == "devoc" else 0.0
        mov_dt = resolve_movimiento_datetime()
        kardex_fecha = mov_dt.date()
        num_dev = erp_devolucion_numero(mov_dt)
        suf = test_suffix()
        numero = f"KD{suf}"[:15]
        contador = next_kardex_contador(conn)

        if args.cod_prv:
            cod_prv, _nom_prv = lookup_provider(conn, args.cod_prv)
            if not cod_prv:
                cod_prv = args.cod_prv.strip()
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cod_prv FROM sinv WHERE codigo = %s LIMIT 1",
                    (codigo,),
                )
                row = cur.fetchone() or {}
            cod_prv, _nom_prv = lookup_provider(conn, row.get("cod_prv"))

        kobs = (
            f"Customer return #{suf}"
            if args.tipo == "devov"
            else format_kobs_devolucion_compra(
                num_dev,
                cod_prv or "0000000000",
                operador=args.operador,
                when=mov_dt,
            )
        )

        delta = qty if args.tipo == "devov" else -qty
        ex_antes = read_sinv_existencia(conn, codigo)
        print(f"Product: {codigo} (sinv stock={ex_antes})")
        print(
            f"INSERT kardex: {args.tipo}={qty} numero={numero} "
            f"contador={contador} fecha={kardex_fecha}"
        )
        print(f"  kobs={kobs[:80]}...")
        if not args.no_update_sinv:
            print(f"UPDATE sinv: stock += {delta} (simulates local ERP)")

        if args.dry_run:
            return 0

        with conn.cursor() as cur:
            costo, costopro = read_sinv_costs(conn, codigo)
            ex_despues = ex_antes + delta
            indice = insert_kardex_header(
                cur,
                codigo=codigo,
                fecha=kardex_fecha,
                devoc=devoc,
                devov=devov,
                existenciai=ex_antes,
                entradas=devov,
                salidas=devoc,
                existenciaf=ex_despues,
                costo=costo,
                costopro=costopro,
                kobs=kobs,
                cajero=args.operador[:10],
                numero=numero,
                contador=contador,
                hora=mov_dt.strftime("%H:%M"),
            )
        if not args.no_update_sinv:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, delta)
            print(f"sinv.stock: {ex0} -> {ex1}")
        conn.commit()
        print(f"OK: kardex inserted index={indice} (outbox if triggers active).")
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
