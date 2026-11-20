"""opportunity_log: un ítem se registra como mucho una vez por intervalo, el log se purga por
antigüedad y no vuelve a crecer una fila por ítem y por ciclo (llegó a 1,5 GB de los 2 GB de la base)."""
from datetime import datetime, timedelta, timezone

import pytest

from scheduler.run import opportunity_log_due, screen_opportunities
from storage.db import (
    _first_opportunity_id_since,
    get_connection,
    init_db,
    insert_opportunity,
    purge_opportunity_log,
    recent_opportunity_times,
)

# La purga cuenta desde el reloj real, así que el "ahora" de la prueba también lo es (con una fecha fija la prueba caduca).
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


# ---------------- opportunity_log_due ----------------
def test_a_new_or_changed_item_is_always_logged():
    assert opportunity_log_due("POTENCIAL", None, None, NOW, 60, 720) is True
    assert opportunity_log_due("POTENCIAL", "EN_OBSERVACION", _iso(1), NOW, 60, 720) is True
    assert opportunity_log_due("POTENCIAL", "POTENCIAL", None, NOW, 60, 720) is True  # nunca registrado


def test_useful_states_are_logged_once_per_interval():
    assert opportunity_log_due("POTENCIAL", "POTENCIAL", _iso(10), NOW, 60, 720) is False
    assert opportunity_log_due("POTENCIAL", "POTENCIAL", _iso(59), NOW, 60, 720) is False
    assert opportunity_log_due("POTENCIAL", "POTENCIAL", _iso(61), NOW, 60, 720) is True
    assert opportunity_log_due("EN_OBSERVACION", "EN_OBSERVACION", _iso(61), NOW, 60, 720) is True


def test_discarded_items_use_the_longer_interval():
    assert opportunity_log_due("DESCARTADO", "DESCARTADO", _iso(300), NOW, 60, 720) is False
    assert opportunity_log_due("DESCARTADO", "DESCARTADO", _iso(721), NOW, 60, 720) is True


# ---------------- funciones de base de datos ----------------
@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "oplog.db")
    init_db(path)
    c = get_connection(path)
    for type_id in range(1, 6):
        c.execute("INSERT INTO item_type (type_id, name) VALUES (?, ?)", (type_id, f"item{type_id}"))
    c.commit()
    yield c
    c.close()


def _log(conn, type_id, minutes_ago):
    insert_opportunity(conn, {
        "type_id": type_id, "evaluated_at": _iso(minutes_ago), "buy": 1.0, "sell": 2.0,
        "volumen_deseado": 1.0, "volumen_diario_real": 1.0, "beneficio": 1.0, "spread_bruto": 1.0,
        "precio_min_venta": 1.0, "roi": 1.0, "evaluacion_spread": "ok", "posicion_vs_volumen": 0.1,
        "liquidez": "ok", "recomendacion": "ok",
    })


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM opportunity_log").fetchone()[0]


def test_first_id_since_finds_the_boundary_even_with_gaps_in_the_ids(conn):
    for minutes_ago in (500, 400, 300, 200, 100, 50, 10):  # crecen en el tiempo, como en producción
        _log(conn, 1, minutes_ago)
    conn.execute("DELETE FROM opportunity_log WHERE id IN (2, 5)")  # huecos en la clave primaria
    conn.commit()

    first = _first_opportunity_id_since(conn, _iso(250))

    row = conn.execute("SELECT evaluated_at FROM opportunity_log WHERE id >= ? ORDER BY id LIMIT 1", (first,)).fetchone()
    assert row[0] == _iso(200)  # la de 300 min queda fuera; la primera que entra es la de 200 min


def test_first_id_since_handles_empty_and_all_old_tables(conn):
    assert _first_opportunity_id_since(conn, _iso(10)) is None
    _log(conn, 1, 500)
    assert _first_opportunity_id_since(conn, _iso(10)) is None  # todo es más viejo
    assert _first_opportunity_id_since(conn, _iso(1000)) == 1


def test_recent_opportunity_times_returns_the_latest_per_item(conn):
    _log(conn, 3, 500)  # fuera de la ventana (el log se anexa en orden cronológico)
    _log(conn, 1, 400)
    _log(conn, 1, 30)
    _log(conn, 2, 20)

    times = recent_opportunity_times(conn, _iso(120))

    assert times == {1: _iso(30), 2: _iso(20)}


def test_purge_removes_old_rows_and_keeps_recent_ones(conn):
    for minutes_ago in (6 * 1440, 5 * 1440, 4 * 1440, 1440, 60, 5):
        _log(conn, 1, minutes_ago)

    deleted = purge_opportunity_log(conn, keep_days=3)

    assert deleted == 3
    assert _count(conn) == 3
    assert conn.execute("SELECT MIN(evaluated_at) FROM opportunity_log").fetchone()[0] == _iso(1440)


def test_purge_is_bounded_per_call_and_finishes_over_several_calls(conn):
    for _ in range(50):
        _log(conn, 1, 10 * 1440)
    _log(conn, 1, 5)

    first = purge_opportunity_log(conn, keep_days=3, batch_size=10, max_batches=2)
    assert first == 20 and _count(conn) == 31
    while purge_opportunity_log(conn, keep_days=3, batch_size=10, max_batches=2):
        pass

    assert _count(conn) == 1  # solo queda la reciente


def test_purge_on_an_empty_table_does_nothing(conn):
    assert purge_opportunity_log(conn, keep_days=3) == 0


# ---------------- el ciclo de screening ----------------
@pytest.fixture
def screening_db(tmp_path):
    path = str(tmp_path / "screen.db")
    init_db(path)
    c = get_connection(path)
    c.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    c.execute(
        "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) "
        "VALUES (34, datetime('now'), 4.0, 4.5, 1000, 1000, 3, 3)",
    )
    c.execute(
        "INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
        "VALUES (34, date('now'), 4.2, 4.6, 3.9, 1000, 5)",
    )
    c.commit()
    c.close()
    return path


@pytest.fixture
def quiet_screening(monkeypatch):
    monkeypatch.setattr("scheduler.run.get_current_wallet_balance", lambda: 5_000_000.0)
    monkeypatch.setattr("scheduler.run.dispatch", lambda events: None)
    monkeypatch.setattr("scheduler.run.is_price_sane", lambda *a, **k: True)


def _rows_for(path):
    c = get_connection(path)
    try:
        return c.execute("SELECT COUNT(*) FROM opportunity_log WHERE type_id = 34").fetchone()[0]
    finally:
        c.close()


def test_repeated_screenings_do_not_add_a_row_per_cycle(tmp_path, screening_db, quiet_screening, monkeypatch):
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "ok"))
    excel = str(tmp_path / "r.xlsx")

    for _ in range(6):  # seis ciclos seguidos (30 min a 5 min de cadencia)
        screen_opportunities(screening_db, excel)

    assert _rows_for(screening_db) == 1  # antes: una fila por ciclo


def test_a_state_change_is_logged_immediately(tmp_path, screening_db, quiet_screening, monkeypatch):
    excel = str(tmp_path / "r.xlsx")
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "ok"))
    screen_opportunities(screening_db, excel)
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("EN_OBSERVACION", "ok"))

    screen_opportunities(screening_db, excel)

    assert _rows_for(screening_db) == 2


def test_an_item_is_logged_again_once_the_interval_has_passed(tmp_path, screening_db, quiet_screening, monkeypatch):
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "ok"))
    excel = str(tmp_path / "r.xlsx")
    screen_opportunities(screening_db, excel)
    c = get_connection(screening_db)
    old = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    c.execute("UPDATE opportunity_log SET evaluated_at = ?", (old,))
    c.commit()
    c.close()

    screen_opportunities(screening_db, excel)

    assert _rows_for(screening_db) == 2


def test_the_screening_purges_rows_older_than_the_retention(tmp_path, screening_db, quiet_screening, monkeypatch):
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "ok"))
    monkeypatch.setenv("OPPORTUNITY_LOG_RETENTION_DAYS", "3")
    c = get_connection(screening_db)
    for days_ago in (30, 20, 10):
        insert_opportunity(c, {
            "type_id": 34, "evaluated_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
            "buy": 1.0, "sell": 2.0, "volumen_deseado": 1.0, "volumen_diario_real": 1.0, "beneficio": 1.0,
            "spread_bruto": 1.0, "precio_min_venta": 1.0, "roi": 1.0, "evaluacion_spread": "ok",
            "posicion_vs_volumen": 0.1, "liquidez": "ok", "recomendacion": "viejo",
        })
    c.commit()
    c.close()

    screen_opportunities(screening_db, str(tmp_path / "r.xlsx"))

    c = get_connection(screening_db)
    remaining = [r["recomendacion"] for r in c.execute("SELECT recomendacion FROM opportunity_log")]
    c.close()
    assert "viejo" not in remaining and len(remaining) == 1
