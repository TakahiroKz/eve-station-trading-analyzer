"""Calendario de publicación del histórico diario de la ESI (lo usan el scheduler, la API y los avisos).

La ESI publica el día D-1 a las 11:05 UTC (no antes), así que a cualquier hora previa el último día disponible es D-2: ver el
histórico un día por detrás durante la madrugada UTC es lo normal, no un hueco. Un hueco real es que lo guardado sea
anterior a lo que la ESI ya debe tener (`expected_date`).
"""
from datetime import date, datetime, time, timedelta, timezone

HISTORY_PUBLISH_UTC = (11, 15)    # la ESI publica a las 11:05 UTC; margen de 10 min
_ESI_PUBLISH_AT = time(11, 5)


def expected_date(now: datetime | None = None) -> date:
    """Último día de histórico que la ESI ya debe tener publicado: ayer (UTC) desde las 11:15, y anteayer antes de esa hora
    (así las corridas nocturnas del cron no repiten trabajo inútil)."""
    now = now or datetime.now(timezone.utc)
    published = (now.hour, now.minute) >= HISTORY_PUBLISH_UTC
    return now.date() - timedelta(days=1 if published else 2)


def history_info(latest: str | None, now: datetime | None = None) -> dict:
    """Estado del histórico de un mercado para mostrarlo: último día guardado, el siguiente y cuándo lo publica la ESI.
    `late` solo es verdadero si falta un día que la ESI ya debía haber publicado (hay que reintentar o investigar)."""
    now = now or datetime.now(timezone.utc)
    expected = expected_date(now)
    try:
        latest_day = date.fromisoformat(latest) if latest else None
    except ValueError:
        latest_day = None
    next_day = (latest_day or expected) + timedelta(days=1)
    publish_at = datetime.combine(next_day + timedelta(days=1), _ESI_PUBLISH_AT, tzinfo=timezone.utc)
    return {"latest_date": latest_day.isoformat() if latest_day else None, "expected_date": expected.isoformat(),
            "next_date": next_day.isoformat(), "next_publish_at": publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "late": latest_day is None or latest_day < expected}
