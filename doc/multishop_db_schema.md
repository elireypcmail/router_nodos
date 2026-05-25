# Esquema de Base de Datos - Multishop Local
Este archivo sirve como referencia de contexto para **Windsurf / Copilot / Cursor**. Contiene el catálogo completo de las 356 tablas restauradas en el entorno local de desarrollo (`mysql56-app`) bajo la base de datos `mi_base_restaurada`.

## Información de Conexión Local
- **Motor:** MySQL 5.6 (Docker Container: `mysql56-app`)
- **Host:** `localhost` o `127.0.0.1`
- **Puerto:** `3306`
- **Base de Datos Principal:** `mi_base_restaurada`
- **Usuario:** `root`
- **Password:** `multishop`

---

## Diccionario de Tablas (Clasificadas por Módulos Sugeridos)

### 📦 Inventario y Productos (`sinv`, `kardex`, `ajustes`)
Tablas encargadas de la gestión de stock, códigos alternos, descripciones físicas y control de almacenes.
- `ajuste`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `ajustes`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `categoria`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `cierre_inv`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `cierre_inv_det`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `cl_despacho_inv`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `cl_despacho_inv_det`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `invdef`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `invxdepositos`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `kardex`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `kardexd`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `linea`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `marca`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `ofertainv`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `pinventario`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `rinv`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `rinvcomp`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `scategoria`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `scomoinv`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinv`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinv_09032023`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinv_original`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinvaf`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinvbin`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinvimg`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinvimgp`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.
- `sinvxdep`: Control de inventarios, variantes de artículos, movimientos o cierres de stock.

### 🛒 Ventas, Facturación y Puntos de Venta (`ventas`, `factura`, `pv`)
- `arqueopv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `auditoriapv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `auditorpv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `cajeropv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `diariov`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `diariovi`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `dventas`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `dventasd`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `dventasi`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `factura`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `facturad`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ncndventa`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `parametropv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `pinventario`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `puntosdeventa`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `sservpv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `tickets`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `tipooppv`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ventas`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ventasd`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ventasds`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ventasi`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ventasl`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `ventasm`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `vventas`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `vventasd`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.
- `vventasi`: Registro de transacciones de ventas, detalles de facturas, comandas e impresiones fiscales.

### 🏦 Bancos, Cuentas y Movimientos Financieros (`cuentasb`, `banco`)
- `banco`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `bancossitef`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cheques`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `chequescxp`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `conciliab`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `conciliaboa`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `conciliaboanc`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasb`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbdet`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbmov`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbmov_ccadi`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbmova`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbmovitf`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbmovnc`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasbmovt`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `cuentasdifer`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `gasto`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `gasto2024`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.
- `mpvbanco`: Control de cajas virtuales, movimientos bancarios, conciliaciones y egresos.

### 👥 Clientes, Proveedores y Usuarios (`scli`, `sprv`, `usuario`)
- `departuser`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `mesonero`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `scli`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `scli_aux`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `sprv`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `sprvcdp`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `users`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `usuario`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `usuarioi`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).
- `usuariou`: Entidades del sistema (Clientes, Proveedores, Usuarios internos, Roles y Accesos).

### 🔒 Auditoría, Parámetros y Configuración General
- `auditor`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditorc`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditorcompras`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditorconrec`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoria_confirmacion`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoria_igtf`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoria_parametro`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoria_visorp`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoriag`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoriaif`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoriapv`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditoriav`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditorpv`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `auditorscli`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `controles`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `controlpf`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `controlpfl`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `controlplan`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `datasis`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `empresa`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `error`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `moneda`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `monedas`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `parametro`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `parametroc`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `parametroc2024`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.
- `parametropv`: Logs de auditoría, tasas de cambio de monedas (IGTF/USD), configuraciones globales y trazas de error.

### 🧩 Otras Tablas del Sistema (Estructura Multishop Unificada)
Lista alfabética completa de las 356 tablas mapeadas en la base de datos:

`acaba`, `actualizacion`, `additionalinterfaces`, `adr_exp`, `aivapad`, `aivapai`, `aivared`, `aivarei`, `ajuste`, `ajuste_scom`, `ajustei`, `ajusteila`, `ajustela`, `ajustepe`, `ajustepei`, `ajustepes`, `ajustes`, `amortizacion`, `ancho`, `anuladas`, `anuladasd`, `anuladasi`, `arqueopv`, `asientodivp`, `asientos`, `asientos2024`, `asientosa`, `asientosdbf`, `asientost`, `asignacion`, `asignacioni`, `auditor`, `auditorc`, `auditorcompras`, `auditorconrec`, `auditoria_confirmacion`, `auditoria_igtf`, `auditoria_parametro`, `auditoria_visorp`, `auditoriag`, `auditoriaif`, `auditoriapv`, `audutoriaus`, `auditoriav`, `auditorpv`, `auditorscli`, `auxiliar`, `auxiliar_uni`, `banco`, `bancossitef`, `bandas`, `cajavirtual`, `cajero`, `cajeropv`, `calculocant`, `calternos`, `calternos_original`, `cancelaop`, `caract`, `cashea`, `catalogoe`, `catalogoed`, `catalogoei`, `catego`, `catego_cli`, `catego_prv`, `categoaf`, `categoria`, `cfiscal`, `cheques`, `chequescxp`, `cierre`, `cierre_inv`, `cierre_inv_det`, `cierrecajavirtual`, `cierrecontab`, `cierrelcv`, `cl_articulo_act_vw`, `cl_consumo_devolucion`, `cl_despacho_inv`, `cl_despacho_inv_det`, `cl_det_consumo_devolucion`, `comandav`, `compo`, `comprasdbf`, `compuesto`, `concepto`, `conciliab`, `conciliaboa`, `conciliaboanc`, `consumos`, `consumosi`, `controles`, `controlpf`, `controlpfl`, `controlplan`, `correlativo`, `correo`, `costousd`, `cotiza`, `cotizai`, `cuentasb`, `cuentasbdet`, `cuentasbmov`, `cuentasbmov_ccadi`, `cuentasbmova`, `cuentasbmovitf`, `cuentasbmovnc`, `cuentasbmovt`, `cuentasdifer`, `datacaja`, `datacajacz`, `datacajafi`, `datacorreo`, `dataidigital`, `dataidigitalnf`, `datasis`, `datasis2024`, `datasis_unificado`, `dataws`, `datawsa`, `depart_amort`, `departaf`, `departuser`, `depo`, `depositos`, `depositoscxp`, `depreciacionaf`, `depreciacionamort`, `descriptores`, `detalle`, `detallecxc`, `detallee`, `detallei`, `detallepr`, `detalleprr`, `detalleu`, `device`, `devices`, `diarioiva`, `diariov`, `diariov_18102023`, `diariovi`, `diariovi_18102023`, `difxdepositos`, `dscom`, `dscomd`, `dscst`, `dventas`, `dventasd`, `dventasi`, `empresa`, `entrada`, `eprograma`, `eprogramar`, `error`, `especialista`, `especialista_catego`, `especialista_mov`, `etiqueta`, `extraccion0`, `extraccion1`, `extraccion2`, `extraccion3`, `extraccion4`, `extracciong`, `factura`, `facturad`, `flujodecaja`, `formulad`, `frecauda`, `gasto`, `gasto2024`, `general`, `historialasigaf`, `historialasigamort`, `historialbandas`, `historialbfc`, `historialc`, `historialcrm`, `historialfallas`, `historialfc`, `historialp`, `iefectivo`, `ietabla`, `ietabla_ccadi`, `ietablacxp`, `invdef`, `invxdepositos`, `ivapa`, `ivare`, `ivaret`, `kardex`, `kardexd`, `kardexd_25082023`, `linea`, `mapa`, `marca`, `marcar_sincronizados_siclhos`, `medidacomprobchq`, `medidascomprobextra`, `mesonero`, `messages`, `moneda`, `monedaomfc`, `monedas`, `monedasd`, `monedasigtf`, `motivo`, `motivoretaf`, `movements`, `mpvbanco`, `multimedia`, `ncndventa`, `notae`, `notaei`, `obligacion`, `obligacion_ccadi`, `obligacion_ccadid`, `obligaciond`, `observa`, `oferta`, `ofertai`, `ofertainv`, `ofertar`, `orden`, `ordenc`, `ordenci`, `ordencr`, `ordencri`, `ordencs`, `ordencsi`, `ordene`, `ordenei`, `ordeni`, `ordenp`, `ordenpi`, `oservicio`, `oservicioi`, `pactivo`, `parametro`, `parametroc`, `parametroc2024`, `parametropv`, `patolo`, `pedidostbe`, `pedidosws`, `pedidoswse`, `periodoamortizado`, `periododepreciadoaf`, `peso`, `pinventario`, `plan`, `plancontable`, `preciosi`, `productopp`, `productoppc`, `puntosdeventa`, `puntovt`, `rcontabef`, `rcontabef1`, `recolector`, `registropd`, `remotos`, `resultadoes`, `retefuente`, `retencion`, `retencion_islr`, `retiroaf`, `revisiondepos`, `rinv`, `rinvcomp`, `rr2021`, `rscom`, `rscom_old`, `rscomd`, `rscomd_old`, `rscst`, `rscst_old`, `salidas`, `scategoria`, `scli`, `scli_aux`, `scom`, `scomd`, `scomoinv`, `scst`, `semanario`, `seniates`, `servicios`, `servidor`, `sicopadi_recibido`, `sicopadi_rubro`, `sinv`, `sinv_09032023`, `sinv_original`, `sinvaf`, `sinvbin`, `sinvimg`, `sinvimgp`, `sinvxdep`, `smov`, `smultiple`, `sprm`, `sprmco`, `sprv`, `sprvcdp`, `ssal`, `ssald`, `sservpv`, `svend`, `tarjetas`, `tejido`, `temporalc`, `temporali`, `tickets`, `tipo`, `tipooppv`, `tomafisica`, `tomafisicaa`, `tomafisicaaf`, `transferencia`, `transferenciadet`, `traslado`, `trasladob`, `trasladobi`, `trasladobl`, `trasladobli`, `trasladog`, `turno`, `turno_old`, `turns`, `ubica`, `ubicaaf`, `ubicacion`, `ucma`, `unidad`, `unidadn`, `users`, `usuario`, `usuarioi`, `usuariou`, `ventas`, `ventasd`, `ventasds`, `ventasi`, `ventasl`, `ventasm`, `vmd`, `vpagositef`, `vpsitef`, `vueltositef`, `vventas`, `vventasd`, `vventasi`, `zona`
