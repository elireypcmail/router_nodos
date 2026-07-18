#!/usr/bin/env python3
"""Simula venta ERP: kardex (ventas) + kardexd + detalle (FEFO) -> outbox sale + inventory_lot."""

from __future__ import annotations

import argparse

from _common import (
    add_common_args,
    apply_detalle_venta_deducciones,
    apply_sinv_existencia_delta,
    connect_dict,
    erp_venta_numero,
    format_kobs_venta,
    insert_diariovi_sale_line,
    insert_kardex_header,
    insert_kardexd_line,
    maybe_flush,
    next_kardex_contador,
    pick_product,
    plan_detalle_venta,
    read_sinv_costs,
    read_sinv_existencia,
    require_mysql,
    resolve_diariovi_sale_pricing,
    resolve_movimiento_datetime,
    show_recent_outbox,
    test_suffix,
)


def _print_detalle_plan(deducciones) -> None:
    for d in deducciones:
        vence = d.vence.isoformat() if d.vence else "(sin vence)"
        print(
            f"UPDATE detalle: lote={d.lote or '(default)'} cubica={d.cubica} "
            f"vence={vence} {d.qty_antes} -> {d.qty_despues} (-{d.deducido})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Simula venta ERP (kardex + kardexd + detalle FEFO; "
            "outbox diariovi + inventory_lot vía triggers)"
        )
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
        "--lote",
        default=None,
        help="Descontar solo de este lote (default: FEFO por vencimiento)",
    )
    parser.add_argument(
        "--cubica",
        default=None,
        help="Filtrar detalle por cubica (opcional)",
    )
    parser.add_argument(
        "--legacy-ventasi",
        action="store_true",
        help="INSERT solo en ventasi (sin outbox; ya no hay trg_ventasi_*)",
    )
    parser.add_argument(
        "--precio",
        type=float,
        default=None,
        help="Precio unitario de venta Bs (default: sinv.precio1)",
    )
    parser.add_argument(
        "--factor",
        type=float,
        default=None,
        help="Tipo de cambio ticket (diariovi.dolar; default detallepr.cambiodc o 400)",
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

        mov_dt = resolve_movimiento_datetime()
        kardex_fecha = mov_dt.date()
        numero = (args.numero or erp_venta_numero(mov_dt))[:15]
        contador = next_kardex_contador(conn)
        pricing = resolve_diariovi_sale_pricing(
            conn,
            codigo,
            cantidad,
            precio_bs_override=args.precio,
            factor_override=args.factor,
        )
        kobs_kwargs: dict = {
            "cliente": args.cliente,
            "caja": args.caja,
            "operador": "CAJA01",
            "when": mov_dt,
        }
        if pricing.preciodiv is not None and pricing.dolar > 0:
            kobs_kwargs.update(
                precio_bs=pricing.precio_bs,
                precio_usd=pricing.preciodiv,
                tasa_usd=pricing.dolar,
            )
        kobs = format_kobs_venta(numero, **kobs_kwargs)

        ex_antes = read_sinv_existencia(conn, codigo)
        costo, costopro = read_sinv_costs(conn, codigo)
        ex_despues = ex_antes - cantidad
        descrip = str(product.get("descrip") or "").strip()

        deducciones = []
        if not args.no_update_sinv:
            deducciones = plan_detalle_venta(
                conn,
                codigo,
                cantidad,
                lote=args.lote,
                cubica=args.cubica,
            )

        print(f"Product: {codigo} (sinv stock={ex_antes})")
        print(
            f"INSERT diariovi: fecha={kardex_fecha} cantidad={cantidad} costo={pricing.precio_bs} "
            f"preciodiv={pricing.preciodiv} dolar={pricing.dolar} "
            f"subtotal2={pricing.subtotal2} numero={numero} contador={contador}"
        )
        print(
            f"INSERT kardex: fecha={kardex_fecha} ventas={cantidad} numero={numero} "
            f"contador={contador}"
        )
        if deducciones:
            for d in deducciones:
                print(
                    f"INSERT kardexd: cubica={d.cubica} ajustesn={d.deducido} "
                    f"(lote={d.lote or 'default'})"
                )
        else:
            print(f"INSERT kardexd: cubica=01 ajustesn={cantidad}")
        if not args.no_update_sinv:
            print(f"UPDATE sinv: stock -= {cantidad}")
            _print_detalle_plan(deducciones)

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
                    (numero, codigo, cantidad, kardex_fecha, contador, args.caja, ""),
                )
            if not args.no_update_sinv:
                apply_detalle_venta_deducciones(conn, deducciones)
                ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, -cantidad)
                print(f"sinv.stock: {ex0} -> {ex1}")
            conn.commit()
            print("OK: legacy sale inserted (sin outbox; ventasi sin triggers).")
            show_recent_outbox(conn, ["ventasi", "detalle"])
            maybe_flush(args.flush)
            return 0

        with conn.cursor() as cur:
            insert_diariovi_sale_line(
                cur,
                numero=numero,
                codigo=codigo,
                descrip=descrip,
                fecha=kardex_fecha,
                cantidad=cantidad,
                pricing=pricing,
                contador=contador,
                ccaja="CAJA01",
            )
            indice_k = insert_kardex_header(
                cur,
                codigo=codigo,
                fecha=kardex_fecha,
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
            indices_d: list[int] = []
            running_ex = ex_antes
            if deducciones:
                for d in deducciones:
                    ex_line_f = running_ex - d.deducido
                    indice_d = insert_kardexd_line(
                        cur,
                        codigo=codigo,
                        fecha=kardex_fecha,
                        cubica=d.cubica,
                        ajustesn=d.deducido,
                        existenciai=running_ex,
                        salidas=d.deducido,
                        existenciaf=ex_line_f,
                        costo=costo,
                        costopro=costopro,
                        kobs=kobs,
                        cajero="CAJA01",
                        numero=numero,
                        contador=contador,
                    )
                    indices_d.append(indice_d)
                    running_ex = ex_line_f
            else:
                indice_d = insert_kardexd_line(
                    cur,
                    codigo=codigo,
                    fecha=kardex_fecha,
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
                indices_d = [indice_d]

        if not args.no_update_sinv:
            apply_detalle_venta_deducciones(conn, deducciones)
            ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, -cantidad)
            print(f"sinv.stock: {ex0} -> {ex1}")

        conn.commit()
        print(
            f"OK: ERP sale diariovi + kardex indice={indice_k}, kardexd={indices_d} "
            f"(outbox diariovi + detalle inventory_lot)."
        )
        show_recent_outbox(conn, ["diariovi", "ventasi", "detalle"])
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
