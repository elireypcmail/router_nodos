#!/usr/bin/env python3
"""Simula venta ERP: kardex (ventas) + kardexd (ajustesn) -> outbox sale."""

from __future__ import annotations

import argparse

from _common import (
    add_common_args,
    apply_sinv_existencia_delta,
    connect_dict,
    format_kobs_venta,
    insert_kardex_header,
    insert_kardexd_line,
    maybe_flush,
    next_kardex_contador,
    pick_product,
    read_sinv_costs,
    read_sinv_existencia,
    require_mysql,
    show_recent_outbox,
    test_suffix,
    today,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula venta ERP (kardex + kardexd; outbox ventasi vía trigger kardex)"
    )
    add_common_args(parser)
    parser.add_argument(
        "--numero",
        default=None,
        help="Número de factura/ticket (default VT+timestamp)",
    )
    parser.add_argument(
        "--caja",
        default="10",
        help="Caja en kobs (default 10)",
    )
    parser.add_argument(
        "--cliente",
        default="V25497333 CLIENTE PRUEBA",
        help="Texto cliente en kobs",
    )
    parser.add_argument(
        "--legacy-ventasi",
        action="store_true",
        help="INSERT solo en ventasi (sin outbox; ya no hay trg_ventasi_*)",
    )
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
        numero = (args.numero or f"VT{suf}")[:15]
        contador = next_kardex_contador(conn)
        fecha = today()
        kobs = format_kobs_venta(
            numero, cliente=args.cliente, caja=args.caja, operador="CAJA01"
        )

        ex_antes = read_sinv_existencia(conn, codigo)
        costo, costopro = read_sinv_costs(conn, codigo)
        ex_despues = ex_antes - cantidad

        print(f"Product: {codigo} (sinv stock={ex_antes})")
        print(
            f"INSERT kardex: ventas={cantidad} numero={numero} contador={contador}"
        )
        print(f"INSERT kardexd: cubica=01 ajustesn={cantidad}")
        if not args.no_update_sinv:
            print(f"UPDATE sinv: stock -= {cantidad}")

        if args.dry_run:
            return 0

        if args.legacy_ventasi:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ventasi (
                      numero, codigo, cantidad, fecha, contador, ccaja, cod_ven
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (numero, codigo, cantidad, fecha, contador, args.caja, ""),
                )
            if not args.no_update_sinv:
                ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, -cantidad)
                print(f"sinv.stock: {ex0} -> {ex1}")
            conn.commit()
            print("OK: legacy sale inserted (sync_outbox ventasi).")
            show_recent_outbox(conn, "ventasi")
            maybe_flush(args.flush)
            return 0

        with conn.cursor() as cur:
            indice_k = insert_kardex_header(
                cur,
                codigo=codigo,
                fecha=fecha,
                ventas=cantidad,
                existenciai=ex_antes,
                salidas=cantidad,
                existenciaf=ex_despues,
                costo=costo,
                costopro=costopro,
                kobs=kobs,
                cajero="CAJA01",
                numero=numero,
                contador=contador,
            )
            indice_d = insert_kardexd_line(
                cur,
                codigo=codigo,
                fecha=fecha,
                cubica="01",
                ajustesn=cantidad,
                existenciai=ex_antes,
                salidas=cantidad,
                existenciaf=ex_despues,
                costo=costo,
                costopro=costopro,
                kobs=kobs,
                cajero="CAJA01",
                numero=numero,
                contador=contador,
            )

        if not args.no_update_sinv:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, -cantidad)
            print(f"sinv.stock: {ex0} -> {ex1}")

        conn.commit()
        print(
            f"OK: ERP sale kardex indice={indice_k}, kardexd={indice_d} "
            f"(outbox ventasi from kardex trigger)."
        )
        show_recent_outbox(conn, ["ventasi"])
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
