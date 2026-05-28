-- Tablas transaccionales mínimas (outbox + simulate_*). Sin datos.
-- Catálogo: resumen/catego.sql, sprv.sql, sinv.sql, lotes/detalle.sql

SET NAMES utf8;
SET FOREIGN_KEY_CHECKS=0;

DROP TABLE IF EXISTS `comprasdbf`;
CREATE TABLE `comprasdbf` (
  `codigo` varchar(15) DEFAULT '',
  `cantidad` int(11) DEFAULT NULL,
  `precio` decimal(25,2) DEFAULT NULL,
  `monto` decimal(25,2) DEFAULT NULL,
  `fecha` date DEFAULT NULL,
  `numdoc` varchar(6) DEFAULT NULL,
  `operador` varchar(15) DEFAULT NULL,
  `porcentaje` decimal(25,2) DEFAULT '0.00',
  `fechapc` date DEFAULT NULL,
  `numerocaso` varchar(10) DEFAULT '',
  `csaga` varchar(6) DEFAULT '',
  `factor` int(10) NOT NULL DEFAULT '1',
  `contador` int(20) NOT NULL DEFAULT '0',
  `numcot` varchar(10) DEFAULT '',
  `numfac` varchar(10) DEFAULT NULL
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `kardex`;
CREATE TABLE `kardex` (
  `codigo` varchar(15) DEFAULT NULL,
  `fecha` date DEFAULT NULL,
  `existenciai` decimal(25,2) DEFAULT '0.00',
  `entradas` decimal(25,2) DEFAULT '0.00',
  `salidas` decimal(25,2) DEFAULT '0.00',
  `existenciaf` decimal(25,2) DEFAULT '0.00',
  `ajustesn` decimal(25,2) DEFAULT '0.00',
  `ajustesp` decimal(25,2) DEFAULT '0.00',
  `compras` decimal(25,2) DEFAULT '0.00',
  `ventas` decimal(25,2) DEFAULT '0.00',
  `devoc` decimal(25,2) DEFAULT '0.00',
  `devov` decimal(25,2) DEFAULT '0.00',
  `costo` decimal(25,2) DEFAULT '0.00',
  `costopro` decimal(25,6) DEFAULT '0.000000',
  `kobs` text NOT NULL,
  `indice` int(20) NOT NULL AUTO_INCREMENT,
  `cajero` varchar(10) NOT NULL DEFAULT '',
  `numero` varchar(15) NOT NULL DEFAULT '',
  `contador` int(20) DEFAULT NULL,
  `codigop` varchar(15) DEFAULT '',
  `sincronizado` varchar(1) DEFAULT 'N',
  `hora` varchar(10) DEFAULT '',
  `cod_cli` varchar(15) DEFAULT '',
  `costodiv` decimal(25,6) DEFAULT '0.000000',
  `costoprodiv` decimal(25,6) DEFAULT '0.000000',
  PRIMARY KEY (`indice`),
  KEY `codigo` (`codigo`),
  KEY `fecha` (`fecha`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `kardexd`;
CREATE TABLE `kardexd` (
  `codigo` varchar(15) DEFAULT NULL,
  `fecha` date DEFAULT NULL,
  `existenciai` decimal(25,2) DEFAULT '0.00',
  `entradas` decimal(25,2) DEFAULT '0.00',
  `salidas` decimal(25,2) DEFAULT '0.00',
  `existenciaf` decimal(25,2) DEFAULT '0.00',
  `ajustesn` decimal(25,2) DEFAULT '0.00',
  `ajustesp` decimal(25,2) DEFAULT '0.00',
  `compras` decimal(25,2) DEFAULT '0.00',
  `ventas` decimal(25,2) DEFAULT '0.00',
  `devoc` decimal(25,2) DEFAULT '0.00',
  `devov` decimal(25,2) DEFAULT '0.00',
  `costo` decimal(25,2) DEFAULT '0.00',
  `costopro` decimal(25,6) DEFAULT '0.000000',
  `kobs` text NOT NULL,
  `indice` int(20) NOT NULL AUTO_INCREMENT,
  `cajero` varchar(10) NOT NULL DEFAULT '',
  `numero` varchar(15) NOT NULL DEFAULT '',
  `contador` int(20) DEFAULT NULL,
  `cubica` varchar(10) DEFAULT NULL,
  PRIMARY KEY (`indice`),
  KEY `codigo` (`codigo`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

DROP TABLE IF EXISTS `ventas`;
CREATE TABLE `ventas` (
  `numero` varchar(15) DEFAULT NULL,
  `cod_cli` varchar(30) DEFAULT '',
  `fecha` date DEFAULT NULL,
  `subtotal` decimal(25,2) DEFAULT NULL,
  `total` decimal(25,2) DEFAULT NULL,
  `hora` varchar(15) DEFAULT NULL,
  KEY `numero` (`numero`),
  KEY `fecha` (`fecha`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `ventasd`;
CREATE TABLE `ventasd` (
  `numero` varchar(15) DEFAULT NULL,
  `codigo` varchar(15) DEFAULT NULL,
  `cantidad` decimal(25,2) DEFAULT NULL,
  `precio` decimal(25,2) DEFAULT NULL,
  `monto` decimal(25,2) DEFAULT NULL,
  KEY `numero` (`numero`),
  KEY `codigo` (`codigo`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `ventasi`;
CREATE TABLE `ventasi` (
  `numero` varchar(15) DEFAULT NULL,
  `codigo` varchar(15) DEFAULT NULL,
  `cantidad` decimal(25,2) DEFAULT NULL,
  `precio` decimal(25,2) DEFAULT NULL,
  `monto` decimal(25,2) DEFAULT NULL,
  `contador` int(20) NOT NULL DEFAULT '0',
  KEY `numero` (`numero`),
  KEY `codigo` (`codigo`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `factura`;
CREATE TABLE `factura` (
  `numero` varchar(15) DEFAULT NULL,
  `cod_prv` varchar(30) DEFAULT '',
  `fecha` date DEFAULT NULL,
  `total` decimal(25,2) DEFAULT NULL,
  KEY `numero` (`numero`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

DROP TABLE IF EXISTS `facturad`;
CREATE TABLE `facturad` (
  `numero` varchar(15) DEFAULT NULL,
  `codigo` varchar(15) DEFAULT NULL,
  `cantidad` decimal(25,2) DEFAULT NULL,
  `precio` decimal(25,2) DEFAULT NULL,
  KEY `numero` (`numero`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1;

SET FOREIGN_KEY_CHECKS=1;
