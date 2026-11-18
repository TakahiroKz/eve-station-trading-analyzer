#!/usr/bin/env bash
# Watchdog de la VM: detecta lo que un ping externo no ve --
# la API responde pero los motores dejaron de correr, o cloudflared está caído. Corre
# en el HOST de la VM por cron cada 10 min (ver scripts/setup_cron.sh). Complementa el
# ping externo (UptimeRobot, ver OPERATIONS.md), que cubre VM entera/túnel/DNS caídos.
#
# Chequea:
#   1. La API responde en HEALTH_URL (el contenedor `api` está vivo).
#   2. `last_evaluated_at` (motor de mercado, ciclo de precios cada 5 min) tiene menos de
#      MARKET_MAX_AGE_MIN minutos (default 15: 3 ciclos perdidos).
#   2b. Cada mercado activo (GET /api/markets) tiene `last_evaluated_at` de menos de
#      MARKET_MAX_AGE_MIN minutos; avisa cuáles se atrasaron (Jita ya está cubierto arriba).
#   3. Hay una corrida reciente del motor de posiciones (mtime del log de hoy,
#      ciclo de 5 min) -- menos de POSITIONS_MAX_AGE_MIN minutos (default 20).
#   4. El servicio systemd `cloudflared` está activo.
#   5. Duración del ciclo de mercado: avisa si hay un ciclo corriendo hace más de
#      MARKET_MAX_RUN_MIN minutos (default 4, para no pisar al siguiente de 5 min; un ciclo de precios normal tarda ~35 s) o si el último
#      que terminó ("Pipeline completo en Ns") tardó más que eso. Salta el chequeo del
#      ciclo en marcha si no hay `docker` (CHECK_CYCLE_RUNTIME=0 lo apaga).
#   6. Histórico diario de mercado: su log (history_*.log) se tocó hace menos de
#      HISTORY_MAX_AGE_HOURS horas (default 36). Si todavía no existe ningún log del
#      histórico (primer día tras instalar el cron), no avisa.
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
MARKETS_URL="${MARKETS_URL:-${HEALTH_URL%/summary}/markets}"
MARKET_MAX_AGE_MIN="${MARKET_MAX_AGE_MIN:-15}"
POSITIONS_MAX_AGE_MIN="${POSITIONS_MAX_AGE_MIN:-20}"
LOG_DIR="${LOG_DIR:-$APP_DIR/logs}"
STATE_FILE="${STATE_FILE:-$APP_DIR/.healthcheck.state}"
CHECK_CLOUDFLARED="${CHECK_CLOUDFLARED:-1}"
MARKET_MAX_RUN_MIN="${MARKET_MAX_RUN_MIN:-4}"
HISTORY_MAX_AGE_HOURS="${HISTORY_MAX_AGE_HOURS:-36}"
CHECK_CYCLE_RUNTIME="${CHECK_CYCLE_RUNTIME:-1}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-$(_env_get TELEGRAM_BOT_TOKEN)}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-$(_env_get TELEGRAM_CHAT_ID)}"

failures=()

# 1 + 2: API viva y motor de mercado fresco.
if ! body="$(curl -fsS --max-time 15 "$HEALTH_URL" 2>/dev/null)"; then
  failures+=("la API no responde en ${HEALTH_URL}")
else
  age_min="$(python3 - "$body" <<'PYEOF'
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
        print(f"{(datetime.now(timezone.utc) - dt).total_seconds() / 60:.1f}")
except Exception:
    print("error")
PYEOF
)"
  case "$age_min" in
    none|error)
      failures+=("no se pudo leer last_evaluated_at de la API") ;;
    *)
      if python3 -c "import sys; sys.exit(0 if float('$age_min') <= float('$MARKET_MAX_AGE_MIN') else 1)"; then :; else
        # Sin la antigüedad exacta en el texto: si cambiara en cada corrida, el anti-spam
        # lo tomaría por un aviso nuevo cada 10 min.
        failures+=("el motor de mercado no corre hace más de ${MARKET_MAX_AGE_MIN} min")
      fi ;;
  esac
fi

# 2b: frescura de cada mercado activo. Si /api/markets no responde se omite (el chequeo 1 ya avisa
# si la API cae); si responde, un mercado activo sin evaluar hace más de MARKET_MAX_AGE_MIN min es falla.
if markets_body="$(curl -fsS --max-time 15 "$MARKETS_URL" 2>/dev/null)"; then
  stale_markets="$(python3 - "$markets_body" "$MARKET_MAX_AGE_MIN" <<'PYEOF'
import json
import sys
from datetime import datetime, timezone

try:
    markets = json.loads(sys.argv[1])
    limit = float(sys.argv[2])
    stale = []
    for market in markets:
        last = market.get("last_evaluated_at")
        if not last:
            stale.append(market["market_id"])
            continue
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - dt).total_seconds() / 60 > limit:
            stale.append(market["market_id"])
    print(",".join(stale))
except Exception:
    print("")
PYEOF
)"
  if [ -n "$stale_markets" ]; then
    # Sin la antigüedad en el texto (anti-spam): solo los mercados atrasados.
    failures+=("mercados sin actualizar hace más de ${MARKET_MAX_AGE_MIN} min: ${stale_markets}")
  fi
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

# 6: histórico diario -- solo si ya hay un log (el cron crea el archivo al empezar cada corrida).
latest_history_log="$(ls -t "$LOG_DIR"/history_*.log 2>/dev/null | head -n1 || true)"
if [ -n "$latest_history_log" ]; then
  stale_history="$(find "$latest_history_log" -mmin +"$(( HISTORY_MAX_AGE_HOURS * 60 ))" 2>/dev/null)"
  if [ -n "$stale_history" ]; then
    failures+=("el histórico diario no corre hace más de ${HISTORY_MAX_AGE_HOURS} h")
  fi
fi

# 4: túnel de Cloudflare.
if [ "$CHECK_CLOUDFLARED" = "1" ] && ! systemctl is-active --quiet cloudflared; then
  failures+=("el servicio cloudflared no está activo")
fi

# 5: duración del ciclo de mercado. Los textos no llevan minutos cambiantes para que el
# anti-spam (más abajo) no los vea como un aviso nuevo en cada corrida del cron.
max_run_s=$(( MARKET_MAX_RUN_MIN * 60 ))
last_duration="$(grep -h "Pipeline completo en" "$(ls -t "$LOG_DIR"/scheduler_*.log 2>/dev/null | head -n1)" 2>/dev/null \
  | tail -n1 | sed -E 's/.*Pipeline completo en ([0-9]+)(\.[0-9]+)?s.*/\1/')"
case "$last_duration" in
  ''|*[!0-9]*) ;;
  *) if [ "$last_duration" -gt "$max_run_s" ]; then
       failures+=("el último ciclo de mercado tardó ${last_duration}s (máx ${max_run_s}s)")
     fi ;;
esac
if [ "$CHECK_CYCLE_RUNTIME" = "1" ] && command -v docker > /dev/null 2>&1; then
  now_s="$(date +%s)"
  for cid in $(docker ps -q --filter "label=com.docker.compose.service=engine-market" 2>/dev/null); do
    started="$(docker inspect -f '{{.State.StartedAt}}' "$cid" 2>/dev/null || true)"
    started_s="$(date -d "$started" +%s 2>/dev/null || echo "")"
    if [ -n "$started_s" ] && [ $(( now_s - started_s )) -gt "$max_run_s" ]; then
      failures+=("un ciclo de mercado lleva más de ${MARKET_MAX_RUN_MIN} min corriendo")
    fi
  done
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
