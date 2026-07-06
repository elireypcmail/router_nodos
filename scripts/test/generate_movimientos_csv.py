#!/usr/bin/env python3
"""Genera movimientos.csv con movimientos aleatorios multi-nodo (fechas únicas, orden cronológico)."""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

MOVEMENT_TYPES: tuple[str, ...] = (
    "compra",
    "venta",
    "ajuste_entrada",
    "ajuste_salida",
    "devolucion_proveedor",
)
OUTBOUND_TYPES = frozenset({"venta", "ajuste_salida", "devolucion_proveedor"})
FX_MOVEMENT_TYPES = frozenset({"compra", "venta"})
FACTOR_CAMBIO_MIN = 400.0
FACTOR_CAMBIO_MAX = 667.0

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "movimientos.csv"

CSV_HEADERS = (
    "fecha",
    "nodo",
    "codigo",
    "tipo_movimiento",
    "cantidad",
    "precio",
    "factor_cambio",
    "inventario_inicial",
    "inventario_final",
)


@dataclass(frozen=True)
class PlannedMovement:
    fecha: date
    nodo: int
    tipo_movimiento: str


@dataclass
class MovementRow:
    fecha: date
    nodo: int
    codigo: str
    tipo_movimiento: str
    cantidad: float
    precio: float
    factor_cambio: float | None
    inventario_inicial: float
    inventario_final: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera movimientos.csv con compras, ventas y kardex aleatorios "
            "en varios nodos, fechas únicas anteriores a hoy, orden cronológico. "
            "El inventario simulado nunca queda negativo (stock inicial 0 por defecto)."
        ),
        epilog=(
            "Ejemplo: generate_movimientos_csv.py --codigo FF10000022 --nodos 4 "
            "--movimientos 30"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--codigo",
        default="FF10000022",
        help="Código de producto (default: FF10000022)",
    )
    parser.add_argument(
        "--nodos",
        type=int,
        default=4,
        metavar="N",
        help="Cantidad de nodos/tiendas (1..N; default: 4)",
    )
    parser.add_argument(
        "-m",
        "--movimientos",
        type=int,
        default=None,
        metavar="M",
        dest="movimientos",
        help=(
            "Cantidad total de movimientos/filas en el CSV "
            "(default: nodos × 6, mínimo 20; máximo 365 fechas únicas)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Ruta del CSV (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--semilla",
        type=int,
        default=None,
        help="Semilla RNG para reproducir la misma lista",
    )
    parser.add_argument(
        "--stock-inicial",
        type=float,
        default=0.0,
        metavar="Q",
        help="Existencia inicial por nodo al simular el CSV (default: 0, como MySQL vacío)",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.nodos < 1:
        raise SystemExit("Error: --nodos debe ser >= 1")
    if args.stock_inicial < 0:
        raise SystemExit("Error: --stock-inicial no puede ser negativo")
    count = resolve_movement_count(args)
    if count < len(MOVEMENT_TYPES):
        raise SystemExit(
            f"Error: --movimientos debe ser >= {len(MOVEMENT_TYPES)} "
            f"para incluir todos los tipos"
        )
    if count > 365:
        raise SystemExit(
            "Error: --movimientos no puede superar 365 (fechas únicas en el último año)"
        )


def resolve_movement_count(args: argparse.Namespace) -> int:
    if args.movimientos is not None:
        return max(1, int(args.movimientos))
    return max(20, args.nodos * 6)


def unique_past_dates(count: int, rng: random.Random) -> list[date]:
    today = date.today()
    pool = [today - timedelta(days=offset) for offset in range(1, 366)]
    rng.shuffle(pool)
    chosen = pool[:count]
    chosen.sort()
    return chosen


def build_type_pool(count: int, rng: random.Random) -> list[str]:
    base = list(MOVEMENT_TYPES)
    pool: list[str] = []
    while len(pool) < count:
        chunk = base[:]
        rng.shuffle(chunk)
        pool.extend(chunk)
    rng.shuffle(pool[:count])
    # Garantizar al menos un movimiento de cada tipo.
    for tipo in MOVEMENT_TYPES:
        if tipo not in pool[:count]:
            replace_idx = rng.randrange(count)
            pool[replace_idx] = tipo
    return pool[:count]


def plan_movements(
    *,
    count: int,
    nodos: int,
    rng: random.Random,
) -> list[PlannedMovement]:
    fechas = unique_past_dates(count, rng)
    tipos = build_type_pool(count, rng)
    planned: list[PlannedMovement] = []
    for fecha, tipo in zip(fechas, tipos, strict=True):
        nodo = rng.randint(1, nodos)
        planned.append(
            PlannedMovement(fecha=fecha, nodo=nodo, tipo_movimiento=tipo),
        )
    planned.sort(key=lambda row: (row.fecha, row.nodo, row.tipo_movimiento))
    return ensure_first_movement_per_nodo_is_inbound(planned)


INBOUND_TYPES = frozenset({"compra", "ajuste_entrada"})


def ensure_first_movement_per_nodo_is_inbound(
    planned: list[PlannedMovement],
) -> list[PlannedMovement]:
    """Con stock inicial 0, la primera fila de cada nodo no puede ser salida/venta."""
    seen_nodos: set[int] = set()
    adjusted: list[PlannedMovement] = []
    for item in planned:
        if item.nodo not in seen_nodos:
            seen_nodos.add(item.nodo)
            if item.tipo_movimiento in OUTBOUND_TYPES:
                adjusted.append(
                    PlannedMovement(
                        fecha=item.fecha,
                        nodo=item.nodo,
                        tipo_movimiento="compra",
                    ),
                )
                continue
        adjusted.append(item)
    adjusted.sort(key=lambda row: (row.fecha, row.nodo, row.tipo_movimiento))
    return adjusted


def round_stock(value: float) -> int:
    return max(0, int(round(value)))


def round_price(value: float) -> float:
    return round(max(0.0, value), 2)


def random_factor_cambio(rng: random.Random) -> float:
    return round(rng.uniform(FACTOR_CAMBIO_MIN, FACTOR_CAMBIO_MAX), 6)


def factor_cambio_for_tipo(tipo: str, rng: random.Random) -> float | None:
    if tipo in FX_MOVEMENT_TYPES:
        return random_factor_cambio(rng)
    return None


def apply_compra(
    stock: float,
    cpp: float,
    rng: random.Random,
) -> tuple[int, float, int, float]:
    cantidad = rng.randint(8, 45)
    precio = round_price(rng.uniform(85, 420))
    stock_int = round_stock(stock)
    if stock_int <= 0:
        nuevo_cpp = precio
    else:
        total_units = stock_int + cantidad
        nuevo_cpp = (stock_int * cpp + cantidad * precio) / total_units
    nuevo_stock = stock_int + cantidad
    return cantidad, precio, nuevo_stock, nuevo_cpp


def apply_outbound(
    stock: float,
    cpp: float,
    rng: random.Random,
    *,
    tipo: str,
) -> tuple[int, float, int, float]:
    stock_int = round_stock(stock)
    if stock_int <= 0:
        raise ValueError("stock insuficiente para salida")
    upper = min(stock_int, 22)
    lower = min(5, upper)
    cantidad = rng.randint(lower, upper)
    if cantidad <= 0 or cantidad > stock_int:
        raise ValueError("cantidad de salida inválida")
    if tipo == "venta":
        precio = round_price(
            cpp * rng.uniform(1.22, 1.58) if cpp > 0 else rng.uniform(120, 280),
        )
    else:
        precio = round_price(cpp)
    nuevo_stock = stock_int - cantidad
    if nuevo_stock < 0:
        raise ValueError("inventario final negativo")
    return cantidad, precio, nuevo_stock, cpp


def apply_ajuste_entrada(
    stock: float,
    cpp: float,
    rng: random.Random,
) -> tuple[int, float, int, float]:
    cantidad = rng.randint(2, 18)
    precio = round_price(cpp)
    return cantidad, precio, round_stock(stock) + cantidad, cpp


def materialize_movements(
    planned: list[PlannedMovement],
    *,
    codigo: str,
    rng: random.Random,
    nodos: int,
    stock_inicial: float,
) -> list[MovementRow]:
    initial = max(0.0, stock_inicial)
    stock: dict[int, float] = {n: initial for n in range(1, nodos + 1)}
    cpp: dict[int, float] = {
        n: round_price(rng.uniform(90, 250)) for n in range(1, nodos + 1)
    }
    rows: list[MovementRow] = []

    for item in planned:
        nodo = item.nodo
        tipo = item.tipo_movimiento
        inventario_inicial = round_stock(stock[nodo])
        s = stock[nodo]
        c = cpp[nodo]

        if tipo == "compra":
            cantidad, precio, s, c = apply_compra(s, c, rng)
        elif tipo == "ajuste_entrada":
            cantidad, precio, s, c = apply_ajuste_entrada(s, c, rng)
        elif tipo in OUTBOUND_TYPES:
            try:
                cantidad, precio, s, c = apply_outbound(s, c, rng, tipo=tipo)
            except ValueError:
                cantidad, precio, s, c = apply_compra(s, c, rng)
                tipo = "compra"
        else:
            raise ValueError(f"tipo desconocido: {tipo}")

        inventario_final = int(s)
        if inventario_final < 0:
            raise ValueError(
                f"inventario negativo nodo={nodo} fecha={item.fecha} tipo={tipo}"
            )
        expected_final = expected_inventory_after(
            inventario_inicial,
            tipo,
            cantidad,
        )
        if abs(inventario_final - expected_final) > 0:
            raise ValueError(
                f"inventario incoherente nodo={nodo} fecha={item.fecha}: "
                f"inicial={inventario_inicial} cantidad={cantidad} "
                f"final={inventario_final} esperado={expected_final}"
            )

        stock[nodo] = s
        cpp[nodo] = c
        rows.append(
            MovementRow(
                fecha=item.fecha,
                nodo=nodo,
                codigo=codigo.strip(),
                tipo_movimiento=tipo,
                cantidad=cantidad,
                precio=precio,
                factor_cambio=factor_cambio_for_tipo(tipo, rng),
                inventario_inicial=inventario_inicial,
                inventario_final=inventario_final,
            ),
        )

    validate_non_negative_inventory(rows, stock_inicial=initial)
    return rows


def expected_inventory_after(
    inventario_inicial: int,
    tipo: str,
    cantidad: int,
) -> int:
    if tipo in INBOUND_TYPES:
        return inventario_inicial + cantidad
    if tipo in OUTBOUND_TYPES:
        return inventario_inicial - cantidad
    raise ValueError(f"tipo desconocido: {tipo}")


def validate_non_negative_inventory(
    rows: list[MovementRow],
    *,
    stock_inicial: float,
) -> None:
    by_nodo: dict[int, list[MovementRow]] = {}
    for row in rows:
        by_nodo.setdefault(row.nodo, []).append(row)

    for nodo, node_rows in by_nodo.items():
        stock = round_stock(stock_inicial)
        for row in sorted(node_rows, key=lambda r: (r.fecha, r.tipo_movimiento)):
            if row.inventario_inicial != stock:
                raise SystemExit(
                    f"Error interno: inventario_inicial inconsistente nodo={nodo} "
                    f"fecha={row.fecha} esperado={stock} csv={row.inventario_inicial}"
                )
            if row.inventario_final < 0:
                raise SystemExit(
                    f"Error interno: inventario_final negativo "
                    f"{row.fecha} nodo={nodo} ({row.inventario_final})"
                )
            expected = expected_inventory_after(
                row.inventario_inicial,
                row.tipo_movimiento,
                int(row.cantidad),
            )
            if row.inventario_final != expected:
                raise SystemExit(
                    f"Error interno: inventario_final incoherente nodo={nodo} "
                    f"fecha={row.fecha} inicial={row.inventario_inicial} "
                    f"cantidad={row.cantidad} final={row.inventario_final} "
                    f"esperado={expected}"
                )
            if row.tipo_movimiento in INBOUND_TYPES:
                stock += int(row.cantidad)
            elif row.tipo_movimiento in OUTBOUND_TYPES:
                if int(row.cantidad) > stock:
                    raise SystemExit(
                        f"Error interno: salida excede stock nodo={nodo} "
                        f"fecha={row.fecha} stock={stock} cantidad={row.cantidad}"
                    )
                stock -= int(row.cantidad)
            if stock < 0:
                raise SystemExit(
                    f"Error interno: stock negativo nodo={nodo} fecha={row.fecha} "
                    f"({stock})"
                )
            if stock != row.inventario_final:
                raise SystemExit(
                    f"Error interno: inventario_final inconsistente nodo={nodo} "
                    f"fecha={row.fecha} esperado={stock} csv={row.inventario_final}"
                )


def write_csv(path: Path, rows: list[MovementRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            factor = (
                f"{row.factor_cambio:.6f}".rstrip("0").rstrip(".")
                if row.factor_cambio is not None
                else ""
            )
            writer.writerow(
                {
                    "fecha": row.fecha.isoformat(),
                    "nodo": row.nodo,
                    "codigo": row.codigo,
                    "tipo_movimiento": row.tipo_movimiento,
                    "cantidad": str(int(row.cantidad)),
                    "precio": f"{row.precio:.2f}",
                    "factor_cambio": factor,
                    "inventario_inicial": str(int(row.inventario_inicial)),
                    "inventario_final": str(int(row.inventario_final)),
                },
            )


def summarize(rows: list[MovementRow], path: Path) -> None:
    by_type: dict[str, int] = {}
    by_node: dict[int, int] = {}
    for row in rows:
        by_type[row.tipo_movimiento] = by_type.get(row.tipo_movimiento, 0) + 1
        by_node[row.nodo] = by_node.get(row.nodo, 0) + 1
    print(f"OK: {len(rows)} movimientos → {path}")
    if rows:
        print(f"  codigo={rows[0].codigo}")
        print(f"  fechas: {rows[0].fecha} .. {rows[-1].fecha}")
    print(f"  por tipo: {by_type}")
    print(f"  por nodo: {by_node}")
    min_inv = min((int(r.inventario_final) for r in rows), default=0)
    print(f"  inventario_final mínimo: {min_inv}")


def main() -> int:
    args = parse_args()
    validate_args(args)
    count = resolve_movement_count(args)
    rng = random.Random(args.semilla)

    planned = plan_movements(count=count, nodos=args.nodos, rng=rng)
    rows = materialize_movements(
        planned,
        codigo=args.codigo,
        rng=rng,
        nodos=args.nodos,
        stock_inicial=args.stock_inicial,
    )
    write_csv(args.output, rows)
    summarize(rows, args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
