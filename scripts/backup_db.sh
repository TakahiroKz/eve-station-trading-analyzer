#!/usr/bin/env bash
# Backup diario de storage/market.db a Oracle Object Storage vía Pre-Authenticated
# Request (PAR) -- D10 en DEUDA_TECNICA.md. Corre en el HOST de la VM (no en un
# contenedor), disparado por cron -- ver OPERATIONS.md para cómo se armó el bucket/PAR
# y la Lifecycle Policy que borra objetos de más de 60 días (la retención NO la
# maneja este script, la maneja Oracle del lado del bucket).
#
# Usa sqlite3.Connection.backup() de Python (misma Online Backup API de SQLite que
# el CLI `sqlite3 .backup`, toma una foto consistente aunque el motor de mercado/
# posiciones esté escribiendo en simultáneo) en vez de un simple `cp`, que podría
# capturar el archivo a mitad de una escritura y quedar corrupto. Se eligió Python
# sobre el CLI `sqlite3` porque la VM ya lo tiene (no hace falta instalar nada nuevo
# en el host para esto).
#
# Requiere ORACLE_BACKUP_PAR_URL en .env: la URL de una Pre-Authenticated Request de
# tipo "Bucket" con "Permit object writes" (no de lectura -- si la URL se filtrara,
# solo permite sobrescribir/subir objetos, no leer los backups existentes),
# terminada en "/o/" tal como la muestra Oracle al crearla.
#
# Uso: ./scripts/backup_db.sh   (desde ~/app en la VM, vía cron)

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# .env lo escribe/lee normalmente python-dotenv, que tolera valores como
# "eve-market-screener (contacto: ...)" -- no es sintaxis válida de bash, así que NO
# se puede hacer `source .env` acá (revienta con "syntax error near unexpected token
# '('"). Se leen solo las claves puntuales que hacen falta, línea por línea.
_env_get() {
  [ -f .env ] || return 0
  grep -m1 "^${1}=" .env | cut -d '=' -f2-
}

ORACLE_BACKUP_PAR_URL="$(_env_get ORACLE_BACKUP_PAR_URL)"
DB_PATH="$(_env_get DB_PATH)"
TELEGRAM_BOT_TOKEN="$(_env_get TELEGRAM_BOT_TOKEN)"
TELEGRAM_CHAT_ID="$(_env_get TELEGRAM_CHAT_ID)"

if [ -z "${ORACLE_BACKUP_PAR_URL:-}" ]; then
  echo "ORACLE_BACKUP_PAR_URL no está configurado en .env -- backup salteado." >&2
  exit 1
fi

DB_PATH="${DB_PATH:-./storage/market.db}"
DATE="$(date -u +%Y-%m-%d)"
TMP_BACKUP="/tmp/market-${DATE}.db"
TMP_GZ="${TMP_BACKUP}.gz"

cleanup() { rm -f "$TMP_BACKUP" "$TMP_GZ"; }
trap cleanup EXIT

python3 - "$DB_PATH" "$TMP_BACKUP" <<'PYEOF'
import sqlite3
import sys

src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close()
dst.close()
PYEOF

gzip -f "$TMP_BACKUP"

if ! curl -fsS -X PUT --data-binary "@${TMP_GZ}" "${ORACLE_BACKUP_PAR_URL}market-${DATE}.db.gz"; then
  echo "Falló la subida del backup del ${DATE} a Oracle Object Storage." >&2
  # Aviso por Telegram si está configurado -- un backup fallido en silencio no sirve
  # de nada (ver D11 en DEUDA_TECNICA.md, monitoreo continuo, todavía sin resolver).
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      -d "text=⚠️ Falló el backup diario de market.db (${DATE}) a Oracle Object Storage." \
      > /dev/null || true
  fi
  exit 1
fi

echo "Backup del ${DATE} subido correctamente ($(du -h "$TMP_GZ" | cut -f1))."
