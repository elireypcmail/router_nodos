#!/usr/bin/env python3
"""Simula compra ERP completa: scom → kardex/kardexd → sinv/detalle/historial → outbox."""

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
    erp_compra_numero,
    format_kobs_compra,
    insert_kardex_header,
    insert_kardexd_line,
    insert_scst_purchase_confirmation,
    insert_scom_purchase_line,
    lookup_provider,
    make_test_lote_ids,
    maybe_flush,
    next_compras_contador,
    parse_lotes_percentages,
    pick_product,
    critical_bucket_label,
    critical_vence_dates,
    LOT_EXPIRY_CRITICAL_COUNT,
    random_future_vence,
    read_sinv_costs,
    read_sinv_existencia,
    require_mysql,
    resolve_movimiento_datetime,
    resolve_simulation_fecha,
    show_recent_outbox,
    test_suffix,
    upsert_detalle_lote,
)
from datetime import date

from scom_purchase_line import (
    DEFAULT_SCOM_FACTOR,
    build_scom_purchase_line,
    read_sinv_scom_row,
)


def _resolve_lote_split(
    cantidad: int,
    num_lotes: int | None,
    lotes_pct: str | None,
    *,
    lotes_criticos: bool = False,
) -> list[tuple[str, int, str, date]]:
    if lotes_criticos:
        num_lotes = LOT_EXPIRY_CRITICAL_COUNT
        if cantidad < num_lotes:
            raise ValueError(
                f"--lotes-criticos requiere --cantidad >= {num_lotes} "
                f"(una unidad por rango de vencimiento)"
            )
        if lotes_pct:
            raise ValueError("--lotes-criticos no admite --lotes-pct (reparto en partes iguales)")

    if num_lotes is None:
        return [("01", cantidad, "", random_future_vence())]

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
    if lotes_criticos:
        vences = critical_vence_dates()
    else:
        vences = [random_future_vence() for _ in range(num_lotes)]
    return [
        (cubica, qty, lote, vence)
        for cubica, qty, lote, vence in zip(
            cubicas, amounts, lot_ids, vences, strict=True
        )
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
    cod_prv: str = "",
    nom_prv: str = "",
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
        _apply_post_compra_sinv_and_erp(
            conn,
            codigo=codigo,
            cantidad=cantidad,
            precio=precio,
            costo_antes=costo_antes,
            costopro_antes=costopro_antes,
            num_compra=numdoc,
            cod_prv=cod_prv,
            nom_prv=nom_prv,
            fecha=fecha,
            args=args,
            factor=getattr(args, "factor", None) or DEFAULT_SCOM_FACTOR,
        )
        for split in lote_splits:
            cubica, qty, calidad, vence_row = split
            upsert_detalle_lote(
                conn,
                codigo,
                qty,
                calidad=calidad,
                lote="",
                vence=vence_row,
                costo=precio,
                factor=getattr(args, "factor", None) or DEFAULT_SCOM_FACTOR,
            )
            print(
                f"lot detail: calidad={calidad or cubica} +{qty} vence={vence_row} "
                f"disponible=S (outbox lot -> hub)"
            )


def _apply_post_compra_sinv_and_erp(
    conn,
    *,
    codigo: str,
    cantidad: int,
    precio: float,
    costo_antes: float,
    costopro_antes: float,
    num_compra: str,
    cod_prv: str,
    nom_prv: str,
    fecha,
    args,
    factor: float | None = None,
) -> None:
    from erp_compra_effects import apply_erp_post_compra_effects

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
    if not getattr(args, "no_recalc_precios", False):
        fx = apply_erp_post_compra_effects(
            conn,
            codigo=codigo,
            costo_antes=costo_antes,
            costopro_antes=costopro_antes,
            costo_nuevo=costo_nuevo,
            costopro_nuevo=costopro_nuevo,
            num_compra=num_compra,
            cod_prv=cod_prv or "",
            nom_prv=nom_prv,
            factor=factor,
            operador=getattr(args, "operador", "SUPERVISOR"),
            fecha=fecha,
        )
        if fx.get("historialc"):
            print(f"historialc: {', '.join(fx['historialc'])}")
        if fx.get("historialp"):
            print(f"historialp: {', '.join(fx['historialp'])}")
        if fx.get("sinv_precios"):
            print(f"sinv precios recalculados: {fx['sinv_precios']}")
        if fx.get("detallepr"):
            print(f"detallepr actualizado: {fx['detallepr']}")


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
        "--lotes-criticos",
        action="store_true",
        help=(
            f"Crea {LOT_EXPIRY_CRITICAL_COUNT} lotes con vencimiento en cada rango "
            "de riesgo portal (<30, 30-60, 60-90, 90-120, >120 días); "
            f"requiere --cantidad >= {LOT_EXPIRY_CRITICAL_COUNT}"
        ),
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
    parser.add_argument(
        "--factor",
        type=float,
        default=DEFAULT_SCOM_FACTOR,
        help=f"Tipo de cambio factura (scom.factor); USD = Bs / factor (default {DEFAULT_SCOM_FACTOR:g})",
    )
    parser.add_argument(
        "--operador",
        default="SUPERVISOR",
        help="Usuario ERP en historialc/historialp (default: SUPERVISOR)",
    )
    parser.add_argument(
        "--no-recalc-precios",
        action="store_true",
        help="No recalcula precios ni escribe historialc/historialp post-compra",
    )
    args = parser.parse_args()

    if args.lotes_pct and args.lotes is None and not args.lotes_criticos:
        print("Error: --lotes-pct requires --lotes N", file=sys.stderr)
        return 2
    if args.lotes_criticos and args.lotes is not None and args.lotes != LOT_EXPIRY_CRITICAL_COUNT:
        print(
            f"Aviso: --lotes-criticos fija {LOT_EXPIRY_CRITICAL_COUNT} lotes "
            f"(ignorando --lotes {args.lotes})",
            file=sys.stderr,
        )

    mysql = require_mysql()
    conn = connect_dict(mysql)
    try:
        product = pick_product(conn, args.codigo, aleatorio=args.aleatorio)
        codigo = str(product["codigo"]).strip()
        cantidad = max(1, int(args.cantidad))
        precio = float(args.precio)
        subtotal2 = round(precio * cantidad, 2)
        fecha = resolve_simulation_fecha(args)
        descrip = str(product.get("descrip") or "").strip()
        suf = test_suffix()

        try:
            raw_splits = _resolve_lote_split(
                cantidad,
                args.lotes,
                args.lotes_pct,
                lotes_criticos=args.lotes_criticos,
            )
        except ValueError as ex:
            print(f"Error: {ex}", file=sys.stderr)
            return 2

        lote_splits = raw_splits

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

        mov_dt = resolve_movimiento_datetime()
        kardex_fecha = mov_dt.date()
        num_compra = (
            args.num_compra or erp_compra_numero(mov_dt)
        ).strip()[:30]
        ex_despues = ex_antes + cantidad
        factor = float(args.factor) if args.factor and args.factor > 0 else DEFAULT_SCOM_FACTOR
        sinv_row = read_sinv_scom_row(conn, codigo)
        scom_line = build_scom_purchase_line(
            sinv_row,
            cantidad=float(cantidad),
            costo_unitario=precio,
            costo_antes=costo_antes,
            costopro_antes=costopro_antes,
            existencia_antes=ex_antes,
            factor=factor,
        )

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
                cod_prv=cod_prv or "",
                nom_prv=nom_prv,
            )
            conn.commit()
            print("OK: legacy purchase inserted (sync_outbox comprasdbf).")
            show_recent_outbox(conn, "comprasdbf")
            maybe_flush(args.flush)
            return 0

        print(
            f"INSERT scom: numero={num_compra} codigo={codigo} "
            f"cantidad={cantidad} costo={precio} subtotal2={scom_line['subtotal2']} "
            f"factor={scom_line.get('factor')} costopro={scom_line.get('costopro')}"
        )
        print(
            f"INSERT scst: numero={num_compra} fecha={kardex_fecha} "
            f"fconfirma={kardex_fecha} hconfirma={mov_dt.strftime('%H:%M:%S')}"
        )
        print(
            f"INSERT kardex: fecha={kardex_fecha} compras={cantidad} costo={precio} "
            f"numero={num_compra} (scom.fecha={fecha})"
        )
        for i, (cubica, qty, calidad, vence_row) in enumerate(lote_splits):
            bucket = critical_bucket_label(i) if args.lotes_criticos else None
            print(
                f"INSERT kardexd: cubica={cubica} ajustesp={qty} "
                f"(calidad={calidad or 'default'} vence={vence_row}"
                f"{f' · {bucket}' if bucket else ''})"
            )
        if not args.no_update_sinv:
            print(
                f"UPDATE sinv + detalle + historial: existencia += {cantidad}, "
                f"costo/costopro, historialc/historialp, detallepr"
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
                line=scom_line,
            )
            if not insert_scst_purchase_confirmation(
                cur,
                numero=num_compra,
                cod_prv=cod_prv or "0000000000",
                subtotal2=float(scom_line.get("subtotal2") or subtotal2),
                factor=factor,
                confirmado_en=mov_dt,
            ):
                print(
                    "Aviso: tabla scst no disponible; outbox sin fconfirma/hconfirma",
                    file=sys.stderr,
                )
            kobs = format_kobs_compra(
                num_compra,
                cod_prv,
                nom_prv,
                ind=scom_indice,
                operador=args.operador,
                when=mov_dt,
            )
            cpp_kardex = float(scom_line.get("costopro") or costopro_antes)
            indice_k = insert_kardex_header(
                cur,
                codigo=codigo,
                fecha=kardex_fecha,
                compras=float(cantidad),
                existenciai=ex_antes,
                entradas=float(cantidad),
                existenciaf=ex_despues,
                costo=precio,
                costopro=cpp_kardex,
                kobs=kobs,
                cajero="SUPERVISOR",
                numero=num_compra,
            )
            indices_d: list[int] = []
            for cubica, qty, _lote, _vence in lote_splits:
                indice_d = insert_kardexd_line(
                    cur,
                    codigo=codigo,
                    fecha=kardex_fecha,
                    cubica=cubica,
                    ajustesp=float(qty),
                    existenciai=ex_antes,
                    entradas=float(qty),
                    existenciaf=ex_despues,
                    costo=precio,
                    costopro=cpp_kardex,
                    kobs=kobs,
                    cajero="SUPERVISOR",
                )
                indices_d.append(indice_d)

        if not args.no_update_sinv:
            _apply_post_compra_sinv_and_erp(
                conn,
                codigo=codigo,
                cantidad=cantidad,
                precio=precio,
                costo_antes=costo_antes,
                costopro_antes=costopro_antes,
                num_compra=num_compra,
                cod_prv=cod_prv or "",
                nom_prv=nom_prv,
                fecha=fecha,
                args=args,
                factor=factor,
            )
            for i, (cubica, qty, calidad, vence_row) in enumerate(lote_splits):
                upsert_detalle_lote(
                    conn,
                    codigo,
                    qty,
                    calidad=calidad,
                    lote="",
                    cubica=cubica,
                    vence=vence_row,
                    costo=precio,
                    costopro=cpp_kardex,
                    factor=factor,
                )
                bucket = critical_bucket_label(i) if args.lotes_criticos else None
                print(
                    f"detalle: cubica={cubica} calidad={calidad or '(default)'} "
                    f"+{qty} vence={vence_row} disponible=S"
                    f"{f' · {bucket}' if bucket else ''}"
                )

        conn.commit()
        print(
            f"OK: scom indice={scom_indice}, kardex indice={indice_k}, "
            f"kardexd={indices_d} (outbox monto=subtotal2 from scom)."
        )
        show_recent_outbox(conn, ["comprasdbf", "historialp"])
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
