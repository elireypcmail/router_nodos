#!/usr/bin/env python3
"""INSERT en kardex con devolución a proveedor (devoc) -> outbox kardex -> hub."""

from __future__ import annotations

import argparse

from _common import (
    add_common_args,
    apply_sinv_existencia_delta,
    connect_dict,
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
        description="Simula kardex con devolución a proveedor (sin compras/ventas en la fila)"
    )
    add_common_args(parser)
    parser.add_argument(
        "--tipo",
        choices=("devoc",),
        default="devoc",
        help="devoc=devolución a proveedor (salida). Dev. cliente: ventas negativas en kardex.",
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
        suf = test_suffix()
        numero = f"KD{suf}"[:15]
        contador = int(suf) % 999999 or 1
        fecha = resolve_simulation_fecha(args)
        kobs = f"Customer return #{suf}" if args.tipo == "devov" else f"Supplier return #{suf}"

        delta = qty if args.tipo == "devov" else -qty
        ex_antes = read_sinv_existencia(conn, codigo)
        print(f"Product: {codigo} (sinv stock={ex_antes})")
        print(
            f"INSERT kardex: {args.tipo}={qty} numero={numero} "
            f"contador={contador} fecha={fecha}"
        )
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
                fecha=fecha,
                devoc=devoc,
                devov=devov,
                existenciai=ex_antes,
                entradas=devov,
                salidas=devoc,
                existenciaf=ex_despues,
                costo=costo,
                costopro=costopro,
                kobs=kobs,
                cajero="TEST",
                numero=numero,
                contador=contador,
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
