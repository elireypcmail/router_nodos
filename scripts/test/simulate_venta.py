#!/usr/bin/env python3
"""INSERT en ventasi -> trigger outbox sale -> hub."""

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
    parser = argparse.ArgumentParser(description="Simula una venta (ventasi)")
    add_common_args(parser)
    args = parser.parse_args()

    mysql = require_mysql()
    conn = connect_dict(mysql)
    try:
        product = pick_product(conn, args.codigo, aleatorio=args.aleatorio)
        codigo = str(product["codigo"]).strip()
        cantidad = float(args.cantidad)
        if cantidad <= 0:
            cantidad = 1.0

        suf = test_suffix()
        numero = f"VT{suf}"[:15]
        contador = int(suf) % 999999 or 1
        fecha = today()

        ex_antes = read_sinv_existencia(conn, codigo)
        print(f"Product: {codigo} (sinv stock={ex_antes})")
        print(
            f"INSERT ventasi: numero={numero} codigo={codigo} "
            f"cantidad={cantidad} contador={contador} fecha={fecha}"
        )
        if not args.no_update_sinv:
            print(f"UPDATE sinv: stock -= {cantidad} (simulates local ERP)")

        if args.dry_run:
            return 0

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ventasi (
                  numero, codigo, cantidad, fecha, contador, ccaja, cod_ven
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (numero, codigo, cantidad, fecha, contador, "", ""),
            )
        if not args.no_update_sinv:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, -cantidad)
            print(f"sinv.stock: {ex0} -> {ex1}")
        conn.commit()
        print("OK: sale inserted (should enqueue sync_outbox ventasi).")
        show_recent_outbox(conn, "ventasi")
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
