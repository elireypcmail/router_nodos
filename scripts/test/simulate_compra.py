#!/usr/bin/env python3
"""INSERT en comprasdbf -> trigger outbox purchase -> hub."""

from __future__ import annotations

import argparse
import sys

from _common import (
    add_common_args,
    apply_sinv_cost_after_compra,
    apply_sinv_existencia_delta,
    connect_dict,
    distribute_cantidad_por_lotes,
    equal_lote_percentages,
    make_test_lote_ids,
    maybe_flush,
    next_compras_contador,
    parse_lotes_percentages,
    pick_product,
    read_sinv_existencia,
    require_mysql,
    show_recent_outbox,
    test_suffix,
    today,
    upsert_detalle_lote,
)


def _resolve_lote_split(
    cantidad: int,
    num_lotes: int | None,
    lotes_pct: str | None,
) -> list[tuple[str, int]]:
    if num_lotes is None:
        return [("", cantidad)]

    if num_lotes < 1:
        raise ValueError("--lotes debe ser >= 1")
    if num_lotes > cantidad:
        raise ValueError(
            f"--lotes ({num_lotes}) no puede ser mayor que --cantidad ({cantidad})"
        )

    if lotes_pct:
        percentages = parse_lotes_percentages(lotes_pct)
        if len(percentages) != num_lotes:
            raise ValueError(
                f"--lotes-pct tiene {len(percentages)} valor(es) pero --lotes es {num_lotes}"
            )
    else:
        percentages = equal_lote_percentages(num_lotes)

    amounts = distribute_cantidad_por_lotes(cantidad, percentages)
    suffix = test_suffix()
    lot_ids = make_test_lote_ids(num_lotes, suffix)
    return list(zip(lot_ids, amounts, strict=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Simula una compra (comprasdbf)")
    add_common_args(parser)
    parser.add_argument(
        "--precio",
        type=float,
        default=10.0,
        help="Precio unitario de la compra (comprasdbf.precio y actualización sinv.costo/costopro)",
    )
    parser.add_argument(
        "--lotes",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Crea N filas en detalle y reparte la cantidad de la compra entre ellas "
            "(N <= --cantidad). Sin --lotes-pct reparte en partes iguales."
        ),
    )
    parser.add_argument(
        "--lotes-pct",
        dest="lotes_pct",
        default=None,
        metavar="P1,P2,...",
        help="Porcentajes por lote (deben sumar ~100 y coincidir con --lotes), ej. 50,30,20",
    )
    args = parser.parse_args()

    if args.lotes_pct and args.lotes is None:
        print("Error: --lotes-pct requires --lotes N", file=sys.stderr)
        return 2

    mysql = require_mysql()
    conn = connect_dict(mysql)
    try:
        product = pick_product(conn, args.codigo, aleatorio=args.aleatorio)
        codigo = str(product["codigo"]).strip()
        cantidad = max(1, int(args.cantidad))
        precio = float(args.precio)
        monto = round(precio * cantidad, 2)
        contador = next_compras_contador(conn)
        numdoc = f"T{test_suffix()}"[:6]
        fecha = today()

        try:
            lote_splits = _resolve_lote_split(cantidad, args.lotes, args.lotes_pct)
        except ValueError as ex:
            print(f"Error: {ex}", file=sys.stderr)
            return 2

        ex_antes = read_sinv_existencia(conn, codigo)
        costo_antes = float(product.get("costo") or 0)
        costopro_antes = float(product.get("costopro") or 0)
        print(
            f"Product: {codigo} (cost={costo_antes}, costopro={costopro_antes}, "
            f"sinv stock={ex_antes})"
        )
        print(
            f"INSERT comprasdbf: contador={contador} numdoc={numdoc} "
            f"cantidad={cantidad} precio={precio} monto={monto} fecha={fecha}"
        )
        if not args.no_update_sinv:
            if len(lote_splits) == 1 and lote_splits[0][0] == "":
                print(
                    f"UPDATE sinv + detalle: existencia += {cantidad}, "
                    f"costo/costopro con precio={precio} "
                    f"(lote default, cubica 01)"
                )
            else:
                detalle_plan = ", ".join(
                    f"{lote or '(default)'}={qty}" for lote, qty in lote_splits
                )
                print(
                    f"UPDATE sinv + {len(lote_splits)} lote(s) en detalle: "
                    f"existencia += {cantidad} ({detalle_plan})"
                )

        if args.dry_run:
            return 0

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO comprasdbf (
                  codigo, cantidad, precio, monto, fecha, numdoc, contador
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (codigo, cantidad, precio, monto, fecha, numdoc, contador),
            )
        if not args.no_update_sinv:
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, cantidad)
            print(f"sinv.stock: {ex0} -> {ex1}")
            _, costo_nuevo, costopro_nuevo = apply_sinv_cost_after_compra(
                conn,
                codigo,
                cantidad=cantidad,
                precio_unitario=precio,
                existencia_antes=ex0,
                costo_antes=costo_antes,
                costopro_antes=costopro_antes,
            )
            print(
                f"sinv costos: costo {costo_antes} -> {costo_nuevo}, "
                f"costopro {costopro_antes} -> {costopro_nuevo} (CPP con precio={precio})"
            )
            for lote, qty in lote_splits:
                upsert_detalle_lote(
                    conn,
                    codigo,
                    qty,
                    lote=lote,
                    costo=precio,
                )
                label = lote or "(default)"
                print(f"lot detail: {label} +{qty} (outbox lot -> hub)")
        conn.commit()
        print("OK: purchase inserted (should enqueue sync_outbox comprasdbf).")
        show_recent_outbox(conn, "comprasdbf")
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
