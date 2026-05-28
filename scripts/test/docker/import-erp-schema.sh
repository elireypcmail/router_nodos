#!/usr/bin/env bash
# Redirige al import del backup completo (reemplaza el esquema mínimo resumen/).
exec "$(dirname "$0")/import-backup-to-tiendas.sh" "$@"
