#!/usr/bin/env bash
# Watchdog de la VM (D11 en DEUDA_TECNICA.md): detecta lo que un ping externo no ve --
# la API responde pero los motores dejaron de correr, o cloudflared está caído. Corre
# en el HOST de la VM por cron cada 10 min (ver scripts/setup_cron.sh). Complementa el
# ping externo (UptimeRobot, ver OPERATIONS.md), que cubre VM entera/túnel/DNS caídos.
#
# Chequea:
#   1. La API responde en HEALTH_URL (el contenedor `api` está vivo).
#   2. `last_evaluated_at` (motor de mercado, ciclo de 4h) tiene menos de
#      MARKET_MAX_AGE_HOURS horas (default 5: 4h de ciclo + margen).
#   3. Hay una corrida reciente del motor de posiciones (mtime del log de hoy,
#      ciclo de 5 min) -- menos de POSITIONS_MAX_AGE_MIN minutos (default 20).
#   4. El servicio systemd `cloudflared` está activo.
#
# Anti-spam: guarda el último estado en STATE_FILE y avisa por Telegram solo cuando
# cambia (OK -> falla, cambia el motivo, o falla -> recuperado), no en cada corrida.
#
# Lee .env línea por línea como backup_db.sh (no se puede `source`: tiene valores que
# no son sintaxis válida de bash). Todo es sobreescribible por variable de entorno
# para poder probarlo sin la VM.
#
# Uso: ./scripts/healthcheck.sh   (desde ~/app en la VM, vía cron)

set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

_env_get() {
  [ -f .env ] || return 0
  grep -m1 "^${1}=" .env | cut -d '=' -f2-
}

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8001/api/summary}"
MARKET_MAX_AGE_HOURS="${MARKET_MAX_AGE_HOURS:-5}"
POSITIONS_MAX_AGE_MIN="${POSITIONS_MAX_AGE_MIN:-20}"
LOG_DIR="${LOG_DIR:-$APP_DIR/logs}"
STATE_FILE="${STATE_FILE:-$APP_DIR/.healthcheck.state}"
CHECK_CLOUDFLARED="${CHECK_CLOUDFLARED:-1}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(_env_get TELEGRAM_BOT_TOKEN)}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-$(_env_get TELEGRAM_CHAT_ID)}"

failures=()

# 1 + 2: API viva y motor de mercado fresco.
if ! body="$(curl -fsS --max-time 15 "$HEALTH_URL" 2>/dev/null)"; then
  failures+=("la API no responde en ${HEALTH_URL}")
else
  age_h="$(python3 - "$body" <<'PYEOF'
import json
import sys
from datetime import datetime, timezone

try:
    last = json.loads(sys.argv[1]).get("last_evaluated_at")
    if not last:
        print("none")
    else:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        print(f"{(datetime.now(timezone.utc) - dt).total_seconds() / 3600:.1f}")
except Exception:
    print("error")
PYEOF
)"
  case "$age_h" in
    none|error)
      failures+=("no se pudo leer last_evaluated_at de la API") ;;
    *)
      if python3 -c "import sys; sys.exit(0 if float('$age_h') <= float('$MARKET_MAX_AGE_HOURS') else 1)"; then :; else
        failures+=("el motor de mercado no corre hace ${age_h}h (máx ${MARKET_MAX_AGE_HOURS}h)")
      fi ;;
  esac
fi

# 3: motor de posiciones -- cada corrida (haya o no órdenes) escribe al log del día.
latest_orders_log="$(ls -t "$LOG_DIR"/orders_*.log 2>/dev/null | head -n1 || true)"
if [ -z "$latest_orders_log" ]; then
  failures+=("no hay logs del motor de posiciones en ${LOG_DIR}")
else
  stale="$(find "$latest_orders_log" -mmin +"$POSITIONS_MAX_AGE_MIN" 2>/dev/null)"
  if [ -n "$stale" ]; then
    failures+=("el motor de posiciones no corre hace más de ${POSITIONS_MAX_AGE_MIN} min")
  fi
fi

# 4: túnel de Cloudflare.
if [ "$CHECK_CLOUDFLARED" = "1" ] && ! systemctl is-active --quiet cloudflared; then
  failures+=("el servicio cloudflared no está activo")
fi

if [ ${#failures[@]} -eq 0 ]; then
  current="OK"
else
  current="$(printf '%s; ' "${failures[@]}")"
fi

previous="$(cat "$STATE_FILE" 2>/dev/null || echo "OK")"
echo "$current" > "$STATE_FILE"

notify() {
  echo "$1"
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    # El token va por stdin (--config -) y no en la línea de comandos, que `ps` muestra.
    curl -fsS -X POST --config - \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=$1" > /dev/null <<EOF || true
url = "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
EOF
  fi
}

if [ "$current" = "$previous" ]; then
  exit 0
fi

if [ "$current" = "OK" ]; then
  notify "✅ EveMarket: todo volvió a la normalidad."
  exit 0
fi

notify "🚨 EveMarket: ${current}"
exit 1
