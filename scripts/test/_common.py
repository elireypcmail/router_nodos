"""Utilidades compartidas para simulaciones transaccionales (outbox → router webhooks)."""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from outbox.mysql import OUTBOX_TABLE_NAME, OutboxRepository  # noqa: E402
from outbox.router_client import send_outbox_batch  # noqa: E402


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
        help="Envía pending de sync_outbox_router al router (requiere ROUTER_EVENTS_URL)",
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
    parser.add_argument(
        "--fecha",
        type=parse_fecha_cli,
        default=None,
        metavar="YYYY-MM-DD",
        help="Fecha comercial ERP en scom/kardex/diariovi (default: hoy)",
    )


def parse_fecha_cli(raw: str) -> date:
    text = raw.strip()
    if len(text) >= 10:
        text = text[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(
            f"fecha inválida {raw!r}; use YYYY-MM-DD"
        ) from ex


def resolve_simulation_fecha(args: argparse.Namespace) -> date:
    fecha = getattr(args, "fecha", None)
    return fecha if isinstance(fecha, date) else today()


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
    """Calidad ERP (ej. 1200L, 1201L) — identificador visible; lote queda vacío."""
    _ = suffix
    base = 1200
    return [f"{base + i}L"[:15] for i in range(num_lotes)]


def random_future_vence(*, min_days: int = 60, max_days: int = 730) -> date:
    """Fecha de vencimiento aleatoria en el futuro (pruebas de lotes)."""
    return date.today() + timedelta(days=random.randint(min_days, max_days))


# Rangos alineados con hub lot-expiry-risk.util.ts (portal «Riesgo por vencimiento»).
LOT_EXPIRY_CRITICAL_BUCKETS: list[tuple[str, int, str]] = [
    ("lt30", 15, "< 30 d"),
    ("d30_60", 45, "30–60 d"),
    ("d60_90", 75, "60–90 d"),
    ("d90_120", 105, "90–120 d"),
    ("gt120", 180, "> 120 d"),
]

LOT_EXPIRY_CRITICAL_COUNT = len(LOT_EXPIRY_CRITICAL_BUCKETS)


def critical_vence_dates() -> list[date]:
    """Una fecha de vencimiento por bucket de riesgo (5 lotes típicos)."""
    base = date.today()
    return [base + timedelta(days=days) for _key, days, _label in LOT_EXPIRY_CRITICAL_BUCKETS]


def critical_bucket_label(index: int) -> str:
    """Etiqueta portal del bucket crítico (0..4)."""
    if index < 0 or index >= LOT_EXPIRY_CRITICAL_COUNT:
        return f"bucket-{index}"
    return LOT_EXPIRY_CRITICAL_BUCKETS[index][2]


def upsert_detalle_lote(
    conn: pymysql.connections.Connection,
    codigo: str,
    cantidad: float,
    *,
    calidad: str = "",
    lote: str = "",
    cubica: str = "01",
    vence: date | None = None,
    costo: float = 0.0,
    costopro: float | None = None,
    costopr: float | None = None,
    costopropr: float | None = None,
    factor: float = 36.0,
) -> date:
    """Saldo por lote (tabla detalle) alineado con compra simulada (calidad visible, lote vacío)."""
    vence_val = vence if vence is not None else random_future_vence()
    calidad_val = str(calidad or "").strip()[:15]
    lote_val = str(lote or "").strip()[:15]
    cpp_bs = float(costopro if costopro is not None else costo)
    fx = float(factor) if factor and factor > 0 else 36.0
    costopr_val = float(costopr if costopr is not None else (costo / fx if costo else 0.0))
    cpp_usd = float(
        costopropr if costopropr is not None else (cpp_bs / fx if cpp_bs else 0.0)
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indice, existencia
            FROM detalle
            WHERE codigo = %s AND calidad = %s AND cubica = %s AND vence = %s
            LIMIT 1
            """,
            (codigo.strip(), calidad_val, cubica[:10], vence_val),
        )
        row = cur.fetchone()
        if row:
            nueva = float(row.get("existencia") or 0) + float(cantidad)
            cur.execute(
                """
                UPDATE detalle
                SET existencia = %s,
                    costo = %s,
                    costopro = %s,
                    costopr = %s,
                    costopropr = %s,
                    disponible = 'S'
                WHERE indice = %s
                """,
                (nueva, costo, cpp_bs, costopr_val, cpp_usd, row["indice"]),
            )
        else:
            cur.execute(
                """
                INSERT INTO detalle (
                  codigo, calidad, lote, cubica, vence, existencia,
                  costo, costopro, costopr, costopropr, disponible
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'S')
                """,
                (
                    codigo.strip(),
                    calidad_val,
                    lote_val,
                    cubica[:10],
                    vence_val,
                    cantidad,
                    costo,
                    cpp_bs,
                    costopr_val,
                    cpp_usd,
                ),
            )
    return vence_val


@dataclass(frozen=True)
class DetalleVentaDeduccion:
    indice: int
    lote: str
    cubica: str
    vence: date | None
    qty_antes: float
    qty_despues: float
    deducido: float


def _fetch_detalle_disponible(
    conn: pymysql.connections.Connection,
    codigo: str,
    *,
    lote: str | None = None,
    cubica: str | None = None,
) -> list[dict[str, Any]]:
    """Filas detalle con saldo (disponible S), orden FEFO."""
    clauses = [
        "codigo = %s",
        "UPPER(TRIM(COALESCE(disponible, ''))) = 'S'",
        "COALESCE(existencia, 0) > 0",
    ]
    params: list[Any] = [codigo.strip()]
    if lote is not None and str(lote).strip():
        clauses.append("TRIM(lote) = %s")
        params.append(str(lote).strip()[:15])
    if cubica is not None and str(cubica).strip():
        clauses.append("cubica = %s")
        params.append(str(cubica).strip()[:10])
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT indice, TRIM(lote) AS lote, cubica, vence, existencia
            FROM detalle
            WHERE {where}
            ORDER BY
              CASE
                WHEN vence IS NULL
                  OR DATE(vence) IN ('1970-01-01', '0000-00-00') THEN 1
                ELSE 0
              END,
              vence ASC,
              lote ASC,
              cubica ASC
            """,
            tuple(params),
        )
        return list(cur.fetchall() or [])


def plan_detalle_venta(
    conn: pymysql.connections.Connection,
    codigo: str,
    cantidad: float,
    *,
    lote: str | None = None,
    cubica: str | None = None,
) -> list[DetalleVentaDeduccion]:
    """Reparto FEFO de una venta sobre filas detalle disponibles."""
    qty = float(cantidad)
    if qty <= 0:
        raise ValueError("cantidad debe ser > 0 para descontar detalle")

    rows = _fetch_detalle_disponible(conn, codigo, lote=lote, cubica=cubica)
    if not rows:
        hint = (
            f"codigo={codigo!r}"
            + (f" lote={lote!r}" if lote else "")
            + (f" cubica={cubica!r}" if cubica else "")
        )
        raise RuntimeError(
            f"Sin filas detalle disponibles ({hint}). "
            "Ejecuta simulate_compra.py con --lotes antes de vender."
        )

    remaining = qty
    deducciones: list[DetalleVentaDeduccion] = []
    for row in rows:
        if remaining <= 1e-9:
            break
        avail = float(row.get("existencia") or 0)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        vence_raw = row.get("vence")
        vence: date | None
        if isinstance(vence_raw, datetime):
            vence = vence_raw.date()
        elif isinstance(vence_raw, date):
            vence = vence_raw
        else:
            vence = None
        deducciones.append(
            DetalleVentaDeduccion(
                indice=int(row["indice"]),
                lote=str(row.get("lote") or "").strip(),
                cubica=str(row.get("cubica") or "").strip(),
                vence=vence,
                qty_antes=avail,
                qty_despues=avail - take,
                deducido=take,
            )
        )
        remaining -= take

    if remaining > 1e-6:
        total_disp = sum(float(r.get("existencia") or 0) for r in rows)
        raise RuntimeError(
            f"Stock insuficiente en detalle para {codigo!r}: "
            f"pedido={qty}, disponible={total_disp}, faltan={remaining}"
        )
    return deducciones


def apply_detalle_venta_deducciones(
    conn: pymysql.connections.Connection,
    deducciones: list[DetalleVentaDeduccion],
) -> None:
    """UPDATE detalle.existencia; dispara trg_detalle_au → outbox inventory_lot."""
    with conn.cursor() as cur:
        for d in deducciones:
            cur.execute(
                """
                UPDATE detalle
                SET existencia = %s, disponible = 'S'
                WHERE indice = %s
                """,
                (d.qty_despues, d.indice),
            )
            if cur.rowcount == 0:
                raise RuntimeError(
                    f"UPDATE detalle no afectó indice={d.indice} "
                    f"(lote={d.lote!r} cubica={d.cubica!r})"
                )


DEFAULT_VENTA_FACTOR = 400.0


@dataclass(frozen=True)
class DiarioViSalePricing:
    precio_bs: float
    subtotal2: float
    nprecio1: float
    preciodiv: float | None
    dolar: float
    costoact: float
    costodiv: float | None
    costoant: float | None


def _read_detallepr_pricing(
    conn: pymysql.connections.Connection, codigo: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT precio1, cambiodc, costo
            FROM detallepr
            WHERE TRIM(codigo) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (codigo.strip(),),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def resolve_diariovi_sale_pricing(
    conn: pymysql.connections.Connection,
    codigo: str,
    cantidad: float,
    *,
    precio_bs_override: float | None = None,
    factor_override: float | None = None,
) -> DiarioViSalePricing:
    """Precios Bs + USD para línea diariovi (costo/precio1/subtotal2 + preciodiv/dolar)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(precio1, 0) AS precio1,
                   COALESCE(costo, 0) AS costo,
                   COALESCE(costoant, 0) AS costoant,
                   COALESCE(costopro, 0) AS costopro
            FROM sinv
            WHERE codigo = %s
            LIMIT 1
            """,
            (codigo.strip(),),
        )
        sinv = cur.fetchone() or {}

    if precio_bs_override is not None and float(precio_bs_override) > 0:
        precio_bs = float(precio_bs_override)
    else:
        precio_bs = float(sinv.get("precio1") or 0)
        if precio_bs <= 0:
            precio_bs = float(sinv.get("costo") or 0)
    if precio_bs <= 0:
        raise RuntimeError(
            f"sinv.precio1/costo vacíos para {codigo!r}; pasa --precio UNITARIO"
        )

    det = _read_detallepr_pricing(conn, codigo)
    fx = float(factor_override) if factor_override is not None else 0.0
    if fx <= 0 and det:
        fx = float(det.get("cambiodc") or 0)
    if fx <= 0:
        fx = DEFAULT_VENTA_FACTOR

    qty = float(cantidad)
    subtotal2 = round(precio_bs * qty, 2)
    nprecio1 = precio_bs

    precio_usd_catalog = float(det.get("precio1") or 0) if det else 0.0
    if precio_usd_catalog > 0:
        preciodiv = round(precio_usd_catalog, 6)
    elif fx > 0:
        preciodiv = round(precio_bs / fx, 6)
    else:
        preciodiv = None

    costoact = float(sinv.get("costo") or sinv.get("costopro") or 0)
    costoant = float(sinv.get("costoant") or 0) or None
    costodiv = (
        round(costoact / fx, 6) if fx > 0 and costoact > 0 else None
    )

    return DiarioViSalePricing(
        precio_bs=precio_bs,
        subtotal2=subtotal2,
        nprecio1=nprecio1,
        preciodiv=preciodiv,
        dolar=round(fx, 4),
        costoact=costoact,
        costodiv=costodiv,
        costoant=costoant if costoant else None,
    )


def resolve_sale_unit_price(
    conn: pymysql.connections.Connection,
    codigo: str,
    *,
    override: float | None = None,
) -> float:
    """Precio unitario de venta Bs (diariovi.costo)."""
    return resolve_diariovi_sale_pricing(
        conn, codigo, 1.0, precio_bs_override=override
    ).precio_bs


def insert_diariovi_sale_line(
    cur: pymysql.cursors.Cursor,
    *,
    numero: str,
    codigo: str,
    descrip: str,
    fecha: date,
    cantidad: float,
    pricing: DiarioViSalePricing,
    contador: int,
    ccaja: str = "CAJA01",
) -> None:
    """
    Línea sellada diariovi (Bs + USD).
    Debe existir antes del INSERT kardex para que prepare_sale_payload_for_hub la encuentre.
    """
    qty = float(cantidad)
    unit = pricing.precio_bs
    cur.execute(
        """
        INSERT INTO diariovi (
          numero, codigo, fecha, descrip, cantidad, costo,
          subtotal1, subtotal2, precio1, nprecio1, preciodiv,
          dolar, costoact, costoant, costodiv,
          contador, ccaja, cod_ven
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            numero[:15],
            codigo.strip()[:50],
            fecha,
            (descrip or "")[:240],
            qty,
            unit,
            pricing.subtotal2,
            pricing.subtotal2,
            unit,
            pricing.nprecio1,
            pricing.preciodiv,
            pricing.dolar,
            pricing.costoact,
            pricing.costoant,
            pricing.costodiv,
            contador,
            ccaja[:10],
            "",
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
    if existencia_antes <= 0:
        if costo_actual_factura > 0 and math.isfinite(costo_actual_factura):
            return costo_actual_factura
        if cpp_nodo > 0 and math.isfinite(cpp_nodo):
            return cpp_nodo
        return 0.0

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


_SCOM_OPTIONAL_COLUMNS: tuple[str, ...] = (
    "pg1",
    "pg2",
    "pg3",
    "pg4",
    "pg5",
    "precio1",
    "precio2",
    "precio3",
    "precio4",
    "precio5",
    "costoant",
    "nuevocosto",
    "uxb",
    "nprecio1",
    "nprecio2",
    "nprecio3",
    "nprecio4",
    "nprecio5",
    "base3",
    "iva3",
    "costodiv",
    "preciodiv",
    "factor",
)


def insert_scom_purchase_line(
    cur: pymysql.cursors.Cursor,
    conn: pymysql.connections.Connection,
    *,
    numero: str,
    cod_prv: str,
    codigo: str,
    descrip: str,
    fecha: date,
    line: dict[str, Any],
    indice: str | None = None,
) -> str:
    """Línea de compra ERP (scom). Debe existir antes del INSERT en kardex (trigger lee subtotal2)."""
    line_indice = (indice or next_scom_indice(conn)).strip()[:30]
    qty = float(line.get("cantidad", 0))
    unit = float(line.get("costo", 0))
    subtotal1 = float(line.get("subtotal1", round(unit * qty, 2)))
    subtotal2 = float(line.get("subtotal2", subtotal1))
    exento = float(line.get("exento", subtotal2))
    porvg = float(line.get("porvg", 0))
    iva1 = float(line.get("iva1", 0))
    iva2 = float(line.get("iva2", 0))
    base1 = float(line.get("base1", 0))
    base2 = float(line.get("base2", 0))
    costopro = float(line.get("costopro", 0))
    aplicaprecio = str(line.get("aplicaprecio") or "N")[:10]

    base_cols = [
        "numero",
        "cod_prv",
        "fecha",
        "porvg",
        "codigo",
        "descrip",
        "cantidad",
        "costo",
        "subtotal1",
        "descuento1",
        "descuento2",
        "subtotal2",
        "exento",
        "iva1",
        "iva2",
        "base1",
        "base2",
        "costopro",
        "indice",
        "aplicaprecio",
    ]
    base_vals: list[Any] = [
        numero.strip()[:30],
        cod_prv.strip()[:30],
        fecha,
        porvg,
        codigo.strip()[:50],
        (descrip or "")[:80],
        qty,
        unit,
        subtotal1,
        float(line.get("descuento1", 0)),
        float(line.get("descuento2", 0)),
        subtotal2,
        exento,
        iva1,
        iva2,
        base1,
        base2,
        costopro,
        line_indice,
        aplicaprecio,
    ]

    extra_cols: list[str] = []
    extra_vals: list[Any] = []
    for col in _SCOM_OPTIONAL_COLUMNS:
        if col not in line or line[col] is None:
            continue
        cur.execute("SHOW COLUMNS FROM scom LIKE %s", (col,))
        if cur.fetchone():
            extra_cols.append(col)
            extra_vals.append(line[col])

    all_cols = base_cols + extra_cols
    placeholders = ", ".join(["%s"] * len(all_cols))
    cur.execute(
        f"INSERT INTO scom ({', '.join(all_cols)}) VALUES ({placeholders})",
        tuple(base_vals + extra_vals),
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
            FROM {OUTBOX_TABLE_NAME}
            WHERE table_name IN ({placeholders})
            ORDER BY id DESC
            LIMIT %s
            """,
            (*names, limit),
        )
        rows = cur.fetchall() or []
    if not rows:
        print(f"  (no recent {OUTBOX_TABLE_NAME} for {names}; triggers applied?)")
        return
    for r in rows:
        print(
            f"  outbox id={r['id']} table={r['table_name']} op={r['op']} "
            f"status={r['status']} at={r['created_at']}"
        )


def flush_outbox_once(batch_size: int = 50) -> int:
    router_url = (settings.router_events_url or "").strip().rstrip("/")
    if not router_url:
        print("ROUTER_EVENTS_URL vacía; no se puede --flush", file=sys.stderr)
        raise SystemExit(1)

    mysql = require_mysql()
    repo = OutboxRepository(mysql)
    repo.ensure_schema()
    recovered = repo.recover_processing()
    if recovered:
        print(f"Outbox: recuperadas {recovered} fila(s) en processing → pending")

    events = repo.reserve_pending(limit=batch_size)
    if not events:
        print("Outbox: no hay eventos pending.")
        return 0

    result = send_outbox_batch(events)
    repo.apply_send_result(result)
    print(
        f"Outbox → router: sent={len(result.sent_ids)} ignored={len(result.ignored_ids)} "
        f"failed={len(result.failed_ids)} ({router_url}/internal/nodos/events)"
    )
    return len(result.sent_ids)


def maybe_flush(flush: bool) -> None:
    if not flush:
        print(
            "Tip: con HUEY_ENABLED=true el consumer envía solo; o usa --flush para empujar pending."
        )
        return
    flush_outbox_once()
