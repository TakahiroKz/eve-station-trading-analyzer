#!/usr/bin/env python3
"""Pruebas de mutación del Screener personalizado (?profile=mine): bandas, ROI, estado, filtros, caché y cabeceras."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_check as mc  # noqa: E402

mc.TESTS = ["tests/test_personalized_screener.py"]
P, M, U = "backend/api/personalize.py", "backend/api/main.py", "finance/user_profile.py"
mc.MUTATIONS = [
    ("las bandas de spread no se trasladan a las comisiones del jugador", P,
     "out[key] = round((1 + float(settings[key])) * k - 1, 10)", "out[key] = float(settings[key])"),
    ("las bandas se trasladan al revés", P, "k = (st0 * buy_fee_factor) / (bf0 * sales_tax_factor)",
     "k = (bf0 * sales_tax_factor) / (st0 * buy_fee_factor)"),
    ("el ROI personal usa los factores cruzados", P, "sell * config.sales_tax_factor / (buy * config.buy_fee_factor) - 1",
     "sell * config.buy_fee_factor / (buy * config.sales_tax_factor) - 1"),
    ("un precio incoherente se reclasifica", P, "[\"sane\"]:\n        out[\"status\"]", "[\"sane\"] or True:\n        out[\"status\"]"),
    ("el estado no se vuelve a clasificar", P,
     "if parse_inputs_blob(row[\"score_inputs\"] if \"score_inputs\" in row.keys() else None)[\"sane\"]:", "if False:"),
    ("la evaluación del spread no se actualiza", P, "out[\"evaluacion_spread\"] = spread_eval", "pass"),
    ("el filtro de ROI usa el factor de compra en la venta", P, "{column_sell} * {fv!r}", "{column_sell} * {fc!r}"),
    ("el filtro de ROI ignora el mínimo pedido", P, "* (1 + ?))\"", "* (1 + 0 * ?))\""),
    ("el filtro de ROI acepta precios de compra no positivos", P, "({column_buy} > 0 AND ", "("),
    ("profile=mine sin sesión no da 401", P, "if user is None:", "if False:"),
    ("profile=mine con las cuentas apagadas no da 503", P, "if _config() is None:", "if False:"),
    ("las respuestas personales se pueden cachear", P, "PRIVATE = {\"Cache-Control\": \"private, no-store\", \"Vary\": \"Cookie\"}", "PRIVATE = {}"),
    ("el perfil por defecto se marca como personalizado", P, "\"personalized\": active}", "\"personalized\": True}"),
    ("siempre se considera activo el perfil", P, "active = (st, bf) != (", "active = True or (st, bf) != ("),
    ("las comisiones de venta no incluyen el impuesto", U, "(1 - tax - broker).quantize", "(1 - broker).quantize"),
    ("las comisiones de compra no incluyen el broker", U, "float((1 + broker).quantize(step, ROUND_HALF_UP))",
     "float((1 + 0 * broker).quantize(step, ROUND_HALF_UP))"),
    ("el filtro de estado de SQL sigue activo con comisiones propias", M, "if status and not personal:", "if status:"),
    ("el filtro de estado no recorre el mercado con comisiones propias", M,
     "or sort == \"score\" or (personal and status is not None))", "or sort == \"score\")"),
    ("el filtro de estado propio no se aplica", M, "if personal and status is not None and (hit is None or hit[5] != status):", "if False:"),
    ("el recorrido de mercado no devuelve ROI ni estado propios", M,
     "row.update(roi=hit[4], status=hit[5], evaluacion_spread=hit[6], reason=hit[7])", "pass"),
    ("el detalle no recalcula la cabecera con las comisiones propias", M,
     "status_dict = rescore_row(status_row, settings, make_configs(settings), personal)",
     "status_dict = rescore_row(status_row, settings, make_configs(settings), False)"),
    ("el detalle no recalcula las unidades con las comisiones propias", M, "ctx if personal else None),\n            profile=", "None),\n            profile="),
    ("el detalle no recalcula la evaluación con las comisiones propias", M,
     "build_assessment(status_row, conn, capital, ctx if personal else None)", "build_assessment(status_row, conn, capital, None)"),
    ("el detalle personal se puede cachear", M, "response.headers.update(PRIVATE)\n    personal = ctx is not None and ctx.active\n    conn = _db()",
     "personal = ctx is not None and ctx.active\n    conn = _db()"),
    ("el listado personal se puede cachear", M, "response.headers.update(PRIVATE)       # datos del jugador", "pass                                    # datos del jugador"),
    ("el listado sin puntaje conserva el ROI de referencia", M, "out = personalize_row(out, settings)       # también", "pass       # también"),
]

if __name__ == "__main__":
    sys.exit(mc.main())
