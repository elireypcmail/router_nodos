#!/usr/bin/env python3
"""Espera hasta que MySQL acepte conexiones como la API (pymysql + MYSQL_* / MS_MYSQL_*)."""

from __future__ import annotations

import os
import sys
import time

import pymysql


def _env(name: str, fallback: str = "") -> str:
    return (os.environ.get(name) or os.environ.get(f"MS_{name}") or fallback).strip()


def main() -> int:
    host = _env("MYSQL_HOST", "127.0.0.1")
    port = int(_env("MYSQL_PORT", "3306") or "3306")
    user = _env("MYSQL_USER")
    password = _env("MYSQL_PASSWORD")
    database = _env("MYSQL_DATABASE")
    max_tries = int(_env("MYSQL_WAIT_TRIES", "45") or "45")
    sleep_s = float(_env("MYSQL_WAIT_SLEEP", "2") or "2")

    if not user or not database:
        print("MYSQL_USER y MYSQL_DATABASE requeridos", file=sys.stderr)
        return 2

    last_err: Exception | None = None
    for attempt in range(1, max_tries + 1):
        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset="latin1",
                connect_timeout=5,
                read_timeout=5,
                write_timeout=5,
            )
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 AS ok")
                    cur.fetchone()
            finally:
                conn.close()
            print(f"MySQL listo en {host}:{port} ({database}), intento {attempt}")
            return 0
        except Exception as exc:
            last_err = exc
            print(
                f"Esperando MySQL {host}:{port} ({attempt}/{max_tries}): {exc}",
                file=sys.stderr,
            )
            time.sleep(sleep_s)

    print(f"MySQL no respondió: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
