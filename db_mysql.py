from __future__ import annotations

from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from config import settings


class MySqlConnection:
    """Envoltorio sobre pymysql (estable en hilos/Windows; compatible con dictionary=True)."""

    def __init__(self, raw: pymysql.Connection) -> None:
        self._raw = raw

    def cursor(self, dictionary: bool = False):
        return self._raw.cursor(DictCursor if dictionary else None)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def ping(self, reconnect: bool = True, attempts: int = 1, delay: int = 0) -> None:
        del attempts, delay
        self._raw.ping(reconnect)


class MySqlClient:
    def is_configured(self) -> bool:
        return bool(
            settings.mysql_host
            and settings.mysql_user
            and settings.mysql_password
            and settings.mysql_database
        )

    def connect(self) -> MySqlConnection:
        raw = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            charset="latin1",
            autocommit=False,
        )
        return MySqlConnection(raw)

    def ping(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"configured": False}
        conn = self.connect()
        try:
            conn.ping(reconnect=True, attempts=1, delay=0)
            return {"configured": True, "ok": True}
        finally:
            conn.close()
