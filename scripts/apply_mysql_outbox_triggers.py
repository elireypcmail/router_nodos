"""Aplica mysql_outbox_triggers.sql: siempre desinstala triggers/funciones Multishop y reinstala desde cero.

Evita duplicar eventos por triggers viejos (JSON_OBJECT, orden incorrecto, reinstalaciones parciales).
Usado por install Windows/Linux/Mac y start-dev.sh.

Variables de entorno:
  MS_MYSQL_HOST, MS_MYSQL_USER, MS_MYSQL_PASSWORD, MS_MYSQL_DATABASE, MS_MYSQL_PORT
  MS_SQL_FILE — ruta al .sql (default: scripts/mysql_outbox_triggers.sql junto a este script)
  MS_OUTBOX_SKIP_PREFLIGHT=1 — solo reaplicar SQL sin DROP previo (no recomendado)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pymysql
from pymysql import err as pymysql_errors

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_SQL = _SCRIPT_DIR / "mysql_outbox_triggers.sql"


def parse_sql_statements(text: str) -> list[str]:
    delim = ";"
    buff: list[str] = []
    stmts: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            delim = stripped.split(None, 1)[1].strip()
            continue
        buff.append(line)
        joined = "\n".join(buff).strip()
        if not joined:
            buff = []
            continue
        if delim != ";":
            if stripped.endswith(delim):
                stmt = "\n".join(buff)
                stmt = stmt.rsplit(delim, 1)[0].strip()
                if stmt:
                    stmts.append(stmt + ";")
                buff = []
        else:
            if stripped.endswith(";"):
                stmt = "\n".join(buff).strip()
                if stmt:
                    stmts.append(stmt)
                buff = []
    tail = "\n".join(buff).strip()
    if tail:
        stmts.append(tail)
    return [s for s in stmts if s.strip()]


def is_executable(stmt: str) -> bool:
    lines = [ln.strip() for ln in stmt.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    return not all(ln.startswith("--") for ln in lines)


def stmt_kind(stmt: str) -> tuple[int, int]:
    upper = stmt.upper()
    if "DROP FUNCTION" in upper or "DROP TRIGGER" in upper:
        return (0, 0)
    if upper.startswith("CREATE TABLE") or "CREATE FUNCTION" in upper:
        return (1, 0)
    if "CREATE TRIGGER" in upper:
        return (2, 0)
    return (3, 0)


def order_statements(stmts: list[str]) -> list[str]:
    executable = [s for s in stmts if is_executable(s)]
    return sorted(executable, key=stmt_kind)


def manifest_from_sql(sql_text: str) -> tuple[list[str], list[str]]:
    """Nombres de triggers/funciones definidos en el SQL (fuente única de verdad)."""
    triggers = sorted(set(re.findall(r"CREATE\s+TRIGGER\s+(\w+)\s+", sql_text, re.I)))
    functions = sorted(set(re.findall(r"CREATE\s+FUNCTION\s+(\w+)\s*\(", sql_text, re.I)))
    return triggers, functions


def connect_mysql(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str | None = None,
    autocommit: bool = True,
) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=autocommit,
    )


def preflight_drop_outbox_objects(
    cur: pymysql.cursors.Cursor,
    *,
    triggers: list[str],
    functions: list[str],
) -> None:
    """Elimina triggers y funciones Multishop outbox antes de reinstalar."""
    for name in triggers:
        cur.execute(f"DROP TRIGGER IF EXISTS `{name}`")
    for name in functions:
        cur.execute(f"DROP FUNCTION IF EXISTS `{name}`")


def apply_sql_file(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sql_path: str | Path,
    skip_preflight: bool = False,
) -> int:
    sql_path = Path(sql_path)
    if not sql_path.is_file():
        print(f"No existe el archivo SQL: {sql_path}", file=sys.stderr)
        return 1

    with sql_path.open(encoding="utf-8") as f:
        sql_text = f.read()

    triggers, functions = manifest_from_sql(sql_text)
    stmts = order_statements(parse_sql_statements(sql_text))
    if not stmts:
        print("No se encontraron statements en el SQL", file=sys.stderr)
        return 1

    try:
        cn = connect_mysql(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=False,
        )
    except pymysql_errors.MySQLError as e:
        print(
            f"No se pudo conectar a la base '{database}' en {host}:{port}: {e}",
            file=sys.stderr,
        )
        return 1

    try:
        with cn.cursor() as cur:
            if not skip_preflight:
                print(
                    f"Outbox: desinstalando {len(triggers)} triggers y "
                    f"{len(functions)} funciones ms_json_* (instalación limpia)..."
                )
                preflight_drop_outbox_objects(cur, triggers=triggers, functions=functions)

            for idx, stmt in enumerate(stmts, 1):
                s = stmt.strip()
                try:
                    cur.execute(s)
                except pymysql_errors.MySQLError as e:
                    cn.rollback()
                    head = s.split("\n", 1)[0][:100]
                    m = re.search(
                        r"CREATE TRIGGER (\S+).* ON (\S+)",
                        s,
                        re.IGNORECASE | re.DOTALL,
                    )
                    extra = f" ({m.group(1)} ON {m.group(2)})" if m else ""
                    print(
                        f"Error en statement #{idx}{extra}: {e}\n  → {head}",
                        file=sys.stderr,
                    )
                    if e.args and e.args[0] == 1235:
                        print(
                            "MySQL 5.6: solo un trigger por (tabla, momento, evento). "
                            "Los triggers ERP (p. ej. fechaua_i en sinv) no se tocan; "
                            "no deben ser otro AFTER INSERT en la misma tabla.",
                            file=sys.stderr,
                        )
                    return 1
        cn.commit()
    except pymysql_errors.MySQLError as e:
        cn.rollback()
        print(f"Error al aplicar SQL: {e}", file=sys.stderr)
        return 1
    finally:
        cn.close()

    print(
        f"Outbox instalado en '{database}': {len(triggers)} triggers, "
        f"{len(functions)} funciones ({len(stmts)} statements)."
    )
    return 0


def main() -> int:
    host = os.environ.get("MS_MYSQL_HOST", "").strip()
    user = os.environ.get("MS_MYSQL_USER", "").strip()
    password = os.environ.get("MS_MYSQL_PASSWORD", "")
    database = os.environ.get("MS_MYSQL_DATABASE", "").strip()
    port = int(os.environ.get("MS_MYSQL_PORT", "3306") or "3306")
    sql_path = os.environ.get("MS_SQL_FILE", "").strip() or str(_DEFAULT_SQL)
    skip_preflight = os.environ.get("MS_OUTBOX_SKIP_PREFLIGHT", "").strip() in (
        "1",
        "true",
        "yes",
    )

    if not all([host, user, password, database]):
        print(
            "Faltan variables: MS_MYSQL_HOST, MS_MYSQL_USER, MS_MYSQL_PASSWORD, "
            "MS_MYSQL_DATABASE",
            file=sys.stderr,
        )
        return 1

    try:
        cn = connect_mysql(
            host=host,
            port=port,
            user=user,
            password=password,
            autocommit=True,
        )
    except pymysql_errors.MySQLError as e:
        print(
            f"No se pudo conectar a MySQL en {host}:{port} con el usuario {user}: {e}",
            file=sys.stderr,
        )
        return 1

    try:
        with cn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                (database,),
            )
            if not cur.fetchone():
                print(
                    f"La base de datos '{database}' no existe o el usuario no tiene permisos",
                    file=sys.stderr,
                )
                return 1
    finally:
        cn.close()

    return apply_sql_file(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        sql_path=sql_path,
        skip_preflight=skip_preflight,
    )


if __name__ == "__main__":
    raise SystemExit(main())
