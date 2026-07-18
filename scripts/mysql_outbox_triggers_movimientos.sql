-- Outbox Multishop → hub (SOLO movimientos: compra, venta, kardex/ajustes).
-- Doc: docs/outbox-huey-movimientos.md (raíz del monorepo)
-- Instalación: cd Multishop-nodo-API && MS_SQL_FILE=scripts/mysql_outbox_triggers_movimientos.sql
--   python scripts/apply_mysql_outbox_triggers.py
--
-- Fuente única transaccional: tabla kardex (trg_router_kardex_*).
--   sync_outbox_router.table_name = kardex; entity_type en el hub según fila:
--   compras  <> 0  → purchase | ventas <> 0 → sale | ajuste → kardex
--
-- Convive con el proyecto hub (sync_outbox + trg_kardex_*): nombres router con prefijo.
-- Migración router antiguo: si existían trg_kardex_* solo del router, elimínelos a mano una vez.
-- MySQL 5.6: un solo trigger por (tabla, timing, evento); no pueden coexistir trg_kardex_ai y trg_router_kardex_ai.
-- NO incluye: sinv, sprv, catego, detalle (lotes), ventas, ventasd, catalog_push_digest.

CREATE TABLE IF NOT EXISTS sync_outbox_router (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  table_name VARCHAR(64) NOT NULL,
  op CHAR(1) NOT NULL,
  pk_json TEXT NOT NULL,
  row_json MEDIUMTEXT NULL,
  created_at DATETIME(3) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT NULL,
  sent_at DATETIME(3) NULL,
  event_id CHAR(36) NULL,
  PRIMARY KEY (id),
  KEY idx_status_id (status, id),
  KEY idx_table_created (table_name, created_at),
  UNIQUE KEY uq_sync_outbox_router_event_id (event_id)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

ALTER TABLE sync_outbox_router ENGINE=MyISAM;

-- Helpers JSON router (MySQL 5.6); prefijo ms_router_json_* no pisa ms_json_* del hub.
DROP FUNCTION IF EXISTS ms_router_json_escape;
DROP FUNCTION IF EXISTS ms_router_json_str;
DROP FUNCTION IF EXISTS ms_router_json_int;
DROP FUNCTION IF EXISTS ms_router_json_num;
DROP FUNCTION IF EXISTS ms_router_json_datetime;
DROP FUNCTION IF EXISTS ms_router_json_date;
DELIMITER $$
CREATE FUNCTION ms_router_json_escape(str TEXT)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF str IS NULL THEN
    RETURN NULL;
  END IF;
  RETURN REPLACE(
    REPLACE(
      REPLACE(
        REPLACE(
          REPLACE(str, '\\', '\\\\'),
          '"', '\\"'),
        CHAR(10), '\\n'),
      CHAR(13), '\\r'),
    CHAR(9), '\\t');
END$$

CREATE FUNCTION ms_router_json_str(str TEXT)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF str IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CONCAT('"', ms_router_json_escape(str), '"');
END$$

CREATE FUNCTION ms_router_json_int(n BIGINT)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF n IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CAST(n AS CHAR);
END$$

CREATE FUNCTION ms_router_json_num(n DECIMAL(65, 10))
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF n IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM CAST(n AS CHAR)));
END$$

CREATE FUNCTION ms_router_json_date(d DATE)
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF d IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CONCAT('"', DATE_FORMAT(d, '%Y-%m-%d'), '"');
END$$

CREATE FUNCTION ms_router_json_datetime(dt DATETIME(3))
RETURNS TEXT
DETERMINISTIC
NO SQL
BEGIN
  IF dt IS NULL THEN
    RETURN 'null';
  END IF;
  RETURN CONCAT(
    '"',
    DATE_FORMAT(dt, '%Y-%m-%dT%H:%i:%s.'),
    LPAD(FLOOR(MICROSECOND(dt) / 1000), 3, '0'),
    '"'
  );
END$$
DELIMITER ;

-- Solo triggers router. MySQL 5.6: un slot por (tabla, timing, evento).
-- El backup/hub suele traer trg_kardex_* → sync_outbox; el router los reemplaza aquí.
DROP TRIGGER IF EXISTS trg_kardex_ai;
DROP TRIGGER IF EXISTS trg_kardex_au;
DROP TRIGGER IF EXISTS trg_kardex_ad;
DROP TRIGGER IF EXISTS trg_router_kardex_ai;
DROP TRIGGER IF EXISTS trg_router_kardex_au;
DROP TRIGGER IF EXISTS trg_router_kardex_ad;

DELIMITER $$
CREATE TRIGGER trg_router_kardex_ai AFTER INSERT ON kardex FOR EACH ROW
BEGIN
  IF IFNULL(NEW.compras, 0) <> 0 THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'I',
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),'}'),
      CONCAT('{','\"contador\":',ms_router_json_int(IFNULL(NEW.contador, NEW.indice)),',','\"numdoc\":',ms_router_json_str(IFNULL(NEW.numero, '')),',','\"codigo\":',ms_router_json_str(NEW.codigo),',','\"cantidad\":',ms_router_json_num(NEW.compras),',','\"precio\":',ms_router_json_num(NEW.costo),',','\"monto\":',ms_router_json_num(IFNULL(NEW.compras, 0) * IFNULL(NEW.costo, 0)),',','\"costo_anterior\":',ms_router_json_num((
        SELECT s.costoant
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_promedio_ponderado\":',ms_router_json_num((
        SELECT s.costopro
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_actual_factura\":',ms_router_json_num(NEW.costo),',','\"costo_anterior_usd\":',ms_router_json_num((
        SELECT d.costoant
        FROM detallepr d
        WHERE TRIM(d.codigo) = TRIM(NEW.codigo)
        LIMIT 1
      )),',','\"costo_promedio_ponderado_usd\":',ms_router_json_num((
        SELECT d.costopro
        FROM detallepr d
        WHERE TRIM(d.codigo) = TRIM(NEW.codigo)
        LIMIT 1
      )),',','\"costo_actual_factura_usd\":',ms_router_json_num(IFNULL((
        SELECT CASE WHEN d.cambiodc > 0 THEN NEW.costo / d.cambiodc ELSE 0 END
        FROM detallepr d
        WHERE TRIM(d.codigo) = TRIM(NEW.codigo)
        LIMIT 1
      ), 0)),',','\"fecha\":',ms_router_json_date(NEW.fecha),',','\"kobs\":',ms_router_json_str(NEW.kobs),',','\"compras\":',ms_router_json_num(NEW.compras),',','\"kardex_indice\":',ms_router_json_int(NEW.indice),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
  IF IFNULL(NEW.ventas, 0) <> 0 THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'I',
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),'}'),
      CONCAT('{','\"numero\":',ms_router_json_str(NEW.numero),',','\"fecha\":',ms_router_json_date(NEW.fecha),',','\"codigo\":',ms_router_json_str(NEW.codigo),',','\"cantidad\":',ms_router_json_num(NEW.ventas),',','\"contador\":',ms_router_json_int(IFNULL(NEW.contador, NEW.indice)),',','\"ccaja\":',ms_router_json_str(NEW.cajero),',','\"ventas\":',ms_router_json_num(NEW.ventas),',','\"kobs\":',ms_router_json_str(NEW.kobs),',','\"hora\":',ms_router_json_str(NEW.hora),',','\"kardex_indice\":',ms_router_json_int(NEW.indice),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
  IF IFNULL(NEW.compras, 0) = 0
     AND IFNULL(NEW.ventas, 0) = 0
     AND (IFNULL(NEW.ajustesp, 0) <> 0
          OR IFNULL(NEW.ajustesn, 0) <> 0
          OR IFNULL(NEW.devoc, 0) <> 0) THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'I',
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),'}'),
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),',','\"kardex_indice\":',ms_router_json_int(NEW.indice),',','\"codigo\":',ms_router_json_str(NEW.codigo),',','\"fecha\":',ms_router_json_date(NEW.fecha),',','\"contador\":',ms_router_json_int(NEW.contador),',','\"ajustesp\":',ms_router_json_num(NEW.ajustesp),',','\"ajustesn\":',ms_router_json_num(NEW.ajustesn),',','\"compras\":',ms_router_json_num(NEW.compras),',','\"ventas\":',ms_router_json_num(NEW.ventas),',','\"devoc\":',ms_router_json_num(NEW.devoc),',','\"devov\":',ms_router_json_num(NEW.devov),',','\"kobs\":',ms_router_json_str(NEW.kobs),',','\"hora\":',ms_router_json_str(NEW.hora),',','\"outbox_op\":',ms_router_json_str('I'),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_router_kardex_au AFTER UPDATE ON kardex FOR EACH ROW
BEGIN
  IF IFNULL(NEW.compras, 0) <> 0 THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'U',
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),'}'),
      CONCAT('{','\"contador\":',ms_router_json_int(IFNULL(NEW.contador, NEW.indice)),',','\"numdoc\":',ms_router_json_str(IFNULL(NEW.numero, '')),',','\"codigo\":',ms_router_json_str(NEW.codigo),',','\"cantidad\":',ms_router_json_num(NEW.compras),',','\"precio\":',ms_router_json_num(NEW.costo),',','\"monto\":',ms_router_json_num(IFNULL(NEW.compras, 0) * IFNULL(NEW.costo, 0)),',','\"costo_anterior\":',ms_router_json_num((
        SELECT s.costoant
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_promedio_ponderado\":',ms_router_json_num((
        SELECT s.costopro
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_actual_factura\":',ms_router_json_num(NEW.costo),',','\"costo_anterior_usd\":',ms_router_json_num((
        SELECT d.costoant
        FROM detallepr d
        WHERE TRIM(d.codigo) = TRIM(NEW.codigo)
        LIMIT 1
      )),',','\"costo_promedio_ponderado_usd\":',ms_router_json_num((
        SELECT d.costopro
        FROM detallepr d
        WHERE TRIM(d.codigo) = TRIM(NEW.codigo)
        LIMIT 1
      )),',','\"costo_actual_factura_usd\":',ms_router_json_num(IFNULL((
        SELECT CASE WHEN d.cambiodc > 0 THEN NEW.costo / d.cambiodc ELSE 0 END
        FROM detallepr d
        WHERE TRIM(d.codigo) = TRIM(NEW.codigo)
        LIMIT 1
      ), 0)),',','\"fecha\":',ms_router_json_date(NEW.fecha),',','\"kobs\":',ms_router_json_str(NEW.kobs),',','\"compras\":',ms_router_json_num(NEW.compras),',','\"kardex_indice\":',ms_router_json_int(NEW.indice),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
  IF IFNULL(NEW.ventas, 0) <> 0 THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'U',
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),'}'),
      CONCAT('{','\"numero\":',ms_router_json_str(NEW.numero),',','\"fecha\":',ms_router_json_date(NEW.fecha),',','\"codigo\":',ms_router_json_str(NEW.codigo),',','\"cantidad\":',ms_router_json_num(NEW.ventas),',','\"contador\":',ms_router_json_int(IFNULL(NEW.contador, NEW.indice)),',','\"ccaja\":',ms_router_json_str(NEW.cajero),',','\"ventas\":',ms_router_json_num(NEW.ventas),',','\"kobs\":',ms_router_json_str(NEW.kobs),',','\"hora\":',ms_router_json_str(NEW.hora),',','\"kardex_indice\":',ms_router_json_int(NEW.indice),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
  IF IFNULL(NEW.compras, 0) = 0
     AND IFNULL(NEW.ventas, 0) = 0
     AND (IFNULL(NEW.ajustesp, 0) <> 0
          OR IFNULL(NEW.ajustesn, 0) <> 0
          OR IFNULL(NEW.devoc, 0) <> 0) THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'U',
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),'}'),
      CONCAT('{','\"indice\":',ms_router_json_int(NEW.indice),',','\"kardex_indice\":',ms_router_json_int(NEW.indice),',','\"codigo\":',ms_router_json_str(NEW.codigo),',','\"fecha\":',ms_router_json_date(NEW.fecha),',','\"contador\":',ms_router_json_int(NEW.contador),',','\"ajustesp\":',ms_router_json_num(NEW.ajustesp),',','\"ajustesn\":',ms_router_json_num(NEW.ajustesn),',','\"compras\":',ms_router_json_num(NEW.compras),',','\"ventas\":',ms_router_json_num(NEW.ventas),',','\"devoc\":',ms_router_json_num(NEW.devoc),',','\"devov\":',ms_router_json_num(NEW.devov),',','\"kobs\":',ms_router_json_str(NEW.kobs),',','\"hora\":',ms_router_json_str(NEW.hora),',','\"outbox_op\":',ms_router_json_str('U'),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_router_kardex_ad AFTER DELETE ON kardex FOR EACH ROW
BEGIN
  IF IFNULL(OLD.compras, 0) <> 0 THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'D',
      CONCAT('{','\"indice\":',ms_router_json_int(OLD.indice),'}'),
      CONCAT('{','\"contador\":',ms_router_json_int(IFNULL(OLD.contador, OLD.indice)),',','\"numdoc\":',ms_router_json_str(IFNULL(OLD.numero, '')),',','\"codigo\":',ms_router_json_str(OLD.codigo),',','\"cantidad\":',ms_router_json_num(OLD.compras),',','\"precio\":',ms_router_json_num(OLD.costo),',','\"monto\":',ms_router_json_num(IFNULL(OLD.compras, 0) * IFNULL(OLD.costo, 0)),',','\"costo_anterior\":',ms_router_json_num((
        SELECT s.costoant
        FROM sinv s
        WHERE s.codigo = OLD.codigo
        LIMIT 1
      )),',','\"costo_promedio_ponderado\":',ms_router_json_num((
        SELECT s.costopro
        FROM sinv s
        WHERE s.codigo = OLD.codigo
        LIMIT 1
      )),',','\"costo_actual_factura\":',ms_router_json_num(OLD.costo),',','\"fecha\":',ms_router_json_date(OLD.fecha),',','\"kobs\":',ms_router_json_str(OLD.kobs),',','\"compras\":',ms_router_json_num(OLD.compras),',','\"kardex_indice\":',ms_router_json_int(OLD.indice),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
  IF IFNULL(OLD.ventas, 0) <> 0 THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'D',
      CONCAT('{','\"indice\":',ms_router_json_int(OLD.indice),'}'),
      CONCAT('{','\"numero\":',ms_router_json_str(OLD.numero),',','\"fecha\":',ms_router_json_date(OLD.fecha),',','\"codigo\":',ms_router_json_str(OLD.codigo),',','\"cantidad\":',ms_router_json_num(OLD.ventas),',','\"contador\":',ms_router_json_int(IFNULL(OLD.contador, OLD.indice)),',','\"ccaja\":',ms_router_json_str(OLD.cajero),',','\"ventas\":',ms_router_json_num(OLD.ventas),',','\"kobs\":',ms_router_json_str(OLD.kobs),',','\"hora\":',ms_router_json_str(OLD.hora),',','\"kardex_indice\":',ms_router_json_int(OLD.indice),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
  IF IFNULL(OLD.compras, 0) = 0
     AND IFNULL(OLD.ventas, 0) = 0
     AND (IFNULL(OLD.ajustesp, 0) <> 0
          OR IFNULL(OLD.ajustesn, 0) <> 0
          OR IFNULL(OLD.devoc, 0) <> 0) THEN
    INSERT INTO sync_outbox_router(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'D',
      CONCAT('{','\"indice\":',ms_router_json_int(OLD.indice),'}'),
      CONCAT('{','\"indice\":',ms_router_json_int(OLD.indice),',','\"kardex_indice\":',ms_router_json_int(OLD.indice),',','\"codigo\":',ms_router_json_str(OLD.codigo),',','\"fecha\":',ms_router_json_date(OLD.fecha),',','\"contador\":',ms_router_json_int(OLD.contador),',','\"ajustesp\":',ms_router_json_num(OLD.ajustesp),',','\"ajustesn\":',ms_router_json_num(OLD.ajustesn),',','\"compras\":',ms_router_json_num(OLD.compras),',','\"ventas\":',ms_router_json_num(OLD.ventas),',','\"devoc\":',ms_router_json_num(OLD.devoc),',','\"devov\":',ms_router_json_num(OLD.devov),',','\"kobs\":',ms_router_json_str(OLD.kobs),',','\"hora\":',ms_router_json_str(OLD.hora),',','\"outbox_op\":',ms_router_json_str('D'),',','\"outbox_enqueued_at\":',ms_router_json_datetime(NOW(3)),'}'),
      NOW(3)
    );
  END IF;
END$$
DELIMITER ;
