"""Upsert de proveedores (sprv + auxiliar) alineado con resumen/sprv.txt."""

from __future__ import annotations

from typing import Any

CCONTAB_DEFAULT = "2.01.2.01"

SPRV_BODY_FIELDS = (
    "cod_prv",
    "nom_prv",
    "rif_prv",
    "dir1_prv",
    "dir2_prv",
    "dir3_prv",
    "tel_prv",
    "email1_prv",
    "email2_prv",
    "rep_prv",
    "especial",
    "numcuenta",
)


def normalize_especial(value: str | None) -> str:
    return "si" if str(value or "").strip().lower() == "si" else "no"


def tipo_persona_from_rif(rif: str) -> str:
    rif = (rif or "").strip()
    if not rif:
        return ""
    return rif[0].upper()


def _field(payload: dict, key: str, default: str = "") -> str:
    raw = payload.get(key)
    if raw is None:
        return default
    return str(raw).strip()


def build_sprv_db_row(payload: dict) -> dict[str, Any]:
    body = {k: _field(payload, k) for k in SPRV_BODY_FIELDS}
    if not body["cod_prv"]:
        raise ValueError("provider row requires cod_prv")
    rif = body["rif_prv"]
    nom = body["nom_prv"]
    return {
        **body,
        "especial": normalize_especial(body["especial"]),
        "nit_prv": "",
        "tipo_prv": None,
        "ccontab": CCONTAB_DEFAULT,
        "proveni": "Nacional",
        "tipo_persona": tipo_persona_from_rif(rif),
        "auxiliar1": rif[:30] if rif else "",
        "plazo1": 0,
        "plazo2": 0,
        "plazo3": 0,
        "pretencionp": 75.00,
        "ccate_prv": "",
        "cconcepto": "",
        "act_banco": "N",
        "dgastos": "No",
        "dotros": "No",
        "aplicarac": "No",
        "correosn": 0,
        "odif": 0,
        "odif1": 0,
        "odif2": 0,
    }


def ensure_auxiliar(cur, rif: str, nom: str) -> None:
    if not rif or not nom:
        return
    cur.execute("SELECT 1 FROM auxiliar WHERE cauxiliar = %s LIMIT 1", (rif,))
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO auxiliar (cauxiliar, nauxiliar, rif)
            VALUES (%s, %s, %s)
            """,
            (rif, nom, rif),
        )


def upsert_sprv(cur, payload: dict) -> None:
    """INSERT o UPDATE por cod_prv (evita 1062 cuando UPDATE no cambia filas)."""
    row = build_sprv_db_row(payload)
    ensure_auxiliar(cur, row["rif_prv"], row["nom_prv"])
    cur.execute(
        """
        INSERT INTO sprv (
          cod_prv, nom_prv, rif_prv, nit_prv,
          dir1_prv, dir2_prv, dir3_prv,
          tel_prv, email1_prv, email2_prv, rep_prv,
          plazo1, plazo2, plazo3,
          especial, tipo_prv, act_banco, ccontab,
          dgastos, proveni, dotros, auxiliar1, cconcepto,
          tipo_persona, numcuenta, aplicarac, pretencionp,
          ccate_prv, correosn, odif, odif1, odif2
        )
        VALUES (
          %s, %s, %s, %s,
          %s, %s, %s,
          %s, %s, %s, %s,
          %s, %s, %s,
          %s, %s, %s, %s,
          %s, %s, %s, %s, %s,
          %s, %s, %s, %s,
          %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
          nom_prv = VALUES(nom_prv),
          rif_prv = VALUES(rif_prv),
          nit_prv = VALUES(nit_prv),
          dir1_prv = VALUES(dir1_prv),
          dir2_prv = VALUES(dir2_prv),
          dir3_prv = VALUES(dir3_prv),
          tel_prv = VALUES(tel_prv),
          email1_prv = VALUES(email1_prv),
          email2_prv = VALUES(email2_prv),
          rep_prv = VALUES(rep_prv),
          plazo1 = VALUES(plazo1),
          plazo2 = VALUES(plazo2),
          plazo3 = VALUES(plazo3),
          especial = VALUES(especial),
          tipo_persona = VALUES(tipo_persona),
          auxiliar1 = VALUES(auxiliar1),
          numcuenta = VALUES(numcuenta)
        """,
        (
            row["cod_prv"],
            row["nom_prv"],
            row["rif_prv"],
            row["nit_prv"],
            row["dir1_prv"],
            row["dir2_prv"],
            row["dir3_prv"],
            row["tel_prv"],
            row["email1_prv"],
            row["email2_prv"],
            row["rep_prv"],
            row["plazo1"],
            row["plazo2"],
            row["plazo3"],
            row["especial"],
            row["tipo_prv"],
            row["act_banco"],
            row["ccontab"],
            row["dgastos"],
            row["proveni"],
            row["dotros"],
            row["auxiliar1"],
            row["cconcepto"],
            row["tipo_persona"],
            row["numcuenta"],
            row["aplicarac"],
            row["pretencionp"],
            row["ccate_prv"],
            row["correosn"],
            row["odif"],
            row["odif1"],
            row["odif2"],
        ),
    )


def delete_sprv(cur, cod_prv: str) -> int:
    cur.execute("DELETE FROM sprv WHERE cod_prv = %s", (cod_prv.strip(),))
    return int(cur.rowcount or 0)
