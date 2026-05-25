---
description: Actualiza doc.md con cambios recientes
---

Este workflow mantiene `doc.md` actualizado con una sección de **Cambios recientes** basada en el estado actual del repo.

## Objetivo
- Insertar o actualizar una sección en `doc.md` llamada `## Cambios recientes`.
- La sección debe resumir:
  - Archivos modificados (tracked) y su intención.
  - Archivos nuevos (untracked) relevantes.
  - Cambios funcionales destacados (config/env, workers, endpoints, instaladores).

## Pasos

1) Inspeccionar estado del repo
// turbo
- Ejecuta:
  - `git status --porcelain`
  - `git diff --stat`
  - `git diff`

2) Identificar archivos nuevos (untracked)
// turbo
- Ejecuta:
  - `git ls-files --others --exclude-standard`

3) Obtener diffs de untracked (si aplica)

Para cada archivo untracked relevante (por ejemplo `huey_app.py`, `huey_tasks.py`, `scripts/*`, `config.py`, `requirements.txt`, `main.py`):
// turbo
- Ejecuta:
  - `git diff --no-index /dev/null <ruta-del-archivo>`

4) Actualizar `doc.md`

- Si `doc.md` ya contiene el header `## Cambios recientes`, reemplaza solo el contenido de esa sección (hasta el próximo `## ...`).
- Si no existe, inserta `## Cambios recientes` cerca del inicio (después del primer bloque de introducción).

Formato recomendado dentro de la sección:
- Fecha/hora local.
- Lista de cambios por área:
  - API/Sync
  - Outbox
  - Huey
  - Instaladores
  - Configuración (.env)

Reglas:
- No modificar otras secciones.
- No agregar/eliminar comentarios en código.
- Mantener el texto en español.
