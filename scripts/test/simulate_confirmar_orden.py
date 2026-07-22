#!/usr/bin/env python3
"""Confirma una preventa (POST /ordenes) como venta ERP.

Carga diariov/diariovi por nordene (orderId), asigna numero de factura,
marca confirma='E', escribe kardex/kardexd y descuenta stock (como simulate_venta).
No inserta nuevas líneas diariovi: reutiliza las de la preventa.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from _common import (
    apply_detalle_venta_deducciones,
    apply_sinv_existencia_delta,
    connect_dict,
    erp_venta_numero,
    format_kobs_venta,
    insert_kardex_header,
    insert_kardexd_line,
    maybe_flush,
    plan_detalle_venta,
    read_sinv_costs,
    read_sinv_existencia,
    require_mysql,
    resolve_movimiento_datetime,
    show_recent_outbox,
)


def _print_detalle_plan(deducciones) -> None:
    for d in deducciones:
        vence = d.vence.isoformat() if d.vence else "(sin vence)"
        print(
            f"  UPDATE detalle: lote={d.lote or '(default)'} cubica={d.cubica} "
            f"vence={vence} {d.qty_antes} -> {d.qty_despues} (-{d.deducido})"
        )


def _station_from_ccaja(ccaja: str) -> str:
    code = (ccaja or "").strip()
    return code[:2] if len(code) >= 2 else (code or "01")


def _default_factura_numero(ccaja: str, mov_dt) -> str:
    """Prefijo estación (2) + sufijo tipo erp_venta_numero, máx. 15."""
    station = _station_from_ccaja(ccaja)
    body = erp_venta_numero(mov_dt)
    if body.startswith("1") and len(body) > 1:
        body = body[1:]
    return f"{station}{body}"[:15]


def _load_preventa(conn, nordene: str) -> dict[str, Any]:
    key = nordene.strip()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ccaja, nordene, confirma, numero, cod_cli, total, cod_ven, fecha
            FROM diariov
            WHERE TRIM(nordene) = %s
            LIMIT 1
            """,
            (key,),
        )
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"preventa no encontrada: nordene={key!r}")
    confirma = str(row.get("confirma") or "").strip().upper()
    if confirma == "E":
        raise RuntimeError(
            f"preventa ya confirmada (confirma=E): nordene={key!r} "
            f"numero={row.get('numero')!r}"
        )
    if confirma and confirma != "N":
        raise RuntimeError(
            f"preventa en estado inesperado confirma={confirma!r}: nordene={key!r}"
        )
    existing_num = str(row.get("numero") or "").strip()
    if existing_num:
        raise RuntimeError(
            f"preventa ya tiene numero={existing_num!r}: nordene={key!r}"
        )
    return row


def _load_lines(conn, ccaja: str) -> list[dict[str, Any]]:
    ticket = ccaja.strip()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT codigo, descrip, cantidad, costo, subtotal2, contador,
                   ccaja, cod_cli, COALESCE(porvg, 0) AS porvg
            FROM diariovi
            WHERE TRIM(ccaja) = %s
            ORDER BY contador
            """,
            (ticket,),
        )
        rows = list(cur.fetchall() or [])
    if not rows:
        raise RuntimeError(f"sin líneas diariovi para ccaja={ticket!r}")
    return rows


def _cliente_label(conn, cod_cli: str) -> str:
    code = (cod_cli or "").strip()
    if not code:
        return "CLIENTE"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT nom_cli FROM scli WHERE cod_cli = %s LIMIT 1",
            (code,),
        )
        row = cur.fetchone()
    nom = str((row or {}).get("nom_cli") or "").strip()
    return f"{code} {nom}".strip() if nom else code


def _plan_line_stock(
    conn,
    *,
    codigo: str,
    cantidad: float,
    stock_left: dict[str, float],
    sin_lotes: bool,
    require_lotes: bool,
    lote: str | None,
    cubica: str | None,
    no_update_sinv: bool,
) -> tuple[float, float, list]:
    """Devuelve (ex_antes, ex_despues, deducciones) y actualiza stock_left."""
    if codigo not in stock_left:
        stock_left[codigo] = read_sinv_existencia(conn, codigo)
    ex_antes = stock_left[codigo]

    deducciones = []
    use_detalle = False
    if not no_update_sinv and not sin_lotes:
        require_detalle = bool(require_lotes or lote or cubica)
        deducciones = plan_detalle_venta(
            conn,
            codigo,
            cantidad,
            lote=lote,
            cubica=cubica,
            require_detalle=require_detalle,
        )
        use_detalle = bool(deducciones)
        if not use_detalle:
            print(
                f"Aviso: sin filas en detalle para {codigo}; "
                "descontando solo sinv.existencia"
            )

    if not no_update_sinv and not use_detalle:
        if ex_antes + 1e-9 < cantidad:
            raise RuntimeError(
                f"Stock insuficiente en sinv para {codigo!r}: "
                f"pedido={cantidad}, existencia={ex_antes}"
            )

    ex_despues = ex_antes - cantidad
    stock_left[codigo] = ex_despues
    return ex_antes, ex_despues, deducciones


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Confirma preventa (nordene/orderId) → venta ERP: "
            "confirma=E, numero factura, kardex + stock"
        )
    )
    parser.add_argument(
        "--nordene",
        "--order-id",
        dest="nordene",
        required=True,
        help="orderId público de la preventa (diariov.nordene)",
    )
    parser.add_argument(
        "--numero",
        default=None,
        help="Número de factura (default: estación + timestamp)",
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
        "--sin-lotes",
        action="store_true",
        help="No usa tabla detalle; solo descuenta sinv.existencia",
    )
    parser.add_argument(
        "--require-lotes",
        action="store_true",
        help="Exige filas en detalle (falla si no hay lotes)",
    )
    parser.add_argument(
        "--flush",
        action="store_true",
        help="Envía pending de sync_outbox_router al router",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra el plan, sin UPDATE/INSERT",
    )
    parser.add_argument(
        "--no-update-sinv",
        action="store_true",
        help="No modifica sinv.existencia ni detalle",
    )
    args = parser.parse_args()

    if args.sin_lotes and args.require_lotes:
        print("Error: no combines --sin-lotes y --require-lotes", file=sys.stderr)
        return 2
    if args.sin_lotes and (args.lote or args.cubica):
        print("Error: --sin-lotes no admite --lote / --cubica", file=sys.stderr)
        return 2

    mysql = require_mysql()
    conn = connect_dict(mysql)
    try:
        header = _load_preventa(conn, args.nordene)
        ccaja = str(header["ccaja"]).strip()
        nordene = str(header["nordene"]).strip()
        cod_cli = str(header.get("cod_cli") or "").strip()
        lines = _load_lines(conn, ccaja)

        mov_dt = resolve_movimiento_datetime()
        kardex_fecha = mov_dt.date()
        hora = mov_dt.strftime("%H:%M:%S:")
        numero = (args.numero or _default_factura_numero(ccaja, mov_dt)).strip()[:15]
        station = _station_from_ccaja(ccaja)
        cliente = _cliente_label(conn, cod_cli)

        print(
            f"Preventa nordene={nordene} ccaja={ccaja} "
            f"cliente={cod_cli} total={header.get('total')} líneas={len(lines)}"
        )
        print(
            f"Confirmar → numero={numero} confirma=E "
            f"fconfirma={kardex_fecha} hconfirma={hora}"
        )

        # Validación previa de stock agregado (sinv) antes de escribir.
        demand: dict[str, float] = {}
        for line in lines:
            sku = str(line["codigo"]).strip()
            qty = float(line["cantidad"] or 0)
            if qty <= 0:
                raise RuntimeError(
                    f"cantidad inválida en diariovi contador={line.get('contador')} "
                    f"sku={sku}"
                )
            demand[sku] = demand.get(sku, 0.0) + qty
        if not args.no_update_sinv:
            for sku, qty in demand.items():
                disponible = read_sinv_existencia(conn, sku)
                if disponible + 1e-9 < qty:
                    raise RuntimeError(
                        f"Stock insuficiente en sinv para {sku!r}: "
                        f"pedido={qty}, existencia={disponible}"
                    )

        print(f"UPDATE diariovi SET numero={numero!r} WHERE ccaja={ccaja!r}")
        print(
            f"UPDATE diariov SET numero={numero!r}, confirma='E', "
            f"fconfirma={kardex_fecha}, hconfirma={hora!r} WHERE nordene={nordene!r}"
        )

        if args.dry_run:
            stock_left: dict[str, float] = {}
            for line in lines:
                codigo = str(line["codigo"]).strip()
                cantidad = float(line["cantidad"] or 0)
                contador = int(line["contador"] or 0)
                unit = float(line.get("costo") or 0)
                ex_antes, ex_despues, deducciones = _plan_line_stock(
                    conn,
                    codigo=codigo,
                    cantidad=cantidad,
                    stock_left=stock_left,
                    sin_lotes=args.sin_lotes,
                    require_lotes=args.require_lotes,
                    lote=args.lote,
                    cubica=args.cubica,
                    no_update_sinv=args.no_update_sinv,
                )
                print(
                    f"Línea contador={contador} sku={codigo} qty={cantidad} "
                    f"precio={unit} stock {ex_antes} -> {ex_despues}"
                )
                print(
                    f"  INSERT kardex/kardexd: numero={numero} contador={contador} "
                    f"cajero={station}"
                )
                if deducciones:
                    for d in deducciones:
                        print(
                            f"  INSERT kardexd: cubica={d.cubica} "
                            f"ajustesn={d.deducido} (lote={d.lote or 'default'})"
                        )
                    _print_detalle_plan(deducciones)
                else:
                    print(
                        f"  INSERT kardexd: cubica=01 ajustesn={cantidad} "
                        "(sin lotes / solo sinv)"
                    )
                if not args.no_update_sinv:
                    print(f"  UPDATE sinv: existencia -= {cantidad}")
            print("(dry-run: sin cambios)")
            return 0

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE diariovi SET numero = %s WHERE TRIM(ccaja) = %s",
                (numero, ccaja),
            )
            cur.execute(
                """
                UPDATE diariov
                SET numero = %s,
                    confirma = 'E',
                    fconfirma = %s,
                    hconfirma = %s
                WHERE TRIM(nordene) = %s
                """,
                (numero, kardex_fecha, hora[:15], nordene),
            )

            indices_k: list[int] = []
            # FEFO + sinv línea a línea para que el siguiente SKU vea stock ya descontado.
            for line in lines:
                codigo = str(line["codigo"]).strip()
                cantidad = float(line["cantidad"] or 0)
                contador = int(line["contador"] or 0)
                unit = float(line.get("costo") or 0)
                costo, costopro = read_sinv_costs(conn, codigo)
                ex_antes = read_sinv_existencia(conn, codigo)

                deducciones = []
                if not args.no_update_sinv and not args.sin_lotes:
                    require_detalle = bool(
                        args.require_lotes or args.lote or args.cubica
                    )
                    deducciones = plan_detalle_venta(
                        conn,
                        codigo,
                        cantidad,
                        lote=args.lote,
                        cubica=args.cubica,
                        require_detalle=require_detalle,
                    )
                    if not deducciones:
                        print(
                            f"Aviso: sin filas en detalle para {codigo}; "
                            "descontando solo sinv.existencia"
                        )

                if not args.no_update_sinv and not deducciones:
                    if ex_antes + 1e-9 < cantidad:
                        raise RuntimeError(
                            f"Stock insuficiente en sinv para {codigo!r}: "
                            f"pedido={cantidad}, existencia={ex_antes}"
                        )

                ex_despues = ex_antes - cantidad
                kobs = format_kobs_venta(
                    numero,
                    cliente=cliente,
                    caja=station,
                    operador=station,
                    when=mov_dt,
                )

                print(
                    f"Línea contador={contador} sku={codigo} qty={cantidad} "
                    f"precio={unit} stock {ex_antes} -> {ex_despues}"
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
                    cajero=station,
                    numero=numero,
                    contador=contador,
                )
                indices_k.append(indice_k)

                running_ex = ex_antes
                if deducciones:
                    for d in deducciones:
                        ex_line_f = running_ex - d.deducido
                        insert_kardexd_line(
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
                            cajero=station,
                            numero=numero,
                            contador=contador,
                        )
                        running_ex = ex_line_f
                    apply_detalle_venta_deducciones(conn, deducciones)
                    _print_detalle_plan(deducciones)
                else:
                    insert_kardexd_line(
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
                        cajero=station,
                        numero=numero,
                        contador=contador,
                    )

                if not args.no_update_sinv:
                    ex0, ex1 = apply_sinv_existencia_delta(conn, codigo, -cantidad)
                    print(f"  sinv {codigo}: {ex0} -> {ex1}")

        conn.commit()
        print(
            f"OK: preventa {nordene} confirmada como factura {numero}; "
            f"kardex indices={indices_k}"
        )
        show_recent_outbox(conn, ["kardex", "diariovi", "detalle"])
    except Exception as ex:
        conn.rollback()
        print(f"Error: {ex}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    maybe_flush(args.flush)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
