"""Imágenes de producto (tabla sinvimg: codigo, imagen longblob, …)."""

from __future__ import annotations

import base64
import re
from datetime import date
from typing import Any

MAX_IMAGEN_BYTES = 5 * 1024 * 1024
SINVIMG_USUARIO_DEFAULT = "API Multishop"
SINVIMG_MARCA_DEFAULT = "M"
SINVIMG_ENOFERTA_DEFAULT = "N"

_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.IGNORECASE | re.DOTALL)


def detect_content_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def decode_imagen_base64(value: str) -> bytes:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("imagen_base64 is empty")
    match = _DATA_URL_RE.match(raw)
    if match:
        raw = match.group(2).strip()
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("imagen_base64 is not valid base64") from exc
    if not data:
        raise ValueError("imagen_base64 decoded to empty bytes")
    if len(data) > MAX_IMAGEN_BYTES:
        raise ValueError(f"imagen exceeds max size ({MAX_IMAGEN_BYTES} bytes)")
    if detect_content_type(data) == "application/octet-stream":
        raise ValueError("imagen must be JPEG, PNG, GIF or WebP")
    return data


def encode_imagen_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def fetch_has_imagen_by_codigos(cur, codigos: list[str]) -> dict[str, bool]:
    codes = [c.strip() for c in codigos if c and str(c).strip()]
    if not codes:
        return {}
    placeholders = ", ".join(["%s"] * len(codes))
    cur.execute(
        f"""
        SELECT DISTINCT codigo
        FROM sinvimg
        WHERE codigo IN ({placeholders})
          AND imagen IS NOT NULL
          AND LENGTH(imagen) > 0
        """,
        tuple(codes),
    )
    rows = cur.fetchall() or []
    found: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            found.add(str(row.get("codigo") or ""))
        else:
            found.add(str(row[0] or ""))
    return {code: code in found for code in codes}


def fetch_imagen_bytes(cur, codigo: str) -> bytes | None:
    cur.execute(
        """
        SELECT imagen
        FROM sinvimg
        WHERE codigo = %s
          AND imagen IS NOT NULL
          AND LENGTH(imagen) > 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (codigo.strip(),),
    )
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        data = row.get("imagen")
    else:
        data = row[0]
    if not data:
        return None
    return bytes(data)


def upsert_sinvimg(
    cur,
    codigo: str,
    imagen: bytes,
    *,
    descrip: str = "",
    ccate: str = "",
    usuario: str = SINVIMG_USUARIO_DEFAULT,
) -> None:
    code = codigo.strip()
    if not code:
        raise ValueError("codigo is required for sinvimg")
    if not imagen:
        raise ValueError("imagen is required for sinvimg")

    cur.execute(
        "SELECT id FROM sinvimg WHERE codigo = %s ORDER BY id DESC LIMIT 1",
        (code,),
    )
    row = cur.fetchone()
    today = date.today()
    if row:
        row_id = row["id"] if isinstance(row, dict) else row[0]
        cur.execute(
            """
            UPDATE sinvimg
            SET imagen = %s,
                usuario = %s,
                creado = %s,
                descrip = %s,
                ccate = %s
            WHERE id = %s
            """,
            (imagen, usuario, today, descrip[:240], ccate[:10], row_id),
        )
        return

    cur.execute(
        """
        INSERT INTO sinvimg (
          codigo, imagen, usuario, creado, marca,
          sku, descrip, clinea, ccate, cscate, cmarca, cpactivo, enoferta
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            code,
            imagen,
            usuario,
            today,
            SINVIMG_MARCA_DEFAULT,
            "",
            descrip[:240],
            "",
            ccate[:10],
            "",
            "",
            "",
            SINVIMG_ENOFERTA_DEFAULT,
        ),
    )


def attach_imagen_metadata(cur, item: dict[str, Any], *, include_payload: bool) -> None:
    codigo = str(item.get("codigo") or "")
    data = fetch_imagen_bytes(cur, codigo) if codigo else None
    item["tiene_imagen"] = bool(data)
    if include_payload and data:
        item["imagen_content_type"] = detect_content_type(data)
        item["imagen_base64"] = encode_imagen_base64(data)


def attach_imagen_flags_to_items(cur, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    flags = fetch_has_imagen_by_codigos(
        cur,
        [str(row.get("codigo") or "") for row in items],
    )
    for row in items:
        codigo = str(row.get("codigo") or "")
        row["tiene_imagen"] = flags.get(codigo, False)
