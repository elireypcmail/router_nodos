-- Outbox Multishop → hub. Instalación: scripts/apply_mysql_outbox_triggers.py
-- (siempre DROP de trg_* y ms_json_* del manifiesto y CREATE de nuevo; no pegar este archivo a mano).

CREATE TABLE IF NOT EXISTS sync_outbox (
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
  PRIMARY KEY (id),
  KEY idx_status_id (status, id),
  KEY idx_table_created (table_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

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
  RETURN REPLACE(REPLACE(REPLACE(REPLACE(str, '\\', '\\\\'), '"', '\\"'), CHAR(10), '\\n'), CHAR(13), '\\r');
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

DROP TRIGGER IF EXISTS trg_kardex_ai;
DROP TRIGGER IF EXISTS trg_kardex_au;
DROP TRIGGER IF EXISTS trg_kardex_ad;

DROP TRIGGER IF EXISTS trg_kardexd_ai;
DROP TRIGGER IF EXISTS trg_kardexd_au;
DROP TRIGGER IF EXISTS trg_kardexd_ad;

DELIMITER $$
CREATE TRIGGER trg_kardex_ai AFTER INSERT ON kardex FOR EACH ROW
BEGIN
  IF IFNULL(NEW.compras, 0) = 0
     AND IFNULL(NEW.ventas, 0) = 0
     AND (IFNULL(NEW.ajustesp, 0) <> 0
          OR IFNULL(NEW.ajustesn, 0) <> 0
          OR IFNULL(NEW.devoc, 0) <> 0
          OR IFNULL(NEW.devov, 0) <> 0) THEN
    INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'I',
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),'}'),
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"contador\":',ms_json_int(NEW.contador),',','\"ajustesp\":',ms_json_num(NEW.ajustesp),',','\"ajustesn\":',ms_json_num(NEW.ajustesn),',','\"compras\":',ms_json_num(NEW.compras),',','\"ventas\":',ms_json_num(NEW.ventas),',','\"devoc\":',ms_json_num(NEW.devoc),',','\"devov\":',ms_json_num(NEW.devov),',','\"outbox_op\":',ms_json_str('I'),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_kardex_au AFTER UPDATE ON kardex FOR EACH ROW
BEGIN
  IF IFNULL(NEW.compras, 0) = 0
     AND IFNULL(NEW.ventas, 0) = 0
     AND (IFNULL(NEW.ajustesp, 0) <> 0
          OR IFNULL(NEW.ajustesn, 0) <> 0
          OR IFNULL(NEW.devoc, 0) <> 0
          OR IFNULL(NEW.devov, 0) <> 0) THEN
    INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'U',
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),'}'),
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"contador\":',ms_json_int(NEW.contador),',','\"ajustesp\":',ms_json_num(NEW.ajustesp),',','\"ajustesn\":',ms_json_num(NEW.ajustesn),',','\"compras\":',ms_json_num(NEW.compras),',','\"ventas\":',ms_json_num(NEW.ventas),',','\"devoc\":',ms_json_num(NEW.devoc),',','\"devov\":',ms_json_num(NEW.devov),',','\"outbox_op\":',ms_json_str('U'),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_kardex_ad AFTER DELETE ON kardex FOR EACH ROW
BEGIN
  IF IFNULL(OLD.compras, 0) = 0
     AND IFNULL(OLD.ventas, 0) = 0
     AND (IFNULL(OLD.ajustesp, 0) <> 0
          OR IFNULL(OLD.ajustesn, 0) <> 0
          OR IFNULL(OLD.devoc, 0) <> 0
          OR IFNULL(OLD.devov, 0) <> 0) THEN
    INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardex',
      'D',
      CONCAT('{','\"indice\":',ms_json_int(OLD.indice),'}'),
      CONCAT('{','\"indice\":',ms_json_int(OLD.indice),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"fecha\":',ms_json_date(OLD.fecha),',','\"contador\":',ms_json_int(OLD.contador),',','\"ajustesp\":',ms_json_num(OLD.ajustesp),',','\"ajustesn\":',ms_json_num(OLD.ajustesn),',','\"compras\":',ms_json_num(OLD.compras),',','\"ventas\":',ms_json_num(OLD.ventas),',','\"devoc\":',ms_json_num(OLD.devoc),',','\"devov\":',ms_json_num(OLD.devov),',','\"outbox_op\":',ms_json_str('D'),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_kardexd_ai AFTER INSERT ON kardexd FOR EACH ROW
BEGIN
  IF IFNULL(NEW.compras, 0) = 0
     AND IFNULL(NEW.ventas, 0) = 0
     AND (IFNULL(NEW.ajustesp, 0) <> 0
          OR IFNULL(NEW.ajustesn, 0) <> 0
          OR IFNULL(NEW.devoc, 0) <> 0
          OR IFNULL(NEW.devov, 0) <> 0) THEN
    INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardexd',
      'I',
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),'}'),
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"contador\":',ms_json_int(NEW.contador),',','\"ajustesp\":',ms_json_num(NEW.ajustesp),',','\"ajustesn\":',ms_json_num(NEW.ajustesn),',','\"compras\":',ms_json_num(NEW.compras),',','\"ventas\":',ms_json_num(NEW.ventas),',','\"devoc\":',ms_json_num(NEW.devoc),',','\"devov\":',ms_json_num(NEW.devov),',','\"outbox_op\":',ms_json_str('I'),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_kardexd_au AFTER UPDATE ON kardexd FOR EACH ROW
BEGIN
  IF IFNULL(NEW.compras, 0) = 0
     AND IFNULL(NEW.ventas, 0) = 0
     AND (IFNULL(NEW.ajustesp, 0) <> 0
          OR IFNULL(NEW.ajustesn, 0) <> 0
          OR IFNULL(NEW.devoc, 0) <> 0
          OR IFNULL(NEW.devov, 0) <> 0) THEN
    INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardexd',
      'U',
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),'}'),
      CONCAT('{','\"indice\":',ms_json_int(NEW.indice),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"contador\":',ms_json_int(NEW.contador),',','\"ajustesp\":',ms_json_num(NEW.ajustesp),',','\"ajustesn\":',ms_json_num(NEW.ajustesn),',','\"compras\":',ms_json_num(NEW.compras),',','\"ventas\":',ms_json_num(NEW.ventas),',','\"devoc\":',ms_json_num(NEW.devoc),',','\"devov\":',ms_json_num(NEW.devov),',','\"outbox_op\":',ms_json_str('U'),'}'),
      NOW(3)
    );
  END IF;
END$$

CREATE TRIGGER trg_kardexd_ad AFTER DELETE ON kardexd FOR EACH ROW
BEGIN
  IF IFNULL(OLD.compras, 0) = 0
     AND IFNULL(OLD.ventas, 0) = 0
     AND (IFNULL(OLD.ajustesp, 0) <> 0
          OR IFNULL(OLD.ajustesn, 0) <> 0
          OR IFNULL(OLD.devoc, 0) <> 0
          OR IFNULL(OLD.devov, 0) <> 0) THEN
    INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
    VALUES (
      'kardexd',
      'D',
      CONCAT('{','\"indice\":',ms_json_int(OLD.indice),'}'),
      CONCAT('{','\"indice\":',ms_json_int(OLD.indice),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"fecha\":',ms_json_date(OLD.fecha),',','\"contador\":',ms_json_int(OLD.contador),',','\"ajustesp\":',ms_json_num(OLD.ajustesp),',','\"ajustesn\":',ms_json_num(OLD.ajustesn),',','\"compras\":',ms_json_num(OLD.compras),',','\"ventas\":',ms_json_num(OLD.ventas),',','\"devoc\":',ms_json_num(OLD.devoc),',','\"devov\":',ms_json_num(OLD.devov),',','\"outbox_op\":',ms_json_str('D'),'}'),
      NOW(3)
    );
  END IF;
END$$
DELIMITER ;

DROP TRIGGER IF EXISTS trg_sinv_ai;
DROP TRIGGER IF EXISTS trg_sinv_au;
DROP TRIGGER IF EXISTS trg_sinv_ad;

DROP TRIGGER IF EXISTS trg_sprv_ai;
DROP TRIGGER IF EXISTS trg_sprv_au;
DROP TRIGGER IF EXISTS trg_sprv_ad;

DELIMITER $$
CREATE TRIGGER trg_sinv_ai AFTER INSERT ON sinv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sinv',
    'I',
    CONCAT('{','\"id_inv\":',ms_json_int(NEW.id_inv),',','\"codigo\":',ms_json_str(NEW.codigo),'}'),
    CONCAT('{','\"id_inv\":',ms_json_int(NEW.id_inv),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"descrip\":',ms_json_str(NEW.descrip),',','\"barra\":',ms_json_str(NEW.barra),',','\"existencia\":',ms_json_num(NEW.existencia),',','\"precio1\":',ms_json_num(NEW.precio1),',','\"ccate\":',ms_json_str(NEW.ccate),',','\"cod_prv\":',ms_json_str(NEW.cod_prv),',','\"activo\":',ms_json_str(NEW.activo),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sinv_au AFTER UPDATE ON sinv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sinv',
    'U',
    CONCAT('{','\"id_inv\":',ms_json_int(NEW.id_inv),',','\"codigo\":',ms_json_str(NEW.codigo),'}'),
    CONCAT('{','\"id_inv\":',ms_json_int(NEW.id_inv),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"descrip\":',ms_json_str(NEW.descrip),',','\"barra\":',ms_json_str(NEW.barra),',','\"existencia\":',ms_json_num(NEW.existencia),',','\"precio1\":',ms_json_num(NEW.precio1),',','\"ccate\":',ms_json_str(NEW.ccate),',','\"cod_prv\":',ms_json_str(NEW.cod_prv),',','\"activo\":',ms_json_str(NEW.activo),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sinv_ad AFTER DELETE ON sinv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sinv',
    'D',
    CONCAT('{','\"id_inv\":',ms_json_int(OLD.id_inv),',','\"codigo\":',ms_json_str(OLD.codigo),'}'),
    CONCAT('{','\"id_inv\":',ms_json_int(OLD.id_inv),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"descrip\":',ms_json_str(OLD.descrip),',','\"barra\":',ms_json_str(OLD.barra),',','\"existencia\":',ms_json_num(OLD.existencia),',','\"precio1\":',ms_json_num(OLD.precio1),',','\"ccate\":',ms_json_str(OLD.ccate),',','\"cod_prv\":',ms_json_str(OLD.cod_prv),',','\"activo\":',ms_json_str(OLD.activo),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sprv_ai AFTER INSERT ON sprv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sprv',
    'I',
    CONCAT('{','\"id_sprv\":',ms_json_int(NEW.id_sprv),',','\"cod_prv\":',ms_json_str(NEW.cod_prv),'}'),
    CONCAT('{','\"id_sprv\":',ms_json_int(NEW.id_sprv),',','\"cod_prv\":',ms_json_str(NEW.cod_prv),',','\"nom_prv\":',ms_json_str(NEW.nom_prv),',','\"rif_prv\":',ms_json_str(NEW.rif_prv),',','\"nit_prv\":',ms_json_str(NEW.nit_prv),',','\"dir1_prv\":',ms_json_str(NEW.dir1_prv),',','\"tel_prv\":',ms_json_str(NEW.tel_prv),',','\"email1_prv\":',ms_json_str(NEW.email1_prv),',','\"tipo_prv\":',ms_json_str(NEW.tipo_prv),',','\"plazo1\":',ms_json_num(NEW.plazo1),',','\"plazo2\":',ms_json_num(NEW.plazo2),',','\"plazo3\":',ms_json_num(NEW.plazo3),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sprv_au AFTER UPDATE ON sprv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sprv',
    'U',
    CONCAT('{','\"id_sprv\":',ms_json_int(NEW.id_sprv),',','\"cod_prv\":',ms_json_str(NEW.cod_prv),'}'),
    CONCAT('{','\"id_sprv\":',ms_json_int(NEW.id_sprv),',','\"cod_prv\":',ms_json_str(NEW.cod_prv),',','\"nom_prv\":',ms_json_str(NEW.nom_prv),',','\"rif_prv\":',ms_json_str(NEW.rif_prv),',','\"nit_prv\":',ms_json_str(NEW.nit_prv),',','\"dir1_prv\":',ms_json_str(NEW.dir1_prv),',','\"tel_prv\":',ms_json_str(NEW.tel_prv),',','\"email1_prv\":',ms_json_str(NEW.email1_prv),',','\"tipo_prv\":',ms_json_str(NEW.tipo_prv),',','\"plazo1\":',ms_json_num(NEW.plazo1),',','\"plazo2\":',ms_json_num(NEW.plazo2),',','\"plazo3\":',ms_json_num(NEW.plazo3),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sprv_ad AFTER DELETE ON sprv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sprv',
    'D',
    CONCAT('{','\"id_sprv\":',ms_json_int(OLD.id_sprv),',','\"cod_prv\":',ms_json_str(OLD.cod_prv),'}'),
    CONCAT('{','\"id_sprv\":',ms_json_int(OLD.id_sprv),',','\"cod_prv\":',ms_json_str(OLD.cod_prv),',','\"nom_prv\":',ms_json_str(OLD.nom_prv),',','\"rif_prv\":',ms_json_str(OLD.rif_prv),',','\"nit_prv\":',ms_json_str(OLD.nit_prv),',','\"dir1_prv\":',ms_json_str(OLD.dir1_prv),',','\"tel_prv\":',ms_json_str(OLD.tel_prv),',','\"email1_prv\":',ms_json_str(OLD.email1_prv),',','\"tipo_prv\":',ms_json_str(OLD.tipo_prv),',','\"plazo1\":',ms_json_num(OLD.plazo1),',','\"plazo2\":',ms_json_num(OLD.plazo2),',','\"plazo3\":',ms_json_num(OLD.plazo3),'}'),
    NOW(3)
  );
END$$
DELIMITER ;

DROP TRIGGER IF EXISTS trg_ventas_ai;
DROP TRIGGER IF EXISTS trg_ventas_au;
DROP TRIGGER IF EXISTS trg_ventas_ad;

DROP TRIGGER IF EXISTS trg_ventasd_ai;
DROP TRIGGER IF EXISTS trg_ventasd_au;
DROP TRIGGER IF EXISTS trg_ventasd_ad;

DROP TRIGGER IF EXISTS trg_ventasi_ai;
DROP TRIGGER IF EXISTS trg_ventasi_au;
DROP TRIGGER IF EXISTS trg_ventasi_ad;

DELIMITER $$
CREATE TRIGGER trg_ventas_ai AFTER INSERT ON ventas FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventas',
    'I',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventas_au AFTER UPDATE ON ventas FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventas',
    'U',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventas_ad AFTER DELETE ON ventas FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventas',
    'D',
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasd_ai AFTER INSERT ON ventasd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasd',
    'I',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"indice_det\":',ms_json_int(NEW.indice_det),'}'),
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"vence\":',ms_json_date(NEW.vence),',','\"existencia\":',ms_json_num(NEW.existencia),',','\"cantidad\":',ms_json_num(NEW.existencia),',','\"calidad\":',ms_json_str(NEW.calidad),',','\"elabora\":',ms_json_date(NEW.elabora),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasd_au AFTER UPDATE ON ventasd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasd',
    'U',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"indice_det\":',ms_json_int(NEW.indice_det),'}'),
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"vence\":',ms_json_date(NEW.vence),',','\"existencia\":',ms_json_num(NEW.existencia),',','\"cantidad\":',ms_json_num(NEW.existencia),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasd_ad AFTER DELETE ON ventasd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasd',
    'D',
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"indice_det\":',ms_json_int(OLD.indice_det),'}'),
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"vence\":',ms_json_date(OLD.vence),',','\"existencia\":',ms_json_num(OLD.existencia),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasi_ai AFTER INSERT ON ventasi FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasi',
    'I',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"contador\":',ms_json_int(NEW.contador),',','\"ccaja\":',ms_json_str(NEW.ccaja),'}'),
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"cantidad\":',ms_json_num(NEW.cantidad),',','\"contador\":',ms_json_int(NEW.contador),',','\"ccaja\":',ms_json_str(NEW.ccaja),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasi_au AFTER UPDATE ON ventasi FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasi',
    'U',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"contador\":',ms_json_int(NEW.contador),',','\"ccaja\":',ms_json_str(NEW.ccaja),'}'),
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"cantidad\":',ms_json_num(NEW.cantidad),',','\"contador\":',ms_json_int(NEW.contador),',','\"ccaja\":',ms_json_str(NEW.ccaja),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasi_ad AFTER DELETE ON ventasi FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasi',
    'D',
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"contador\":',ms_json_int(OLD.contador),',','\"ccaja\":',ms_json_str(OLD.ccaja),'}'),
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),',','\"fecha\":',ms_json_date(OLD.fecha),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"cantidad\":',ms_json_num(OLD.cantidad),',','\"contador\":',ms_json_int(OLD.contador),',','\"ccaja\":',ms_json_str(OLD.ccaja),'}'),
    NOW(3)
  );
END$$
DELIMITER ;

DROP TRIGGER IF EXISTS trg_factura_ai;
DROP TRIGGER IF EXISTS trg_factura_au;
DROP TRIGGER IF EXISTS trg_factura_ad;

DROP TRIGGER IF EXISTS trg_facturad_ai;
DROP TRIGGER IF EXISTS trg_facturad_au;
DROP TRIGGER IF EXISTS trg_facturad_ad;

DROP TRIGGER IF EXISTS trg_comprasdbf_ai;
DROP TRIGGER IF EXISTS trg_comprasdbf_au;
DROP TRIGGER IF EXISTS trg_comprasdbf_ad;

DELIMITER $$
CREATE TRIGGER trg_factura_ai AFTER INSERT ON factura FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'factura',
    'I',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_factura_au AFTER UPDATE ON factura FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'factura',
    'U',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_factura_ad AFTER DELETE ON factura FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'factura',
    'D',
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),',','\"codigo\":',ms_json_str(OLD.codigo),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_facturad_ai AFTER INSERT ON facturad FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'facturad',
    'I',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_facturad_au AFTER UPDATE ON facturad FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'facturad',
    'U',
    CONCAT('{','\"numero\":',ms_json_str(NEW.numero),',','\"codigo\":',ms_json_str(NEW.codigo),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_facturad_ad AFTER DELETE ON facturad FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'facturad',
    'D',
    CONCAT('{','\"numero\":',ms_json_str(OLD.numero),',','\"codigo\":',ms_json_str(OLD.codigo),'}'),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_comprasdbf_ai AFTER INSERT ON comprasdbf FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'comprasdbf',
    'I',
    CONCAT('{','\"contador\":',ms_json_int(NEW.contador),',','\"numdoc\":',ms_json_str(NEW.numdoc),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"fecha\":',ms_json_date(NEW.fecha),'}'),
    CONCAT('{','\"contador\":',ms_json_int(NEW.contador),',','\"numdoc\":',ms_json_str(NEW.numdoc),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"cantidad\":',ms_json_num(NEW.cantidad),',','\"precio\":',ms_json_num(NEW.precio),',','\"monto\":',ms_json_num(NEW.monto),',','\"costo_anterior\":',ms_json_num((
        SELECT s.costo
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_promedio_ponderado\":',ms_json_num((
        SELECT s.costopro
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_actual_factura\":',ms_json_num(CASE
          WHEN NEW.cantidad IS NULL OR NEW.cantidad = 0 THEN NEW.precio
          ELSE NEW.monto / NEW.cantidad
        END),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"operador\":',ms_json_str(NEW.operador),',','\"porcentaje\":',ms_json_num(NEW.porcentaje),',','\"fechapc\":',ms_json_date(NEW.fechapc),',','\"numerocaso\":',ms_json_str(NEW.numerocaso),',','\"csaga\":',ms_json_str(NEW.csaga),',','\"factor\":',ms_json_int(NEW.factor),',','\"numcot\":',ms_json_str(NEW.numcot),',','\"numfac\":',ms_json_str(NEW.numfac),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_comprasdbf_au AFTER UPDATE ON comprasdbf FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'comprasdbf',
    'U',
    CONCAT('{','\"contador\":',ms_json_int(NEW.contador),',','\"numdoc\":',ms_json_str(NEW.numdoc),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"fecha\":',ms_json_date(NEW.fecha),'}'),
    CONCAT('{','\"contador\":',ms_json_int(NEW.contador),',','\"numdoc\":',ms_json_str(NEW.numdoc),',','\"codigo\":',ms_json_str(NEW.codigo),',','\"cantidad\":',ms_json_num(NEW.cantidad),',','\"precio\":',ms_json_num(NEW.precio),',','\"monto\":',ms_json_num(NEW.monto),',','\"costo_anterior\":',ms_json_num((
        SELECT s.costo
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_promedio_ponderado\":',ms_json_num((
        SELECT s.costopro
        FROM sinv s
        WHERE s.codigo = NEW.codigo
        LIMIT 1
      )),',','\"costo_actual_factura\":',ms_json_num(CASE
          WHEN NEW.cantidad IS NULL OR NEW.cantidad = 0 THEN NEW.precio
          ELSE NEW.monto / NEW.cantidad
        END),',','\"fecha\":',ms_json_date(NEW.fecha),',','\"operador\":',ms_json_str(NEW.operador),',','\"porcentaje\":',ms_json_num(NEW.porcentaje),',','\"fechapc\":',ms_json_date(NEW.fechapc),',','\"numerocaso\":',ms_json_str(NEW.numerocaso),',','\"csaga\":',ms_json_str(NEW.csaga),',','\"factor\":',ms_json_int(NEW.factor),',','\"numcot\":',ms_json_str(NEW.numcot),',','\"numfac\":',ms_json_str(NEW.numfac),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_comprasdbf_ad AFTER DELETE ON comprasdbf FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'comprasdbf',
    'D',
    CONCAT('{','\"contador\":',ms_json_int(OLD.contador),',','\"numdoc\":',ms_json_str(OLD.numdoc),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"fecha\":',ms_json_date(OLD.fecha),'}'),
    CONCAT('{','\"contador\":',ms_json_int(OLD.contador),',','\"numdoc\":',ms_json_str(OLD.numdoc),',','\"codigo\":',ms_json_str(OLD.codigo),',','\"cantidad\":',ms_json_num(OLD.cantidad),',','\"precio\":',ms_json_num(OLD.precio),',','\"monto\":',ms_json_num(OLD.monto),',','\"costo_anterior\":',ms_json_num((
        SELECT s.costo
        FROM sinv s
        WHERE s.codigo = OLD.codigo
        LIMIT 1
      )),',','\"costo_promedio_ponderado\":',ms_json_num((
        SELECT s.costopro
        FROM sinv s
        WHERE s.codigo = OLD.codigo
        LIMIT 1
      )),',','\"costo_actual_factura\":',ms_json_num(CASE
          WHEN OLD.cantidad IS NULL OR OLD.cantidad = 0 THEN OLD.precio
          ELSE OLD.monto / OLD.cantidad
        END),',','\"fecha\":',ms_json_date(OLD.fecha),',','\"operador\":',ms_json_str(OLD.operador),',','\"porcentaje\":',ms_json_num(OLD.porcentaje),',','\"fechapc\":',ms_json_date(OLD.fechapc),',','\"numerocaso\":',ms_json_str(OLD.numerocaso),',','\"csaga\":',ms_json_str(OLD.csaga),',','\"factor\":',ms_json_int(OLD.factor),',','\"numcot\":',ms_json_str(OLD.numcot),',','\"numfac\":',ms_json_str(OLD.numfac),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_detalle_ai AFTER INSERT ON detalle FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'detalle',
    'I',
    CONCAT('{','\"codigo\":',ms_json_str(NEW.codigo),',','\"lote\":',ms_json_str(NEW.lote),',','\"vence\":',ms_json_date(NEW.vence),',','\"cubica\":',ms_json_str(NEW.cubica),'}'),
    CONCAT('{','\"codigo\":',ms_json_str(NEW.codigo),',','\"lote\":',ms_json_str(NEW.lote),',','\"vence\":',ms_json_date(NEW.vence),',','\"cubica\":',ms_json_str(NEW.cubica),',','\"existencia\":',ms_json_num(NEW.existencia),',','\"costo\":',ms_json_num(NEW.costo),',','\"costopro\":',ms_json_num(NEW.costopro),',','\"calidad\":',ms_json_str(NEW.calidad),',','\"elabora\":',ms_json_date(NEW.elabora),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_detalle_au AFTER UPDATE ON detalle FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'detalle',
    'U',
    CONCAT('{','\"codigo\":',ms_json_str(NEW.codigo),',','\"lote\":',ms_json_str(NEW.lote),',','\"vence\":',ms_json_date(NEW.vence),',','\"cubica\":',ms_json_str(NEW.cubica),'}'),
    CONCAT('{','\"codigo\":',ms_json_str(NEW.codigo),',','\"lote\":',ms_json_str(NEW.lote),',','\"vence\":',ms_json_date(NEW.vence),',','\"cubica\":',ms_json_str(NEW.cubica),',','\"existencia\":',ms_json_num(NEW.existencia),',','\"costo\":',ms_json_num(NEW.costo),',','\"costopro\":',ms_json_num(NEW.costopro),',','\"calidad\":',ms_json_str(NEW.calidad),',','\"elabora\":',ms_json_date(NEW.elabora),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_detalle_ad AFTER DELETE ON detalle FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'detalle',
    'D',
    CONCAT('{','\"codigo\":',ms_json_str(OLD.codigo),',','\"lote\":',ms_json_str(OLD.lote),',','\"vence\":',ms_json_date(OLD.vence),',','\"cubica\":',ms_json_str(OLD.cubica),'}'),
    CONCAT('{','\"codigo\":',ms_json_str(OLD.codigo),',','\"lote\":',ms_json_str(OLD.lote),',','\"vence\":',ms_json_date(OLD.vence),',','\"cubica\":',ms_json_str(OLD.cubica),',','\"existencia\":',ms_json_num(0),'}'),
    NOW(3)
  );
END$$
DELIMITER ;

DROP TRIGGER IF EXISTS trg_catego_ai;
DROP TRIGGER IF EXISTS trg_catego_au;
DROP TRIGGER IF EXISTS trg_catego_ad;

DELIMITER $$
CREATE TRIGGER trg_catego_ai AFTER INSERT ON catego FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'catego',
    'I',
    CONCAT('{','\"ccate\":',ms_json_str(NEW.ccate),'}'),
    CONCAT('{','\"ccate\":',ms_json_str(NEW.ccate),',','\"ncate\":',ms_json_str(NEW.ncate),',','\"pganancia\":',ms_json_num(NEW.pganancia),',','\"pdescu\":',ms_json_num(NEW.pdescu),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_catego_au AFTER UPDATE ON catego FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'catego',
    'U',
    CONCAT('{','\"ccate\":',ms_json_str(NEW.ccate),'}'),
    CONCAT('{','\"ccate\":',ms_json_str(NEW.ccate),',','\"ncate\":',ms_json_str(NEW.ncate),',','\"pganancia\":',ms_json_num(NEW.pganancia),',','\"pdescu\":',ms_json_num(NEW.pdescu),'}'),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_catego_ad AFTER DELETE ON catego FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'catego',
    'D',
    CONCAT('{','\"ccate\":',ms_json_str(OLD.ccate),'}'),
    CONCAT('{','\"ccate\":',ms_json_str(OLD.ccate),',','\"ncate\":',ms_json_str(OLD.ncate),',','\"pganancia\":',ms_json_num(OLD.pganancia),',','\"pdescu\":',ms_json_num(OLD.pdescu),'}'),
    NOW(3)
  );
END$$
DELIMITER ;
