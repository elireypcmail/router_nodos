#!/usr/bin/env python3
"""Ejecuta movimientos.csv con simuladores por tienda (Docker 1-3, local 4)."""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

RunnerMode = Literal["host", "in-container"]
ExecutionMode = Literal["docker", "local"]

SCRIPTS_DIR = Path(__file__).resolve().parent
NODO_ROOT = SCRIPTS_DIR.parents[1]
ENVS_DIR = SCRIPTS_DIR / "envs"
DEFAULT_INPUT = SCRIPTS_DIR / "movimientos.csv"
LOCAL_ENV_FILE = NODO_ROOT / ".env"

DOCKER_NODOS = frozenset({1, 2, 3})
DEFAULT_LOCAL_NODO = 4
DOCKER_CONTAINER_TEMPLATE = "multishop-nodo-tienda-{nodo}"
DOCKER_SCRIPT_PREFIX = "scripts/test"
DEFAULT_MOVEMENT_DELAY_SEC = 5.0

SIMULATOR_BY_TIPO: dict[str, tuple[str, list[str]]] = {
    "compra": ("simulate_compra.py", []),
    "venta": ("simulate_venta.py", []),
    "ajuste_entrada": ("simulate_kardex_ajuste.py", ["--direccion", "entrada"]),
    "ajuste_salida": ("simulate_kardex_ajuste.py", ["--direccion", "salida"]),
    "devolucion_proveedor": (
        "simulate_kardex_devolucion.py",
        ["--tipo", "devoc"],
    ),
}

FX_TIPOS = frozenset({"compra", "venta"})
OUTBOUND_TIPOS = frozenset({"venta", "ajuste_salida", "devolucion_proveedor"})


@dataclass(frozen=True)
class CsvMovement:
    line_no: int
    fecha: date
    nodo: int
    codigo: str
    tipo_movimiento: str
    cantidad: float
    precio: float
    factor_cambio: float | None
    inventario_inicial: float | None
    inventario_final: float | None


@dataclass(frozen=True)
class ExecutionPlan:
    mode: ExecutionMode
    nodo: int
    argv: list[str]
    env: dict[str, str] | None
    cwd: Path | None
    display: str
    label: str = ""


@dataclass
class RunState:
    compra_done: set[int] = field(default_factory=set)
    bootstrap_done: set[int] = field(default_factory=set)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lee movimientos.csv y ejecuta simulate_compra/venta/kardex en el orden "
            "de filas del archivo (línea 2, 3, …). Desde el Mac: nodos 1-3 vía "
            f"docker exec; nodo {DEFAULT_LOCAL_NODO} con .env local. "
            "Dentro de un contenedor tienda-N (--runner in-container): solo ese nodo."
        ),
        epilog=(
            "Ejemplo: run_movimientos_csv.py --dry-run\n"
            "         run_movimientos_csv.py --flush"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"CSV generado por generate_movimientos_csv.py (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--flush",
        action="store_true",
        help="Pasa --flush a cada simulador (envía outbox al hub tras cada movimiento)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo imprime comandos; no ejecuta simuladores",
    )
    parser.add_argument(
        "--from-line",
        type=int,
        default=2,
        metavar="N",
        help="Primera fila de datos del CSV (default: 2, tras encabezado)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Máximo de movimientos a ejecutar",
    )
    parser.add_argument(
        "--local-nodo",
        type=int,
        default=DEFAULT_LOCAL_NODO,
        metavar="N",
        help=f"Número de nodo CSV ejecutado en local (default: {DEFAULT_LOCAL_NODO})",
    )
    parser.add_argument(
        "--router-url",
        "--hub-url",
        dest="router_url",
        default="http://127.0.0.1:3000",
        help="ROUTER_EVENTS_URL para tienda local con --flush (default: http://127.0.0.1:3000)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python del Mac para la tienda local (default: intérprete actual)",
    )
    parser.add_argument(
        "--docker",
        default="docker",
        help="Binario docker para tiendas 1-3 en modo host (default: docker)",
    )
    parser.add_argument(
        "--runner",
        choices=("auto", "host", "in-container"),
        default="auto",
        help=(
            "auto: docker en PATH → orquesta contenedores; si no, modo in-container. "
            "host: siempre docker exec (Mac). in-container: python local en esta tienda."
        ),
    )
    parser.add_argument(
        "--container-nodo",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Nodo CSV al ejecutar dentro de multishop-nodo-tienda-N "
            "(default: detectar por HOSTNAME)"
        ),
    )
    parser.add_argument(
        "--no-recalc-precios",
        action="store_true",
        help="En compras, pasa --no-recalc-precios (más rápido en lotes grandes)",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Sigue con la siguiente fila si un simulador falla",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_MOVEMENT_DELAY_SEC,
        metavar="SEC",
        help=(
            f"Segundos de espera entre simuladores consecutivos "
            f"(default: {DEFAULT_MOVEMENT_DELAY_SEC:g}; 0 = sin pausa)"
        ),
    )
    parser.add_argument(
        "--no-bootstrap-stock",
        action="store_true",
        help=(
            "No inserta compra inicial por tienda antes de la primera salida/venta "
            "(por defecto sí: MySQL parte en 0 y ventas requieren detalle/lotes)"
        ),
    )
    return parser.parse_args()


def is_docker_available(docker_bin: str) -> bool:
    if not shutil.which(docker_bin):
        return False
    try:
        return (
            subprocess.run(
                [docker_bin, "info"],
                capture_output=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect_container_nodo() -> int | None:
    for key in ("HOSTNAME", "CONTAINER_NAME"):
        name = os.environ.get(key, "")
        match = re.search(r"multishop-nodo-tienda-(\d+)", name, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def resolve_runner_mode(args: argparse.Namespace) -> tuple[RunnerMode, int | None]:
    if args.runner == "host":
        if not is_docker_available(args.docker):
            raise SystemExit(
                f"Error: --runner host requiere '{args.docker}' en PATH y accesible."
            )
        return "host", None

    if args.runner == "in-container":
        nodo = args.container_nodo if args.container_nodo is not None else detect_container_nodo()
        if nodo is None:
            raise SystemExit(
                "Error: --runner in-container requiere HOSTNAME multishop-nodo-tienda-N "
                "o --container-nodo N."
            )
        return "in-container", nodo

    if is_docker_available(args.docker):
        return "host", None

    nodo = args.container_nodo if args.container_nodo is not None else detect_container_nodo()
    if nodo is not None:
        return "in-container", nodo

    raise SystemExit(
        "Error: no hay 'docker' en PATH y no se detectó contenedor multishop-nodo-tienda-N.\n"
        "  Orquesta todas las tiendas desde el Mac:\n"
        "    cd Multishop-nodo-API && python scripts/test/run_movimientos_csv.py --flush\n"
        "  O ejecuta solo esta tienda dentro del contenedor:\n"
        "    python scripts/test/run_movimientos_csv.py --runner in-container --container-nodo N"
    )


def parse_fecha(raw: str) -> date:
    return date.fromisoformat(raw.strip()[:10])


def parse_float(raw: str) -> float:
    text = raw.strip()
    if not text:
        return 0.0
    return float(text.replace(",", "."))


def parse_optional_float(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    return float(text.replace(",", "."))


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"No existe archivo env: {path}")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def read_movements(path: Path) -> list[CsvMovement]:
    if not path.is_file():
        raise SystemExit(f"Error: no existe {path}")
    rows: list[CsvMovement] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "fecha",
            "nodo",
            "codigo",
            "tipo_movimiento",
            "cantidad",
            "precio",
        }
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise SystemExit(
                f"Error: CSV debe incluir columnas {sorted(required)}; "
                f"tiene {reader.fieldnames}"
            )
        for line_no, raw in enumerate(reader, start=2):
            tipo = raw["tipo_movimiento"].strip()
            if tipo not in SIMULATOR_BY_TIPO:
                raise SystemExit(
                    f"Error línea {line_no}: tipo_movimiento desconocido {tipo!r}"
                )
            rows.append(
                CsvMovement(
                    line_no=line_no,
                    fecha=parse_fecha(raw["fecha"]),
                    nodo=int(raw["nodo"].strip()),
                    codigo=raw["codigo"].strip(),
                    tipo_movimiento=tipo,
                    cantidad=parse_float(raw["cantidad"]),
                    precio=parse_float(raw["precio"]),
                    factor_cambio=parse_optional_float(
                        raw.get("factor_cambio", "") or ""
                    ),
                    inventario_inicial=parse_optional_float(
                        raw.get("inventario_inicial", "") or ""
                    ),
                    inventario_final=parse_optional_float(
                        raw.get("inventario_final", "") or ""
                    ),
                ),
            )
    return rows


def docker_container_name(nodo: int) -> str:
    return DOCKER_CONTAINER_TEMPLATE.format(nodo=nodo)


def validate_nodos_for_movements(
    movements: list[CsvMovement],
    *,
    local_nodo: int,
    runner_mode: RunnerMode,
    container_nodo: int | None,
) -> None:
    nodos = sorted({movement.nodo for movement in movements})
    problems: list[str] = []
    for nodo in nodos:
        if runner_mode == "in-container":
            if nodo != container_nodo:
                continue
            if not LOCAL_ENV_FILE.is_file():
                problems.append(
                    f"falta {LOCAL_ENV_FILE} para tienda en contenedor (nodo {nodo})"
                )
            continue
        if nodo in DOCKER_NODOS:
            continue
        if nodo == local_nodo:
            if not LOCAL_ENV_FILE.is_file():
                problems.append(f"falta {LOCAL_ENV_FILE} para tienda local (nodo {nodo})")
            continue
        problems.append(
            f"nodo {nodo} no mapeado (docker {sorted(DOCKER_NODOS)}, "
            f"local --local-nodo={local_nodo})"
        )
    if problems:
        raise SystemExit("Error: " + "; ".join(problems))


def build_simulator_argv(
    movement: CsvMovement,
    *,
    flush: bool,
    no_recalc_precios: bool,
) -> tuple[str, list[str]]:
    script_name, extra = SIMULATOR_BY_TIPO[movement.tipo_movimiento]
    argv = [
        *extra,
        "--codigo",
        movement.codigo,
        "--fecha",
        movement.fecha.isoformat(),
        "--cantidad",
        str(movement.cantidad),
    ]
    if movement.tipo_movimiento in FX_TIPOS:
        if movement.precio > 0:
            argv.extend(["--precio", str(movement.precio)])
        if movement.factor_cambio is not None and movement.factor_cambio > 0:
            argv.extend(["--factor", str(movement.factor_cambio)])
    if movement.tipo_movimiento == "compra" and no_recalc_precios:
        argv.append("--no-recalc-precios")
    if movement.tipo_movimiento == "compra":
        lotes = max(1, min(int(movement.cantidad), 5))
        argv.extend(["--lotes", str(lotes)])
    if flush:
        argv.append("--flush")
    return script_name, argv


def first_compra_profile(
    movements: list[CsvMovement],
    nodo: int,
) -> tuple[float, float]:
    for movement in movements:
        if movement.nodo == nodo and movement.tipo_movimiento == "compra":
            factor = movement.factor_cambio if movement.factor_cambio else 500.0
            return movement.precio, factor
    for movement in movements:
        if movement.nodo == nodo and movement.precio > 0:
            factor = movement.factor_cambio if movement.factor_cambio else 500.0
            return movement.precio, factor
    return 200.0, 500.0


def outbound_demand_for_nodo(movements: list[CsvMovement], nodo: int) -> float:
    total = 0.0
    for movement in movements:
        if movement.nodo != nodo:
            continue
        if movement.tipo_movimiento in OUTBOUND_TIPOS:
            total += movement.cantidad
    return total


def first_fecha_for_nodo(movements: list[CsvMovement], nodo: int) -> date:
    for movement in movements:
        if movement.nodo == nodo:
            return movement.fecha
    return date.today()


def build_bootstrap_compra(
    *,
    nodo: int,
    codigo: str,
    selected: list[CsvMovement],
) -> CsvMovement:
    precio, factor = first_compra_profile(selected, nodo)
    demand = outbound_demand_for_nodo(selected, nodo)
    cantidad = int(max(50, math.ceil(max(demand, 1.0) * 1.25)))
    fecha = first_fecha_for_nodo(selected, nodo) - timedelta(days=1)
    return CsvMovement(
        line_no=0,
        fecha=fecha,
        nodo=nodo,
        codigo=codigo,
        tipo_movimiento="compra",
        cantidad=cantidad,
        precio=precio,
        factor_cambio=factor,
        inventario_inicial=None,
        inventario_final=None,
    )


def needs_bootstrap_stock(
    movement: CsvMovement,
    state: RunState,
    *,
    enabled: bool,
) -> bool:
    if not enabled:
        return False
    if movement.tipo_movimiento not in OUTBOUND_TIPOS:
        return False
    if movement.nodo in state.compra_done:
        return False
    return movement.nodo not in state.bootstrap_done


def build_execution_plan(
    movement: CsvMovement,
    args: argparse.Namespace,
    *,
    label: str = "",
) -> ExecutionPlan:
    script_name, argv = build_simulator_argv(
        movement,
        flush=args.flush,
        no_recalc_precios=args.no_recalc_precios,
    )

    runner_mode: RunnerMode = args.runner_mode
    container_nodo: int | None = args.container_nodo
    run_local = movement.nodo == args.local_nodo or (
        runner_mode == "in-container" and movement.nodo == container_nodo
    )

    if movement.nodo in DOCKER_NODOS and runner_mode == "host":
        container = docker_container_name(movement.nodo)
        script_path = f"{DOCKER_SCRIPT_PREFIX}/{script_name}"
        cmd = [args.docker, "exec", container, "python", script_path, *argv]
        return ExecutionPlan(
            mode="docker",
            nodo=movement.nodo,
            argv=cmd,
            env=None,
            cwd=None,
            display=shlex.join(cmd),
            label=label,
        )

    if run_local:
        cmd = [args.python, str(SCRIPTS_DIR / script_name), *argv]
        env = os.environ.copy()
        env.update(load_dotenv(LOCAL_ENV_FILE))
        if args.flush and not (
            runner_mode == "in-container" and env.get("ROUTER_EVENTS_URL")
        ):
            env["ROUTER_EVENTS_URL"] = args.router_url.rstrip("/")
        display = shlex.join(cmd)
        if args.flush and env.get("ROUTER_EVENTS_URL"):
            display = f"ROUTER_EVENTS_URL={env['ROUTER_EVENTS_URL']} {display}"
        return ExecutionPlan(
            mode="local",
            nodo=movement.nodo,
            argv=cmd,
            env=env,
            cwd=NODO_ROOT,
            display=display,
            label=label,
        )

    if runner_mode == "in-container":
        raise SystemExit(
            f"Error: movimiento línea {movement.line_no} es nodo {movement.nodo}, "
            f"pero el contenedor es tienda {container_nodo}."
        )

    raise SystemExit(
        f"Error: nodo {movement.nodo} no configurado "
        f"(docker {sorted(DOCKER_NODOS)}, local {args.local_nodo})"
    )


def execute_plan(plan: ExecutionPlan, args: argparse.Namespace) -> int:
    prefix = f"{plan.label} " if plan.label else ""
    print(f"{prefix}{plan.display}")
    if args.dry_run:
        return 0
    return subprocess.run(
        plan.argv,
        cwd=str(plan.cwd) if plan.cwd else None,
        env=plan.env,
        check=False,
    ).returncode


def pause_between_movements(args: argparse.Namespace) -> None:
    delay = max(0.0, float(args.delay))
    if delay <= 0 or args.dry_run:
        return
    print(f"  … esperando {delay:g}s antes del siguiente movimiento")
    time.sleep(delay)


def run_movements(args: argparse.Namespace, movements: list[CsvMovement]) -> int:
    start = max(2, args.from_line)
    selected = [row for row in movements if row.line_no >= start]
    if args.limit is not None:
        selected = selected[: max(0, args.limit)]

    if args.runner_mode == "in-container":
        other = [row for row in selected if row.nodo != args.container_nodo]
        if other:
            print(
                f"Modo contenedor (nodo {args.container_nodo}): "
                f"omitiendo {len(other)} movimiento(s) de otros nodos."
            )
        selected = [row for row in selected if row.nodo == args.container_nodo]

    if not selected:
        print("No hay movimientos para ejecutar.")
        return 0

    validate_nodos_for_movements(
        selected,
        local_nodo=args.local_nodo,
        runner_mode=args.runner_mode,
        container_nodo=args.container_nodo,
    )

    print(f"Ejecutando {len(selected)} movimiento(s) desde {args.input}")
    if args.runner_mode == "host":
        print(
            f"  docker: nodos {sorted(DOCKER_NODOS)} → "
            f"{DOCKER_CONTAINER_TEMPLATE.format(nodo='N')}"
        )
        print(f"  local: nodo {args.local_nodo} → {NODO_ROOT} ({LOCAL_ENV_FILE.name})")
    else:
        print(
            f"  in-container: nodo {args.container_nodo} → "
            f"{NODO_ROOT} ({LOCAL_ENV_FILE.name})"
        )
    if not args.no_bootstrap_stock:
        print("  bootstrap: compra + --lotes antes de la primera salida/venta por tienda")
    if args.delay > 0 and not args.dry_run:
        print(f"  delay: {args.delay:g}s entre cada simulador")

    state = RunState()
    failures = 0
    steps = 0
    ran_simulator = False
    for movement in selected:
        if needs_bootstrap_stock(
            movement,
            state,
            enabled=not args.no_bootstrap_stock,
        ):
            bootstrap = build_bootstrap_compra(
                nodo=movement.nodo,
                codigo=movement.codigo,
                selected=selected,
            )
            steps += 1
            print(
                f"\n=== [bootstrap {steps}] nodo={movement.nodo} "
                f"compra qty={bootstrap.cantidad:.0f} fecha={bootstrap.fecha} "
                f"(antes de línea {movement.line_no}) ==="
            )
            plan = build_execution_plan(
                bootstrap,
                args,
                label="[bootstrap]",
            )
            if ran_simulator:
                pause_between_movements(args)
            rc = execute_plan(plan, args)
            if not args.dry_run:
                ran_simulator = True
            if rc != 0:
                failures += 1
                print(
                    f"Fallo bootstrap nodo {movement.nodo} (exit {rc})",
                    file=sys.stderr,
                )
                if not args.continue_on_error:
                    return rc
            else:
                state.bootstrap_done.add(movement.nodo)
                state.compra_done.add(movement.nodo)

        steps += 1
        plan = build_execution_plan(movement, args)
        header = (
            f"[{steps}/{len(selected) + len(state.bootstrap_done)}] "
            f"línea {movement.line_no} {movement.fecha} nodo={movement.nodo} "
            f"({plan.mode}) {movement.tipo_movimiento} qty={movement.cantidad}"
        )
        print(f"\n=== {header} ===")
        if ran_simulator:
            pause_between_movements(args)
        rc = execute_plan(plan, args)
        if not args.dry_run:
            ran_simulator = True
        if rc != 0:
            failures += 1
            print(
                f"Fallo línea {movement.line_no} (exit {rc})",
                file=sys.stderr,
            )
            if not args.continue_on_error:
                return rc
        elif movement.tipo_movimiento == "compra":
            state.compra_done.add(movement.nodo)

    if args.dry_run:
        print("\nDry-run: no se ejecutó ningún simulador.")
        return 0

    if failures:
        print(f"\nTerminado con {failures} fallo(s).", file=sys.stderr)
        return 1
    print(f"\nOK: {len(selected)} movimiento(s) del CSV ejecutados.")
    return 0


def main() -> int:
    args = parse_args()
    runner_mode, container_nodo = resolve_runner_mode(args)
    args.runner_mode = runner_mode
    args.container_nodo = container_nodo
    movements = read_movements(args.input.resolve())
    return run_movements(args, movements)


if __name__ == "__main__":
    raise SystemExit(main())
