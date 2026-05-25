Plan de trabajo para completar al 100% el proyecto de nodos (Python) + migración a Multishop-node-API
Ya armé un plan en el tablero (ver TODOs). Con tu decisión de modelo híbrido (push + pull), el nodo “completo” quedaría orientado a resiliencia: recibe cambios cuando hay conectividad, y puede “ponerse al día” cuando vuelve.

## Nota de acoplamiento (IMPORTANTE)

El proyecto del nodo Python **debe acoplarse** a los contratos del orquestador y del nodo guía provistos por el otro desarrollador:

- **Orquestador guía**: `multishop-hub/` (Nest)
- **Nodo guía**: `nodo/` (FastAPI)

Estos dos proyectos son **solo referencia** y **no se editan**. Por tanto, el “100%” del nodo Python incluye un **compat layer** para igualar:

- **Paths** y **payloads** esperados por el hub.
- **Autenticación**: `Authorization: Bearer <apiToken del nodo>` (no `x-internal-api-key`) para comunicación hub⇄nodo.

### Contratos detectados en la guía (para implementar en Multishop-nodo-API)

- **Health** (hub → nodo):
  - `GET /api/health` con `Authorization: Bearer <nodo.apiToken>`

- **Inventario** (hub → nodo):
  - `GET /api/inventario?search=...` con `Authorization: Bearer <nodo.apiToken>`

- **Sync push (hub → nodo)**:
  - `POST /api/sync/events`
  - Body: `{ "entity_type": "inventory_category" | "provider" | ..., "payload": { ... } }`
  - Auth: `Authorization: Bearer <nodo.apiToken>`
  - Nota: en la guía existe compatibilidad legacy `POST /api/sync/categorias` que delega al handler genérico.

- **Sync pull inicial de categorías (hub → nodo, pero disparado por hub)**:
  - `POST /api/sync/categorias/pull` (hub le pide al nodo ejecutar pull paginado)
  - El nodo pagina al hub en:
    - `GET <HUB_BASE_URL>/api/nodo/sync/categorias?page=1&limit=100`
    - Auth: `Authorization: Bearer <nodo.apiToken>`

- **Nodo → hub (crear categoría en hub)**:
  - `POST <HUB_BASE_URL>/api/nodo/categorias`
  - Auth: `Authorization: Bearer <nodo.apiToken>`
  - (El hub guarda y encola la entrega al resto de nodos.)

Plan (milestones)
1) Definir alcance de “100% completado” (en progreso)
Roles:
Nodo Master (Táriba): aplica cambios y puede tener lógica adicional (p.ej. validaciones/reglas/transformaciones).
Nodos Esclavos (San Cristóbal / La Fría): aplican cambios recibidos; San Cristóbal con FIFO obligatorio.
Sync híbrido:
Push: el hub envía eventos/cambios al endpoint del nodo.
Pull: el nodo consulta al hub por eventos faltantes (catch-up por rango de secuencia/offset).
Catálogos a sincronizar (mínimo viable de maestros):
Categorías (catego/categoria), Proveedores (sprv), Productos (sinv), Alternos (calternos), Marcas/Líneas (marca, linea).
Requisitos de operación:
Solo VPN + TLS interno en prod.
Auth por token + idempotencia (no duplicar eventos).
Estado/observabilidad (/api/sync/status, últimos eventos aplicados, cola, errores).
2) Migración de código
Todo lo de arquitectura/nodo se moverá a Multishop-node-API/ y ahí quedará el proyecto “oficial”.
Definir qué pasa con arquitectura/nodo:
Opción A (recomendada): dejarlo como wrapper/nota deprecada apuntando al nuevo path.
Opción B: eliminarlo si ya no se usará.
3) Persistencia local real (reemplazar stubs)
Conexión a BD local del nodo (MySQL).
Reemplazar:
/api/inventario (de stub a query real)
/api/sync/categorias (de stub a extracción real si aplica)
Estructura recomendada:
db/ (pool/engine)
repositories/ + services/
4) Motor de sincronización (núcleo del objetivo)
Modelo de eventos:
event_id, entity, action, payload, sequence, created_at
Idempotencia:
tabla local de applied_events o sync_state (last_applied_sequence)
FIFO persistente (para esclavos):
cola en BD local (tabla sync_queue) con worker secuencial
Endpoints mínimos del nodo:
POST /api/sync/events (push del hub, contrato guía)
POST /api/sync/categorias/pull (pull inicial de categorías, contrato guía)
Pull/catch-up (nodo→hub): implementar cliente configurable que respete el contrato guía cuando exista (paginado o por secuencia, según defina el hub).
GET /api/sync/status
Reintentos + manejo de errores (dead-letter / retries)

Compatibilidad requerida:
- Mantener (si aplica) `POST /api/sync/categorias` como alias legacy hacia `/api/sync/events` con `entity_type=inventory_category`.
- Mantener (si aplica) `GET /api/sync/categorias` como export local de categorías (para diagnóstico/consulta del hub).
5) Hardening + entrega
Config prod/dev clara (.env.example actualizado en el nuevo repo).
TLS obligatorio en producción.
Reglas firewall recomendadas (solo 10.66.0.1 hacia 8443).
Tests mínimos (health, apply idempotente, orden FIFO, catch-up).
Documentación de instalación/operación.

Checklist de acoplamiento final (antes de declarar 100%):
- El nodo responde a los paths esperados por `multishop-hub` (`/api/health`, `/api/inventario`, `/api/sync/events`, `/api/sync/categorias/pull`).
- El nodo usa `Authorization: Bearer <nodo_api_token>` para requests hacia el hub (`/api/nodo/*`).
- Los cambios de DB en el nodo (outbox/triggers/migraciones) se aplican desde instaladores (Linux/Windows).
Confirmación necesaria antes de mover archivos
Tu petición dice: “migrarlo a la carpeta Multishop-node-API”.

En la raíz existe Multishop-nodo-API/ (con .git) pero no veo Multishop-node-API/ (en el listado anterior).
Antes de ejecutar la migración necesito que me confirmes:

¿El destino correcto es Multishop-nodo-API/ (con “nodo”) o quieres crear una carpeta nueva Multishop-node-API/ (con “node”)?
Si es la segunda, también dime si ese repo debería tener su propio .git o si lo manejas como parte del monorepo.
Estado
Plan creado y listo.
Pendiente tu confirmación del path destino exacto para ejecutar la migración.