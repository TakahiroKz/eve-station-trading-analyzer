"""Cuándo avisar por Telegram de un cambio de tendencia de precio.

Reglas (aprobadas): solo para ítems en los que el usuario tiene una orden activa, solo con
suficiente actividad (promedio de operaciones/día), y solo cuando la misma señal (sube o baja)
se confirma en dos lecturas diarias consecutivas del histórico del mercado. Después de avisar,
no se repite el aviso hasta pasados unos días de enfriamiento y solo si es una racha nueva.

La lectura es "diaria" porque el histórico de la ESI se publica una vez al día: la fecha de
lectura es la última fecha del histórico del mercado, no la hora de cada ciclo de 5 minutos.
"""
from dataclasses import dataclass
from datetime import date

ACTIVE_LABELS = {"up", "down"}
CONFIRMATION_DAYS = 1       # la señal debe llevar al menos 1 día más que su primera lectura
MAX_GAP_DAYS = 3            # si faltan más días entre lecturas, la racha se reinicia
COOLDOWN_DAYS = 3           # días mínimos entre dos avisos del mismo ítem y mercado


@dataclass
class TrendAlertState:
    label: str
    since_date: str          # primera lectura de la racha actual
    last_date: str           # última lectura vista
    alerted_since: str | None = None   # `since_date` de la racha por la que ya se avisó
    last_alerted_date: str | None = None


def _days(later: str, earlier: str) -> int:
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def advance(prev: TrendAlertState | None, label: str, reading_date: str) -> tuple[TrendAlertState, bool]:
    """Actualiza el estado con la lectura de `reading_date` (YYYY-MM-DD) y dice si toca avisar."""
    if prev is None or prev.label != label or _days(reading_date, prev.last_date) > MAX_GAP_DAYS:
        state = TrendAlertState(
            label=label, since_date=reading_date, last_date=reading_date,
            alerted_since=prev.alerted_since if prev else None,
            last_alerted_date=prev.last_alerted_date if prev else None,
        )
    else:
        state = TrendAlertState(
            label=prev.label, since_date=prev.since_date, last_date=max(prev.last_date, reading_date),
            alerted_since=prev.alerted_since, last_alerted_date=prev.last_alerted_date,
        )

    confirmed = label in ACTIVE_LABELS and _days(reading_date, state.since_date) >= CONFIRMATION_DAYS
    new_streak = state.alerted_since != state.since_date
    cooled = state.last_alerted_date is None or _days(reading_date, state.last_alerted_date) >= COOLDOWN_DAYS
    should_alert = confirmed and new_streak and cooled
    if should_alert:
        state.alerted_since = state.since_date
        state.last_alerted_date = reading_date
    return state, should_alert
