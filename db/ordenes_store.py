"""Creación de preventas (órdenes por facturar): diariov + diariovi + pagos.

No toca kardex, ventasi, detalle ni sinv.existencia.
Antes de insertar, exige cantidad ≤ sinv.existencia por SKU.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import secrets
from typing import Any, Literal

from core.store_datetime import store_timezone

PAYMENT_TOLERANCE = Decimal("0.01")
MONEY_Q = Decimal("0.01")


def _money(value: float | Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def _now_store() -> datetime:
    return datetime.now(store_timezone())


def generate_nordene(now: datetime | None = None) -> str:
    """Código público de preventa (`diariov.nordene`, varchar(15)).

    Formato: ``YYMMDDHHMMSS`` (12) + 3 hex aleatorios (15 total).
    La semilla temporal reduce colisiones; el sufijo cubre ráfagas en el mismo segundo.
    """
    ts = (now or _now_store()).strftime("%y%m%d%H%M%S")
    return f"{ts}{secrets.token_hex(2)[:3]}"


def allocate_nordene(cur, *, max_attempts: int = 8) -> str:
    """Genera ``nordene`` único comprobando que no exista en ``diariov``."""
    for _ in range(max_attempts):
        code = generate_nordene()
        cur.execute(
            "SELECT 1 FROM diariov WHERE TRIM(nordene)=%s LIMIT 1",
            (code,),
        )
        if cur.fetchone() is None:
            return code
    raise OrdenesStoreError(
        "could not allocate unique nordene after retries"
    )


@dataclass(frozen=True)
class OrdenLineInput:
    sku: str
    quantity: float
    unit_price: float | None = None


@dataclass(frozen=True)
class OrdenPaymentInput:
    method: Literal["card", "deposit"]
    amount: float
    bank_code: str
    card_number: str | None = None
    holder_name: str | None = None
    confirmation_number: str | None = None
    operation_type: str | None = None


@dataclass(frozen=True)
class OrdenCustomerInput:
    document_id: str
    name: str
    phone: str
    address_line1: str = ""
    address_line2: str = ""
    address_line3: str = ""


class OrdenesStoreError(ValueError):
    """Error de negocio al crear preventa."""


def _split_iva(total_incl: Decimal, porvg: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Devuelve (base, iva, exento) a partir del precio con IVA incluido."""
    rate = float(porvg)
    if rate <= 0:
        return Decimal("0.00"), Decimal("0.00"), total_incl
    divisor = Decimal("1") + (porvg / Decimal("100"))
    base = (total_incl / divisor).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    iva = (total_incl - base).quantize(MONEY_Q, rounding=ROUND_HALF_UP)
    return base, iva, Decimal("0.00")


def _bucket_porvg(porvg: Decimal) -> str:
    rate = float(porvg)
    if rate <= 0:
        return "exento"
    if abs(rate - 8.0) < 0.01:
        return "base2"
    if abs(rate - 31.0) < 0.01:
        return "base3"
    return "base1"


def ensure_scli(
    cur,
    *,
    document_id: str,
    name: str,
    phone: str,
    address_line1: str = "",
    address_line2: str = "",
    address_line3: str = "",
) -> str:
    """Devuelve cod_cli; crea cliente mínimo si no existe."""
    cod_cli = document_id.strip()[:15]
    if not cod_cli:
        raise OrdenesStoreError("customer.document_id is required")
    cur.execute(
        "SELECT cod_cli FROM scli WHERE cod_cli = %s OR rif_cli = %s LIMIT 1",
        (cod_cli, cod_cli),
    )
    row = cur.fetchone()
    if row:
        existing = row["cod_cli"] if isinstance(row, dict) else row[0]
        return str(existing)

    nom = (name or "").strip()[:240]
    tel = (phone or "").strip()[:80]
    dir1 = (address_line1 or "").strip()[:200]
    dir2 = (address_line2 or "").strip()[:200]
    dir3 = (address_line3 or "").strip()[:200]
    if not nom or not tel:
        raise OrdenesStoreError(
            "customer name and phone are required to create a new client"
        )
    today = _now_store().date()
    cur.execute(
        """
        INSERT INTO scli (
          cod_cli, nom_cli, rif_cli, nit_cli,
          dir1_cli, dir2_cli, dir3_cli,
          tel_cli, email1_cli, email2_cli, rep_cli,
          limite, tprecio, especial, tipo_cli,
          cod_ven, casociada, cobserva, diasp, ccaract,
          act_banco, retefu, reteiva, adic, ced_rep, ccontab,
          bloqueo, rbloqueo, czona, ccate_cli, fcrea, genero
        ) VALUES (
          %s, %s, %s, '',
          %s, %s, %s,
          %s, '', '', '',
          0, 0, 'No', 'No Contribuyente',
          '', '', '', 0, '00',
          'N', 'N', 'N', '', 0, '',
          0, '', '', '99', %s, 'M'
        )
        """,
        (cod_cli, nom, cod_cli, dir1, dir2, dir3, tel, today),
    )
    return cod_cli


def allocate_order_ccaja(cur, cajero_code: str) -> str:
    """Compone ccaja = cajero.ccaja + faccaj y incrementa faccaj (+1).

    Requiere fila en tabla ``cajero``. Misma transacción que la orden.
    """
    code = (cajero_code or "").strip()[:10]
    if not code:
        raise OrdenesStoreError(
            "cajero_ccaja is required "
            "(configure system parameter ordenes.cajero_ccaja in admin)"
        )
    cur.execute(
        """
        SELECT TRIM(ccaja) AS ccaja, COALESCE(faccaj, 0) AS faccaj
        FROM cajero
        WHERE TRIM(ccaja) = %s
        LIMIT 1
        FOR UPDATE
        """,
        (code,),
    )
    row = cur.fetchone()
    if not row:
        raise OrdenesStoreError(
            f"cajero_ccaja {code!r} not found in cajero catalog"
        )
    station = str(row["ccaja"] if isinstance(row, dict) else row[0]).strip()
    faccaj = int(row["faccaj"] if isinstance(row, dict) else row[1])
    order_ccaja = f"{station}{faccaj}"
    if len(order_ccaja) > 10:
        raise OrdenesStoreError(
            f"composed ccaja {order_ccaja!r} exceeds varchar(10); "
            f"reset or archive faccaj for cajero {station!r}"
        )
    cur.execute(
        "UPDATE cajero SET faccaj = faccaj + 1 WHERE TRIM(ccaja) = %s",
        (station,),
    )
    return order_ccaja


def next_contador(cur, count: int) -> list[int]:
    cur.execute("SELECT IFNULL(MAX(contador), 0) AS m FROM diariovi")
    row = cur.fetchone()
    start = int(row["m"] if isinstance(row, dict) else row[0])
    return [start + i for i in range(1, count + 1)]


def _load_product(cur, sku: str) -> dict[str, Any]:
    cur.execute(
        """
        SELECT codigo, descrip, COALESCE(porvg, 0) AS porvg,
               COALESCE(precio1, 0) AS precio1,
               COALESCE(costo, 0) AS costo,
               COALESCE(costoant, 0) AS costoant,
               COALESCE(pg1, 0) AS pg1,
               COALESCE(existencia, 0) AS existencia
        FROM sinv
        WHERE codigo = %s
        LIMIT 1
        """,
        (sku.strip(),),
    )
    row = cur.fetchone()
    if not row:
        raise OrdenesStoreError(f"product not found: {sku}")
    if not isinstance(row, dict):
        return {
            "codigo": row[0],
            "descrip": row[1],
            "porvg": row[2],
            "precio1": row[3],
            "costo": row[4],
            "costoant": row[5],
            "pg1": row[6],
            "existencia": row[7],
        }
    return row


def _lookup_banco(cur, cbanco: str) -> tuple[str, str]:
    """Devuelve (nbanco, cmoneda). Exige que cbanco exista en banco."""
    code = (cbanco or "").strip()[:10]
    if not code:
        raise OrdenesStoreError("bank_code is required")
    cur.execute(
        "SELECT nbanco, COALESCE(cmoneda, '03') AS cmoneda FROM banco WHERE cbanco = %s LIMIT 1",
        (code,),
    )
    row = cur.fetchone()
    if not row:
        raise OrdenesStoreError(
            f"bank_code {code!r} not found in banco catalog"
        )
    if isinstance(row, dict):
        return str(row.get("nbanco") or ""), str(row.get("cmoneda") or "03")
    return str(row[0] or ""), str(row[1] or "03")


def create_orden(
    conn,
    *,
    customer: OrdenCustomerInput,
    items: list[OrdenLineInput],
    payments: list[OrdenPaymentInput],
    deposito_ncuenta: str,
    tarjeta_npunto: str,
    cod_ven: str,
    cajero_ccaja: str,
    use_sinv_precio1: bool = False,
    enforce_min_precio1: bool = False,
) -> dict[str, Any]:
    if not items:
        raise OrdenesStoreError("items must not be empty")
    if not payments:
        raise OrdenesStoreError("payments must not be empty")

    ncuenta = (deposito_ncuenta or "").strip()
    if any(p.method == "deposit" for p in payments) and not ncuenta:
        raise OrdenesStoreError(
            "deposito_ncuenta is required when using deposit payments "
            "(configure system parameter ordenes.deposito_ncuenta in admin)"
        )

    npunto = (tarjeta_npunto or "").strip()[:2]
    if not npunto:
        raise OrdenesStoreError(
            "tarjeta_npunto is required "
            "(configure system parameter ordenes.tarjeta_npunto in admin)"
        )
    vendor = (cod_ven or "").strip()[:10]
    if not vendor:
        raise OrdenesStoreError(
            "cod_ven is required "
            "(configure system parameter ordenes.cod_ven in admin)"
        )
    now = _now_store()
    fecha: date = now.date()
    hora = now.strftime("%H:%M:%S:")

    with conn.cursor(dictionary=True) as cur:
        cod_cli = ensure_scli(
            cur,
            document_id=customer.document_id,
            name=customer.name,
            phone=customer.phone,
            address_line1=customer.address_line1,
            address_line2=customer.address_line2,
            address_line3=customer.address_line3,
        )
        ccaja = allocate_order_ccaja(cur, cajero_ccaja)
        nordene = allocate_nordene(cur)
        contadores = next_contador(cur, len(items))

        line_rows: list[dict[str, Any]] = []
        tot_subtotal_incl = Decimal("0.00")
        tot_base1 = Decimal("0.00")
        tot_base2 = Decimal("0.00")
        tot_base3 = Decimal("0.00")
        tot_exento = Decimal("0.00")
        tot_iva1 = Decimal("0.00")
        tot_iva2 = Decimal("0.00")
        tot_iva3 = Decimal("0.00")
        # Stock restante por SKU (sinv.existencia); acumula líneas del mismo código.
        stock_left: dict[str, Decimal] = {}

        for idx, item in enumerate(items):
            product = _load_product(cur, item.sku)
            qty = Decimal(str(item.quantity))
            if qty <= 0:
                raise OrdenesStoreError(f"invalid quantity for sku {item.sku}")
            sku_key = str(product["codigo"]).strip()
            if sku_key not in stock_left:
                stock_left[sku_key] = Decimal(str(product["existencia"] or 0))
            available = stock_left[sku_key]
            if qty > available:
                raise OrdenesStoreError(
                    f"insufficient stock for sku {sku_key}: "
                    f"requested {qty}, available {available} (sinv.existencia)"
                )
            stock_left[sku_key] = available - qty
            porvg = _money(product["porvg"])
            catalog_price = _money(product["precio1"])
            # unitPrice API = con IVA. Default: sinv.precio1.
            # use_sinv_precio1=true → siempre precio1 (ignora unitPrice del request).
            if use_sinv_precio1:
                unit = catalog_price
            elif item.unit_price is not None and float(item.unit_price) > 0:
                unit = _money(item.unit_price)
                if enforce_min_precio1 and catalog_price > 0 and unit < catalog_price:
                    raise OrdenesStoreError(
                        f"unit price {unit} below sinv.precio1 {catalog_price} "
                        f"for sku {item.sku} "
                        "(ordenes.enforce_min_precio1 is enabled)"
                    )
            else:
                unit = catalog_price
            if unit <= 0:
                raise OrdenesStoreError(
                    f"unit price missing for sku {item.sku}; pass unit_price"
                    if not use_sinv_precio1
                    else f"sinv.precio1 missing for sku {item.sku}"
                )
            line_total = _money(unit * qty)
            base, iva, exento = _split_iva(line_total, porvg)
            bucket = _bucket_porvg(porvg)

            if bucket == "exento":
                tot_exento += exento
            elif bucket == "base2":
                tot_base2 += base
                tot_iva2 += iva
            elif bucket == "base3":
                tot_base3 += base
                tot_iva3 += iva
            else:
                tot_base1 += base
                tot_iva1 += iva
            tot_subtotal_incl += line_total

            costo_ref = _money(product["costo"] or 0)
            costoant = _money(product["costoant"] or product["costo"] or 0)
            # Patrón ERP en ventas: diariovi.pg1 = 0 (margen queda en sinv).
            line_rows.append(
                {
                    "sku": str(product["codigo"]),
                    "descrip": str(product["descrip"] or "")[:240],
                    "quantity": float(qty),
                    "unit_price": float(unit),
                    "subtotal1": float(line_total),
                    "subtotal2": float(line_total),
                    "porvg": float(porvg),
                    "base": float(base),
                    "iva": float(iva),
                    "exento": float(exento),
                    "contador": contadores[idx],
                    "costoant": float(costoant),
                    "nuevocosto": float(costo_ref),
                    "pg1": 0.0,
                    "bucket": bucket,
                }
            )

        tot_iva = tot_iva1 + tot_iva2 + tot_iva3
        tot_total = tot_subtotal_incl
        # Patrón Multishop (facturas): diariov.subtotal = neto; total = con IVA
        tot_neto = tot_base1 + tot_base2 + tot_base3 + tot_exento

        pay_sum = sum((_money(p.amount) for p in payments), Decimal("0.00"))
        if abs(pay_sum - tot_total) > PAYMENT_TOLERANCE:
            raise OrdenesStoreError(
                f"payments sum {pay_sum} does not match order total {tot_total}"
            )

        cur.execute(
            """
            INSERT INTO diariov (
              numero, cod_cli, fecha, subtotal, base1, base2, exento,
              iva1, iva2, por_des, descuento, total, hora,
              importado, editado, tipo_doc, iva, confirma, hconfirma,
              ccaja, cod_ven, norden, numerocf, nordene, pret, ncompra,
              pretiva, base3, iva3, obs_adi, tasausd, trpromocion,
              baseigtf, montoigtf
            ) VALUES (
              NULL, %s, %s, %s, %s, %s, %s,
              %s, %s, NULL, 0, %s, %s,
              '', '', 'FC', %s, 'N', '0',
              %s, %s, 'NA', '', %s, 0, '',
              0, %s, %s, '', 0, 0,
              0, 0
            )
            """,
            (
                cod_cli,
                fecha,
                float(tot_neto),
                float(tot_base1),
                float(tot_base2),
                float(tot_exento),
                float(tot_iva1),
                float(tot_iva2),
                float(tot_total),
                hora,
                float(tot_iva),
                ccaja,
                vendor,
                nordene,
                float(tot_base3),
                float(tot_iva3),
            ),
        )

        for line in line_rows:
            base1 = line["base"] if line["bucket"] == "base1" else 0.0
            iva1 = line["iva"] if line["bucket"] == "base1" else 0.0
            base2 = line["base"] if line["bucket"] == "base2" else 0.0
            iva2 = line["iva"] if line["bucket"] == "base2" else 0.0
            base3 = line["base"] if line["bucket"] == "base3" else 0.0
            iva3 = line["iva"] if line["bucket"] == "base3" else 0.0
            cur.execute(
                """
                INSERT INTO diariovi (
                  numero, cod_cli, fecha, porvg, codigo, descrip, cantidad,
                  costo, subtotal1, descuento1, descuento2, subtotal2,
                  exento, iva1, iva2, base1, base2, pg1, pg2, pg3, pg4,
                  precio1, aplicaprecio, costoant, nuevocosto, uxb,
                  lotei, lotef, vence, canlote, calidad,
                  nprecio1, ccaja, cod_ven, contador, numerocd, obsi,
                  numerocf, dcantidad, ucantidad, base3, iva3
                ) VALUES (
                  '', %s, %s, %s, %s, %s, %s,
                  %s, %s, 0, 0, %s,
                  %s, %s, %s, %s, %s, %s, 0, 0, 0,
                  %s, 'N', %s, %s, 1,
                  '', '', %s, 0, '',
                  %s, %s, %s, %s, '', '',
                  '', 'UND', %s, %s, %s
                )
                """,
                (
                    cod_cli,
                    fecha,
                    line["porvg"],
                    line["sku"],
                    line["descrip"],
                    line["quantity"],
                    line["unit_price"],
                    line["subtotal1"],
                    line["subtotal2"],
                    line["exento"],
                    iva1,
                    iva2,
                    base1,
                    base2,
                    line["pg1"],
                    line["unit_price"],
                    line["costoant"],
                    line["nuevocosto"],
                    fecha,
                    line["unit_price"],
                    ccaja,
                    vendor,
                    line["contador"],
                    # ucantidad debe ser 1 con uxb=1/UND; si = cantidad el ERP
                    # multiplica al bajar kardex (qty^2).
                    1.0,
                    base3,
                    iva3,
                ),
            )

        payment_out: list[dict[str, Any]] = []
        for pay in payments:
            amount = float(_money(pay.amount))
            bank_code = (pay.bank_code or "").strip()[:10]
            nbanco, cmoneda = _lookup_banco(cur, bank_code)

            if pay.method == "card":
                ntarjeta = (pay.card_number or "").strip()[:15]
                if not ntarjeta:
                    raise OrdenesStoreError("card payments require card_number")
                titular = (pay.holder_name or "").strip()[:200]
                indice = f"{ccaja}{npunto}"[:15]
                cur.execute(
                    """
                    INSERT INTO tarjetas (
                      fecha, cajero, numero, monto, fvalor, ntarjeta, titular,
                      cbanco, estado, numie, cod_cli, procesa, chequeo, npunto, indice
                    ) VALUES (
                      %s, %s, '', %s, %s, %s, %s,
                      %s, 'R', NULL, %s, 'N', '', %s, %s
                    )
                    """,
                    (
                        fecha,
                        ccaja,
                        amount,
                        fecha,
                        ntarjeta,
                        titular,
                        bank_code,
                        cod_cli,
                        npunto,
                        indice,
                    ),
                )
                payment_out.append(
                    {
                        "method": "card",
                        "amount": amount,
                        "card_number": ntarjeta,
                        "holder_name": titular,
                        "bank_code": bank_code,
                    }
                )
            elif pay.method == "deposit":
                ndeposito = (pay.confirmation_number or "").strip()[:15]
                if not ndeposito:
                    raise OrdenesStoreError(
                        "deposit payments require confirmation_number"
                    )
                # depositos.titular = nombre de quien realizó el depósito
                # (no el tipo de operación). Fallback: nombre del cliente.
                titular = (pay.holder_name or customer.name or "").strip()[:240]
                if not titular:
                    raise OrdenesStoreError(
                        "deposit payments require holder_name or customer.name"
                    )
                cur.execute(
                    """
                    INSERT INTO depositos (
                      fecha, cajero, numero, monto, fvalor, ndeposito, titular,
                      cbanco, estado, numie, cod_cli, procesa, recibido, cambio,
                      cmoneda, nmoneda, nbanco, chequeo, ncuenta, cusuario
                    ) VALUES (
                      %s, %s, '', %s, %s, %s, %s,
                      %s, 'R', NULL, %s, 'N', %s, 1,
                      %s, 'Bolivares', %s, '', %s, ''
                    )
                    """,
                    (
                        fecha,
                        ccaja,
                        amount,
                        fecha,
                        ndeposito,
                        titular,
                        bank_code,
                        cod_cli,
                        amount,
                        cmoneda,
                        nbanco,
                        ncuenta[:25],
                    ),
                )
                payment_out.append(
                    {
                        "method": "deposit",
                        "amount": amount,
                        "confirmation_number": ndeposito,
                        "holder_name": titular,
                        "bank_code": bank_code,
                    }
                )
            else:
                raise OrdenesStoreError(f"unsupported payment method: {pay.method}")

        return {
            "nordene": nordene,
            "cod_cli": cod_cli,
            "fecha": fecha.isoformat(),
            "subtotal": float(tot_neto),
            "base1": float(tot_base1),
            "iva1": float(tot_iva1),
            "base2": float(tot_base2),
            "iva2": float(tot_iva2),
            "base3": float(tot_base3),
            "iva3": float(tot_iva3),
            "exento": float(tot_exento),
            "iva": float(tot_iva),
            "total": float(tot_total),
            "items": [
                {
                    "codigo": r["sku"],
                    "descrip": r["descrip"],
                    "cantidad": r["quantity"],
                    "costo": r["unit_price"],
                    "subtotal2": r["subtotal2"],
                    "porvg": r["porvg"],
                    "base": r["base"],
                    "iva": r["iva"],
                    "exento": r["exento"],
                    "contador": r["contador"],
                }
                for r in line_rows
            ],
            "payments": payment_out,
            "message": "orden creada",
        }


def status_from_confirma(confirma: Any) -> str:
    if str(confirma or "").strip().upper() == "E":
        return "confirmed"
    return "pending"


def _fecha_iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)[:10]


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def list_ordenes(
    conn,
    *,
    search: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Lista preventas online (nordene no vacío)."""
    q = (search or "").strip()
    fd = (fecha_desde or "").strip()[:10]
    fh = (fecha_hasta or "").strip()[:10]
    st = (status or "").strip().lower()
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 50), 500))
    offset = (page - 1) * limit

    where = ["TRIM(IFNULL(d.nordene, '')) <> ''"]
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        where.append(
            "(TRIM(d.nordene) LIKE %s OR TRIM(d.cod_cli) LIKE %s "
            "OR TRIM(IFNULL(d.numero, '')) LIKE %s)"
        )
        params.extend([like, like, like])
    if fd:
        where.append("d.fecha >= %s")
        params.append(fd)
    if fh:
        where.append("d.fecha <= %s")
        params.append(fh)
    if st == "pending":
        where.append(
            "(d.confirma IS NULL OR TRIM(d.confirma) = '' "
            "OR UPPER(TRIM(d.confirma)) = 'N')"
        )
    elif st == "confirmed":
        where.append("UPPER(TRIM(d.confirma)) = 'E'")

    where_sql = " AND ".join(where)
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM diariov d WHERE {where_sql}",
            tuple(params),
        )
        total = int((cur.fetchone() or {}).get("cnt") or 0)
        cur.execute(
            f"""
            SELECT
              TRIM(d.nordene) AS nordene,
              TRIM(d.cod_cli) AS cod_cli,
              d.fecha,
              COALESCE(d.total, 0) AS total,
              COALESCE(d.base1, 0) AS base1,
              COALESCE(d.base2, 0) AS base2,
              COALESCE(d.base3, 0) AS base3,
              COALESCE(d.exento, 0) AS exento,
              COALESCE(d.iva1, 0) AS iva1,
              COALESCE(d.iva2, 0) AS iva2,
              COALESCE(d.iva3, 0) AS iva3,
              d.confirma,
              TRIM(IFNULL(d.numero, '')) AS numero,
              TRIM(d.ccaja) AS ccaja,
              (
                SELECT COUNT(*)
                FROM diariovi i
                WHERE TRIM(i.ccaja) = TRIM(d.ccaja)
              ) AS line_count
            FROM diariov d
            WHERE {where_sql}
            ORDER BY d.fecha DESC, d.nordene DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = list(cur.fetchall() or [])

    items: list[dict[str, Any]] = []
    for row in rows:
        base1 = _f(row.get("base1"))
        base2 = _f(row.get("base2"))
        base3 = _f(row.get("base3"))
        exento = _f(row.get("exento"))
        iva1 = _f(row.get("iva1"))
        iva2 = _f(row.get("iva2"))
        iva3 = _f(row.get("iva3"))
        status_val = status_from_confirma(row.get("confirma"))
        numero = str(row.get("numero") or "").strip() or None
        items.append(
            {
                "nordene": str(row.get("nordene") or "").strip(),
                "cod_cli": str(row.get("cod_cli") or "").strip(),
                "fecha": _fecha_iso(row.get("fecha")),
                "total": _f(row.get("total")),
                "subtotal": base1 + base2 + base3 + exento,
                "iva": iva1 + iva2 + iva3,
                "status": status_val,
                "numero": numero,
                "line_count": int(row.get("line_count") or 0),
            }
        )
    return items, total


def _load_payments_for_ccaja(cur, ccaja: str) -> list[dict[str, Any]]:
    ticket = (ccaja or "").strip()
    out: list[dict[str, Any]] = []
    cur.execute(
        """
        SELECT monto, ntarjeta, titular, cbanco
        FROM tarjetas
        WHERE TRIM(cajero) = %s
        ORDER BY id ASC
        """,
        (ticket,),
    )
    for row in cur.fetchall() or []:
        out.append(
            {
                "method": "card",
                "amount": _f(row.get("monto")),
                "card_number": str(row.get("ntarjeta") or "").strip(),
                "holder_name": str(row.get("titular") or "").strip(),
                "bank_code": str(row.get("cbanco") or "").strip(),
            }
        )
    cur.execute(
        """
        SELECT monto, ndeposito, titular, cbanco
        FROM depositos
        WHERE TRIM(cajero) = %s
        ORDER BY id ASC
        """,
        (ticket,),
    )
    for row in cur.fetchall() or []:
        out.append(
            {
                "method": "deposit",
                "amount": _f(row.get("monto")),
                "confirmation_number": str(row.get("ndeposito") or "").strip(),
                "holder_name": str(row.get("titular") or "").strip(),
                "bank_code": str(row.get("cbanco") or "").strip(),
            }
        )
    return out


def get_orden_by_nordene(conn, nordene: str) -> dict[str, Any] | None:
    """Detalle de preventa online por nordene (orderId)."""
    key = (nordene or "").strip()
    if not key:
        return None

    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            """
            SELECT
              TRIM(nordene) AS nordene,
              TRIM(cod_cli) AS cod_cli,
              fecha,
              COALESCE(total, 0) AS total,
              COALESCE(base1, 0) AS base1,
              COALESCE(base2, 0) AS base2,
              COALESCE(base3, 0) AS base3,
              COALESCE(exento, 0) AS exento,
              COALESCE(iva1, 0) AS iva1,
              COALESCE(iva2, 0) AS iva2,
              COALESCE(iva3, 0) AS iva3,
              confirma,
              TRIM(IFNULL(numero, '')) AS numero,
              TRIM(ccaja) AS ccaja
            FROM diariov
            WHERE TRIM(nordene) = %s
            LIMIT 1
            """,
            (key,),
        )
        header = cur.fetchone()
        if not header:
            return None

        ccaja = str(header.get("ccaja") or "").strip()
        cur.execute(
            """
            SELECT
              codigo, descrip, cantidad, costo, subtotal2, contador,
              COALESCE(porvg, 0) AS porvg,
              COALESCE(exento, 0) AS exento,
              COALESCE(base1, 0) AS base1,
              COALESCE(base2, 0) AS base2,
              COALESCE(base3, 0) AS base3,
              COALESCE(iva1, 0) AS iva1,
              COALESCE(iva2, 0) AS iva2,
              COALESCE(iva3, 0) AS iva3
            FROM diariovi
            WHERE TRIM(ccaja) = %s
            ORDER BY contador ASC
            """,
            (ccaja,),
        )
        line_rows = list(cur.fetchall() or [])
        payments = _load_payments_for_ccaja(cur, ccaja)

    base1 = _f(header.get("base1"))
    base2 = _f(header.get("base2"))
    base3 = _f(header.get("base3"))
    exento = _f(header.get("exento"))
    iva1 = _f(header.get("iva1"))
    iva2 = _f(header.get("iva2"))
    iva3 = _f(header.get("iva3"))
    status_val = status_from_confirma(header.get("confirma"))
    numero = str(header.get("numero") or "").strip() or None

    items: list[dict[str, Any]] = []
    for row in line_rows:
        line_base = _f(row.get("base1")) + _f(row.get("base2")) + _f(row.get("base3"))
        line_iva = _f(row.get("iva1")) + _f(row.get("iva2")) + _f(row.get("iva3"))
        items.append(
            {
                "codigo": str(row.get("codigo") or "").strip(),
                "descrip": str(row.get("descrip") or "").strip(),
                "cantidad": _f(row.get("cantidad")),
                "costo": _f(row.get("costo")),
                "subtotal2": _f(row.get("subtotal2")),
                "porvg": _f(row.get("porvg")),
                "base": line_base,
                "iva": line_iva,
                "exento": _f(row.get("exento")),
                "contador": int(row.get("contador") or 0),
            }
        )

    return {
        "nordene": str(header.get("nordene") or "").strip(),
        "cod_cli": str(header.get("cod_cli") or "").strip(),
        "fecha": _fecha_iso(header.get("fecha")),
        "subtotal": base1 + base2 + base3 + exento,
        "base1": base1,
        "iva1": iva1,
        "base2": base2,
        "iva2": iva2,
        "base3": base3,
        "iva3": iva3,
        "exento": exento,
        "iva": iva1 + iva2 + iva3,
        "total": _f(header.get("total")),
        "status": status_val,
        "numero": numero,
        "items": items,
        "payments": payments,
        "message": "ok",
    }
