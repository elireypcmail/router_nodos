#!/usr/bin/env python3
"""INSERT en kardex con devolución (devov o devoc) → outbox kardex → hub."""

from __future__ import annotations

import argparse

from _common import (
    add_common_args,
    apply_sinv_existencia_delta,
    connect_dict,
    maybe_flush,
    pick_product,
    read_sinv_existencia,
    require_mysql,
    show_recent_outbox,
    test_suffix,
    today,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula kardex con devolución (sin compras/ventas en la fila)"
    )
    add_common_args(parser)
    parser.add_argument(
        "--tipo",
        choices=("devov", "devoc"),
        default="devov",
        help="devov=devolución cliente (entrada); devoc=devolución a proveedor (salida)",
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
        fecha = today()
        kobs = f"MULTISHOP-TEST-DEV-{args.tipo.upper()}"

        delta = qty if args.tipo == "devov" else -qty
        ex_antes = read_sinv_existencia(conn, codigo)
        print(f"Producto: {codigo} (existencia sinv={ex_antes})")
        print(
            f"INSERT kardex: {args.tipo}={qty} numero={numero} "
            f"contador={contador} fecha={fecha}"
        )
        if not args.no_update_sinv:
            print(f"UPDATE sinv: existencia += {delta} (simula ERP local)")

        if args.dry_run:
            return 0

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kardex (
                  codigo, fecha, compras, ventas, devoc, devov,
                  ajustesp, ajustesn, entradas, salidas,
                  kobs, cajero, numero, contador
                ) VALUES (
                  %s, %s, 0, 0, %s, %s,
                  0, 0, 0, 0,
                  %s, 'TEST', %s, %s
                )
                """,
                (codigo, fecha, devoc, devov, kobs, numero, contador),
            )
            cur.execute("SELECT LAST_INSERT_ID() AS indice")
            row = cur.fetchone() or {}
            indice = row.get("indice")
        if not args.no_update_sinv:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, delta)
            print(f"sinv.existencia: {ex0} → {ex1}")
        conn.commit()
        print(f"OK: kardex insertado indice={indice} (outbox si triggers activos).")
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
