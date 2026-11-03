"""Calcula cuándo corre cada motor la próxima vez.

Windows (dev local): se pregunta directo al Programador de Tareas
(scripts/setup_task_scheduler.ps1 registra EveMarketScreener_Pipeline/-Positions) en
vez de derivarlo de datos propios de la app, porque el trigger de esa tarea es
relativo a CUÁNDO se registró (`-Once -At (Get-Date)`), no a una hora fija del reloj
— un refresco manual de "Mis Órdenes" no mueve el próximo disparo real, así que
estimarlo desde actividad de la app daría un valor incorrecto ahí.

Linux (VM de producción, scripts/setup_cron.sh): a diferencia de Windows, el cron que
instala ese script SÍ está anclado a límites fijos del reloj (`0 */4 * * *`, `*/5 * * *
*`) — no depende de cuándo se instaló el crontab. Eso permite calcularlo con
aritmética pura, sin depender de ningún comando externo (cron no tiene un
equivalente directo a Get-ScheduledTaskInfo consultable fácilmente desde Python).

Degrada sin bloquear (devuelve None) si powershell falla o las tareas de Windows
todavía no están registradas.
"""
import json
import logging
import platform
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_PS_SCRIPT = (
    "$market = (Get-ScheduledTaskInfo -TaskName 'EveMarketScreener_Pipeline' "
    "-ErrorAction SilentlyContinue).NextRunTime; "
    "$positions = (Get-ScheduledTaskInfo -TaskName 'EveMarketScreener_Positions' "
    "-ErrorAction SilentlyContinue).NextRunTime; "
    "[PSCustomObject]@{ "
    "market = if ($market) { $market.ToString('o') } else { $null }; "
    "positions = if ($positions) { $positions.ToString('o') } else { $null } "
    "} | ConvertTo-Json -Compress"
)

_MARKET_INTERVAL_MINUTES = 4 * 60
_POSITIONS_INTERVAL_MINUTES = 5


def _next_clock_boundary(now: datetime, interval_minutes: int) -> datetime:
    """Próximo múltiplo de `interval_minutes` alineado al reloj (no a `now` mismo) --
    1970-01-01T00:00:00Z ya es un límite válido para cualquier divisor de 60 (minutos)
    o de 24h (horas), así que los minutos-desde-epoch alcanzan sin tocar zona horaria."""
    epoch_minutes = int(now.timestamp() // 60)
    next_boundary = (epoch_minutes // interval_minutes + 1) * interval_minutes
    return datetime.fromtimestamp(next_boundary * 60, tz=timezone.utc)


def _get_next_run_times_windows() -> dict[str, str | None]:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
            capture_output=True, text=True, timeout=10, check=True,
        )
        data = json.loads(result.stdout)
        return {"market_next_run": data.get("market"), "positions_next_run": data.get("positions")}
    except Exception:
        logger.exception("Fallo al consultar el Programador de Tareas de Windows")
        return {"market_next_run": None, "positions_next_run": None}


def _get_next_run_times_cron() -> dict[str, str | None]:
    now = datetime.now(timezone.utc)
    return {
        "market_next_run": _next_clock_boundary(now, _MARKET_INTERVAL_MINUTES).isoformat(),
        "positions_next_run": _next_clock_boundary(now, _POSITIONS_INTERVAL_MINUTES).isoformat(),
    }


def get_next_run_times() -> dict[str, str | None]:
    if platform.system() == "Windows":
        return _get_next_run_times_windows()
    return _get_next_run_times_cron()
