#!/usr/bin/env python3
"""INSERT en kardex con ajuste (ajustesp / ajustesn) → outbox kardex → hub."""

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
    parser = argparse.ArgumentParser(description="Simula kardex con ajuste de inventario")
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
        numero = f"KA{suf}"[:15]
        contador = int(suf) % 999999 or 1
        fecha = today()
        kobs = f"MULTISHOP-TEST-AJUSTE-{args.direccion.upper()}"

        delta = ajustesp - ajustesn
        ex_antes = read_sinv_existencia(conn, codigo)
        print(f"Producto: {codigo} (existencia sinv={ex_antes})")
        print(
            f"INSERT kardex: ajustesp={ajustesp} ajustesn={ajustesn} "
            f"numero={numero} fecha={fecha}"
        )
        if not args.no_update_sinv and delta != 0:
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
                  %s, %s, 0, 0, 0, 0,
                  %s, %s, 0, 0,
                  %s, 'TEST', %s, %s
                )
                """,
                (codigo, fecha, ajustesp, ajustesn, kobs, numero, contador),
            )
            cur.execute("SELECT LAST_INSERT_ID() AS indice")
            row = cur.fetchone() or {}
            indice = row.get("indice")
        if not args.no_update_sinv and delta != 0:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, delta)
            print(f"sinv.existencia: {ex0} → {ex1}")
        conn.commit()
        print(f"OK: kardex insertado indice={indice}.")
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
