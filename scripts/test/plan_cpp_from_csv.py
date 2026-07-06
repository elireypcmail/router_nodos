#!/usr/bin/env python3
"""Genera movimientos-cpp-plan.txt desde movimientos.csv (replay CPP hub + trazabilidad)."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = REPO_ROOT / "movimientos.csv"
DEFAULT_OUTPUT = REPO_ROOT / "movimientos-cpp-plan.txt"
DEFAULT_OUTPUT_CSV = REPO_ROOT / "movimientos-cpp-plan.csv"

KIND_PRIORITY = {
    "purchase": 0,
    "kardex_entrada": 1,
    "sale": 2,
    "kardex_salida": 3,
}

TIPO_TO_KIND = {
    "compra": "purchase",
    "ajuste_entrada": "kardex_entrada",
    "venta": "sale",
    "ajuste_salida": "kardex_salida",
    "devolucion_proveedor": "kardex_salida",
}


@dataclass(frozen=True)
class CsvRow:
    line_no: int
    fecha: date
    nodo: int
    codigo: str
    tipo: str
    cantidad: int
    precio: float
    factor_cambio: float | None
    inventario_inicial: int
    inventario_final: int


@dataclass
class CppState:
    unidades: float = 0.0
    valor: float = 0.0
    cpp: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Simula replay CPP hub desde movimientos.csv y escribe un plan "
            "de trazabilidad (orden ejecución vs orden CPP, existencia hub, "
            "numero probable scom)."
        ),
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="CSV auxiliar con una fila por paso CPP (default: movimientos-cpp-plan.csv)",
    )
    parser.add_argument(
        "--match",
        default="",
        help="Resalta filas cuyo numero probable o texto contenga este fragmento",
    )
    return parser.parse_args()


def parse_date(raw: str) -> date:
    return date.fromisoformat(raw.strip())


def parse_int(raw: str) -> int:
    return int(float(raw.strip()))


def parse_float(raw: str) -> float:
    return float(raw.strip())


def load_rows(path: Path) -> list[CsvRow]:
    rows: list[CsvRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for line_no, raw in enumerate(reader, start=2):
            rows.append(
                CsvRow(
                    line_no=line_no,
                    fecha=parse_date(raw["fecha"]),
                    nodo=int(raw["nodo"]),
                    codigo=raw["codigo"].strip(),
                    tipo=raw["tipo_movimiento"].strip(),
                    cantidad=parse_int(raw["cantidad"]),
                    precio=parse_float(raw["precio"]),
                    factor_cambio=(
                        parse_float(raw["factor_cambio"])
                        if (raw.get("factor_cambio") or "").strip()
                        else None
                    ),
                    inventario_inicial=parse_int(raw.get("inventario_inicial", "0") or "0"),
                    inventario_final=parse_int(raw.get("inventario_final", "0") or "0"),
                ),
            )
    return rows


def cpp_from_state(state: CppState) -> float:
    if state.unidades > 0:
        return state.valor / state.unidades
    return state.cpp


def apply_entrada(state: CppState, cantidad: float, costo: float) -> CppState:
    if cantidad <= 0:
        return state
    if state.unidades <= 0:
        return CppState(
            unidades=cantidad,
            valor=cantidad * costo,
            cpp=costo,
        )
    unidades = state.unidades + cantidad
    valor = state.valor + cantidad * costo
    return CppState(unidades=unidades, valor=valor, cpp=valor / unidades)


def apply_entrada_cpp_vigente(state: CppState, cantidad: float) -> CppState:
    if cantidad <= 0:
        return state
    cpp = cpp_from_state(state)
    unidades = state.unidades + cantidad
    valor = state.valor + cantidad * cpp
    return CppState(unidades=unidades, valor=valor, cpp=cpp)


def apply_salida(state: CppState, cantidad: float) -> CppState:
    if cantidad <= 0:
        return state
    cpp = cpp_from_state(state)
    unidades = max(0.0, state.unidades - cantidad)
    valor = max(0.0, state.valor - cantidad * cpp)
    return CppState(unidades=unidades, valor=valor, cpp=cpp if unidades > 0 else cpp)


def apply_movement(state: CppState, kind: str, cantidad: int, precio: float) -> CppState:
    if kind == "purchase":
        return apply_entrada(state, cantidad, precio)
    if kind == "kardex_entrada":
        return apply_entrada_cpp_vigente(state, cantidad)
    if kind in {"sale", "kardex_salida"}:
        return apply_salida(state, cantidad)
    return state


def probable_numero_compra(fecha: date) -> str:
    return fecha.strftime("%d%m%Y")


def sort_cpp_replay(rows: list[CsvRow]) -> list[CsvRow]:
    return sorted(
        rows,
        key=lambda r: (
            r.fecha,
            r.nodo,
            KIND_PRIORITY.get(TIPO_TO_KIND.get(r.tipo, ""), 9),
            r.line_no,
        ),
    )


def fmt_money(value: float) -> str:
    return f"{value:.2f}"


def fmt_cpp(value: float) -> str:
    return f"{value:.2f}"


def build_plan(rows: list[CsvRow], *, match: str) -> tuple[list[str], list[dict[str, str]]]:
    if not rows:
        return ["(CSV vacío)"], []

    codigo = rows[0].codigo
    exec_order = sorted(rows, key=lambda r: (r.fecha, r.nodo, r.tipo, r.line_no))
    cpp_order = sort_cpp_replay(rows)

    lines: list[str] = []
    csv_out: list[dict[str, str]] = []

    lines.append(f"Plan CPP — {codigo}")
    lines.append(f"Generado: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Filas CSV: {len(rows)}")
    lines.append("")
    lines.append(
        "Notas:\n"
        "  · inventario_inicial/final del CSV = stock POR NODO (tienda).\n"
        "  · Exist. ant. / Total uds. del portal = stock HUB agregado (todas las tiendas).\n"
        "  · numero scom probable = DDMMYYYY + HHMMSS al ejecutar simulate_compra.\n"
        "  · El historial portal ordena por eventOccurredAt (outbox); si todo se flush el "
        "mismo día, la UI puede no coincidir con fecha ERP.\n"
        "  · Solo las COMPRAS generan fila en Historial CPP; ventas/ajustes mueven U/V en replay."
    )
    lines.append("")
    lines.append("=" * 88)
    lines.append("A) ORDEN EJECUCIÓN (run_movimientos_csv.py — fecha global)")
    lines.append("=" * 88)

    hub_exec = CppState()
    for idx, row in enumerate(exec_order, start=1):
        kind = TIPO_TO_KIND.get(row.tipo, "")
        hub_before = hub_exec.unidades
        hub_exec = apply_movement(hub_exec, kind, row.cantidad, row.precio)
        numero = probable_numero_compra(row.fecha) if row.tipo == "compra" else ""
        flag = " <<<" if match and match in f"n{row.nodo}{numero}{row.line_no}" else ""
        lines.append(
            f"{idx:03d} L{row.line_no:02d} {row.fecha} nodo={row.nodo} {row.tipo:22s} "
            f"qty={row.cantidad:4d} precio={fmt_money(row.precio):>8s} "
            f"nodo_inv {row.inventario_inicial:4d}->{row.inventario_final:4d} "
            f"hub_u {hub_before:4.0f}->{hub_exec.unidades:4.0f} "
            f"hub_cpp={fmt_cpp(cpp_from_state(hub_exec)):>8s}"
            f"{f'  num~{numero}******' if numero else ''}"
            f"{flag}"
        )

    lines.append("")
    lines.append("=" * 88)
    lines.append("B) ORDEN REPLAY CPP HUB (fecha ERP → nodo → tipo compra/entrada/venta/salida)")
    lines.append("=" * 88)

    hub = CppState()
    purchase_no = 0
    purchases_before = 0
    for idx, row in enumerate(cpp_order, start=1):
        kind = TIPO_TO_KIND.get(row.tipo, "")
        hub_before = hub.unidades
        cpp_before = cpp_from_state(hub)
        hub = apply_movement(hub, kind, row.cantidad, row.precio)
        cpp_after = cpp_from_state(hub)
        numero = probable_numero_compra(row.fecha) if row.tipo == "compra" else ""
        is_purchase = row.tipo == "compra"

        highlight = bool(
            match
            and (
                match in numero
                or match in f"{row.nodo}{numero}"
                or match in f"nodo {row.nodo}"
            )
        )
        marker = " <<< BUSCAR" if highlight else ""

        if is_purchase:
            purchase_no += 1
            valor_antes = hub_before * cpp_before if hub_before > 0 else 0.0
            valor_compra = row.cantidad * row.precio
            valor_despues = hub.valor
            lines.append(
                f"CPP#{purchase_no:02d} paso={idx:03d} L{row.line_no:02d} "
                f"{row.fecha} nodo={row.nodo} COMPRA"
            )
            lines.append(
                f"       num~{numero}******  qty={row.cantidad}  costo_u={fmt_money(row.precio)}"
            )
            lines.append(
                f"       hub Exist.ant={hub_before:.0f}  Cant={row.cantidad}  "
                f"Total uds={hub.unidades:.0f}  CPP {fmt_cpp(cpp_before)} -> {fmt_cpp(cpp_after)}"
            )
            lines.append(
                f"       Valor ant={fmt_money(valor_antes)}  + compra {fmt_money(valor_compra)} "
                f"= subtotal {fmt_money(valor_despues)}"
            )
            if hub_before == 0 and purchases_before > 0:
                lines.append(
                    "       ⚠ Exist.ant=0 pero ya hubo compras antes en replay: "
                    "revisar orden/fecha o ingesta incompleta al hub."
                )
            if marker:
                lines.append(f"       {marker}")
            lines.append("")
            purchases_before += 1
        else:
            lines.append(
                f"paso={idx:03d} L{row.line_no:02d} {row.fecha} nodo={row.nodo} "
                f"{row.tipo:22s} qty={row.cantidad:4d}  "
                f"hub_u {hub_before:4.0f}->{hub.unidades:4.0f}  "
                f"cpp={fmt_cpp(cpp_after)}{marker}"
            )

        csv_out.append(
            {
                "paso_cpp": str(idx),
                "linea_csv": str(row.line_no),
                "fecha_erp": row.fecha.isoformat(),
                "nodo": str(row.nodo),
                "tipo": row.tipo,
                "kind_cpp": kind,
                "cantidad": str(row.cantidad),
                "precio": fmt_money(row.precio),
                "numero_probable": f"{numero}******" if numero else "",
                "nodo_inv_inicial": str(row.inventario_inicial),
                "nodo_inv_final": str(row.inventario_final),
                "hub_exist_antes": f"{hub_before:.0f}",
                "hub_exist_despues": f"{hub.unidades:.0f}",
                "hub_cpp_antes": fmt_cpp(cpp_before),
                "hub_cpp_despues": fmt_cpp(cpp_after),
                "es_compra_cpp": "1" if is_purchase else "0",
            },
        )

    lines.append("")
    lines.append("=" * 88)
    lines.append("C) COMPRAS — resumen para cruzar con Historial CPP portal")
    lines.append("=" * 88)
    lines.append(
        f"{'#':>3}  {'fecha':<12} {'nodo':>4}  {'qty':>4}  {'costo':>8}  "
        f"{'Exist.ant':>9}  {'Total uds':>9}  {'CPP nuevo':>9}  numero~"
    )
    lines.append("-" * 88)

    hub = CppState()
    purchase_no = 0
    for row in cpp_order:
        kind = TIPO_TO_KIND.get(row.tipo, "")
        hub_before = hub.unidades
        cpp_before = cpp_from_state(hub)
        hub = apply_movement(hub, kind, row.cantidad, row.precio)
        if row.tipo != "compra":
            continue
        purchase_no += 1
        numero = probable_numero_compra(row.fecha)
        highlight = match and (match in numero or match in f"{row.nodo}{numero}")
        suffix = " <<<" if highlight else ""
        lines.append(
            f"{purchase_no:3d}  {row.fecha}  n{row.nodo:>3}  {row.cantidad:4d}  "
            f"{fmt_money(row.precio):>8}  {hub_before:9.0f}  {hub.unidades:9.0f}  "
            f"{fmt_cpp(cpp_from_state(hub)):>9}  {numero}******{suffix}"
        )

    lines.append("")
    lines.append(
        f"Estado final replay: hub_unidades={hub.unidades:.0f}  hub_cpp={fmt_cpp(cpp_from_state(hub))}"
    )
    last_by_nodo: dict[int, int] = {}
    for row in sorted(rows, key=lambda r: (r.fecha, r.line_no)):
        last_by_nodo[row.nodo] = row.inventario_final
    sum_last = sum(last_by_nodo.values())
    lines.append(
        f"Suma inventario_final por nodo (última fila de cada tienda): {sum_last}  "
        f"(debe coincidir con hub si no hay desfase)"
    )
    if abs(sum_last - hub.unidades) > 0.5:
        lines.append(
            f"⚠ Diferencia hub replay ({hub.unidades:.0f}) vs suma nodos ({sum_last}): "
            "normal si el CSV no refleja todo el stock hub o hay bootstrap extra."
        )

    return lines, csv_out


def write_txt(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Error: no existe {args.input}")

    rows = load_rows(args.input)
    lines, csv_rows = build_plan(rows, match=args.match.strip())
    write_txt(args.output, lines)
    write_csv(args.output_csv, csv_rows)

    print(f"OK: plan CPP → {args.output.resolve()}")
    print(f"     CSV aux  → {args.output_csv.resolve()}")
    if rows:
        print(f"     codigo={rows[0].codigo}  filas={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
