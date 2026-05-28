#!/usr/bin/env python3
"""Convierte JSON_OBJECT → CONCAT + ms_json_* en mysql_outbox_triggers.sql (MySQL 5.6)."""

from __future__ import annotations

import re
from pathlib import Path

SQL_PATH = Path(__file__).resolve().parent / "mysql_outbox_triggers.sql"

FUNCTIONS_HEADER = """
-- Helpers JSON para MySQL 5.6 (sin tipo JSON nativo)
DROP FUNCTION IF EXISTS ms_json_escape;
DROP FUNCTION IF EXISTS ms_json_str;
DROP FUNCTION IF EXISTS ms_json_int;
DROP FUNCTION IF EXISTS ms_json_num;
DROP FUNCTION IF EXISTS ms_json_date;

DELIMITER $$
CREATE FUNCTION ms_json_escape(str TEXT)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF str IS NULL THEN
    RETURN NULL;
  END IF;
  RETURN REPLACE(REPLACE(REPLACE(REPLACE(str, '\\\\', '\\\\\\\\'), '"', '\\\\"'), CHAR(10), '\\\\n'), CHAR(13), '\\\\r');
END$$

CREATE FUNCTION ms_json_str(str TEXT)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF str IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CONCAT('"', ms_json_escape(str), '"');
END$$

CREATE FUNCTION ms_json_int(n BIGINT)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF n IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CAST(n AS CHAR);
END$$

CREATE FUNCTION ms_json_num(n DECIMAL(65, 10))
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF n IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM CAST(n AS CHAR)));
END$$

CREATE FUNCTION ms_json_date(d DATE)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF d IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CONCAT('"', DATE_FORMAT(d, '%Y-%m-%d'), '"');
END$$
DELIMITER ;

"""

DATE_COLS = frozenset({"fecha", "fechapc", "vence"})
INT_COLS = frozenset(
    {
        "contador",
        "indice",
        "id_inv",
        "id_sprv",
        "factor",
        "indice_det",
    }
)
NUM_COLS = frozenset(
    {
        "cantidad",
        "precio",
        "monto",
        "existencia",
        "precio1",
        "costo",
        "costopro",
        "porcentaje",
        "pganancia",
        "pdescu",
        "plazo1",
        "plazo2",
        "plazo3",
        "ajustesp",
        "ajustesn",
        "compras",
        "ventas",
        "devoc",
        "devov",
        "entradas",
        "salidas",
        "uxb",
        "canlote",
    }
)


def find_matching_paren(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"Unbalanced paren at {open_idx}")


def parse_json_object_args(inner: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    i = 0
    n = len(inner)
    while i < n:
        while i < n and inner[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        if inner[i] != "'":
            raise ValueError(f"Expected key at {i}: {inner[i : i + 40]!r}")
        i += 1
        key_start = i
        while i < n and inner[i] != "'":
            i += 1
        key = inner[key_start:i]
        i += 1
        while i < n and inner[i] in " \t\n\r,":
            i += 1
        val_start = i
        depth = 0
        while i < n:
            c = inner[i]
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and c == ",":
                j = i + 1
                while j < n and inner[j] in " \t\n\r":
                    j += 1
                if j < n and inner[j] == "'":
                    k = j + 1
                    while k < n and inner[k] != "'":
                        k += 1
                    if k < n:
                        k += 1
                        while k < n and inner[k] in " \t\n\r":
                            k += 1
                        if k < n and inner[k] == ",":
                            break
            i += 1
        value = inner[val_start:i].strip()
        pairs.append((key, value))
    return pairs


def value_expr(key: str, value: str) -> str:
    v = value.strip()
    if re.fullmatch(r"'[^']*'", v):
        lit = v[1:-1].replace("'", "''")
        return f"ms_json_str('{lit}')"
    if v.upper() == "NULL":
        return "null"
    if v.startswith("(SELECT") or v.startswith("( SELECT"):
        return f"ms_json_num({v})"
    if v.startswith("CASE"):
        return f"ms_json_num({v})"
    m = re.match(r"^(NEW|OLD)\.(\w+)$", v)
    if m:
        col = m.group(2)
        if col in DATE_COLS:
            return f"ms_json_date({v})"
        if col in INT_COLS and col not in NUM_COLS:
            return f"ms_json_int({v})"
        if col in NUM_COLS:
            return f"ms_json_num({v})"
        return f"ms_json_str({v})"
    return f"ms_json_str(CAST({v} AS CHAR))"


def pairs_to_concat(pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return "CONCAT('{}')"
    parts = ["CONCAT('{"]
    for idx, (key, val) in enumerate(pairs):
        if idx > 0:
            parts.append(",','")
        # Claves JSON como literales SQL entre comillas simples: '"campo":'
        parts.append(f"'\"{key}\":',")
        parts.append(value_expr(key, val))
    parts.append(",'}')")
    return "".join(parts)


def replace_json_objects(text: str) -> str:
    out: list[str] = []
    pos = 0
    marker = "JSON_OBJECT"
    while True:
        idx = text.find(marker, pos)
        if idx < 0:
            out.append(text[pos:])
            break
        out.append(text[pos:idx])
        open_paren = text.find("(", idx)
        close_paren = find_matching_paren(text, open_paren)
        inner = text[open_paren + 1 : close_paren]
        pairs = parse_json_object_args(inner)
        out.append(pairs_to_concat(pairs))
        pos = close_paren + 1
    return "".join(out)


def main() -> None:
    raw = SQL_PATH.read_text(encoding="utf-8")
    if "ms_json_str" in raw and "JSON_OBJECT" not in raw:
        print("Ya convertido (sin JSON_OBJECT).")
        return
    if "CREATE FUNCTION ms_json_str" not in raw:
        # Insert after sync_outbox CREATE TABLE block
        anchor = ") ENGINE=InnoDB DEFAULT CHARSET=utf8;\n\n"
        if anchor not in raw:
            raise SystemExit("No se encontró ancla para insertar funciones JSON")
        raw = raw.replace(anchor, anchor + FUNCTIONS_HEADER.strip() + "\n\n", 1)

    converted = replace_json_objects(raw)
    if "JSON_OBJECT" in converted:
        raise SystemExit("Quedaron JSON_OBJECT sin convertir")

    SQL_PATH.write_text(converted, encoding="utf-8")
    print(f"OK: {SQL_PATH} actualizado para MySQL 5.6 ({converted.count('ms_json_')} usos ms_json_*).")


if __name__ == "__main__":
    main()
