#!/usr/bin/env python3
"""Ejecuta las cuatro simulaciones en secuencia."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
SCRIPTS = (
    "simulate_compra.py",
    "simulate_venta.py",
    "simulate_kardex_devolucion.py",
    "simulate_kardex_ajuste.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Corre todas las simulaciones transaccionales")
    parser.add_argument("--flush", action="store_true", help="Pasa --flush a cada script")
    parser.add_argument("--codigo", help="SKU fijo para todos")
    parser.add_argument("--dry-run", action="store_true")
    args, extra = parser.parse_known_args()

    py = sys.executable
    rc = 0
    for i, name in enumerate(SCRIPTS):
        cmd = [py, str(DIR / name)]
        if args.codigo:
            cmd.extend(["--codigo", args.codigo])
        if args.dry_run:
            cmd.append("--dry-run")
        if args.flush:
            cmd.append("--flush")
        cmd.extend(extra)
        print(f"\n=== {name} ===")
        r = subprocess.run(cmd, cwd=str(DIR.parent.parent))
        if r.returncode != 0:
            rc = r.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
