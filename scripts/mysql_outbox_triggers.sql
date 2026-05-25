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

DROP TRIGGER IF EXISTS trg_kardex_ai;
DROP TRIGGER IF EXISTS trg_kardex_au;
DROP TRIGGER IF EXISTS trg_kardex_ad;

DROP TRIGGER IF EXISTS trg_kardexd_ai;
DROP TRIGGER IF EXISTS trg_kardexd_au;
DROP TRIGGER IF EXISTS trg_kardexd_ad;

DELIMITER $$
CREATE TRIGGER trg_kardex_ai AFTER INSERT ON kardex FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'kardex',
    'I',
    JSON_OBJECT('indice', NEW.indice),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_kardex_au AFTER UPDATE ON kardex FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'kardex',
    'U',
    JSON_OBJECT('indice', NEW.indice),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_kardex_ad AFTER DELETE ON kardex FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'kardex',
    'D',
    JSON_OBJECT('indice', OLD.indice),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_kardexd_ai AFTER INSERT ON kardexd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'kardexd',
    'I',
    JSON_OBJECT('indice', NEW.indice),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_kardexd_au AFTER UPDATE ON kardexd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'kardexd',
    'U',
    JSON_OBJECT('indice', NEW.indice),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_kardexd_ad AFTER DELETE ON kardexd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'kardexd',
    'D',
    JSON_OBJECT('indice', OLD.indice),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sinv_ai AFTER INSERT ON sinv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sinv',
    'I',
    JSON_OBJECT('id_inv', NEW.id_inv, 'codigo', NEW.codigo),
    JSON_OBJECT(
      'id_inv', NEW.id_inv,
      'codigo', NEW.codigo,
      'descrip', NEW.descrip,
      'barra', NEW.barra,
      'existencia', NEW.existencia,
      'precio1', NEW.precio1,
      'ccate', NEW.ccate,
      'cod_prv', NEW.cod_prv,
      'activo', NEW.activo
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sinv_au AFTER UPDATE ON sinv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sinv',
    'U',
    JSON_OBJECT('id_inv', NEW.id_inv, 'codigo', NEW.codigo),
    JSON_OBJECT(
      'id_inv', NEW.id_inv,
      'codigo', NEW.codigo,
      'descrip', NEW.descrip,
      'barra', NEW.barra,
      'existencia', NEW.existencia,
      'precio1', NEW.precio1,
      'ccate', NEW.ccate,
      'cod_prv', NEW.cod_prv,
      'activo', NEW.activo
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sinv_ad AFTER DELETE ON sinv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sinv',
    'D',
    JSON_OBJECT('id_inv', OLD.id_inv, 'codigo', OLD.codigo),
    JSON_OBJECT(
      'id_inv', OLD.id_inv,
      'codigo', OLD.codigo,
      'descrip', OLD.descrip,
      'barra', OLD.barra,
      'existencia', OLD.existencia,
      'precio1', OLD.precio1,
      'ccate', OLD.ccate,
      'cod_prv', OLD.cod_prv,
      'activo', OLD.activo
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sprv_ai AFTER INSERT ON sprv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sprv',
    'I',
    JSON_OBJECT('id_sprv', NEW.id_sprv, 'cod_prv', NEW.cod_prv),
    JSON_OBJECT(
      'id_sprv', NEW.id_sprv,
      'cod_prv', NEW.cod_prv,
      'nom_prv', NEW.nom_prv,
      'rif_prv', NEW.rif_prv,
      'nit_prv', NEW.nit_prv,
      'dir1_prv', NEW.dir1_prv,
      'tel_prv', NEW.tel_prv,
      'email1_prv', NEW.email1_prv,
      'tipo_prv', NEW.tipo_prv,
      'plazo1', NEW.plazo1,
      'plazo2', NEW.plazo2,
      'plazo3', NEW.plazo3
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sprv_au AFTER UPDATE ON sprv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sprv',
    'U',
    JSON_OBJECT('id_sprv', NEW.id_sprv, 'cod_prv', NEW.cod_prv),
    JSON_OBJECT(
      'id_sprv', NEW.id_sprv,
      'cod_prv', NEW.cod_prv,
      'nom_prv', NEW.nom_prv,
      'rif_prv', NEW.rif_prv,
      'nit_prv', NEW.nit_prv,
      'dir1_prv', NEW.dir1_prv,
      'tel_prv', NEW.tel_prv,
      'email1_prv', NEW.email1_prv,
      'tipo_prv', NEW.tipo_prv,
      'plazo1', NEW.plazo1,
      'plazo2', NEW.plazo2,
      'plazo3', NEW.plazo3
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_sprv_ad AFTER DELETE ON sprv FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'sprv',
    'D',
    JSON_OBJECT('id_sprv', OLD.id_sprv, 'cod_prv', OLD.cod_prv),
    JSON_OBJECT(
      'id_sprv', OLD.id_sprv,
      'cod_prv', OLD.cod_prv,
      'nom_prv', OLD.nom_prv,
      'rif_prv', OLD.rif_prv,
      'nit_prv', OLD.nit_prv,
      'dir1_prv', OLD.dir1_prv,
      'tel_prv', OLD.tel_prv,
      'email1_prv', OLD.email1_prv,
      'tipo_prv', OLD.tipo_prv,
      'plazo1', OLD.plazo1,
      'plazo2', OLD.plazo2,
      'plazo3', OLD.plazo3
    ),
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

DELIMITER $$
CREATE TRIGGER trg_ventas_ai AFTER INSERT ON ventas FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventas',
    'I',
    JSON_OBJECT('numero', NEW.numero),
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
    JSON_OBJECT('numero', NEW.numero),
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
    JSON_OBJECT('numero', OLD.numero),
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
    JSON_OBJECT('numero', NEW.numero, 'codigo', NEW.codigo, 'indice_det', NEW.indice_det),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasd_au AFTER UPDATE ON ventasd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasd',
    'U',
    JSON_OBJECT('numero', NEW.numero, 'codigo', NEW.codigo, 'indice_det', NEW.indice_det),
    NULL,
    NOW(3)
  );
END$$

CREATE TRIGGER trg_ventasd_ad AFTER DELETE ON ventasd FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'ventasd',
    'D',
    JSON_OBJECT('numero', OLD.numero, 'codigo', OLD.codigo, 'indice_det', OLD.indice_det),
    NULL,
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
    JSON_OBJECT('numero', NEW.numero, 'codigo', NEW.codigo),
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
    JSON_OBJECT('numero', NEW.numero, 'codigo', NEW.codigo),
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
    JSON_OBJECT('numero', OLD.numero, 'codigo', OLD.codigo),
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
    JSON_OBJECT('numero', NEW.numero, 'codigo', NEW.codigo),
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
    JSON_OBJECT('numero', NEW.numero, 'codigo', NEW.codigo),
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
    JSON_OBJECT('numero', OLD.numero, 'codigo', OLD.codigo),
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
    JSON_OBJECT(
      'contador', NEW.contador,
      'numdoc', NEW.numdoc,
      'codigo', NEW.codigo,
      'fecha', NEW.fecha
    ),
    JSON_OBJECT(
      'contador', NEW.contador,
      'numdoc', NEW.numdoc,
      'codigo', NEW.codigo,
      'cantidad', NEW.cantidad,
      'precio', NEW.precio,
      'monto', NEW.monto,
      'fecha', NEW.fecha,
      'operador', NEW.operador,
      'porcentaje', NEW.porcentaje,
      'fechapc', NEW.fechapc,
      'numerocaso', NEW.numerocaso,
      'csaga', NEW.csaga,
      'factor', NEW.factor,
      'numcot', NEW.numcot,
      'numfac', NEW.numfac
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_comprasdbf_au AFTER UPDATE ON comprasdbf FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'comprasdbf',
    'U',
    JSON_OBJECT(
      'contador', NEW.contador,
      'numdoc', NEW.numdoc,
      'codigo', NEW.codigo,
      'fecha', NEW.fecha
    ),
    JSON_OBJECT(
      'contador', NEW.contador,
      'numdoc', NEW.numdoc,
      'codigo', NEW.codigo,
      'cantidad', NEW.cantidad,
      'precio', NEW.precio,
      'monto', NEW.monto,
      'fecha', NEW.fecha,
      'operador', NEW.operador,
      'porcentaje', NEW.porcentaje,
      'fechapc', NEW.fechapc,
      'numerocaso', NEW.numerocaso,
      'csaga', NEW.csaga,
      'factor', NEW.factor,
      'numcot', NEW.numcot,
      'numfac', NEW.numfac
    ),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_comprasdbf_ad AFTER DELETE ON comprasdbf FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'comprasdbf',
    'D',
    JSON_OBJECT(
      'contador', OLD.contador,
      'numdoc', OLD.numdoc,
      'codigo', OLD.codigo,
      'fecha', OLD.fecha
    ),
    JSON_OBJECT(
      'contador', OLD.contador,
      'numdoc', OLD.numdoc,
      'codigo', OLD.codigo,
      'cantidad', OLD.cantidad,
      'precio', OLD.precio,
      'monto', OLD.monto,
      'fecha', OLD.fecha,
      'operador', OLD.operador,
      'porcentaje', OLD.porcentaje,
      'fechapc', OLD.fechapc,
      'numerocaso', OLD.numerocaso,
      'csaga', OLD.csaga,
      'factor', OLD.factor,
      'numcot', OLD.numcot,
      'numfac', OLD.numfac
    ),
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
    JSON_OBJECT('ccate', NEW.ccate),
    JSON_OBJECT('ccate', NEW.ccate, 'ncate', NEW.ncate, 'pganancia', NEW.pganancia, 'pdescu', NEW.pdescu),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_catego_au AFTER UPDATE ON catego FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'catego',
    'U',
    JSON_OBJECT('ccate', NEW.ccate),
    JSON_OBJECT('ccate', NEW.ccate, 'ncate', NEW.ncate, 'pganancia', NEW.pganancia, 'pdescu', NEW.pdescu),
    NOW(3)
  );
END$$

CREATE TRIGGER trg_catego_ad AFTER DELETE ON catego FOR EACH ROW
BEGIN
  INSERT INTO sync_outbox(table_name, op, pk_json, row_json, created_at)
  VALUES (
    'catego',
    'D',
    JSON_OBJECT('ccate', OLD.ccate),
    JSON_OBJECT('ccate', OLD.ccate, 'ncate', OLD.ncate, 'pganancia', OLD.pganancia, 'pdescu', OLD.pdescu),
    NOW(3)
  );
END$$
DELIMITER ;
