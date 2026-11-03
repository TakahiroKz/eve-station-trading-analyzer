import sqlite3

import pytest

from notifications.events import PositionChanged
from scheduler.orders_run import _init_db_with_retry, check_character_orders
from storage.db import get_connection, init_db


def test_init_db_with_retry_succeeds_on_first_try(monkeypatch):
    calls = []
    monkeypatch.setattr("scheduler.orders_run.init_db", lambda db_path: calls.append(db_path))
    monkeypatch.setattr("scheduler.orders_run.time.sleep", lambda s: pytest.fail("no debería dormir"))

    _init_db_with_retry("fake.db")

    assert calls == ["fake.db"]


def test_init_db_with_retry_recovers_after_one_locked_error(monkeypatch):
    attempts = []

    def fake_init_db(db_path):
        attempts.append(db_path)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("scheduler.orders_run.init_db", fake_init_db)
    slept = []
    monkeypatch.setattr("scheduler.orders_run.time.sleep", lambda s: slept.append(s))

    _init_db_with_retry("fake.db", attempts=2, delay_seconds=5.0)

    assert len(attempts) == 2
    assert slept == [5.0]


def test_init_db_with_retry_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr(
        "scheduler.orders_run.init_db",
        lambda db_path: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )
    monkeypatch.setattr("scheduler.orders_run.time.sleep", lambda s: None)

    with pytest.raises(sqlite3.OperationalError):
        _init_db_with_retry("fake.db", attempts=2, delay_seconds=0.01)


class _FakeEsiClient:
    """Simula la ESI para una única orden de venta cuyo volume_remain baja entre
    dos corridas — sin competidores en el libro, para no ejercitar compute_position
    más de lo necesario en este test (eso ya lo cubre tests/test_order_position.py)."""

    def __init__(self, order: dict):
        self._order = order

    def get_character_orders(self, character_id, access_token):
        return [self._order]

    def get_orders(self, region_id, order_type, type_id):
        return [{"order_id": self._order["order_id"], "price": self._order["price"]}]


def test_check_character_orders_persists_partial_fill(tmp_path, monkeypatch):
    """D1 (indirecto): hasta ahora un fill parcial solo viajaba a Telegram y se
    perdía — este test confirma que además queda en character_order_fill, que es
    lo que lee el nuevo endpoint /api/character-orders/fills."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (34, 'Tritanium')")
    conn.commit()
    conn.close()

    monkeypatch.setattr("scheduler.orders_run.get_valid_session", lambda: ("token", 123))
    monkeypatch.setattr("scheduler.orders_run.get_current_wallet_balance", lambda: 1_000_000.0)
    monkeypatch.setattr("scheduler.orders_run.dispatch", lambda events: None)

    order = {
        "order_id": 1, "type_id": 34, "region_id": 10000002, "is_buy_order": False,
        "price": 5.0, "volume_remain": 100, "volume_total": 200, "issued": "2026-01-01T00:00:00Z",
    }

    # Primera corrida: siembra el estado inicial (sin fill todavía, nada que comparar).
    check_character_orders(_FakeEsiClient(order), db_path, notify=False)

    # Segunda corrida: se ejecutaron 30 unidades (volume_remain 100 -> 70).
    order["volume_remain"] = 70
    check_character_orders(_FakeEsiClient(order), db_path, notify=False)

    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM character_order_fill").fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0]["order_id"] == 1
    assert rows[0]["type_id"] == 34
    assert rows[0]["filled_units"] == 30
    assert rows[0]["volume_remain"] == 70


class _FakeOrdersClient:
    """Más general que _FakeEsiClient: lista de órdenes activas, libro por ítem, e
    historial de órdenes cerradas configurables — para los escenarios de D3
    (undercut, cierre de órdenes, flag notify) que no dependen de un único order_id
    fijo."""

    def __init__(self, orders=None, book=None, history=None):
        self._orders = orders or []
        self._book = book if book is not None else []
        self._history = history if history is not None else []

    def get_character_orders(self, character_id, access_token):
        return self._orders

    def get_orders(self, region_id, order_type, type_id):
        return self._book

    def get_character_order_history(self, character_id, access_token):
        return self._history


def _seed_item_type(db_path, type_id=34, name="Tritanium"):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (?, ?)", (type_id, name))
    conn.commit()
    conn.close()


def test_check_character_orders_returns_without_touching_anything_if_no_esi_session(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    monkeypatch.setattr("scheduler.orders_run.get_valid_session", lambda: None)
    dispatched = []
    monkeypatch.setattr("scheduler.orders_run.dispatch", lambda events: dispatched.append(events))

    # No debería ni tocar la DB -- si lo hiciera, un client que revienta al usarse lo revelaría.
    class _ExplodingClient:
        def get_character_orders(self, *a, **k):
            raise AssertionError("no debería llamarse sin sesión ESI")

    check_character_orders(_ExplodingClient(), db_path, notify=True)

    assert dispatched == []


def test_check_character_orders_dispatches_position_changed_only_when_undercut_appears(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_item_type(db_path)
    monkeypatch.setattr("scheduler.orders_run.get_valid_session", lambda: ("token", 123))
    monkeypatch.setattr("scheduler.orders_run.get_current_wallet_balance", lambda: 500.0)
    dispatched = []
    monkeypatch.setattr("scheduler.orders_run.dispatch", lambda events: dispatched.append(list(events)))

    order = {
        "order_id": 1, "type_id": 34, "region_id": 10000002, "is_buy_order": False,
        "price": 5.0, "volume_remain": 100, "volume_total": 100, "issued": "2026-01-01T00:00:00Z",
    }

    # Primera corrida: vas primero (sin competidores) -- no hay "cambio" que notificar.
    check_character_orders(
        _FakeOrdersClient(orders=[order], book=[{"order_id": 1, "price": 5.0}]), db_path, notify=True,
    )
    assert dispatched == [[]]

    # Segunda corrida: aparece un competidor más barato -> te undercutean.
    dispatched.clear()
    check_character_orders(
        _FakeOrdersClient(
            orders=[order], book=[{"order_id": 1, "price": 5.0}, {"order_id": 2, "price": 4.5}],
        ),
        db_path, notify=True,
    )

    assert len(dispatched) == 1 and len(dispatched[0]) == 1
    event = dispatched[0][0]
    assert isinstance(event, PositionChanged)
    assert event.orders_ahead == 1


def test_check_character_orders_notify_false_never_calls_dispatch(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_item_type(db_path)
    monkeypatch.setattr("scheduler.orders_run.get_valid_session", lambda: ("token", 123))
    monkeypatch.setattr("scheduler.orders_run.get_current_wallet_balance", lambda: 500.0)
    dispatch_calls = []
    monkeypatch.setattr("scheduler.orders_run.dispatch", lambda events: dispatch_calls.append(events))

    order = {
        "order_id": 1, "type_id": 34, "region_id": 10000002, "is_buy_order": False,
        "price": 5.0, "volume_remain": 70, "volume_total": 100, "issued": "2026-01-01T00:00:00Z",
    }
    # Un fill parcial genera evento igual (se persiste en character_order_fill), pero
    # con notify=False jamás debería llegar a dispatch() -- lo usa el refresco manual
    # de la app para no duplicar el aviso que ya mandó (o va a mandar) el motor de 5min.
    check_character_orders(
        _FakeOrdersClient(orders=[order], book=[{"order_id": 1, "price": 5.0}]), db_path, notify=False,
    )

    assert dispatch_calls == []


def test_check_character_orders_closes_an_order_and_infers_completed_from_zero_remain(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_item_type(db_path)
    monkeypatch.setattr("scheduler.orders_run.get_valid_session", lambda: ("token", 123))
    monkeypatch.setattr("scheduler.orders_run.get_current_wallet_balance", lambda: 500.0)
    monkeypatch.setattr("scheduler.orders_run.dispatch", lambda events: None)

    order = {
        "order_id": 1, "type_id": 34, "region_id": 10000002, "is_buy_order": False,
        "price": 5.0, "volume_remain": 10, "volume_total": 100, "issued": "2026-01-01T00:00:00Z",
    }
    check_character_orders(
        _FakeOrdersClient(orders=[order], book=[{"order_id": 1, "price": 5.0}]), db_path,
    )
    # La ESI no vuelve a mostrar la orden como completada con volume_remain=0 antes de
    # que desaparezca -- se fuerza acá para ejercitar la inferencia documentada en
    # _resolve_closed_order_state (ver scheduler/orders_run.py).
    conn = get_connection(db_path)
    conn.execute("UPDATE character_order SET volume_remain = 0 WHERE order_id = 1")
    conn.commit()
    conn.close()

    # Segunda corrida: la orden ya no aparece entre las activas, y tampoco en el
    # historial de la ESI (típico si se completó hace poco).
    check_character_orders(_FakeOrdersClient(orders=[], history=[]), db_path)

    conn = get_connection(db_path)
    closed = conn.execute("SELECT * FROM character_order_closed").fetchall()
    still_active = conn.execute("SELECT * FROM character_order").fetchall()
    conn.close()

    assert len(closed) == 1
    assert closed[0]["final_state"] == "completada"
    assert still_active == []


def test_check_character_orders_closes_an_order_as_cancelled_per_esi_history(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_item_type(db_path)
    monkeypatch.setattr("scheduler.orders_run.get_valid_session", lambda: ("token", 123))
    monkeypatch.setattr("scheduler.orders_run.get_current_wallet_balance", lambda: 500.0)
    monkeypatch.setattr("scheduler.orders_run.dispatch", lambda events: None)

    order = {
        "order_id": 1, "type_id": 34, "region_id": 10000002, "is_buy_order": True,
        "price": 5.0, "volume_remain": 40, "volume_total": 100, "issued": "2026-01-01T00:00:00Z",
    }
    check_character_orders(
        _FakeOrdersClient(orders=[order], book=[{"order_id": 1, "price": 5.0}]), db_path,
    )

    check_character_orders(
        _FakeOrdersClient(orders=[], history=[{"order_id": 1, "state": "cancelled", "volume_remain": 40}]),
        db_path,
    )

    conn = get_connection(db_path)
    closed = conn.execute("SELECT * FROM character_order_closed").fetchone()
    conn.close()
    assert closed["final_state"] == "cancelada"
