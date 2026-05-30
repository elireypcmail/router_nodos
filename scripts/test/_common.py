"""Utilidades compartidas para simulaciones transaccionales (outbox -> hub)."""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import os

import pymysql

NODO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = NODO_ROOT / ".env"

# Rutas relativas (data/, etc.) y imports coherentes desde cualquier cwd.
os.chdir(NODO_ROOT)
if str(NODO_ROOT) not in sys.path:
    sys.path.insert(0, str(NODO_ROOT))

from core.config import settings  # noqa: E402
from db.mysql import MySqlClient  # noqa: E402
from hub.client import HubClient  # noqa: E402
from outbox.mysql import OutboxRepository  # noqa: E402


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--codigo",
        help="SKU en sinv; si se omite, se elige el primer producto disponible",
    )
    parser.add_argument(
        "--aleatorio",
        action="store_true",
        help="Producto al azar de sinv (no combinar con --codigo)",
    )
    parser.add_argument(
        "--cantidad",
        type=float,
        default=1.0,
        help="Cantidad del movimiento (default: 1)",
    )
    parser.add_argument(
        "--flush",
        action="store_true",
        help="Envía pending de sync_outbox al hub (requiere HUB_BASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra qué haría, sin INSERT",
    )
    parser.add_argument(
        "--no-update-sinv",
        action="store_true",
        help="No modifica sinv.existencia (solo outbox; Sync existencia seguirá leyendo sinv)",
    )


def require_mysql() -> MySqlClient:
    mysql = MySqlClient()
    if not mysql.is_configured():
        print(
            f"Set MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD and MYSQL_DATABASE in:\n  {ENV_FILE}",
            file=sys.stderr,
        )
        if not ENV_FILE.is_file():
            print(f"  (file not found)", file=sys.stderr)
        raise SystemExit(1)
    return mysql


def connect_dict(mysql: MySqlClient) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="latin1",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def read_sinv_existencia(
    conn: pymysql.connections.Connection, codigo: str
) -> float:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(existencia, 0) AS ex FROM sinv WHERE codigo = %s LIMIT 1",
            (codigo.strip(),),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"No existe sinv.codigo={codigo!r}")
        return float(row.get("ex") or 0)


def parse_lotes_percentages(raw: str) -> list[float]:
    """Lista de porcentajes desde '50,30,20'."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("--lotes-pct vacío; usa valores separados por coma, ej. 50,30,20")
    try:
        return [float(p) for p in parts]
    except ValueError as ex:
        raise ValueError(f"--lotes-pct inválido: {raw!r}") from ex


def equal_lote_percentages(num_lotes: int) -> list[float]:
    if num_lotes < 1:
        raise ValueError("num_lotes debe ser >= 1")
    base = 100.0 / num_lotes
    return [base] * num_lotes


def distribute_cantidad_por_lotes(
    cantidad: int,
    percentages: list[float],
) -> list[int]:
    """
    Reparte cantidad entera entre lotes según % (método del mayor resto).
    Requiere len(percentages) <= cantidad y cada porcentaje > 0.
    """
    n = len(percentages)
    if n < 1:
        raise ValueError("Se requiere al menos un porcentaje")
    if cantidad < n:
        raise ValueError(
            f"La cantidad de lotes ({n}) no puede ser mayor que la cantidad "
            f"de la compra ({cantidad})"
        )
    if any(p <= 0 for p in percentages):
        raise ValueError("Cada porcentaje de --lotes-pct debe ser > 0")

    total_pct = sum(percentages)
    if total_pct <= 0:
        raise ValueError("La suma de porcentajes debe ser > 0")
    normalized = [p / total_pct for p in percentages]

    exact = [cantidad * w for w in normalized]
    amounts = [int(x) for x in exact]
    remainders = sorted(
        ((exact[i] - amounts[i], i) for i in range(n)),
        reverse=True,
    )
    diff = cantidad - sum(amounts)
    for k in range(diff):
        amounts[remainders[k % n][1]] += 1

    if any(a < 1 for a in amounts):
        raise ValueError(
            f"No se puede repartir {cantidad} unidad(es) en {n} lote(s) con los "
            f"porcentajes dados (cada lote necesita al menos 1 unidad)"
        )
    return amounts


def make_test_lote_ids(num_lotes: int, suffix: str) -> list[str]:
    """Identificadores de lote únicos para pruebas (máx. 15 chars ERP)."""
    base = suffix[:8]
    return [f"L{base}{i + 1:02d}"[:15] for i in range(num_lotes)]


def upsert_detalle_lote(
    conn: pymysql.connections.Connection,
    codigo: str,
    cantidad: float,
    *,
    lote: str = "",
    cubica: str = "01",
    vence: date | None = None,
    costo: float = 0.0,
) -> None:
    """Saldo por lote (tabla detalle) alineado con compra simulada."""
    vence_val = vence or date(1970, 1, 1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indice, existencia
            FROM detalle
            WHERE codigo = %s AND lote = %s AND cubica = %s AND vence = %s
            LIMIT 1
            """,
            (codigo.strip(), lote[:15], cubica[:10], vence_val),
        )
        row = cur.fetchone()
        if row:
            nueva = float(row.get("existencia") or 0) + float(cantidad)
            cur.execute(
                "UPDATE detalle SET existencia = %s WHERE indice = %s",
                (nueva, row["indice"]),
            )
        else:
            cur.execute(
                """
                INSERT INTO detalle (
                  codigo, lote, cubica, vence, existencia, costo, costopro
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    codigo.strip(),
                    lote[:15],
                    cubica[:10],
                    vence_val,
                    cantidad,
                    costo,
                    costo,
                ),
            )


def apply_sinv_existencia_delta(
    conn: pymysql.connections.Connection,
    codigo: str,
    delta: float,
) -> tuple[float, float]:
    """
    Ajusta sinv.existencia como haría el ERP tras el movimiento.
    Los triggers de outbox no actualizan sinv; sin esto Sync existencia lee 0.
    """
    antes = read_sinv_existencia(conn, codigo)
    despues = antes + float(delta)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sinv SET existencia = %s WHERE codigo = %s",
            (despues, codigo.strip()),
        )
        if cur.rowcount == 0:
            raise RuntimeError(f"UPDATE sinv no afectó filas para codigo={codigo!r}")
    return antes, despues


def resolve_cpp_nuevo(
    *,
    existencia_antes: float,
    existencia_despues: float,
    cantidad_compra: float,
    cpp_nodo: float,
    costo_actual_factura: float,
) -> float:
    """Misma fórmula que hub/servidor inventario/cpp-resolve.util.ts."""
    denom = existencia_despues
    if denom == 0:
        calculado = cpp_nodo
    else:
        calculado = (
            cpp_nodo * existencia_antes + costo_actual_factura * cantidad_compra
        ) / denom

    if calculado >= 0 and math.isfinite(calculado):
        return calculado
    if cpp_nodo > 0 and math.isfinite(cpp_nodo):
        return cpp_nodo
    if costo_actual_factura > 0 and math.isfinite(costo_actual_factura):
        return costo_actual_factura
    return 0.0


def apply_sinv_cost_after_compra(
    conn: pymysql.connections.Connection,
    codigo: str,
    *,
    cantidad: float,
    precio_unitario: float,
    existencia_antes: float,
    costo_antes: float,
    costopro_antes: float,
) -> tuple[float, float, float]:
    """
    Actualiza sinv.costoant, costo y costopro como el ERP / sync cost del hub.
    Debe llamarse después de conocer existencia_antes (antes del delta de stock).
    """
    existencia_despues = existencia_antes + float(cantidad)
    costo_factura = float(precio_unitario)
    cpp_nuevo = resolve_cpp_nuevo(
        existencia_antes=existencia_antes,
        existencia_despues=existencia_despues,
        cantidad_compra=float(cantidad),
        cpp_nodo=float(costopro_antes),
        costo_actual_factura=costo_factura,
    )
    nuevo_costo = costo_factura if costo_factura != 0 else cpp_nuevo
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sinv
            SET costoant = %s, costo = %s, costopro = %s
            WHERE codigo = %s
            """,
            (costo_antes, nuevo_costo, cpp_nuevo, codigo.strip()),
        )
        if cur.rowcount == 0:
            raise RuntimeError(
                f"UPDATE sinv costos no afectó filas para codigo={codigo!r}"
            )
    return costo_antes, nuevo_costo, cpp_nuevo


def pick_product(
    conn: pymysql.connections.Connection,
    codigo: str | None = None,
    *,
    aleatorio: bool = False,
) -> dict[str, Any]:
    if aleatorio and codigo:
        print("Use --aleatorio or --codigo, not both", file=sys.stderr)
        raise SystemExit(2)

    with conn.cursor() as cur:
        if codigo:
            cur.execute(
                """
                SELECT codigo, descrip, costo, costopro
                FROM sinv
                WHERE codigo = %s
                LIMIT 1
                """,
                (codigo.strip(),),
            )
            row = cur.fetchone()
            if not row:
                print(f"sinv.codigo={codigo!r} not found", file=sys.stderr)
                raise SystemExit(1)
            return row

        if aleatorio:
            cur.execute(
                """
                SELECT codigo, descrip, costo, costopro
                FROM sinv
                WHERE codigo IS NOT NULL AND TRIM(codigo) <> ''
                ORDER BY RAND()
                LIMIT 1
                """
            )
        else:
            cur.execute(
                """
                SELECT codigo, descrip, costo, costopro
                FROM sinv
                WHERE codigo IS NOT NULL AND TRIM(codigo) <> ''
                ORDER BY codigo
                LIMIT 1
                """
            )
        row = cur.fetchone()
        if not row:
            print("No products in sinv", file=sys.stderr)
            raise SystemExit(1)
        return row


def test_suffix() -> str:
    """Sufijo corto único para numdoc/numero (límite ERP ~6-15 chars)."""
    return datetime.now().strftime("%H%M%S")


def today() -> date:
    return date.today()


def next_compras_contador(conn: pymysql.connections.Connection) -> int:
    """Solo modo legacy (--legacy-comprasdbf); el ERP no usa comprasdbf."""
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(contador), 0) + 1 AS n FROM comprasdbf")
        row = cur.fetchone() or {}
        return int(row.get("n") or 1)


def next_scom_indice(conn: pymysql.connections.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(CAST(indice AS UNSIGNED)), 0) + 1 AS n
            FROM scom
            WHERE indice REGEXP '^[0-9]+$'
            """
        )
        row = cur.fetchone() or {}
        return str(int(row.get("n") or 1))


def insert_scom_purchase_line(
    cur: pymysql.cursors.Cursor,
    conn: pymysql.connections.Connection,
    *,
    numero: str,
    cod_prv: str,
    codigo: str,
    descrip: str,
    fecha: date,
    cantidad: float,
    costo: float,
    costopro: float,
    indice: str | None = None,
    subtotal2: float | None = None,
) -> str:
    """Línea de compra ERP (scom). Debe existir antes del INSERT en kardex (trigger lee subtotal2)."""
    line_indice = (indice or next_scom_indice(conn)).strip()[:30]
    qty = float(cantidad)
    unit = float(costo)
    total = float(subtotal2) if subtotal2 is not None else round(unit * qty, 2)
    cur.execute(
        """
        INSERT INTO scom (
          numero, cod_prv, fecha, porvg, codigo, descrip, cantidad, costo,
          subtotal1, descuento1, descuento2, subtotal2, exento,
          iva1, iva2, base1, base2, costopro, indice, aplicaprecio
        ) VALUES (
          %s, %s, %s, 0, %s, %s, %s, %s,
          %s, 0, 0, %s, %s,
          0, 0, 0, 0, %s, %s, 'N'
        )
        """,
        (
            numero.strip()[:30],
            cod_prv.strip()[:30],
            fecha,
            codigo.strip()[:50],
            (descrip or "")[:80],
            qty,
            unit,
            total,
            total,
            total,
            costopro,
            line_indice,
        ),
    )
    return line_indice


def next_kardex_contador(conn: pymysql.connections.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(contador), 0) + 1 AS n FROM kardex")
        row = cur.fetchone() or {}
        return int(row.get("n") or 1)


def lookup_provider(
    conn: pymysql.connections.Connection, cod_prv: str | None
) -> tuple[str, str]:
    code = (cod_prv or "").strip()
    if not code:
        return "", ""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cod_prv, nom_prv FROM sprv WHERE cod_prv = %s LIMIT 1",
            (code,),
        )
        row = cur.fetchone() or {}
    return str(row.get("cod_prv") or code), str(row.get("nom_prv") or "").strip()


def read_sinv_costs(
    conn: pymysql.connections.Connection, codigo: str
) -> tuple[float, float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(costo, 0) AS costo, COALESCE(costopro, 0) AS costopro "
            "FROM sinv WHERE codigo = %s LIMIT 1",
            (codigo.strip(),),
        )
        row = cur.fetchone() or {}
    return float(row.get("costo") or 0), float(row.get("costopro") or 0)


def erp_hora_label() -> str:
    return datetime.now().strftime("%I:%M:%S %p").replace("AM", "a. m.").replace("PM", "p. m.")


def format_kobs_compra(
    num_compra: str,
    cod_prv: str,
    nom_prv: str = "",
    *,
    ind: str | None = None,
    operador: str = "SUPERVISOR",
) -> str:
    prv = f"{cod_prv} {nom_prv}".strip() if nom_prv else cod_prv
    ind_part = ind or test_suffix()[:5]
    return (
        f"Compra#: {num_compra} Proveedor: {prv} Ind: {ind_part} "
        f"{erp_hora_label()}  Relizado por: {operador}"
    )


def format_kobs_venta(
    numero: str,
    *,
    cliente: str = "V25497333 CLIENTE PRUEBA",
    caja: str = "10",
    operador: str = "CAJA01",
) -> str:
    return (
        f"Vta#: {numero} Cliente: {cliente}  Caja:{caja} "
        f"Hora:{erp_hora_label()}  Atendido por: {operador} /"
    )


def format_kobs_ajuste(nro: str, *, accion: str = "*Aumento") -> str:
    fecha = datetime.now().strftime("%d/%m/%Y")
    return (
        f"Ajuste Nro: {nro} de Fecha {fecha} - Hora: {erp_hora_label()}  "
        f"Accion:  {accion}"
    )


def insert_kardex_header(
    cur: pymysql.cursors.Cursor,
    *,
    codigo: str,
    fecha: date,
    compras: float = 0,
    ventas: float = 0,
    ajustesp: float = 0,
    ajustesn: float = 0,
    devoc: float = 0,
    devov: float = 0,
    existenciai: float = 0,
    entradas: float = 0,
    salidas: float = 0,
    existenciaf: float = 0,
    costo: float = 0,
    costopro: float = 0,
    kobs: str,
    cajero: str = "TEST",
    numero: str = "",
    contador: int | None = None,
) -> int:
    cur.execute(
        """
        INSERT INTO kardex (
          codigo, fecha, existenciai, entradas, salidas, existenciaf,
          compras, ventas, devoc, devov, ajustesp, ajustesn,
          costo, costopro, kobs, cajero, numero, contador
        ) VALUES (
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s
        )
        """,
        (
            codigo.strip(),
            fecha,
            existenciai,
            entradas,
            salidas,
            existenciaf,
            compras,
            ventas,
            devoc,
            devov,
            ajustesp,
            ajustesn,
            costo,
            costopro,
            kobs,
            cajero[:10],
            numero[:15],
            contador,
        ),
    )
    cur.execute("SELECT LAST_INSERT_ID() AS indice")
    row = cur.fetchone() or {}
    return int(row.get("indice") or 0)


def insert_kardexd_line(
    cur: pymysql.cursors.Cursor,
    *,
    codigo: str,
    fecha: date,
    cubica: str,
    ajustesp: float = 0,
    ajustesn: float = 0,
    devoc: float = 0,
    devov: float = 0,
    existenciai: float = 0,
    entradas: float = 0,
    salidas: float = 0,
    existenciaf: float = 0,
    costo: float = 0,
    costopro: float = 0,
    kobs: str,
    cajero: str = "TEST",
    numero: str = "",
    contador: int | None = None,
) -> int:
    cur.execute(
        """
        INSERT INTO kardexd (
          codigo, fecha, cubica, existenciai, entradas, salidas, existenciaf,
          compras, ventas, devoc, devov, ajustesp, ajustesn,
          costo, costopro, kobs, cajero, numero, contador
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s,
          0, 0, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s
        )
        """,
        (
            codigo.strip(),
            fecha,
            cubica[:10],
            existenciai,
            entradas,
            salidas,
            existenciaf,
            devoc,
            devov,
            ajustesp,
            ajustesn,
            costo,
            costopro,
            kobs,
            cajero[:10],
            numero[:15],
            contador,
        ),
    )
    cur.execute("SELECT LAST_INSERT_ID() AS indice")
    row = cur.fetchone() or {}
    return int(row.get("indice") or 0)


def show_recent_outbox(
    conn: pymysql.connections.Connection,
    table_name: str | list[str],
    limit: int = 3,
) -> None:
    names = [table_name] if isinstance(table_name, str) else list(table_name)
    placeholders = ", ".join(["%s"] * len(names))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, table_name, op, status, created_at
            FROM sync_outbox
            WHERE table_name IN ({placeholders})
            ORDER BY id DESC
            LIMIT %s
            """,
            (*names, limit),
        )
        rows = cur.fetchall() or []
    if not rows:
        print(f"  (no recent sync_outbox for {names}; triggers applied?)")
        return
    for r in rows:
        print(
            f"  outbox id={r['id']} table={r['table_name']} op={r['op']} "
            f"status={r['status']} at={r['created_at']}"
        )


async def flush_outbox_once(batch_size: int = 50) -> int:
    if not settings.hub_base_url:
        print("HUB_BASE_URL empty; cannot --flush", file=sys.stderr)
        raise SystemExit(1)

    mysql = require_mysql()
    repo = OutboxRepository(mysql)
    repo.ensure_schema()
    hub = HubClient()

    events = repo.fetch_pending(limit=batch_size)
    if not events:
        print("Outbox: no pending events.")
        return 0

    payload = [
        {
            "outbox_id": e.id,
            "table": e.table_name,
            "op": e.op,
            "pk": e.pk,
            "row": e.row,
            "created_at": e.created_at,
        }
        for e in events
    ]
    ids = [e.id for e in events]
    result = await hub.send_outbox_batch(payload)
    repo.apply_send_result(result)
    print(
        f"Outbox: hub ingest sent={len(result.sent_ids)} ignored={len(result.ignored_ids)} "
        f"failed={len(result.failed_ids)} -> {settings.hub_base_url}{settings.hub_push_path}"
    )
    return len(result.sent_ids)


def maybe_flush(flush: bool) -> None:
    if not flush:
        print(
            "Tip: with API + Huey consumer running (HUEY_ENABLED=true) events send automatically; "
            "or run with --flush"
        )
        return
    asyncio.run(flush_outbox_once())
