from __future__ import annotations

import time
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from core.config import settings

# Errores típicos cuando MySQL arranca, reinicia o cierra conexiones idle.
_TRANSIENT_MYSQL_ERRNOS = frozenset({2002, 2003, 2006, 2013, 2055})


def is_transient_mysql_error(exc: BaseException) -> bool:
    if isinstance(exc, pymysql.Error):
        code = exc.args[0] if exc.args else None
        return code in _TRANSIENT_MYSQL_ERRNOS
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return is_transient_mysql_error(cause)
    return False


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

    def start_transaction(self) -> None:
        self._raw.begin()

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

    def connect(self, *, attempts: int = 4) -> MySqlConnection:
        last_err: Exception | None = None
        tries = max(1, attempts)
        for attempt in range(tries):
            try:
                return self._connect_once()
            except pymysql.Error as exc:
                last_err = exc
                if not is_transient_mysql_error(exc) or attempt >= tries - 1:
                    raise
                time.sleep(min(2**attempt, 8))
        assert last_err is not None
        raise last_err

    def _connect_once(self) -> MySqlConnection:
        raw = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            charset="latin1",
            autocommit=False,
            connect_timeout=10,
            read_timeout=60,
            write_timeout=60,
        )
        return MySqlConnection(raw)

    def ping(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"configured": False, "ok": False}
        conn: MySqlConnection | None = None
        try:
            conn = self.connect()
            conn.ping(reconnect=True, attempts=1, delay=0)
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
            return {"configured": True, "ok": True}
        except Exception:
            return {"configured": True, "ok": False}
        finally:
            if conn is not None:
                conn.close()


def mysql_db_health_status() -> str:
    """
    Valor de `db` en GET /api/health (contrato hub-ui):
    - simulated: MYSQL_* no configurado
    - ok: conexión y SELECT 1 correctos
    - error: configurado pero no responde
    """
    client = MySqlClient()
    if not client.is_configured():
        return "simulated"
    result = client.ping()
    if result.get("ok"):
        return "ok"
    return "error"
