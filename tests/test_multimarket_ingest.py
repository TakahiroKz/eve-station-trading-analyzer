"""El motor recorre los mercados activos uno tras otro, aislados, y cada uno guarda sus datos con su market_id."""
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

import scheduler.run as run_module
from ingestion.markets import UnknownMarketError, list_markets
from scheduler.run import ingest_history, ingest_orders
from storage.db import get_connection, init_db

JITA, AMARR, DODIXIE = 10000002, 10000043, 10000032


class _RecordingClient:
    """Registra qué región pide cada paso; `fail_regions` hace fallar la descarga de órdenes."""

    def __init__(self, fail_regions=()):
        self.fail_regions = set(fail_regions)
        self.orders_regions = []
        self.history_regions = []
        self.active_regions = []

    def get_active_type_ids(self, region_id):
        self.active_regions.append(region_id)
        return [34]

    def get_orders(self, region_id):
        self.orders_regions.append(region_id)
        if region_id in self.fail_regions:
            raise RuntimeError(f"ESI caída para {region_id}")
        return [{"type_id": 34, "is_buy_order": False, "volume_remain": 5, "price": 10.0}]

    def get_type_names_bulk(self, type_ids):
        return {t: "Tritanium" for t in type_ids}

    def get_history(self, region_id, type_id):
        self.history_regions.append(region_id)
        today = datetime.now(timezone.utc).date()
        return [
            {"date": (today - timedelta(days=days)).isoformat(), "average": 4.0, "highest": 4.2, "lowest": 3.8,
             "volume": 10, "order_count": 2}
            for days in (40, 5)
        ]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ing.db")
    init_db(db_path)
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("EXCEL_REGISTRO_PATH", str(tmp_path / "r.xlsx"))
    state = {"client": _RecordingClient(), "screened": [], "categories": 0}

    class _CM:
        def __enter__(self):
            return state["client"]

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(run_module, "EsiClient", lambda *a, **k: _CM())
    monkeypatch.setattr(run_module, "screen_opportunities",
                        lambda db, excel, fallback=None, market_id="jita": state["screened"].append(market_id))
    monkeypatch.setattr(run_module, "ingest_categories",
                        lambda *a, **k: state.__setitem__("categories", state["categories"] + 1))
    monkeypatch.setattr(run_module, "flush_notifications", lambda *a, **k: None)

    def enable(*market_ids):
        conn = sqlite3.connect(db_path)
        conn.executemany("UPDATE market SET enabled = 1 WHERE market_id = ?", [(m,) for m in market_ids])
        conn.commit()
        conn.close()

    def run(*flags):
        monkeypatch.setattr(sys, "argv", ["scheduler.run", *flags])
        return run_module.main()

    return run, enable, state, db_path


# ---------------- list_markets ----------------
def test_list_markets_returns_the_enabled_ones_in_order_and_rejects_unknown_ids(tmp_path):
    path = str(tmp_path / "m.db")
    init_db(path)
    assert [m.market_id for m in list_markets(path)] == ["jita"]

    conn = sqlite3.connect(path)
    conn.execute("UPDATE market SET enabled = 1 WHERE market_id IN ('amarr', 'hek')")
    conn.commit()
    conn.close()

    assert [m.market_id for m in list_markets(path)] == ["jita", "amarr", "hek"]
    assert [(m.market_id, m.region_id) for m in list_markets(path, ["rens", "jita", "rens"])] == [
        ("rens", 10000030), ("jita", JITA)]  # desactivado pero pedido; sin repetidos
    with pytest.raises(UnknownMarketError):
        list_markets(path, ["nope"])


# ---------------- ciclo de precios ----------------
def test_each_enabled_market_is_fetched_from_its_region_and_screened(engine, caplog):
    run, enable, state, _ = engine
    enable("amarr")
    caplog.set_level(logging.INFO)

    assert run("--prices-only") == 0

    assert state["client"].orders_regions == [JITA, AMARR]
    assert state["screened"] == ["jita", "amarr"]
    assert state["categories"] == 2
    text = caplog.text
    assert "Mercado jita completo" in text and "Mercado amarr completo" in text
    assert text.count("Pipeline completo en") == 1  # una sola línea total para el watchdog


def test_only_jita_runs_by_default(engine):
    run, _, state, _ = engine

    run("--prices-only")

    assert state["client"].orders_regions == [JITA] and state["screened"] == ["jita"]


def test_a_failing_market_does_not_stop_the_others(engine, caplog):
    run, enable, state, _ = engine
    enable("amarr", "dodixie")
    state["client"] = _RecordingClient(fail_regions={AMARR})
    caplog.set_level(logging.INFO)

    code = run("--prices-only")

    assert code == 0  # no fallaron todos
    assert state["client"].orders_regions == [JITA, AMARR, DODIXIE]
    assert state["screened"] == ["jita", "dodixie"]
    assert "Fallo en el mercado amarr" in caplog.text and "Mercados con fallo: amarr" in caplog.text
    assert "Pipeline completo en" in caplog.text


def test_the_exit_code_is_one_only_when_every_market_failed(engine):
    run, enable, state, _ = engine
    enable("amarr")
    state["client"] = _RecordingClient(fail_regions={JITA, AMARR})

    assert run("--prices-only") == 1


def test_markets_option_overrides_the_enabled_flag_and_unknown_ids_are_rejected(engine):
    run, _, state, _ = engine

    run("--prices-only", "--markets", "amarr")
    assert state["client"].orders_regions == [AMARR] and state["screened"] == ["amarr"]

    with pytest.raises(SystemExit):
        run("--prices-only", "--markets", "nope")


def test_the_data_of_each_market_is_stored_under_its_market_id(engine):
    run, enable, state, db_path = engine
    enable("amarr")

    ingest_orders(state["client"], JITA, db_path, market_id="jita")
    ingest_orders(state["client"], AMARR, db_path, market_id="amarr")

    conn = get_connection(db_path)
    markets = [r["market_id"] for r in conn.execute("SELECT market_id FROM market_snapshot ORDER BY market_id")]
    conn.close()
    assert markets == ["amarr", "jita"]


# ---------------- histórico ----------------
def test_history_only_walks_every_market_without_screening(engine, caplog):
    run, enable, state, _ = engine
    enable("amarr")
    caplog.set_level(logging.INFO)

    run("--history-only")

    assert state["client"].active_regions == [JITA, AMARR]
    assert state["client"].history_regions == [JITA, AMARR]
    assert state["screened"] == [] and state["categories"] == 0
    assert "Histórico completo en" in caplog.text and "Pipeline completo" not in caplog.text


def test_history_days_keeps_only_the_recent_rows_of_a_backfill(engine):
    _, _, state, db_path = engine
    seed = sqlite3.connect(db_path)
    seed.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    seed.commit()
    seed.close()

    ingest_history(state["client"], JITA, db_path, [34], backfill=True, history_days=10)

    conn = get_connection(db_path)
    rows = conn.execute("SELECT date FROM market_history").fetchall()
    conn.close()
    assert len(rows) == 1  # la de hace 5 días; la de hace 40 queda fuera


def test_history_days_requires_backfill_and_a_positive_value(engine):
    run, _, _, _ = engine

    with pytest.raises(SystemExit):
        run("--history-only", "--history-days", "30")
    with pytest.raises(SystemExit):
        run("--history-only", "--backfill", "--history-days", "0")


# ---------------- histórico: huecos, reintentos y fallos masivos ----------------
def _day(days_ago):
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


def _history_row(days_ago):
    return {"date": _day(days_ago), "average": 4.0, "highest": 4.2, "lowest": 3.8, "volume": 10, "order_count": 2}


class _GapClient(_RecordingClient):
    """Devuelve el año como la ESI: filas viejas, el hueco y el día más reciente."""

    def get_history(self, region_id, type_id):
        self.history_regions.append(region_id)
        return [_history_row(d) for d in (30, 4, 3, 2, 1)]


def _seed_item(db_path, *type_ids):
    conn = sqlite3.connect(db_path)
    conn.executemany("INSERT INTO item_type (type_id, name) VALUES (?, ?)", [(t, f"item {t}") for t in type_ids])
    conn.commit()
    conn.close()


def _stored_dates(db_path, type_id, market_id="jita"):
    conn = get_connection(db_path)
    rows = conn.execute("SELECT date FROM market_history WHERE market_id = ? AND type_id = ? ORDER BY date",
                        (market_id, type_id)).fetchall()
    conn.close()
    return [r["date"] for r in rows]


def test_daily_history_fills_the_days_missed_by_a_failed_run(engine):
    _, _, _, db_path = engine
    _seed_item(db_path, 34, 35)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO market_history (market_id, type_id, date, avg_price, highest, lowest, volume, "
                 "order_count) VALUES ('jita', 34, ?, 4, 4, 4, 1, 1)", (_day(4),))
    conn.commit()
    conn.close()

    ingest_history(_GapClient(), JITA, db_path, [34, 35])

    # tipo con historial: todo lo posterior a su última fecha; tipo nuevo: solo la última fila
    assert _stored_dates(db_path, 34) == [_day(4), _day(3), _day(2), _day(1)]
    assert _stored_dates(db_path, 35) == [_day(1)]


def test_history_is_current_needs_yesterday_covered_like_the_day_before(engine):
    _, _, _, db_path = engine
    _seed_item(db_path, *range(1, 11))
    conn = sqlite3.connect(db_path)
    insert = ("INSERT INTO market_history (market_id, type_id, date, avg_price, highest, lowest, volume, "
              "order_count) VALUES ('jita', ?, ?, 1, 1, 1, 1, 1)")
    conn.executemany(insert, [(t, _day(2)) for t in range(1, 11)])
    conn.commit()
    assert run_module.history_is_current(db_path, "jita") is False  # ayer sin datos

    conn.executemany(insert, [(t, _day(1)) for t in range(1, 6)])  # cortada a medias: 50 %
    conn.commit()
    assert run_module.history_is_current(db_path, "jita") is False

    conn.executemany(insert, [(t, _day(1)) for t in range(6, 10)])  # 90 %
    conn.commit()
    conn.close()
    assert run_module.history_is_current(db_path, "jita") is True
    assert run_module.history_is_current(db_path, "amarr") is False  # sin datos


def test_history_only_skips_a_market_that_is_already_current_but_backfill_does_not(engine, caplog):
    run, _, state, db_path = engine
    _seed_item(db_path, 34)
    conn = sqlite3.connect(db_path)
    conn.executemany("INSERT INTO market_history (market_id, type_id, date, avg_price, highest, lowest, volume, "
                     "order_count) VALUES ('jita', 34, ?, 1, 1, 1, 1, 1)", [(_day(2),), (_day(1),)])
    conn.commit()
    conn.close()
    caplog.set_level(logging.INFO)

    run("--history-only")
    assert state["client"].active_regions == [] and "ya al día" in caplog.text

    run("--history-only", "--backfill", "--history-days", "5")
    assert state["client"].active_regions == [JITA]


def test_a_history_run_with_many_failed_types_fails_the_market_so_cron_retries(engine, caplog):
    import httpx

    run, _, state, db_path = engine

    class _Down(_RecordingClient):
        def get_active_type_ids(self, region_id):
            return list(range(1, 31))

        def get_history(self, region_id, type_id):
            response = httpx.Response(503, request=httpx.Request("GET", "http://esi"))
            raise httpx.HTTPStatusError("503", request=response.request, response=response)

    state["client"] = _Down()
    caplog.set_level(logging.INFO)

    assert run("--history-only") == 1  # el único mercado falló

    assert "Mercados con fallo: jita" in caplog.text
    assert run_module.history_is_current(db_path, "jita") is False
