"""scripts/audit_classification.py: detecta incoherencias de estado, filas congeladas y ventanas estiradas, y sus
reglas reescritas coinciden con las del motor."""
import importlib.util
import itertools
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from analytics.classification import classify
from analytics.eve_calculator import DEFAULT_CONFIG, evaluar_liquidez, evaluar_spread
from storage.db import get_app_settings_dict, init_db

_SPEC = importlib.util.spec_from_file_location(
    "audit_classification", Path(__file__).resolve().parents[1] / "scripts" / "audit_classification.py")
audit_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_mod)

NOW = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)
ANCHOR = date(2026, 11, 25)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "audit.db")
    init_db(path)
    return path


def add_item(path, type_id, status, *, buy=100.0, sell=150.0, spread_label="🟢🟢🟢 Excelente, si existe volumen",
             liquidity="Buena", vol7=1000.0, ops7=50.0, vol30=1000.0, evaluated=NOW,
             history_days=range(30), volume=1000, ops=50, snapshot=True):
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO item_type (type_id, name) VALUES (?, ?)", (type_id, f"item {type_id}"))
    conn.execute(
        "INSERT INTO item_status (market_id, type_id, status, reason, spread_bruto, evaluacion_spread, liquidez, roi, "
        "best_buy, best_sell, volumen_diario_real, avg_daily_volume_7d, avg_daily_order_count_7d, last_evaluated_at) "
        "VALUES ('jita', ?, ?, 'r', ?, ?, ?, 0.3, ?, ?, ?, ?, ?, ?)",
        (type_id, status, round(sell / buy - 1, 4), spread_label, liquidity, buy, sell, vol30, vol7, ops7,
         evaluated.isoformat()))
    for d in history_days:
        conn.execute("INSERT INTO market_history (market_id, type_id, date, avg_price, highest, lowest, volume, "
                     "order_count) VALUES ('jita', ?, ?, 120, 130, 110, ?, ?)",
                     (type_id, (ANCHOR - timedelta(days=d)).isoformat(), volume, ops))
    if snapshot:
        conn.execute("INSERT INTO market_snapshot (market_id, type_id, captured_at, best_buy, best_sell, "
                     "buy_order_count, sell_order_count) VALUES ('jita', ?, ?, ?, ?, 5, 5)",
                     (type_id, evaluated.isoformat(), buy, sell))
    conn.commit()
    conn.close()


def jita(report):
    return report["markets"]["jita"]["issues"]


def test_a_coherent_liquid_item_raises_nothing(db):
    add_item(db, 1, "POTENCIAL")
    report = audit_mod.audit(db, wallet=None)
    assert jita(report) == {} and audit_mod.failures(report) == 0


def test_a_status_that_contradicts_its_inputs_is_reported(db):
    add_item(db, 1, "POTENCIAL")
    add_item(db, 2, "EN_OBSERVACION")          # mismos insumos que el 1: debería ser POTENCIAL
    issues = jita(audit_mod.audit(db))
    assert issues["status_vs_inputs"]["n"] == 1
    assert issues["status_vs_inputs"]["sample"][0] == {"type_id": 2, "stored": "EN_OBSERVACION", "expected": "POTENCIAL"}


def test_a_row_the_last_cycle_did_not_evaluate_is_frozen(db):
    add_item(db, 1, "POTENCIAL")
    add_item(db, 2, "POTENCIAL", evaluated=NOW - timedelta(days=50), snapshot=False)
    report = audit_mod.audit(db)
    stale = jita(report)["stale"]
    assert stale["n"] == 1 and stale["by_status"] == {"POTENCIAL": 1} and stale["older_than_7d"] == 1
    assert stale["why"] == {"sin snapshot": 1}
    assert audit_mod.failures(report) == 1


def test_seven_rows_spread_over_weeks_are_a_stretched_window(db):
    add_item(db, 1, "POTENCIAL")
    # 7 días con operaciones repartidos en 31 días: por filas 50 ops/día, por calendario 8/7 ops y 200 u/día (30 d)
    add_item(db, 2, "POTENCIAL", history_days=[0, 5, 10, 15, 20, 25, 30], ops=4, volume=1000, ops7=4.0)
    report = audit_mod.audit(db)
    issues = jita(report)
    assert issues["window_stretched"]["sample"][0] == {"type_id": 2, "status": "POTENCIAL", "days": 31}
    assert issues["calendar_change"]["transitions"] == {"POTENCIAL->EN_OBSERVACION": 1}
    assert audit_mod.failures(report) == 0 and audit_mod.failures(report, strict_window=True) == 1


def test_the_rewritten_rules_match_the_engine(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    settings = get_app_settings_dict(conn)
    conn.close()
    spreads = [-0.1, 0.139, 0.14, 0.149, 0.15, 0.2, 0.29, 0.3, 0.49, 0.5, 2.0]
    positions = [0.0, 0.099, 0.1, 0.24, 0.25, 0.49, 0.5, 0.99, 1.0, 3.0]
    activity = [(0, 0), (9.9, 3), (10, 2.9), (10, 3), (500, 40)]
    inverse_spread = {v: k for k, v in audit_mod.SPREAD_LABEL.items()}
    for s, p, (v, o) in itertools.product(spreads, positions, activity):
        spread_label, liq_label = evaluar_spread(s, DEFAULT_CONFIG), evaluar_liquidez(p, DEFAULT_CONFIG)
        code_s = audit_mod.band(s, settings, audit_mod.SPREAD_BANDS, audit_mod.SPREAD_CODES)
        code_l = audit_mod.band(p, settings, audit_mod.LIQ_BANDS, audit_mod.LIQ_CODES)
        assert inverse_spread[code_s] == spread_label and audit_mod.LIQ_LABEL[liq_label] == code_l
        assert audit_mod.rule(code_s, code_l, v, o, settings) == classify(spread_label, liq_label, v, o)[0]
