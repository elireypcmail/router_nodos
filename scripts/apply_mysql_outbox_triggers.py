"""Aplica scripts/mysql_outbox_triggers.sql usando MYSQL_* del entorno (instalador Windows)."""

from __future__ import annotations

import os
import sys

import mysql.connector
from mysql.connector import errors


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
        cn = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            autocommit=True,
        )
    except errors.Error as e:
        print(
            f"No se pudo conectar a MySQL en {host}:{port} con el usuario {user}: {e}",
            file=sys.stderr,
        )
        return 1

    try:
        cur = cn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()
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
        try:
            cn.close()
        except Exception:
            pass

    with open(sql_path, encoding="utf-8") as f:
        sql_text = f.read()

    stmts = parse_sql_statements(sql_text)
    if not stmts:
        print("No se encontraron statements en el SQL", file=sys.stderr)
        return 1

    cn = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        autocommit=False,
    )
    try:
        cur = cn.cursor()
        for stmt in stmts:
            s = stmt.strip()
            if not s:
                continue
            cur.execute(s)
        cn.commit()
    finally:
        try:
            cn.close()
        except Exception:
            pass

    print(f"Triggers/outbox aplicados en {database} ({len(stmts)} statements).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
