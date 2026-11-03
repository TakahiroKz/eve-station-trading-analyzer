#!/usr/bin/env bash
# Instala (o reemplaza) las corridas programadas en el crontab del usuario —
# equivalente Linux de scripts/setup_task_scheduler.ps1 (Windows). Corre en la VM,
# no en la máquina de desarrollo.
#
# Motor de mercado (scheduler/run.py) cada 4h, motor de posiciones
# (scheduler/orders_run.py) cada 5 min — mismos dos motores, misma cadencia que en
# Windows, pero disparando contenedores de un solo uso (`docker compose run --rm`)
# en vez de invocar python directo. Más el backup diario de la DB (D10, scripts/
# backup_db.sh) a las 03:17 UTC — fuera de los :00 en punto para no coincidir con el
# arranque del motor de mercado.
#
# `flock -n` reemplaza el MultipleInstances=IgnoreNew de la tarea de Windows: si una
# corrida anterior sigue activa cuando toca la siguiente, esta se salta en vez de
# superponerse (evita dos procesos escribiendo la misma SQLite a la vez).
#
# Uso: ./scripts/setup_cron.sh   (desde ~/app en la VM, después de `git pull`)

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$APP_DIR/logs"

CRON_BLOCK=$(cat <<'CRONEOF'
# evemarket-screener: motor de mercado, cada 4h
0 */4 * * * cd __APP_DIR__ && flock -n .market.lock docker compose --profile cron run --rm engine-market >> logs/scheduler_$(date +\%Y-\%m-\%d).log 2>&1
# evemarket-screener: motor de posiciones, cada 5 min
*/5 * * * * cd __APP_DIR__ && flock -n .positions.lock docker compose --profile cron run --rm engine-positions >> logs/orders_$(date +\%Y-\%m-\%d).log 2>&1
# evemarket-screener: backup diario de la DB (D10)
17 3 * * * cd __APP_DIR__ && flock -n .backup.lock ./scripts/backup_db.sh >> logs/backup_$(date +\%Y-\%m-\%d).log 2>&1
# evemarket-screener: watchdog de salud (D11), cada 10 min
*/10 * * * * cd __APP_DIR__ && flock -n .healthcheck.lock ./scripts/healthcheck.sh >> logs/healthcheck_$(date +\%Y-\%m-\%d).log 2>&1
CRONEOF
)
CRON_BLOCK="${CRON_BLOCK//__APP_DIR__/$APP_DIR}"

# Saca cualquier entrada previa de evemarket-screener (reinstalación idempotente),
# preserva el resto del crontab del usuario si tuviera otras cosas. `|| true` en el
# grep: con set -e, un crontab vacío/inexistente hace que grep sin coincidencias
# (exit 1, "nada que filtrar") aborte el script antes de llegar a escribir el nuevo
# -- pasó en la práctica en la VM recién creada, sin crontab previo.
{ crontab -l 2>/dev/null | grep -vE "evemarket-screener|engine-market|engine-positions|backup_db|healthcheck" || true; echo "$CRON_BLOCK"; } | crontab -

echo "Crontab instalado:"
crontab -l
