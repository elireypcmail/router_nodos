from __future__ import annotations

from typing import Any

import mysql.connector

from config import settings


class MySqlClient:
    def is_configured(self) -> bool:
        return bool(
            settings.mysql_host
            and settings.mysql_user
            and settings.mysql_password
            and settings.mysql_database
        )

    def connect(self) -> mysql.connector.MySQLConnection:
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            autocommit=False,
        )

    def ping(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"configured": False}
        conn = self.connect()
        try:
            conn.ping(reconnect=True, attempts=1, delay=0)
            return {"configured": True, "ok": True}
        finally:
            conn.close()
