#!/usr/bin/env python3
"""Auditoría independiente de la clasificación de ítems (solo lectura, solo biblioteca estándar).

Reimplementa aquí, sin importar el motor (analytics/classification.py, analytics/eve_calculator.py), las reglas de
estado POTENCIAL / POTENCIAL_SIN_ORDENES / EN_OBSERVACION / DESCARTADO y las compara con `item_status`:

- coherencia: el estado guardado es el que dictan las reglas con los insumos guardados (spread, liquidez,
  actividad de 7 días y ajustes de `app_settings`), y la banda de spread corresponde a los precios guardados;
- congelados: filas que el último ciclo del mercado no volvió a evaluar (se muestran con un estado viejo);
- datos crudos: el estado recalculado desde el último snapshot y el histórico, con la ventana de filas que usa
  el motor y con una ventana de días naturales (ítems poco líquidos: 7 filas pueden abarcar semanas).

Uso (en la VM, el script no va en la imagen):
    docker exec -i evemarket-api python - --wallet 226046089.85 < scripts/audit_classification.py

`--wallet` es el ISK con el que el motor calculó la liquidez (línea "Wallet ISK" del log del scheduler); sin él
se usa `volumen_deseado_fallback`. Sale con código 1 si hay incoherencias o filas congeladas; con `--strict-window`,
también si algún estado cambiaría al medir la actividad en días naturales.
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

CYCLE_SLACK_MIN = 10          # una fila evaluada más de 10 min antes que la última del mercado no es de ese ciclo
SPREAD_BANDS = ("spread_perdida_max", "spread_casi_cero_max", "spread_pequeno_max", "spread_buen_margen_max",
                "spread_muy_bueno_max")
SPREAD_CODES = ("P", "CC", "PB", "BM", "MB", "EX")
LIQ_BANDS = ("liquidez_excelente_max", "liquidez_buena_max", "liquidez_aceptable_max", "liquidez_cuidado_max")
LIQ_CODES = ("EXC", "BUE", "ACE", "CUI", "LENTA")
SPREAD_LABEL = {"❌ Pérdida": "P", "🟡 Casi cero": "CC", "🟢 Pequeño beneficio": "PB", "🟢 Buen margen": "BM",
                "🟢🟢 Muy bueno": "MB", "🟢🟢🟢 Excelente, si existe volumen": "EX"}
LIQ_LABEL = {"Excelente liquidez": "EXC", "Buena": "BUE", "Aceptable": "ACE", "Cuidado": "CUI",
             "Muy lenta para tu capital": "LENTA"}
SAMPLE = 8


def band(value: float, settings: dict, keys: tuple, codes: tuple) -> str:
    for key, code in zip(keys, codes):
        if value < settings[key]:
            return code
    return codes[-1]


def rule(spread: str, liquidity: str, vol7: float, ops7: float, settings: dict) -> str:
    """Las reglas de estado, escritas de nuevo a partir de su documentación."""
    if spread == "P" or liquidity == "LENTA":
        return "DESCARTADO"
    if spread in ("BM", "MB", "EX") and liquidity in ("EXC", "BUE"):
        vmin = settings["min_daily_volume_7d"]
        volume_ok = vmin <= 0 or vol7 >= vmin
        return "POTENCIAL" if volume_ok and ops7 >= settings["min_daily_order_count_7d"] else "POTENCIAL_SIN_ORDENES"
    return "EN_OBSERVACION"


def wanted_units(buy: float, wallet: float | None, settings: dict) -> float:
    if wallet is None or buy <= 0:
        return settings["volumen_deseado_fallback"]
    return max(wallet * settings["position_size_pct_wallet"] / buy, 1)


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def raw_status(snap, rows: list, anchor: date, wallet: float | None, settings: dict, calendar: bool) -> str:
    """Estado desde los datos crudos. `calendar`: actividad sobre 7/30 días naturales hasta `anchor` (los días sin
    fila cuentan 0); si no, sobre las últimas 7/30 filas, como hace hoy el motor."""
    last30 = rows[-30:]
    ref = median([r["avg_price"] for r in last30])
    sane = ref > 0 and snap["best_buy"] >= ref * settings["sanity_min_ratio"] \
        and snap["best_sell"] <= ref * settings["sanity_max_ratio"]
    if calendar:
        cut7, cut30 = (anchor - timedelta(days=6)).isoformat(), (anchor - timedelta(days=29)).isoformat()
        vol30 = sum(r["volume"] for r in rows if r["date"] >= cut30) / 30
        vol7 = sum(r["volume"] for r in rows if r["date"] >= cut7) / 7
        ops7 = sum(r["order_count"] for r in rows if r["date"] >= cut7) / 7
    else:
        last7 = rows[-7:]
        vol30 = sum(r["volume"] for r in last30) / len(last30)
        vol7 = sum(r["volume"] for r in last7) / len(last7)
        ops7 = sum(r["order_count"] for r in last7) / len(last7)
    if not sane or vol30 <= 0:
        return "DESCARTADO"
    spread = band(snap["best_sell"] / snap["best_buy"] - 1, settings, SPREAD_BANDS, SPREAD_CODES)
    liquidity = band(wanted_units(snap["best_buy"], wallet, settings) / vol30, settings, LIQ_BANDS, LIQ_CODES)
    return rule(spread, liquidity, vol7, ops7, settings)


def audit_market(conn, market: str, settings: dict, wallet: float | None) -> dict:
    found = defaultdict(list)
    counts = Counter()
    latest_eval = conn.execute("SELECT MAX(last_evaluated_at) FROM item_status WHERE market_id = ?",
                               (market,)).fetchone()[0]
    if latest_eval is None:
        return {"counts": {}, "issues": {}}
    cycle_cut = (datetime.fromisoformat(latest_eval) - timedelta(minutes=CYCLE_SLACK_MIN)).isoformat()
    hist_max = conn.execute("SELECT MAX(date) FROM market_history WHERE market_id = ?", (market,)).fetchone()[0]
    anchor = date.fromisoformat(hist_max) if hist_max else None
    history = defaultdict(list)
    for r in conn.execute("SELECT type_id, date, avg_price, volume, order_count FROM market_history "
                          "WHERE market_id = ? ORDER BY type_id, date", (market,)):
        history[r["type_id"]].append(r)
    snaps = {r["type_id"]: r for r in conn.execute(
        "SELECT s.* FROM market_snapshot s WHERE s.market_id = ? AND s.captured_at = (SELECT MAX(s2.captured_at) "
        "FROM market_snapshot s2 WHERE s2.market_id = s.market_id AND s2.type_id = s.type_id)", (market,))}

    for row in conn.execute("SELECT * FROM item_status WHERE market_id = ?", (market,)):
        type_id, status = row["type_id"], row["status"]
        counts[status] += 1
        snap, rows = snaps.get(type_id), history.get(type_id, [])
        if row["last_evaluated_at"] < cycle_cut:
            age_h = (datetime.fromisoformat(latest_eval) - datetime.fromisoformat(row["last_evaluated_at"])
                     ).total_seconds() / 3600
            why = ("sin snapshot" if snap is None else "sin compra" if not snap["best_buy"]
                   else "sin venta" if not snap["best_sell"] else "sin histórico" if not rows else "otro")
            found["stale"].append({"type_id": type_id, "status": status, "age_h": round(age_h, 1), "why": why})
            continue
        if "basura" in (row["reason"] or "") or not row["best_buy"] or not row["best_sell"] \
                or not row["volumen_diario_real"]:
            continue    # descartado por el filtro de basura (o sin precios): no lo deciden las bandas
        spread = band(row["best_sell"] / row["best_buy"] - 1, settings, SPREAD_BANDS, SPREAD_CODES)
        if SPREAD_LABEL.get(row["evaluacion_spread"]) != spread:
            found["spread_band"].append({"type_id": type_id, "stored": row["evaluacion_spread"], "expected": spread})
        expected = rule(SPREAD_LABEL.get(row["evaluacion_spread"]), LIQ_LABEL.get(row["liquidez"]),
                        row["avg_daily_volume_7d"], row["avg_daily_order_count_7d"], settings)
        if expected != status:
            found["status_vs_inputs"].append({"type_id": type_id, "stored": status, "expected": expected})
        liquidity = band(wanted_units(row["best_buy"], wallet, settings) / row["volumen_diario_real"],
                         settings, LIQ_BANDS, LIQ_CODES)
        if LIQ_LABEL.get(row["liquidez"]) != liquidity:
            found["liquidity_vs_capital"].append({"type_id": type_id, "stored": row["liquidez"], "expected": liquidity})
        if snap is None or not rows or not snap["best_buy"] or not snap["best_sell"] or anchor is None:
            continue
        by_rows = raw_status(snap, rows, anchor, wallet, settings, calendar=False)
        if by_rows != status:
            found["raw_rows"].append({"type_id": type_id, "stored": status, "raw": by_rows})
        span = (anchor - date.fromisoformat(rows[-7:][0]["date"])).days + 1
        if span > 7:
            found["window_stretched"].append({"type_id": type_id, "status": status, "days": span})
        by_calendar = raw_status(snap, rows, anchor, wallet, settings, calendar=True)
        if by_calendar != status:
            found["calendar_change"].append({"type_id": type_id, "stored": status, "calendar": by_calendar,
                                             "days": span})

    issues = {}
    for key, items in found.items():
        entry = {"n": len(items), "sample": items[:SAMPLE]}
        if key == "stale":
            entry["by_status"] = dict(Counter(i["status"] for i in items))
            entry["why"] = dict(Counter(i["why"] for i in items))
            entry["older_than_7d"] = sum(i["age_h"] >= 168 for i in items)
        if key == "calendar_change":
            entry["transitions"] = dict(Counter(f"{i['stored']}->{i['calendar']}" for i in items).most_common())
        issues[key] = entry
    return {"counts": dict(counts), "latest_eval": latest_eval, "history_until": hist_max, "issues": issues}


def audit(db_path: str, wallet: float | None = None) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings")}
        markets = [r[0] for r in conn.execute("SELECT market_id FROM market WHERE enabled = 1 ORDER BY sort_order")]
        return {"wallet": wallet, "markets": {m: audit_market(conn, m, settings, wallet) for m in markets}}
    finally:
        conn.close()


def failures(report: dict, strict_window: bool = False) -> int:
    keys = ["status_vs_inputs", "spread_band", "stale"] + (["calendar_change"] if strict_window else [])
    return sum(m["issues"].get(k, {}).get("n", 0) for m in report["markets"].values() for k in keys)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default="storage/market.db")
    p.add_argument("--wallet", type=float, default=None, help="ISK usado por el motor para la liquidez")
    p.add_argument("--strict-window", action="store_true", help="falla también si la ventana natural cambia estados")
    args = p.parse_args(argv)
    report = audit(args.db, args.wallet)
    bad = failures(report, args.strict_window)
    report["failures"] = bad
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
