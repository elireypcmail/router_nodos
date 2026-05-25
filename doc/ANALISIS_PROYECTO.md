# Análisis del proyecto (carpeta raíz: `nodos`)

## 1) Qué contiene la raíz

En la raíz `/Users/wilsonpernia/Desktop/nodos` se ven estos elementos principales:

- **`arquitectura/`**: es el proyecto real (código + infraestructura + documentación) para un sistema **hub-spoke** (hub en VPS + nodos en tiendas) basado en:
  - **Hub**: NestJS + MySQL + WireGuard + Nginx
  - **Nodo (tienda)**: FastAPI/uvicorn (Python) detrás de una VPN WireGuard
- **`multishop_db_schema.md`**: documento de referencia del **catálogo de tablas** (356 tablas) restauradas en el entorno local.
- **`catego.json`**: definición/descripción de columnas para la tabla **`catego`**.
- **`backup_seguro.sql.gz.enc`**: backup cifrado (no analizado por ser binario/cifrado).
- **`Multishop-nodo-API/`**: solo contiene `.git` (sin código dentro en el estado actual).

## 2) Objetivo del sistema (visión de alto nivel)

El sistema implementa un patrón **hub-and-spoke**:

- **Hub (servidor central)** expone una **API pública** para terceros (partners) por Internet (`/api/v1/*`).
- El **hub** agrega/consulta información de múltiples **nodos (tiendas)** a través de una **red privada WireGuard** (IPs `10.66.0.x`).
- Cada **nodo** publica una API HTTP(S) **solo accesible desde el hub** por la VPN.

### 2.1 Propósito del proyecto y meta clave (según el diagrama)

La captura (`Captura de pantalla 2026-05-21 a la(s) 12.10.01 a.m..png`) describe el **estado objetivo** del proyecto: un sistema **distribuido, on-premise / edge**, para operación **multitienda** (tipo ERP/POS/inventario) donde cada sucursal puede operar **100% local** (sin depender de Internet), pero manteniendo **consistencia de datos maestros** mediante un flujo de **sincronización/replicación orquestado**.

- **Meta clave**
  - Asegurar que las sucursales sigan operando aunque “se caiga” Internet.
  - Centralizar la administración de datos maestros (catálogos) y propagar cambios hacia todas las tiendas de forma controlada, auditable y eventualmente consistente.

### 2.2 Topología en estrella (hub-and-spoke) y red privada (VPN)

En el estado objetivo, la comunicación entre componentes sigue una **topología en estrella**:

- **Núcleo (hub)**
  - El servidor central con **API NestJS** actúa como punto único de coordinación.
  - Inicia/gestiona la comunicación hacia cada tienda.

- **Satélites (spokes)**
  - Las tiendas locales (por ejemplo: **Táriba**, **San Cristóbal**, **La Fría**) son nodos satélite.
  - No existe comunicación directa “tienda a tienda” (no es malla/mesh). Toda orquestación y despacho de operaciones pasa por el hub.

En esta topología:

- **Táriba** mantiene lógica adicional tipo “Master” (Python/API local y DB local), pero **sigue siendo** un nodo conectado al hub.
- **San Cristóbal** y **La Fría** operan como nodos esclavos (satélites) con su operación local, recibiendo cambios orquestados.

#### VPN (WireGuard / Tailscale) como capa de direccionamiento estable

Para evitar depender de IP pública fija en cada tienda (que puede ser dinámica), se utiliza una **VPN** que provee:

- **IP privada fija por nodo** dentro del túnel (ej. `10.0.0.X` o `10.66.0.X`).
- **Canal cifrado** entre el hub y cada nodo.
- Simplificación del ruteo: el hub siempre puede apuntar a la IP privada del nodo para consumir su API.

Esto reemplaza el problema de “¿cuál es la IP pública actual de la tienda?” por “la tienda siempre vive en la VPN con una IP estable”.

### 2.3 Segmentación del VPS / servidor central (zona pública vs zona privada)

El servidor central (VPS o servidor on-prem del hub) se divide conceptualmente en dos zonas:

- **Zona pública (expuesta a Internet)**
  - Para que la **app web admin** y/o clientes externos consuman la API pública del hub.
  - En la implementación actual, esto se expresa como:
    - Nginx expone `/api/v1/*` por `:443`.
    - Nest escucha en `127.0.0.1:3000` (recomendado en producción) y Nginx hace reverse proxy.

- **Zona privada (solo red VPN)**
  - Canal exclusivo y cifrado por donde el hub se comunica con las **APIs de los nodos**.
  - Los nodos deben exponer sus endpoints únicamente dentro de la VPN (y idealmente con firewall permitiendo solo el hub).
  - La autenticación de aplicación (por ejemplo, API key/Bearer token) complementa la seguridad del túnel.

En otras palabras: Internet solo “ve” el hub (API pública). Los nodos y sus bases de datos permanecen aislados detrás del túnel VPN.

#### Componentes que aparecen en el diagrama

- **App web admin**
  - Panel desde el cual un administrador gestiona datos maestros.

- **Servidor (Orquestador) — API NestJS**
  - Recibe acciones administrativas.
  - Consulta una **tabla de IP de nodos** (descubrimiento/ruteo hacia nodos aunque cambien IPs).
  - Orquesta la distribución de actualizaciones hacia los nodos.
  - En el diagrama, persiste estado global en **`Db - postgress`** (PostgreSQL) con:
    - categorías
    - productos
    - tabla de IP de nodos

- **Nodo 1 (Táriba) — Master regional**
  - Tiene:
    - `api del nodo python`
    - `db-mysql`
    - `Desktop app - nodo1 Tariba` (operación local)
  - Rol: primer receptor de cambios y punto de referencia regional.

- **Nodo 2 (San Cristóbal) — Esclavo**
  - Tiene `db` y `api del nodo`.
  - Destaca un mecanismo de **colas FIFO** para aplicar actualizaciones en orden (evitar condiciones de carrera / sobrescrituras por orden incorrecto).
  - Incluye autenticación por **api key** y un mecanismo para **actualizar IP pública**.

- **Nodo 3 (La Fría) — Esclavo**
  - Tiene `db` y `api del nodo`.

#### Datos maestros que se buscan replicar (según notas del diagrama)

- categorías
- proveedores
- “catego del proveedor”
- componentes activos
- códigos alternos

Y para el caso específico de categorías se listan atributos típicos:

- categorías
- código
- porcentaje de descuento
- porcentaje de ganancia
- nombre

#### Flujo objetivo de replicación (cambio → propagación)

- **Origen del cambio**
  - Un administrador crea/actualiza un dato maestro (por ejemplo: porcentaje de descuento, proveedor, categoría).

- **Registro y orquestación**
  - La API de NestJS persiste el cambio en la BD central (en el diagrama: PostgreSQL) y consulta la “tabla de IPs de nodos” para determinar a qué direcciones enviar.

- **Distribución punto a punto (P2P)**
  - El orquestador empuja el payload directamente a las APIs locales de cada nodo.

- **Aplicación local**
  - Cada nodo aplica el cambio en su BD local.
  - En el caso de Nodo 2 (San Cristóbal), el objetivo es aplicar por **FIFO** para mantener el orden de eventos.

#### Nota de alineación con el código actual del repositorio

En el código actual dentro de `arquitectura/` se observa un enfoque hub-spoke con **NestJS + MySQL** en el hub (docker MySQL 5.6) y un **nodo FastAPI** con endpoints stub. El diagrama, en cambio, plantea como meta una BD central en **PostgreSQL** y un modelo “master/esclavos” con colas FIFO en al menos un nodo. Puede interpretarse como:

- El repositorio actual es un **MVP** (provisioning + VPN + consulta agregada) orientado a “conectividad/control” entre hub y nodos.
- El diagrama representa el **target** (replicación completa de datos maestros y operación descentralizada robusta).

En el estado actual, el caso de uso implementado es:

- **Inventario agregado**: el hub consulta a cada nodo por VPN, agrega resultados y los retorna al cliente de Internet.

## 3) Estructura de `arquitectura/`

Dentro de `arquitectura/`:

- **`docker-compose.yml`**: levanta MySQL 5.6 para desarrollo.
- **`docs/`**: documentación operativa (dev, prod, api pública, red privada).
- **`infra/`**: piezas de infraestructura (Nginx, TLS interno, WireGuard scripts).
- **`servidor/`**: el hub (NestJS/TypeScript).
- **`nodo/`**: el nodo de tienda (FastAPI/Python).

## 3.1) Documentación (`arquitectura/docs`) — qué cubre y qué no

La carpeta `arquitectura/docs/` contiene documentación orientada a operación y puesta en marcha del MVP:

- **`docs/README.md`**
  - Índice de guías (dev/prod/api pública/red privada).

- **`docs/desarrollo.md`**
  - Flujo de desarrollo local “sin VPS” (Nest + nodo + MySQL con Docker).
  - Explica cómo simular el entorno sin VPN usando `NODO_USE_HTTP=true` en el hub y `NODO_VPN_IP=127.0.0.1` en el nodo.
  - Describe el flujo E2E mínimo:
    - levantar MySQL
    - levantar Nest
    - levantar nodo FastAPI
    - `POST /provisioning/nodos`
    - `POST /orchestration/nodos/:id/ping`
    - `GET /api/v1/inventario`

- **`docs/api-publica.md`**
  - Contrato del prefijo **`/api/v1`** y separación clara entre:
    - API pública (partners) con `PUBLIC_API_KEY`
    - API interna (admin) con `INTERNAL_API_KEY`
  - Documenta el flujo de inventario agregado:
    - Cliente Internet → Nginx :443 → Nest 127.0.0.1:3000 → VPN → nodos :8443

- **`docs/red-privada.md`**
  - Define explícitamente la red **hub-spoke** por WireGuard con IPs fijas `10.66.0.x`.
  - Describe el flujo de alta (provisioning) y troubleshooting.

- **`docs/produccion-vps.md`**
  - Es una guía extensa de hardening y despliegue en VPS:
    - firewall (443/51820, no exponer 3000/3306)
    - Nest detrás de Nginx
    - WireGuard hub
    - TLS interno con CA
    - systemd para Nest

### ¿La documentación cumple con lo que hemos analizado del proyecto?

**Sí, para el alcance MVP actual del repositorio**: lo documentado es consistente con la arquitectura que ya existe en código:

- Topología **en estrella** (hub-spoke): hub llama a nodos por VPN.
- Segmentación “pública vs privada”:
  - público: Nginx 443 → `/api/v1/*`
  - privado: hub → VPN → APIs de nodos
- VPN resuelve IP pública dinámica: las tiendas quedan con IP fija `10.66.0.x`.
- Separación de audiencias y llaves: `PUBLIC_API_KEY` vs `INTERNAL_API_KEY`.

**No cubre aún (porque el código tampoco lo implementa) la meta final de replicación completa de datos maestros** que planteaste en el diagrama:

- Replicación/orquestación de catálogos (categorías/proveedores/productos/...) como flujo robusto.
- Estrategia de idempotencia, versionado de eventos, reintentos.
- FIFO/colas persistentes en nodos esclavos.

En resumen: `docs/` está muy bien alineado con la implementación actual y el “cómo operar el MVP”, pero todavía no es la documentación del “ERP multitienda replicado” completo.

## 3.2) Infraestructura (`arquitectura/infra`) — componentes

La carpeta `arquitectura/infra/` agrupa los componentes de infraestructura que hacen viable el despliegue hub-spoke seguro.

### 3.2.1 Nginx (`infra/nginx`)

- **`infra/nginx/multishop-api.conf.example`**
  - Expone **solo** `/api/v1/` hacia `http://127.0.0.1:3000`.
  - Bloquea `/provisioning`, `/orchestration`, `/nodos` desde Internet (404).
  - Incluye `limit_req` (rate limiting) para la API pública.

### 3.2.2 WireGuard (`infra/wireguard`)

- **`infra/wireguard/README.md`** define:
  - hub con IP fija `10.66.0.1`
  - nodos con `10.66.0.x` y túnel saliente
  - advertencia clave: **Nest debe correr donde exista la interfaz `wg0`** (si corre en Docker bridge no verá la red, salvo `network_mode: host` o sidecar).

- **`infra/wireguard/add-peer.sh`**
  - Añade peer al hub y persiste un archivo por nodo en `peers.d/`.
  - Valida que la IP esté en `10.66.0.0/24`.

- **`infra/wireguard/remove-peer.sh`**
  - Remueve peer por IP VPN o por public key.
  - Limpia el archivo persistido del peer cuando aplica.

### 3.2.3 TLS interno (`infra/tls`)

- Scripts para operar una **CA interna** y emitir certificados por IP VPN:
  - `generate-ca.sh`
  - `generate-node-cert.sh <10.66.0.x>` (incluye SAN `IP:<vpnIp>`)
- Esto permite:
  - Nodo sirviendo HTTPS con cert propio
  - Hub validando con `TLS_CA_FILE` y `NODO_TLS_REJECT_UNAUTHORIZED=true`


## 4) Base de datos (MySQL)

### 4.1 Docker compose

`arquitectura/docker-compose.yml` define:

- **Imagen**: `mysql:5.6`
- **Container**: `mysql56-app`
- **Puerto**: `127.0.0.1:3306:3306` (correcto para **no** exponer MySQL a Internet)
- **Root password**: `multishop`

### 4.2 `multishop_db_schema.md` (referencia)

Este archivo no es un schema SQL “ejecutable”; es una **guía de contexto** del entorno local:

- Base: `mi_base_restaurada`
- Tablas: **356**
- Organizadas por módulos sugeridos: inventario/productos, ventas, bancos, clientes/usuarios, auditoría/configuración, etc.

Esto sirve como mapa conceptual para:

- Identificar tablas fuente de inventario/maestros.
- Planificar sincronizaciones desde tiendas al hub.

### 4.3 `catego.json`

Describe la tabla `catego` (no confundir con `categoria`). Incluye columnas y reglas de negocio implícitas:

- **Obligatorias desde request**: `ccate` (código único), `ncate`.
- **Porcentajes**: `pganancia`, `pdescu` (0..100 según descripción).
- **Campos por default DB (no enviar)**: `odescu`, `pcomision`, `pcomision2`, `pcomision3`, `incluirSincSiclhos`, `conteotf`, `controldc`, etc.
- **PK/ID**: `id_catego` autoincremental.

Relevancia: encaja con el endpoint stub `GET /api/sync/categorias` del nodo (sincronización futura de categorías).

## 5) Componente `nodo/` (tienda) — Python/FastAPI

### 5.1 Entry point

- **`nodo/main.py`** crea un `FastAPI()` y registra routers:
  - `health`
  - `inventario`
  - `sync`
- Ejecuta con `uvicorn.run(...)`.
- Soporta TLS con:
  - `NODO_SSL_CERTFILE`
  - `NODO_SSL_KEYFILE`
- Bloquea HTTP sin TLS si `NODO_ALLOW_INSECURE=false`.

Archivo legacy:

- **`nodo/api.py`** es un wrapper legacy que solo llama `run()`.

### 5.2 Configuración

- **`nodo/config.py`** usa `pydantic-settings` con `.env`:
  - `nodo_id`, `nodo_nombre`, `nodo_api_token`
  - `nodo_vpn_ip`
  - `nodo_host`, `nodo_port`
  - `nodo_ssl_certfile`, `nodo_ssl_keyfile`
  - `nodo_allow_insecure`

### 5.3 Seguridad del nodo

- Middleware `verify_bearer` en `nodo/middleware/auth.py`:
  - Requiere header `Authorization: Bearer <token>`.
  - Compara con `settings.nodo_api_token`.
  - Respuestas:
    - `401` si no hay Bearer
    - `403` si token inválido

### 5.4 Endpoints del nodo

- **`GET /`** (sin auth en el código actual) retorna `{service, nodo_id}`.
- **`GET /api/health`** (con Bearer) retorna estado y metadata.
- **`GET /api/inventario?search=`** (con Bearer) retorna un catálogo **stub** `_CATALOGO_STUB` filtrable.
- **`GET /api/sync/categorias`** (con Bearer) stub, retorna `items: []`.
- **`GET /api/sync/status`** (con Bearer) stub.

### 5.5 Dependencias

`nodo/requirements.txt`:

- `fastapi`, `uvicorn[standard]`, `python-dotenv`, `pydantic-settings`

### 5.6 Instalación en tienda

Scripts:

- `nodo/scripts/install-linux.sh`:
  - Requiere `wg` instalado.
  - Copia `wg0.conf` a `/etc/wireguard/wg0.conf`.
  - Levanta `wg0`.
  - Copia `.env` del bundle al nodo.
  - Crea venv e instala `requirements.txt`.
- `nodo/scripts/install-windows.ps1`:
  - Instruye importar `wg0.conf` en WireGuard GUI.
  - Crea venv e instala requirements.

## 6) Componente `servidor/` (hub) — NestJS

### 6.1 Entry point y configuración global

- `src/main.ts`:
  - `ValidationPipe` global (`whitelist`, `transform`).
  - `listen(port, bindHost)` desde `ConfigService`.

- `src/config/configuration.ts` (fuente de verdad de variables):
  - **DB**: `DATABASE_*`
  - **API pública**: `PUBLIC_API_KEY` (lista separada por comas)
  - **API interna**: `INTERNAL_API_KEY`
  - **WireGuard**: `WG_*`, subnet/ipStart
  - **Nodo API**:
    - `NODO_API_PORT`
    - `NODO_TLS_REJECT_UNAUTHORIZED`
    - `TLS_CA_FILE`

### 6.2 Módulos Nest

`src/app.module.ts` importa:

- `NodosModule`
- `VpnModule`
- `ProvisioningModule`
- `OrchestrationModule`
- `PublicApiModule`

Con TypeORM:

- Conecta a MySQL.
- Registra `NodoEntity`.
- `synchronize` controlado por `DATABASE_SYNC`.

### 6.3 Modelo de datos del hub

`NodoEntity` (`servidor/src/nodos/entities/nodo.entity.ts`):

- `id` UUID
- `nombre`
- `vpnIp` (único)
- `wgPublicKey`, `wgPrivateKey` (private select: false)
- `apiToken` (token Bearer para llamar al nodo)
- `estado`: `pendiente | activo | offline`
- `ultimoHealthAt`
- timestamps `createdAt/updatedAt`

### 6.4 Autenticación/Autorización en Nest

- **Interna (admin)**: `InternalApiKeyGuard`
  - Header: `x-internal-api-key`
  - Variable: `INTERNAL_API_KEY`
  - Protege: `/nodos`, `/provisioning`, `/orchestration`

- **Pública (partners)**: `PartnerApiKeyGuard`
  - Header: `Authorization: Bearer ...` o `x-api-key`
  - Variable: `PUBLIC_API_KEY` (una o varias)
  - Protege endpoints de negocio bajo `/api/v1/*`

### 6.5 HTTP hacia nodos (hub → tiendas)

`NodosHttpService`:

- Construye base URL con `NodosService.buildApiBaseUrl()`:
  - `https://<vpnIp>:<port>` por defecto
  - `http://...` si `NODO_USE_HTTP=true` (desarrollo)
- Endpoints hacia nodo:
  - `GET /api/health`
  - `GET /api/inventario`
  - `GET /api/sync/categorias`
- TLS:
  - Si `NODO_TLS_REJECT_UNAUTHORIZED=false`, desactiva validación.
  - Si `TLS_CA_FILE` está definido, carga CA para confiar en certificados internos.

Además actualiza estado:

- Si health ok: `ACTIVO` + `ultimoHealthAt`.
- Si falla: `OFFLINE`.

### 6.6 API interna de administración

- `POST /provisioning/nodos` (ver docs; implementado en `ProvisioningService`):
  - Genera par de claves WireGuard.
  - Asigna IP VPN libre.
  - Genera token API.
  - Persiste nodo en DB.
  - Ejecuta script `add-peer.sh`.
  - Devuelve bundle con:
    - `wireguardConfig` (wg0.conf para tienda)
    - `envFile` (variables para nodo)

- `POST /orchestration/nodos/:id/ping`
- `POST /orchestration/nodos/:id/sync` (stub de persistencia)
- `POST /orchestration/nodos/ping-all`
- `GET /orchestration/nodos/:id/info`

### 6.7 API pública v1

Documentada en `docs/api-publica.md`.

- `GET /api/v1` (sin auth) devuelve metadatos.
- `GET /api/v1/inventario?search=` (con PartnerApiKeyGuard)
  - Agrega inventarios consultando a cada nodo por VPN.
  - Devuelve:
    - métricas `consultados/exitosos/fallidos`
    - resultados por nodo
    - `items` aplanados con `_nodo` y `_vpnIp`

## 7) Infraestructura `infra/`

### 7.1 Nginx

`infra/nginx/multishop-api.conf.example`:

- Expone **solo** `/api/v1/` hacia Nest en `127.0.0.1:3000`.
- Bloquea `/provisioning`, `/orchestration`, `/nodos` desde Internet retornando 404.

### 7.2 WireGuard

`infra/wireguard/`:

- Scripts `add-peer.sh` y `remove-peer.sh`.
- Plantilla `hub.wg0.conf.example`.
- Nota clave: **Nest debe correr en un host que vea la interfaz `wg0`** (en docs recomiendan correr Nest en el host o `network_mode: host`).

### 7.3 TLS interno

`infra/tls/`:

- `generate-ca.sh` crea CA.
- `generate-node-cert.sh <vpnIp>` crea cert por IP VPN.
- Nest usa `TLS_CA_FILE`.
- Nodo usa `NODO_SSL_CERTFILE`/`NODO_SSL_KEYFILE`.

## 8) Documentación (`docs/`)

La carpeta `arquitectura/docs/` es bastante completa para operación:

- `desarrollo.md`: setup local.
- `produccion-vps.md`: guía exhaustiva de hardening/despliegue.
- `api-publica.md`: contrato y flujo de API pública.
- `red-privada.md`: explicación técnica de la VPN y troubleshooting.

## 9) Flujo E2E resumido (inventario)

1. Cliente externo llama:
   - `GET /api/v1/inventario?search=...`
   - Auth con `PUBLIC_API_KEY`.
2. Nginx (443) proxya a Nest (3000 localhost).
3. Nest lista nodos desde MySQL.
4. Nest consulta a cada nodo por VPN:
   - `GET https://10.66.0.x:8443/api/inventario?search=...`
   - Auth con `Authorization: Bearer <apiToken>` (token por nodo almacenado en DB).
5. Nest agrega y responde.

## 10) Observaciones y riesgos (técnicos / operativos)

- **Nodos stub**: inventario y sync están en modo stub; falta integración real con BD local de tienda.
- **Exposición del root endpoint del nodo**: `GET /` no tiene auth en el código actual. No es grave si el nodo solo es accesible por VPN y firewall, pero conviene tratarlo como superficie adicional.
- **TypeORM synchronize**:
  - En producción debe ser `DATABASE_SYNC=false` (la doc ya lo remarca).
- **Ejecución de scripts WG**:
  - `add-peer.sh/remove-peer.sh` suelen requerir privilegios; la doc propone `sudoers` acotado.
- **Multishop-nodo-API vacío**:
  - Hay una carpeta con `.git` sin contenido. Puede ser submódulo incompleto o placeholder.

## 11) Próximos pasos recomendados (si tu meta es pasar de MVP a “real”)

- **Inventario real**:
  - Definir fuente de datos en tienda (MySQL local / servicio existente).
  - Implementar `/api/inventario` consultando tablas reales (probablemente `sinv`, `categoria`, etc., según `multishop_db_schema.md`).

- **Sync categorías**:
  - Implementar `/api/sync/categorias` en nodo para extraer `catego`/`categoria`.
  - Implementar persistencia en hub (en `/orchestration/nodos/:id/sync` hoy es stub).

- **Modelo de dominio en hub**:
  - Hoy el hub solo almacena `nodos` (registro/provisioning/estado).
  - Falta decidir si el hub persistirá catálogos agregados o solo “passthrough”.

- **Seguridad**:
  - Asegurar que el nodo no escuche en interfaces no necesarias (solo `wg0` si aplica).
  - En producción: TLS interno obligatorio y `NODO_ALLOW_INSECURE=false`.

---

## Estado del análisis

- Se analizó el contenido de la carpeta raíz `nodos`, especialmente `arquitectura/`, `catego.json` y `multishop_db_schema.md`.
- Se generó este reporte como `ANALISIS_PROYECTO.md` en la raíz del proyecto.
