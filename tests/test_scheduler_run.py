"""Cobertura de orquestación del motor de mercado (D3): qué persiste ingest()/
ingest_categories()/screen_opportunities(), y cuándo se dispara cada evento. Las
funciones puras que ya usan (classify, is_price_sane, evaluar_oportunidad) tienen su
propio test en analytics/ -- acá se mockean para aislar solo la orquestación."""
import pytest

from notifications.events import NewOpportunity
from scheduler.run import ingest, ingest_categories, screen_opportunities
from storage.db import get_connection, init_db


class _FakeMarketClient:
    """Cubre los métodos que usa ingest(): tipos activos, libro de órdenes agregado,
    nombres en bulk, e histórico por ítem."""

    def __init__(self, type_ids, orders, names, history_by_type=None):
        self._type_ids = type_ids
        self._orders = orders
        self._names = names
        self._history_by_type = history_by_type or {}

    def get_active_type_ids(self, region_id):
        return self._type_ids

    def get_orders(self, region_id):
        return self._orders

    def get_type_names_bulk(self, type_ids):
        return self._names

    def get_history(self, region_id, type_id):
        return self._history_by_type.get(type_id, [])


class _FakeCategoryClient:
    """Cubre los métodos que usa ingest_categories(): group_id por ítem, y
    grupo/categoría por group_id -- con contadores para verificar cacheo."""

    def __init__(self, group_by_type, groups, category_names):
        self._group_by_type = group_by_type
        self._groups = groups
        self._category_names = category_names
        self.get_group_calls = 0
        self.get_type_group_id_calls = []

    def get_type_group_id(self, type_id):
        self.get_type_group_id_calls.append(type_id)
        return self._group_by_type[type_id]

    def get_group(self, group_id):
        self.get_group_calls += 1
        return self._groups[group_id]

    def get_category_name(self, category_id):
        return self._category_names[category_id]


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_ingest_persists_item_type_and_snapshot_for_every_active_type(db_path):
    client = _FakeMarketClient(
        type_ids=[34, 35],
        orders=[
            {"type_id": 34, "is_buy_order": False, "volume_remain": 1000, "price": 4.5},
            {"type_id": 34, "is_buy_order": True, "volume_remain": 500, "price": 4.0},
        ],
        names={34: "Tritanium", 35: "Pyerite"},
    )

    result = ingest(client, region_id=10000002, db_path=db_path, backfill=False)

    assert result == [34, 35]
    conn = get_connection(db_path)
    types = {r["type_id"]: r["name"] for r in conn.execute("SELECT * FROM item_type").fetchall()}
    snapshots = {r["type_id"]: dict(r) for r in conn.execute("SELECT * FROM market_snapshot").fetchall()}
    conn.close()

    assert types == {34: "Tritanium", 35: "Pyerite"}
    assert snapshots[34]["best_sell"] == 4.5
    assert snapshots[34]["best_buy"] == 4.0
    # 35 no tuvo órdenes en el libro -- igual queda con una fila de snapshot (todo None/0).
    assert snapshots[35]["best_buy"] is None


def test_ingest_backfill_persists_full_history_vs_only_the_latest_point(db_path):
    history = [
        {"date": "2026-09-01", "average": 4.0, "highest": 4.2, "lowest": 3.8, "volume": 100, "order_count": 3},
        {"date": "2026-09-02", "average": 4.1, "highest": 4.3, "lowest": 3.9, "volume": 120, "order_count": 4},
    ]
    client = _FakeMarketClient(
        type_ids=[34], orders=[], names={34: "Tritanium"}, history_by_type={34: history},
    )

    ingest(client, region_id=10000002, db_path=db_path, backfill=True)
    conn = get_connection(db_path)
    rows = conn.execute("SELECT date FROM market_history ORDER BY date").fetchall()
    conn.close()
    assert [r["date"] for r in rows] == ["2026-09-01", "2026-09-02"]


def test_ingest_non_backfill_persists_only_the_latest_history_point(db_path):
    history = [
        {"date": "2026-09-01", "average": 4.0, "highest": 4.2, "lowest": 3.8, "volume": 100, "order_count": 3},
        {"date": "2026-09-02", "average": 4.1, "highest": 4.3, "lowest": 3.9, "volume": 120, "order_count": 4},
    ]
    client = _FakeMarketClient(
        type_ids=[34], orders=[], names={34: "Tritanium"}, history_by_type={34: history},
    )

    ingest(client, region_id=10000002, db_path=db_path, backfill=False)
    conn = get_connection(db_path)
    rows = conn.execute("SELECT date FROM market_history").fetchall()
    conn.close()
    assert [r["date"] for r in rows] == ["2026-09-02"]


def test_ingest_categories_skips_items_already_cached(db_path):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium'), (35, 'Pyerite')")
    conn.execute(
        "INSERT INTO item_category (type_id, group_id, group_name, category_id, category_name) "
        "VALUES (34, 1, 'Minerals', 4, 'Material')",
    )
    conn.commit()
    conn.close()

    client = _FakeCategoryClient(
        group_by_type={35: 2}, groups={2: {"name": "Ice", "category_id": 25}},
        category_names={25: "Asteroid"},
    )

    ingest_categories(client, db_path, type_ids=[34, 35])

    assert client.get_type_group_id_calls == [35]  # 34 ya estaba cacheado, no se vuelve a pedir


def test_ingest_categories_reuses_the_group_cache_within_one_run(db_path):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium'), (35, 'Pyerite')")
    conn.commit()
    conn.close()

    client = _FakeCategoryClient(
        group_by_type={34: 1, 35: 1}, groups={1: {"name": "Minerals", "category_id": 4}},
        category_names={4: "Material"},
    )

    ingest_categories(client, db_path, type_ids=[34, 35])

    # Los dos ítems comparten group_id=1 -- get_group() solo debería llamarse una vez.
    assert client.get_group_calls == 1
    conn = get_connection(db_path)
    rows = {r["type_id"]: r["category_name"] for r in conn.execute("SELECT * FROM item_category").fetchall()}
    conn.close()
    assert rows == {34: "Material", 35: "Material"}


@pytest.fixture
def screening_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.execute(
        "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) "
        "VALUES (34, datetime('now'), 4.0, 4.5, 1000, 1000, 3, 3)",
    )
    conn.execute(
        "INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
        "VALUES (34, date('now'), 4.2, 4.6, 3.9, 1000, 5)",
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mocked_screening(monkeypatch):
    """Aísla screen_opportunities() de las funciones puras (ya testeadas aparte) y de
    los side effects externos (ESI, Telegram, Excel local sigue siendo real -- es I/O
    de archivo, no red)."""
    monkeypatch.setattr("scheduler.run.get_current_wallet_balance", lambda: 5_000_000.0)
    dispatched = []
    monkeypatch.setattr("scheduler.run.dispatch", lambda events: dispatched.append(list(events)))
    return dispatched


def test_screen_opportunities_persists_opportunity_and_status(tmp_path, screening_db, mocked_screening, monkeypatch):
    monkeypatch.setattr("scheduler.run.is_price_sane", lambda *a, **k: True)
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "buen spread"))

    screen_opportunities(screening_db, str(tmp_path / "registro.xlsx"))

    conn = get_connection(screening_db)
    opportunity = conn.execute("SELECT * FROM opportunity_log WHERE type_id = 34").fetchone()
    status = conn.execute("SELECT * FROM item_status WHERE type_id = 34").fetchone()
    history = conn.execute("SELECT * FROM item_status_history WHERE type_id = 34").fetchall()
    conn.close()

    assert opportunity is not None
    assert status["status"] == "POTENCIAL"
    assert status["reason"] == "buen spread"
    # Primera clasificación: previous_status era None -> queda un registro en el historial.
    assert len(history) == 1
    assert history[0]["previous_status"] is None
    assert history[0]["new_status"] == "POTENCIAL"
    # POTENCIAL nuevo (antes no lo era) -> dispara notificación.
    assert len(mocked_screening) == 1
    assert len(mocked_screening[0]) == 1
    assert isinstance(mocked_screening[0][0], NewOpportunity)


def test_screen_opportunities_does_not_redispatch_an_already_potencial_item(
    tmp_path, screening_db, mocked_screening, monkeypatch,
):
    monkeypatch.setattr("scheduler.run.is_price_sane", lambda *a, **k: True)
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "buen spread"))
    excel_path = str(tmp_path / "registro.xlsx")

    screen_opportunities(screening_db, excel_path)
    mocked_screening.clear()
    screen_opportunities(screening_db, excel_path)

    conn = get_connection(screening_db)
    history = conn.execute("SELECT * FROM item_status_history WHERE type_id = 34").fetchall()
    conn.close()

    # Sigue POTENCIAL en la segunda corrida: ni nuevo registro de historial ni un
    # segundo aviso de Telegram por la misma oportunidad.
    assert len(history) == 1
    assert mocked_screening == [[]]


def test_screen_opportunities_forces_descartado_when_price_is_insane(
    tmp_path, screening_db, mocked_screening, monkeypatch,
):
    monkeypatch.setattr("scheduler.run.is_price_sane", lambda *a, **k: False)
    # Si is_price_sane fuera consultado, esto haría fallar el assert de abajo --
    # confirma que el resultado real viene del gate de sanity, no de classify().
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "no debería usarse"))

    screen_opportunities(screening_db, str(tmp_path / "registro.xlsx"))

    conn = get_connection(screening_db)
    status = conn.execute("SELECT * FROM item_status WHERE type_id = 34").fetchone()
    conn.close()

    assert status["status"] == "DESCARTADO"
    assert mocked_screening == [[]]  # DESCARTADO nunca dispara NewOpportunity


def test_screen_opportunities_uses_only_the_latest_snapshot_and_a_bounded_history(
    tmp_path, screening_db, mocked_screening, monkeypatch,
):
    """Regresión de memoria: el screening no debe cargar TODAS las filas de
    market_snapshot/market_history (en la VM de 1 GB de RAM llevó al swap thrashing),
    sino el último snapshot por ítem y las últimas HISTORY_WINDOW filas de histórico."""
    seen = {}

    def fake_evaluar(item, buy, sell, volumen_deseado, volumen_diario_real, config):
        seen["buy"], seen["sell"], seen["volumen_diario_real"] = buy, sell, volumen_diario_real
        from analytics.eve_calculator import evaluar_oportunidad
        return evaluar_oportunidad(item, buy, sell, volumen_deseado, volumen_diario_real, config)

    monkeypatch.setattr("scheduler.run.evaluar_oportunidad", fake_evaluar)
    monkeypatch.setattr("scheduler.run.is_price_sane", lambda *a, **k: True)
    monkeypatch.setattr("scheduler.run.classify", lambda *a, **k: ("POTENCIAL", "ok"))

    conn = get_connection(screening_db)
    # Snapshots viejos con precios distintos: el vigente es el de datetime('now') del fixture.
    for days_ago, price in ((1, 1.0), (2, 2.0), (3, 3.0)):
        conn.execute(
            "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, "
            "sell_volume, buy_order_count, sell_order_count) "
            f"VALUES (34, datetime('now', '-{days_ago} days'), {price}, {price + 1}, 10, 10, 1, 1)",
        )
    # 60 días de histórico viejo con volumen enorme: fuera de la ventana de 30 filas.
    for days_ago in range(1, 61):
        conn.execute(
            "INSERT INTO market_history (type_id, date, avg_price, highest, lowest, volume, order_count) "
            f"VALUES (34, date('now', '-{days_ago} days'), 4.2, 4.6, 3.9, "
            f"{1000 if days_ago < 30 else 10_000_000}, 5)",
        )
    conn.commit()
    conn.close()

    screen_opportunities(screening_db, str(tmp_path / "registro.xlsx"))

    assert (seen["buy"], seen["sell"]) == (4.0, 4.5)  # el snapshot más reciente, no uno viejo
    assert seen["volumen_diario_real"] == 1000  # las 30 filas más recientes, sin el histórico viejo


def test_ingest_prunes_snapshots_older_than_the_retention_window(db_path, monkeypatch):
    monkeypatch.setenv("SNAPSHOT_RETENTION_DAYS", "7")
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.execute(
        "INSERT INTO market_snapshot (type_id, captured_at, best_buy, best_sell, buy_volume, "
        "sell_volume, buy_order_count, sell_order_count) "
        "VALUES (34, datetime('now', '-30 days'), 1, 2, 1, 1, 1, 1)",
    )
    conn.commit()
    conn.close()
    client = _FakeMarketClient(
        type_ids=[34],
        orders=[{"type_id": 34, "is_buy_order": False, "volume_remain": 10, "price": 4.5}],
        names={34: "Tritanium"},
    )

    ingest(client, region_id=10000002, db_path=db_path, backfill=False)

    conn = get_connection(db_path)
    remaining = conn.execute("SELECT COUNT(*) FROM market_snapshot WHERE type_id = 34").fetchone()[0]
    conn.close()
    assert remaining == 1  # solo el snapshot nuevo; el de hace 30 días se borró


class _TrackingClient(_FakeMarketClient):
    """Registra qué pide cada modo: nombres solicitados e histórico consultado."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.names_requested = []
        self.history_calls = []

    def get_type_names_bulk(self, type_ids):
        self.names_requested.append(list(type_ids))
        return {t: self._names[t] for t in type_ids}

    def get_history(self, region_id, type_id):
        self.history_calls.append(type_id)
        return super().get_history(region_id, type_id)


def test_ingest_orders_does_not_fetch_history_and_only_asks_for_unknown_names(db_path):
    from scheduler.run import ingest_orders

    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (36, 'type_36')")  # nombre provisional
    conn.commit()
    conn.close()
    client = _TrackingClient(
        type_ids=[34, 35, 36],
        orders=[{"type_id": 34, "is_buy_order": False, "volume_remain": 10, "price": 4.5}],
        names={34: "Tritanium", 35: "Pyerite", 36: "Mexallon"},
    )

    result = ingest_orders(client, region_id=10000002, db_path=db_path)

    assert result == [34, 35, 36]
    assert client.history_calls == []
    assert client.names_requested == [[35, 36]]  # el 34 ya tenía nombre real
    conn = get_connection(db_path)
    names = {r["type_id"]: r["name"] for r in conn.execute("SELECT * FROM item_type").fetchall()}
    snapshots = conn.execute("SELECT COUNT(*) FROM market_snapshot").fetchone()[0]
    conn.close()
    assert names == {34: "Tritanium", 35: "Pyerite", 36: "Mexallon"}
    assert snapshots == 3


def test_ingest_orders_skips_the_names_request_when_every_type_is_known(db_path):
    from scheduler.run import ingest_orders

    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.commit()
    conn.close()
    client = _TrackingClient(type_ids=[34], orders=[], names={34: "Tritanium"})

    ingest_orders(client, region_id=10000002, db_path=db_path)

    assert client.names_requested == []


def test_snapshot_retention_hours_reads_the_new_variable_then_the_legacy_days(monkeypatch):
    from scheduler.run import DEFAULT_SNAPSHOT_RETENTION_HOURS, snapshot_retention_hours

    monkeypatch.delenv("SNAPSHOT_RETENTION_HOURS", raising=False)
    monkeypatch.delenv("SNAPSHOT_RETENTION_DAYS", raising=False)
    assert snapshot_retention_hours() == DEFAULT_SNAPSHOT_RETENTION_HOURS
    monkeypatch.setenv("SNAPSHOT_RETENTION_DAYS", "2")
    assert snapshot_retention_hours() == 48
    monkeypatch.setenv("SNAPSHOT_RETENTION_HOURS", "3")
    assert snapshot_retention_hours() == 3


@pytest.fixture
def run_main(db_path, monkeypatch):
    """Ejecuta scheduler.run.main() con un cliente falso y el screening/categorías espiados."""
    import sys

    import scheduler.run as run_module

    calls = {"screen": 0, "categories": 0}
    client = _TrackingClient(type_ids=[34], orders=[], names={34: "Tritanium"})

    class _CM:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return client

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(run_module, "EsiClient", _CM)
    monkeypatch.setattr(run_module, "screen_opportunities", lambda *a, **k: calls.__setitem__("screen", calls["screen"] + 1))
    monkeypatch.setattr(run_module, "ingest_categories", lambda *a, **k: calls.__setitem__("categories", calls["categories"] + 1))
    monkeypatch.setenv("DB_PATH", db_path)

    def _run(*flags):
        monkeypatch.setattr(sys, "argv", ["scheduler.run", *flags])
        return run_module.main()

    return _run, client, calls


def test_main_prices_only_screens_without_downloading_history(run_main):
    run, client, calls = run_main

    assert run("--prices-only") == 0

    assert client.history_calls == []
    assert calls == {"screen": 1, "categories": 1}


def test_main_history_only_downloads_history_without_screening(run_main):
    run, client, calls = run_main

    assert run("--history-only") == 0

    assert client.history_calls == [34]
    assert calls == {"screen": 0, "categories": 0}


def test_main_without_flags_runs_the_full_pipeline(run_main):
    run, client, calls = run_main

    assert run() == 0

    assert client.history_calls == [34]
    assert calls == {"screen": 1, "categories": 1}


def test_main_rejects_incompatible_flags(run_main):
    run, _, _ = run_main

    for flags in (("--prices-only", "--history-only"), ("--prices-only", "--backfill"),
                  ("--history-only", "--rescreen-only")):
        with pytest.raises(SystemExit):
            run(*flags)


def test_ingest_history_does_not_hold_the_write_lock_while_waiting_for_esi(db_path):
    """Con un solo escritor en SQLite, una transacción abierta durante la espera a ESI deja sin
    escribir al ciclo de precios que corre a la vez (falló con "database is locked" en producción)."""
    import sqlite3

    from scheduler.run import ingest_history

    conn = get_connection(db_path)
    conn.executemany("INSERT INTO item_type (type_id, name) VALUES (?, ?)", [(t, f"item{t}") for t in range(1, 121)])
    conn.commit()
    conn.close()
    probe = {}

    class _Client:
        def __init__(self):
            self.calls = 0

        def get_history(self, region_id, type_id):
            self.calls += 1
            if self.calls == 60:  # a mitad del primer lote de 100, con resultados ya recibidos
                other = sqlite3.connect(db_path, timeout=0.2)
                try:
                    other.execute("INSERT INTO item_type (type_id, name) VALUES (999999, 'probe')")
                    other.commit()
                    probe["ok"] = True
                except sqlite3.OperationalError as exc:
                    probe["ok"] = False
                    probe["error"] = str(exc)
                finally:
                    other.close()
            return [{"date": "2026-09-02", "average": 4.1, "highest": 4.3, "lowest": 3.9, "volume": 120,
                     "order_count": 4}]

    ingest_history(_Client(), 10000002, db_path, list(range(1, 121)), max_workers=1)

    assert probe == {"ok": True}
    conn = get_connection(db_path)
    stored = conn.execute("SELECT COUNT(*) FROM market_history").fetchone()[0]
    conn.close()
    assert stored == 120  # el buffer se escribe completo, incluido el último lote parcial
