#!/usr/bin/env python3
"""Simula compra ERP: scom (línea + subtotal2) → kardex + kardexd → outbox purchase."""

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
    format_kobs_compra,
    insert_kardex_header,
    insert_kardexd_line,
    insert_scom_purchase_line,
    lookup_provider,
    make_test_lote_ids,
    maybe_flush,
    next_compras_contador,
    parse_lotes_percentages,
    pick_product,
    read_sinv_costs,
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
        return [("01", cantidad)]

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
    cubicas = [f"{i + 1:02d}" for i in range(num_lotes)]
    return [
        (cubica, qty, lote)
        for cubica, qty, lote in zip(cubicas, amounts, lot_ids, strict=True)
    ]


def _insert_legacy_comprasdbf(
    conn,
    *,
    codigo: str,
    cantidad: int,
    precio: float,
    monto: float,
    fecha,
    numdoc: str,
    contador: int,
    lote_splits,
    args,
    costo_antes: float,
    costopro_antes: float,
) -> None:
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
        for split in lote_splits:
            if len(split) == 3:
                cubica, qty, lote = split
            else:
                cubica, qty = split
                lote = ""
            upsert_detalle_lote(conn, codigo, qty, lote=lote, costo=precio)
            print(f"lot detail: {lote or cubica} +{qty} (outbox lot -> hub)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simula compra ERP (scom → kardex + kardexd; outbox purchase vía trigger kardex)"
    )
    add_common_args(parser)
    parser.add_argument(
        "--precio",
        type=float,
        default=10.0,
        help="Precio unitario (kardex.costo y actualización sinv)",
    )
    parser.add_argument(
        "--num-compra",
        default=None,
        help="Número de compra en kobs (default: sufijo de prueba)",
    )
    parser.add_argument(
        "--cod-prv",
        default=None,
        help="Código proveedor en kobs (default: sinv.cod_prv)",
    )
    parser.add_argument(
        "--legacy-comprasdbf",
        action="store_true",
        help="Solo comprasdbf (NO flujo ERP; sin scom ni outbox)",
    )
    parser.add_argument(
        "--lotes",
        type=int,
        default=None,
        metavar="N",
        help="N líneas kardexd/detalle repartiendo la cantidad (N <= --cantidad)",
    )
    parser.add_argument(
        "--lotes-pct",
        dest="lotes_pct",
        default=None,
        metavar="P1,P2,...",
        help="Porcentajes por cubica/lote, ej. 50,30,20",
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
        subtotal2 = round(precio * cantidad, 2)
        fecha = today()
        descrip = str(product.get("descrip") or "").strip()
        suf = test_suffix()

        try:
            raw_splits = _resolve_lote_split(cantidad, args.lotes, args.lotes_pct)
        except ValueError as ex:
            print(f"Error: {ex}", file=sys.stderr)
            return 2

        if raw_splits and len(raw_splits[0]) == 3:
            lote_splits = raw_splits
        else:
            lote_splits = [(c, q, "") for c, q in raw_splits]

        ex_antes = read_sinv_existencia(conn, codigo)
        costo_antes, costopro_antes = read_sinv_costs(conn, codigo)
        if args.cod_prv:
            cod_prv, nom_prv = lookup_provider(conn, args.cod_prv)
            if not cod_prv:
                cod_prv = args.cod_prv.strip()
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cod_prv FROM sinv WHERE codigo = %s LIMIT 1",
                    (codigo,),
                )
                row = cur.fetchone() or {}
            cod_prv, nom_prv = lookup_provider(conn, row.get("cod_prv"))

        num_compra = (args.num_compra or fecha.strftime("%d%m%Y")).strip()
        ex_despues = ex_antes + cantidad

        print(
            f"Product: {codigo} (cost={costo_antes}, costopro={costopro_antes}, "
            f"sinv stock={ex_antes})"
        )

        if args.legacy_comprasdbf:
            contador = next_compras_contador(conn)
            numdoc = f"T{suf}"[:6]
            print(
                f"[legacy] INSERT comprasdbf: contador={contador} numdoc={numdoc} "
                f"cantidad={cantidad} precio={precio} monto={subtotal2}"
            )
            if args.dry_run:
                return 0
            _insert_legacy_comprasdbf(
                conn,
                codigo=codigo,
                cantidad=cantidad,
                precio=precio,
                monto=subtotal2,
                fecha=fecha,
                numdoc=numdoc,
                contador=contador,
                lote_splits=lote_splits,
                args=args,
                costo_antes=costo_antes,
                costopro_antes=costopro_antes,
            )
            conn.commit()
            print("OK: legacy purchase inserted (sync_outbox comprasdbf).")
            show_recent_outbox(conn, "comprasdbf")
            maybe_flush(args.flush)
            return 0

        print(
            f"INSERT scom: numero={num_compra} codigo={codigo} "
            f"cantidad={cantidad} costo={precio} subtotal2={subtotal2}"
        )
        print(
            f"INSERT kardex: compras={cantidad} costo={precio} numero={num_compra}"
        )
        for cubica, qty, lote in lote_splits:
            print(
                f"INSERT kardexd: cubica={cubica} ajustesp={qty} "
                f"(lote detalle={lote or 'default'})"
            )
        if not args.no_update_sinv:
            print(
                f"UPDATE sinv + detalle: existencia += {cantidad}, "
                f"costo/costopro con precio={precio}"
            )

        if args.dry_run:
            return 0

        with conn.cursor() as cur:
            scom_indice = insert_scom_purchase_line(
                cur,
                conn,
                numero=num_compra,
                cod_prv=cod_prv or "0000000000",
                codigo=codigo,
                descrip=descrip,
                fecha=fecha,
                cantidad=float(cantidad),
                costo=precio,
                costopro=costopro_antes,
                subtotal2=subtotal2,
            )
            kobs = format_kobs_compra(
                num_compra, cod_prv, nom_prv, ind=scom_indice
            )
            indice_k = insert_kardex_header(
                cur,
                codigo=codigo,
                fecha=fecha,
                compras=float(cantidad),
                existenciai=ex_antes,
                entradas=float(cantidad),
                existenciaf=ex_despues,
                costo=precio,
                costopro=costopro_antes,
                kobs=kobs,
                cajero="SUPERVISOR",
                numero=num_compra,
            )
            indices_d: list[int] = []
            for cubica, qty, _lote in lote_splits:
                indice_d = insert_kardexd_line(
                    cur,
                    codigo=codigo,
                    fecha=fecha,
                    cubica=cubica,
                    ajustesp=float(qty),
                    existenciai=ex_antes,
                    entradas=float(qty),
                    existenciaf=ex_despues,
                    costo=precio,
                    costopro=costopro_antes,
                    kobs=kobs,
                    cajero="SUPERVISOR",
                )
                indices_d.append(indice_d)

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
                f"costopro {costopro_antes} -> {costopro_nuevo}"
            )
            for cubica, qty, lote in lote_splits:
                upsert_detalle_lote(conn, codigo, qty, lote=lote, cubica=cubica, costo=precio)
                print(f"detalle: cubica={cubica} lote={lote or '(default)'} +{qty}")

        conn.commit()
        print(
            f"OK: scom indice={scom_indice}, kardex indice={indice_k}, "
            f"kardexd={indices_d} (outbox monto=subtotal2 from scom)."
        )
        show_recent_outbox(conn, ["comprasdbf"])
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
