#!/usr/bin/env python3
"""
Extrae del mysqldump (solo datos) filas del producto y documentos relacionados
(compras, ventas, facturas contables, cabeceras, etc.).

Usa estructura_tablas_json/ para indices de columnas (codigo, numero, id, ...).

Pasada 1: filas con codigo = producto → recolecta claves (numero compra/venta, scst.id, ...).
Pasada 2: filas por codigo, por claves o por texto (asientos, auditoria, outbox).

Uso:
  python scripts/extract_product_from_sql_dump.py \\
    --input ../../sistema-20260531.sql \\
    --codigo FF23834 \\
    --output ../../backup-FF23834.sql \\
    --include-text-tables
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

INSERT_RE = re.compile(
    r"^INSERT INTO `(\w+)`(?:\s*\(([^)]+)\))?\s*VALUES\s*(.+);\s*$",
    re.DOTALL,
)

KOBS_COMPRA_RE = re.compile(r"Compra#:\s*([^\s]+)", re.I)
KOBS_VTA_RE = re.compile(r"Vta#:\s*([^\s]+)", re.I)
AJUSTE_NRO_RE = re.compile(r"Ajuste Nro:\s*([^\s]+)", re.I)

DEFAULT_TEXT_TABLES = frozenset(
    {
        "catalog_push_digest",
        "sync_outbox_router",
        "auditoriag",
        "auditor",
        "auditorcompras",
        "asientos",
        "historialc",
        "historialp",
    }
)

# Tablas maestras enlazadas por clave (no siempre aparece el codigo en la linea INSERT).
MASTER_KEY_TABLES: dict[str, str] = {
    "catego": "ccate",
    "sprv": "cod_prv",
    "scli": "cod_cli",
    "scli_aux": "cod_cli",
}

# Tablas donde numero = documento de compra (linea o cabecera).
PURCHASE_NUMERO_TABLES = frozenset(
    {
        "scom",
        "scomd",
        "dscom",
        "rscom",
        "rscomd",
        "scst",
        "rscst",
        "rscst_old",
        "rscom_old",
        "comprasdbf",
        "scomoinv",
        "dscst",
        "ivapa",
        "aivapai",
        "aivapad",
    }
)

SALE_NUMERO_TABLES = frozenset(
    {
        "ventas",
        "ventasi",
        "ventasd",
        "ventasl",
        "ventasm",
        "vventasi",
        "vventasd",
        "diariovi",
        "dventasi",
        "dventasd",
        "diariov",
        "notaei",
        "notae",
        "cotizai",
    }
)

AJUSTE_NUMERO_TABLES = frozenset(
    {
        "ajuste",
        "ajustei",
        "ajusteila",
        "ajustepei",
        "ajustepes",
        "ajustes",
    }
)


@dataclass
class TableSchema:
    columns: list[str]

    def idx(self, name: str) -> int | None:
        try:
            return self.columns.index(name)
        except ValueError:
            return None


@dataclass
class RelatedKeys:
    compra_numeros: set[str] = field(default_factory=set)
    venta_numeros: set[str] = field(default_factory=set)
    ajuste_numeros: set[str] = field(default_factory=set)
    scst_ids: set[str] = field(default_factory=set)
    cod_prv: set[str] = field(default_factory=set)
    ccate: set[str] = field(default_factory=set)
    cod_cli: set[str] = field(default_factory=set)
    kardex_indices: set[str] = field(default_factory=set)

    def all_needles(self) -> list[str]:
        """Subcadenas para tablas solo-texto (asientos, etc.)."""
        needles: list[str] = []
        for n in sorted(self.compra_numeros):
            needles.append(n)
        for n in sorted(self.venta_numeros):
            needles.append(n)
        for n in sorted(self.ajuste_numeros):
            needles.append(n)
        for i in sorted(self.scst_ids):
            needles.append(i)
        return needles


def load_schemas(schema_dir: Path) -> dict[str, TableSchema]:
    out: dict[str, TableSchema] = {}
    for path in sorted(schema_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cols = [c.get("nombre", "") for c in data.get("columnas") or []]
        if cols:
            out[path.stem] = TableSchema(columns=cols)
    return out


def iter_row_blobs(values_blob: str):
    i = 0
    n = len(values_blob)
    while i < n:
        while i < n and values_blob[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if values_blob[i] != "(":
            raise ValueError(f"se esperaba '(' en pos {i}")
        i += 1
        start = i
        depth = 1
        in_str = False
        esc = False
        while i < n and depth > 0:
            ch = values_blob[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == "'":
                    in_str = False
                i += 1
                continue
            if ch == "'":
                in_str = True
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        yield values_blob[start : i - 1]
        while i < n and values_blob[i] in " \t\r\n,":
            i += 1


def split_fields(row_blob: str) -> list[str]:
    fields: list[str] = []
    i = 0
    n = len(row_blob)
    cur_start = 0
    depth = 0
    in_str = False
    esc = False

    def flush(end: int) -> None:
        fields.append(row_blob[cur_start:end].strip())

    while i < n:
        ch = row_blob[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "'":
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if ch == "," and depth == 0:
            flush(i)
            i += 1
            cur_start = i
            continue
        i += 1
    flush(n)
    return fields


def normalize_sql_value(raw: str) -> str | None:
    s = raw.strip()
    if s.upper() == "NULL":
        return None
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        inner = s[1:-1]
        inner = inner.replace("\\'", "'").replace("''", "'")
        return inner
    return s


def field_matches_codigo(field: str, codigo: str) -> bool:
    val = normalize_sql_value(field)
    return val is not None and val.strip() == codigo


def add_keys_from_row(
    table: str,
    fields: list[str],
    schema: TableSchema | None,
    keys: RelatedKeys,
) -> None:
    if not schema:
        return

    def val(name: str) -> str | None:
        i = schema.idx(name)
        if i is None or i >= len(fields):
            return None
        return normalize_sql_value(fields[i])

    c = val("codigo")
    if c:
        if schema.idx("cod_prv") is not None:
            p = val("cod_prv")
            if p:
                keys.cod_prv.add(p)
        if schema.idx("ccate") is not None:
            cat = val("ccate")
            if cat:
                keys.ccate.add(cat)

    numero = val("numero")
    if numero:
        if table in PURCHASE_NUMERO_TABLES or table in {"kardex", "kardexd", "historialc"}:
            keys.compra_numeros.add(numero)
        if table in SALE_NUMERO_TABLES or table in {"kardex", "kardexd", "diariovi"}:
            keys.venta_numeros.add(numero)

    if table in AJUSTE_NUMERO_TABLES and numero:
        keys.ajuste_numeros.add(numero)

    indice = val("indice")
    if indice and table in {"scom", "scomd", "kardex", "kardexd"}:
        keys.kardex_indices.add(indice)
        keys.scst_ids.add(indice)

    scst_id = val("id")
    if scst_id and table == "scst":
        keys.scst_ids.add(scst_id)

    cli = val("cod_cli")
    if cli:
        keys.cod_cli.add(cli)

    kobs = val("kobs")
    if kobs:
        for m in KOBS_COMPRA_RE.finditer(kobs):
            keys.compra_numeros.add(m.group(1).strip())
        for m in KOBS_VTA_RE.finditer(kobs):
            keys.venta_numeros.add(m.group(1).strip())
        for m in AJUSTE_NRO_RE.finditer(kobs):
            keys.ajuste_numeros.add(m.group(1).strip())


def row_matches(
    table: str,
    fields: list[str],
    codigo: str,
    keys: RelatedKeys,
    schema: TableSchema | None,
    *,
    text_mode: bool,
    needles: list[str],
) -> bool:
    if schema and schema.idx("codigo") is not None:
        i = schema.idx("codigo")
        if i < len(fields) and field_matches_codigo(fields[i], codigo):
            return True

    if schema:
        def val(name: str) -> str | None:
            i = schema.idx(name)
            if i is None or i >= len(fields):
                return None
            return normalize_sql_value(fields[i])

        numero = val("numero")
        if numero:
            if table in PURCHASE_NUMERO_TABLES and numero in keys.compra_numeros:
                return True
            if table in SALE_NUMERO_TABLES and numero in keys.venta_numeros:
                return True
            if table in AJUSTE_NUMERO_TABLES and numero in keys.ajuste_numeros:
                return True
            # scomd: numero largo 3005202691 — prefijo de compra
            for cn in keys.compra_numeros:
                if numero.startswith(cn):
                    return True

        scst_id = val("id")
        if scst_id and scst_id in keys.scst_ids:
            return True

        indice = val("indice")
        if indice and indice in keys.kardex_indices:
            return True

        prv = val("cod_prv")
        if prv and prv in keys.cod_prv:
            return True

        cat = val("ccate")
        if cat and cat in keys.ccate:
            return True

        cli = val("cod_cli")
        if cli and cli in keys.cod_cli:
            return True

        codigod = val("codigod")
        if codigod and codigod.strip() == codigo:
            return True

    if text_mode:
        blob = ",".join(fields)
        if f"'{codigo}'" in blob:
            return True
        for needle in needles:
            if len(needle) >= 4 and needle in blob:
                return True

    return False


def filter_rows(
    values_blob: str,
    table: str,
    codigo: str,
    keys: RelatedKeys,
    schema: TableSchema | None,
    *,
    text_mode: bool,
    needles: list[str],
) -> list[str]:
    kept: list[str] = []
    for row in iter_row_blobs(values_blob):
        fields = split_fields(row)
        if row_matches(
            table,
            fields,
            codigo,
            keys,
            schema,
            text_mode=text_mode,
            needles=needles,
        ):
            kept.append(f"({row})")
    return kept


def collect_keys_pass(
    input_path: Path,
    codigo: str,
    schemas: dict[str, TableSchema],
) -> RelatedKeys:
    keys = RelatedKeys()
    for line in input_path.open("r", encoding="utf-8", errors="replace"):
        if codigo not in line:
            continue
        m = INSERT_RE.match(line)
        if not m:
            continue
        table = m.group(1)
        schema = schemas.get(table)
        if not schema or schema.idx("codigo") is None:
            continue
        try:
            for row in iter_row_blobs(m.group(3)):
                fields = split_fields(row)
                ci = schema.idx("codigo")
                if ci >= len(fields) or not field_matches_codigo(fields[ci], codigo):
                    continue
                add_keys_from_row(table, fields, schema, keys)
        except ValueError:
            continue
    return keys


def scan_dump(
    input_path: Path,
    output_path: Path,
    codigo: str,
    schemas: dict[str, TableSchema],
    keys: RelatedKeys,
    include_text_tables: bool,
) -> dict[str, int]:
    stats: dict[str, int] = {}
    needles = keys.all_needles()
    lines_read = 0
    t0 = time.perf_counter()

    with input_path.open("r", encoding="utf-8", errors="replace") as src, output_path.open(
        "w", encoding="utf-8"
    ) as out:
        for _ in range(16):
            line = src.readline()
            if not line:
                break
            out.write(line)

        out.write(
            f"\n-- Extraido: codigo={codigo}\n"
            f"-- Claves: compras={len(keys.compra_numeros)} ventas={len(keys.venta_numeros)} "
            f"ajustes={len(keys.ajuste_numeros)} scst_ids={len(keys.scst_ids)} "
            f"proveedores={len(keys.cod_prv)} categorias={len(keys.ccate)}\n"
        )
        if keys.compra_numeros:
            out.write(f"-- Numeros compra: {', '.join(sorted(keys.compra_numeros)[:20])}\n")
        if keys.venta_numeros:
            out.write(f"-- Numeros venta: {', '.join(sorted(keys.venta_numeros)[:20])}\n")
        out.write("\n")

        for line in src:
            lines_read += 1
            if lines_read % 500_000 == 0:
                print(
                    f"  ... {lines_read:,} lineas ({time.perf_counter() - t0:.0f}s)",
                    file=sys.stderr,
                )

            m = INSERT_RE.match(line)
            if not m:
                continue

            table, _, values_part = m.group(1), m.group(2), m.group(3)
            schema = schemas.get(table)
            text_mode = include_text_tables and table in DEFAULT_TEXT_TABLES

            has_codigo_col = schema is not None and schema.idx("codigo") is not None
            can_link = (
                has_codigo_col
                or text_mode
                or (schema and schema.idx("numero") is not None)
                or (schema and schema.idx("id") is not None)
                or table in MASTER_KEY_TABLES
            )
            if not can_link:
                continue

            quick_need = (
                codigo in line
                or text_mode
                or any(n in line for n in needles if len(n) >= 6)
            )
            if not quick_need and table in MASTER_KEY_TABLES:
                master_vals = {
                    "ccate": keys.ccate,
                    "cod_prv": keys.cod_prv,
                    "cod_cli": keys.cod_cli,
                }[MASTER_KEY_TABLES[table]]
                quick_need = any(k in line for k in master_vals)
            if not quick_need:
                continue

            try:
                rows = filter_rows(
                    values_part,
                    table,
                    codigo,
                    keys,
                    schema,
                    text_mode=text_mode,
                    needles=needles,
                )
            except ValueError as exc:
                print(f"WARN {table}: {exc}", file=sys.stderr)
                continue

            if not rows:
                continue

            out.write(f"\n-- `{table}` ({len(rows)} filas)\n")
            out.write(f"LOCK TABLES `{table}` WRITE;\n")
            out.write(f"/*!40000 ALTER TABLE `{table}` DISABLE KEYS */;\n")
            out.write(f"INSERT INTO `{table}` VALUES {','.join(rows)};\n")
            out.write(f"/*!40000 ALTER TABLE `{table}` ENABLE KEYS */;\n")
            out.write("UNLOCK TABLES;\n")
            stats[table] = len(rows)

        out.write("\n-- Fin extracto\n")

    stats["_lines_read"] = lines_read
    return stats


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    default_schema = repo_root / "estructura_tablas_json"
    default_input = repo_root / "sistema-20260531.sql"

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=default_input)
    p.add_argument("--codigo", required=True)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--schema-dir", type=Path, default=default_schema)
    p.add_argument(
        "--include-text-tables",
        action="store_true",
        help="Incluir asientos, outbox, auditoria por texto",
    )
    args = p.parse_args()

    codigo = args.codigo.strip()
    if not codigo:
        print("codigo vacio", file=sys.stderr)
        return 2

    input_path = args.input.resolve()
    if not input_path.is_file():
        print(f"No existe: {input_path}", file=sys.stderr)
        return 1

    schema_dir = args.schema_dir.resolve()
    if not schema_dir.is_dir():
        print(f"No existe schema-dir: {schema_dir}", file=sys.stderr)
        return 1

    output_path = (
        args.output.resolve()
        if args.output
        else input_path.parent / f"backup-{codigo}.sql"
    )

    schemas = load_schemas(schema_dir)
    print(f"Entrada:  {input_path} ({input_path.stat().st_size / 1e9:.2f} GB)", file=sys.stderr)
    print(f"Salida:   {output_path}", file=sys.stderr)
    print(f"Producto: {codigo}", file=sys.stderr)

    print("Pasada 1: claves relacionadas...", file=sys.stderr)
    keys = collect_keys_pass(input_path, codigo, schemas)
    print(
        f"  compras={sorted(keys.compra_numeros)} ventas={sorted(keys.venta_numeros)} "
        f"ajustes={sorted(keys.ajuste_numeros)} scst_id={sorted(keys.scst_ids)[:10]}",
        file=sys.stderr,
    )

    print("Pasada 2: extraccion...", file=sys.stderr)
    stats = scan_dump(
        input_path,
        output_path,
        codigo,
        schemas,
        keys,
        args.include_text_tables,
    )

    total = sum(v for k, v in stats.items() if not k.startswith("_"))
    print(f"\nListo: {total} filas en {len(stats)} tablas → {output_path}", file=sys.stderr)
    for table in sorted(k for k in stats if not k.startswith("_")):
        print(f"  {table}: {stats[table]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
