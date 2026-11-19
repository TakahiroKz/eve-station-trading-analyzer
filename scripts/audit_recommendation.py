#!/usr/bin/env python3
"""Auditoría independiente de la recomendación de unidades (solo lectura, solo biblioteca estándar).

Recalcula desde cero, con las fórmulas escritas a mano aquí (sin importar código del proyecto), lo que la API
devuelve en `GET /api/items/{id}?capital=...` -> `recommendation`, y lo compara. Con `--esi` compara además los
precios y los volúmenes guardados contra la ESI en vivo (veracidad de los datos de origen).

Uso (en la VM o donde llegue la API):
    python3 scripts/audit_recommendation.py --base http://127.0.0.1:8001 --per-market 40 --settings-db storage/market.db
    python3 scripts/audit_recommendation.py --esi --per-market 15

Sale con código 1 si encuentra discrepancias.
"""
import argparse
import json
import math
import random
import re
import sqlite3
import statistics
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REGIONS = {"jita": 10000002, "amarr": 10000043, "dodixie": 10000032, "rens": 10000030, "hek": 10000042}
CAPITALS = [None, 50_000_000, 250_000_000, 5_000_000_000, 123_000_000, 7_654_321_000]


def get_json(url: str, timeout: int = 30):
    request = urllib.request.Request(url, headers={"User-Agent": "recommendation-audit"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL fija de la auditoría
        return json.load(response), response.headers


def settings_from_db(path: str | None) -> dict:
    defaults = {"sales_tax_factor": 0.901, "buy_fee_factor": 1.024, "position_size_pct_wallet": 0.10,
                "capture_participation_rate": 0.10, "score_reference_capital": 1_000_000_000.0}
    if not path:
        return defaults
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        defaults.update({k: v for k, v in conn.execute("SELECT key, value FROM app_settings")
                         if k in defaults})
    finally:
        conn.close()
    return defaults


# ---- Fórmulas escritas desde la especificación (no se importa nada del proyecto) ----
def snap(capital: float) -> float:
    step = 10 ** (math.floor(math.log10(capital)) - 1)
    return float(round(capital / step) * step)


def spread_label(spread: float) -> str:
    for limit, label in ((0.14, "loss"), (0.15, "zero"), (0.20, "small"), (0.30, "good"), (0.50, "very_good")):
        if spread < limit:
            return label
    return "excellent"


def liquidity_label(position: float) -> str:
    for limit, label in ((0.10, "excellent"), (0.25, "good"), (0.50, "ok"), (1.00, "careful")):
        if position < limit:
            return label
    return "very_slow"


def engine_units(buy: float, sell: float, desired: float, volume_30d: float) -> tuple[int, str]:
    """Unidades de recomendar() y el texto esperado (por clave)."""
    spread = sell / buy - 1
    sp, lq = spread_label(spread), liquidity_label(desired / volume_30d)
    if sp in ("loss", "zero"):
        return 0, "no_trade"
    if lq == "excellent" and sp in ("good", "very_good", "excellent"):
        return round(desired), "scale"
    if lq in ("excellent", "good"):      # excelente liquidez con un spread que no llega a «buen margen» también se mantiene
        return round(desired), "keep"
    if lq == "ok":
        if sp in ("very_good", "excellent"):
            return round(desired), "very_favorable"
        return round(volume_30d * 0.25), "trim"
    return round(volume_30d * 0.40), "lower"


def expected_block(detail: dict, capital: float | None, s: dict) -> dict:
    status, snap_row = detail["status"], detail["latest_snapshot"] or {}
    buy = snap_row.get("best_buy") or status["best_buy"]
    sell = snap_row.get("best_sell") or status["best_sell"]
    used = snap(capital) if capital is not None else s["score_reference_capital"]
    pct = s["position_size_pct_wallet"]
    position = used * pct
    unit_cost = buy * s["buy_fee_factor"]
    desired = max(position / buy, 1)
    units_engine, kind = engine_units(buy, sell, desired, status["volumen_diario_real"])
    max_units = int(position // unit_cost)
    action = detail["assessment"]["recommendation"]["action"] if detail.get("assessment") else None
    units = 0 if (action == "REJECT" or max_units < 1) else min(units_engine, max_units)
    unit_profit = sell * s["sales_tax_factor"] - buy * s["buy_fee_factor"]
    days = units / (status["avg_daily_volume_7d"] * s["capture_participation_rate"]) \
        if units and status["avg_daily_volume_7d"] > 0 else None
    return {
        "capital": used, "posicion_isk": round(position), "unidades_sugeridas": units, "alcanza": max_units >= 1,
        "precio_unidad_isk": round(unit_cost), "inversion_isk": round(units * unit_cost),
        "beneficio_neto_isk": round(units * unit_profit), "dias_rotacion": None if days is None else round(days, 2),
        "kind": kind,
    }


def text_kind(text: str) -> str:
    for needle, kind in (("No ejecutar", "no_trade"), ("Hay margen para escalar", "scale"), ("bien calibrado", "keep"),
                         ("Spread muy favorable", "very_favorable"), ("Recorta", "trim"), ("Baja el volumen", "lower")):
        if needle in text:
            return kind
    return "unknown"


def compare(actual: dict, expected: dict) -> list[str]:
    problems = []
    for key in ("capital", "posicion_isk", "unidades_sugeridas", "alcanza", "precio_unidad_isk"):
        if actual[key] != expected[key]:
            problems.append(f"{key}: API {actual[key]} != esperado {expected[key]}")
    if expected.get("kind") and expected["kind"] != text_kind(actual["recomendacion"]):
        problems.append(f"frase: API '{actual['recomendacion'][:60]}...' != tipo esperado {expected['kind']}")
    # Importes: el redondeo a unidades enteras puede mover 1 ISK; el resto debe coincidir.
    for key in ("inversion_isk", "beneficio_neto_isk"):
        if abs(actual[key] - expected[key]) > max(2, abs(expected[key]) * 1e-9):
            problems.append(f"{key}: API {actual[key]} != esperado {expected[key]}")
    a, e = actual["dias_rotacion"], expected["dias_rotacion"]
    if (a is None) != (e is None) or (a is not None and abs(a - e) > 0.0051):
        problems.append(f"dias_rotacion: API {a} != esperado {e}")
    # Invariantes que no dependen de nuestra fórmula.
    if actual["inversion_isk"] > actual["posicion_isk"]:
        problems.append("la inversión supera la posición")
    if actual["unidades_sugeridas"] < 0:
        problems.append("unidades negativas")
    if actual["action"] == "REJECT" and (actual["unidades_sugeridas"] or not actual["blocked_by"]):
        problems.append("REJECT debe tener 0 unidades y motivos")
    if actual["action"] != "REJECT" and actual["blocked_by"]:
        problems.append("hay motivos de bloqueo sin REJECT")
    return problems


def sample_items(base: str, market: str, n: int, rng: random.Random) -> list[int]:
    ids: list[int] = []
    for status in ("POTENCIAL", "POTENCIAL_SIN_ORDENES", "EN_OBSERVACION", "DESCARTADO"):
        page, _ = get_json(f"{base}/api/items?market={market}&status={status}&limit=500&sort=volumen_diario_real")
        pool = [i["type_id"] for i in page["items"]]
        ids += rng.sample(pool, min(len(pool), max(1, n // 4)))
    return ids


def audit_math(base: str, per_market: int, s: dict, rng: random.Random) -> int:
    jobs = [(market, tid, cap) for market in REGIONS for tid in sample_items(base, market, per_market, rng)
            for cap in CAPITALS]
    failures: list[str] = []
    stats = {"texts": {}, "checked": 0}

    def run(job):
        market, tid, cap = job
        url = f"{base}/api/items/{tid}?market={market}" + ("" if cap is None else f"&capital={cap}")
        detail, _ = get_json(url)
        block = detail["recommendation"]
        if block is None:
            return [f"{market}/{tid}/{cap}: sin bloque de recomendación"], None
        expected = expected_block(detail, cap, s)
        return [f"{market}/{tid} capital={cap}: {p}" for p in compare(block, expected)], (block, expected)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for problems, pair in pool.map(run, jobs):
            stats["checked"] += 1
            failures += problems
            if pair:
                stats["texts"][pair[1]["kind"]] = stats["texts"].get(pair[1]["kind"], 0) + 1
    print(f"[matemática] {stats['checked']} consultas comparadas; tipos de frase del motor: {stats['texts']}")
    for line in failures[:25]:
        print("  FALLO", line)
    print(f"[matemática] discrepancias: {len(failures)}")
    return len(failures)


def audit_text_vs_numbers(base: str, per_market: int, rng: random.Random, s: dict) -> int:
    """La frase del motor no puede contradecir las cifras que se muestran junto a ella."""
    bad: list[str] = []
    for market in REGIONS:
        for tid in sample_items(base, market, per_market, rng):
            for cap in (None, 50_000_000, 5_000_000_000):
                url = f"{base}/api/items/{tid}?market={market}" + ("" if cap is None else f"&capital={cap}")
                d, _ = get_json(url)
                r = d["recommendation"]
                if not r or r["action"] == "REJECT" or not r["alcanza"]:
                    continue
                vol = d["status"]["volumen_diario_real"]
                position_vs_volume = r["volumen_deseado"] / vol if vol else math.inf
                text = r["recomendacion"]
                if "inmovilizado" in text and position_vs_volume < 0.25:
                    bad.append(f"{market}/{tid} cap={cap}: la frase dice capital inmovilizado pero la posición es "
                               f"{position_vs_volume:.1%} del volumen diario ({text[:80]}...)")
                if "Recorta" in text and position_vs_volume < 0.25:
                    bad.append(f"{market}/{tid} cap={cap}: dice recortar con posición de {position_vs_volume:.1%}")
                quoted = re.search(r"~([d,]+) unidades", text)
                if quoted and "Hay margen" not in text:
                    cited = int(quoted.group(1).replace(",", ""))
                    buy = (d["latest_snapshot"] or {}).get("best_buy") or d["status"]["best_buy"]
                    fits = r["posicion_isk"] / (buy * s["buy_fee_factor"])
                    # La frase cita las unidades del motor; la sugerencia puede ser menor solo si no caben con la comisión.
                    if r["unidades_sugeridas"] != cited and not (r["unidades_sugeridas"] < cited and abs(
                            r["unidades_sugeridas"] - fits) <= 1):
                        bad.append(f"{market}/{tid} cap={cap}: la frase cita {cited} unidades y se sugieren "
                                   f"{r['unidades_sugeridas']} (caben {fits:.0f})")
                if r["dias_rotacion"] is not None and r["dias_rotacion"] > 30 and "Hay margen" in text:
                    bad.append(f"{market}/{tid} cap={cap}: 'hay margen' con {r['dias_rotacion']} días de rotación")
    print(f"[texto vs cifras] contradicciones: {len(bad)}")
    for line in bad[:25]:
        print("  CONTRADICCIÓN", line)
    return len(bad)


# ---- Veracidad frente a la ESI ----
def esi_best_prices(region: int, type_id: int) -> tuple[float | None, float | None, int]:
    buys: list[float] = []
    sells: list[float] = []
    page, total = 1, 1
    while page <= total:
        data, headers = get_json(f"https://esi.evetech.net/latest/markets/{region}/orders/"
                                 f"?type_id={type_id}&order_type=all&page={page}", timeout=40)
        total = int(headers.get("X-Pages", 1))
        for order in data:
            (buys if order["is_buy_order"] else sells).append(order["price"])
        page += 1
    return (max(buys) if buys else None, min(sells) if sells else None, len(buys) + len(sells))


def esi_history(region: int, type_id: int) -> list[dict]:
    try:
        return get_json(f"https://esi.evetech.net/latest/markets/{region}/history/?type_id={type_id}", timeout=40)[0]
    except urllib.error.HTTPError:
        return []


def audit_esi(base: str, per_market: int, rng: random.Random) -> int:
    price_gaps: list[float] = []
    problems: list[str] = []
    volume_checked = volume_exact = 0
    for market, region in REGIONS.items():
        page, _ = get_json(f"{base}/api/items?market={market}&status=POTENCIAL&limit=200&sort=volumen_diario_real")
        for item in rng.sample(page["items"], min(per_market, len(page["items"]))):
            tid = item["type_id"]
            detail, _ = get_json(f"{base}/api/items/{tid}?market={market}")
            snap_row = detail["latest_snapshot"]
            if not snap_row:
                continue
            buy, sell, orders = esi_best_prices(region, tid)
            for label, ours, live in (("compra", snap_row["best_buy"], buy), ("venta", snap_row["best_sell"], sell)):
                if ours is None or live is None:
                    continue
                gap = abs(ours - live) / live
                price_gaps.append(gap)
                if gap > 0.25:
                    problems.append(f"{market}/{tid} {item['name']}: mejor precio de {label} {ours} vs ESI {live} "
                                    f"({gap:.0%})")
            history = esi_history(region, tid)
            last7 = history[-7:]
            if last7 and detail["history"]:
                ours_days = {h["date"]: h["volume"] for h in detail["history"]}
                matched = [(d["date"], d["volume"], ours_days[d["date"]]) for d in last7 if d["date"] in ours_days]
                for date, live_volume, our_volume in matched:
                    volume_checked += 1
                    volume_exact += live_volume == our_volume
                    if live_volume != our_volume:
                        problems.append(f"{market}/{tid} {date}: volumen guardado {our_volume} vs ESI {live_volume}")
    median = statistics.median(price_gaps) if price_gaps else float("nan")
    within5 = sum(g <= 0.05 for g in price_gaps) / len(price_gaps) if price_gaps else float("nan")
    print(f"[ESI] precios comparados: {len(price_gaps)}; diferencia mediana {median:.2%}; dentro del 5 %: {within5:.0%}")
    print(f"[ESI] volúmenes diarios comparados: {volume_checked}; idénticos: {volume_exact}")
    for line in problems[:25]:
        print("  DIFERENCIA", line)
    print(f"[ESI] diferencias relevantes: {len(problems)}")
    return len(problems)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--per-market", type=int, default=40)
    parser.add_argument("--settings-db", default=None, help="market.db (solo lectura) para leer comisiones y %")
    parser.add_argument("--esi", action="store_true", help="comparar también con la ESI en vivo")
    parser.add_argument("--skip-math", action="store_true", help="omite la auditoría matemática (solo --esi)")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    settings = settings_from_db(args.settings_db)
    print("ajustes usados:", settings)
    total = 0
    if not args.skip_math:
        total += audit_math(args.base, args.per_market, settings, rng)
        total += audit_text_vs_numbers(args.base, max(8, args.per_market // 4), rng, settings)
    if args.esi:
        total += audit_esi(args.base, args.per_market, rng)
    print("RESULTADO:", "sin discrepancias" if total == 0 else f"{total} discrepancias")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
