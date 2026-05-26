"""Aplica scripts/mysql_outbox_triggers.sql usando MYSQL_* del entorno (instalador Windows)."""

from __future__ import annotations

import os
import sys

import pymysql
from pymysql import err as pymysql_errors


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


def main() -> int:
    host = os.environ.get("MS_MYSQL_HOST", "").strip()
    user = os.environ.get("MS_MYSQL_USER", "").strip()
    password = os.environ.get("MS_MYSQL_PASSWORD", "")
    database = os.environ.get("MS_MYSQL_DATABASE", "").strip()
    port = int(os.environ.get("MS_MYSQL_PORT", "3306") or "3306")
    sql_path = os.environ.get("MS_SQL_FILE", "").strip()

    if not all([host, user, password, database, sql_path]):
        print(
            "Faltan variables: MS_MYSQL_HOST, MS_MYSQL_USER, MS_MYSQL_PASSWORD, "
            "MS_MYSQL_DATABASE, MS_SQL_FILE",
            file=sys.stderr,
        )
        return 1

    if not os.path.isfile(sql_path):
        print(f"No existe el archivo SQL: {sql_path}", file=sys.stderr)
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
                    f"La base de datos '{database}' no existe o el usuario no tiene permisos para verla",
                    file=sys.stderr,
                )
                return 1
    finally:
        cn.close()

    with open(sql_path, encoding="utf-8") as f:
        sql_text = f.read()

    stmts = parse_sql_statements(sql_text)
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
            for stmt in stmts:
                s = stmt.strip()
                if not s:
                    continue
                cur.execute(s)
        cn.commit()
    except pymysql_errors.MySQLError as e:
        cn.rollback()
        print(f"Error al aplicar SQL: {e}", file=sys.stderr)
        return 1
    finally:
        cn.close()

    print(f"Triggers/outbox aplicados en {database} ({len(stmts)} statements).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
