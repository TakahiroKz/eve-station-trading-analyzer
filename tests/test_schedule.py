from datetime import datetime, timezone

from ingestion.schedule import _get_next_run_times_cron, _next_clock_boundary


def test_next_clock_boundary_rounds_up_to_next_5_minute_mark():
    now = datetime(2026, 9, 22, 19, 47, 30, tzinfo=timezone.utc)
    assert _next_clock_boundary(now, 5) == datetime(2026, 9, 22, 19, 50, tzinfo=timezone.utc)


def test_next_clock_boundary_rounds_up_to_next_4_hour_mark():
    now = datetime(2026, 9, 22, 19, 47, 30, tzinfo=timezone.utc)
    assert _next_clock_boundary(now, 4 * 60) == datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)


def test_next_clock_boundary_crosses_day_boundary():
    now = datetime(2026, 9, 22, 23, 5, 0, tzinfo=timezone.utc)
    assert _next_clock_boundary(now, 4 * 60) == datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)


def test_next_clock_boundary_exactly_on_a_boundary_still_advances():
    """A las 20:00:00 en punto, el próximo disparo de */4 es a las 00:00, no ahora mismo
    -- cron no vuelve a disparar en el mismo minuto en que ya disparó."""
    now = datetime(2026, 9, 22, 20, 0, 0, tzinfo=timezone.utc)
    assert _next_clock_boundary(now, 4 * 60) == datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)


def test_get_next_run_times_cron_returns_both_as_iso_strings():
    result = _get_next_run_times_cron()
    assert result["market_next_run"] is not None
    assert result["positions_next_run"] is not None
    # No debe tirar -- confirma que son ISO 8601 parseables.
    datetime.fromisoformat(result["market_next_run"])
    datetime.fromisoformat(result["positions_next_run"])
