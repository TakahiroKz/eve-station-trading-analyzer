"""Registro central de todos los parámetros configurables del programa (Ajustes).

Única fuente de verdad: de acá salen (a) las filas que se siembran en app_settings la
primera vez, (b) el default al que vuelve cada parámetro al "Restablecer valores por
defecto", y (c) la categoría/label/descripción que arma la pantalla "Ajustes" de la PWA.
Agregar un parámetro nuevo es agregar una entrada acá — storage/db.py y la API ya
funcionan de forma genérica sobre esta lista, no hace falta tocarlos.

Los `key` son también los nombres de campo de analytics.eve_calculator.EveCalculatorConfig
y analytics.sanity.SanityConfig (salvo min_daily_volume_7d/min_daily_order_count_7d, que
alimentan analytics.classification.classify()) — así scheduler/run.py arma esos configs
directo con **kwargs filtrados desde el dict de settings, sin mapeo manual campo por campo.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SettingDef:
    key: str
    category: str
    label: str
    description: str
    default_value: float


SETTINGS: list[SettingDef] = [
    # --- Clasificación (AlertRules) ---
    SettingDef(
        "min_daily_volume_7d", "Clasificación", "Volumen mínimo diario (unidades, prom. 7d)",
        "Debajo de este promedio de unidades/día vendidas (últimos 7 días), un ítem con buen "
        "spread y liquidez cuenta como POTENCIAL_SIN_ORDENES en vez de POTENCIAL. Depende "
        "directo del costo del ítem — poné 0 para no usarlo como criterio.",
        10.0,
    ),
    SettingDef(
        "min_daily_order_count_7d", "Clasificación", "Operaciones mínimas diarias (prom. 7d)",
        "Operaciones ejecutadas distintas/día (últimos 7 días) mínimas para descartar 'una sola "
        "ballena'. Indispensable — siempre se evalúa, no se puede poner en 0.",
        3.0,
    ),

    # --- Fees de EVE (EveCalculator) ---
    SettingDef(
        "sales_tax_factor", "Fees de EVE", "Factor de sales tax (neto)",
        "Multiplicador aplicado al precio de venta después de impuestos. Default 0.901 = 9.9% "
        "de impuesto. Bajalo si tu skill de Accounting o tus standings reducen tu sales tax real.",
        0.901,
    ),
    SettingDef(
        "buy_fee_factor", "Fees de EVE", "Factor de comisión de compra (neto)",
        "Multiplicador aplicado al precio de compra por comisión de broker. Default 1.024 = 2.4% "
        "de comisión. Bajalo si tu skill de Broker Relations reduce tu comisión real.",
        1.024,
    ),

    # --- Umbrales de spread ---
    SettingDef(
        "spread_perdida_max", "Umbrales de spread", "Techo de spread 'Pérdida' (❌)",
        "Spread por debajo de este valor (ej. 0.14 = 14%) se clasifica como Pérdida.", 0.14,
    ),
    SettingDef(
        "spread_casi_cero_max", "Umbrales de spread", "Techo de spread 'Casi cero' (🟡)",
        "Spread por debajo de este valor (y por encima del techo de Pérdida) es Casi cero.", 0.15,
    ),
    SettingDef(
        "spread_pequeno_max", "Umbrales de spread", "Techo de spread 'Pequeño beneficio' (🟢)",
        "Spread por debajo de este valor es Pequeño beneficio.", 0.20,
    ),
    SettingDef(
        "spread_buen_margen_max", "Umbrales de spread", "Techo de spread 'Buen margen' (🟢)",
        "Spread por debajo de este valor es Buen margen.", 0.30,
    ),
    SettingDef(
        "spread_muy_bueno_max", "Umbrales de spread", "Techo de spread 'Muy bueno' (🟢🟢)",
        "Spread por debajo de este valor es Muy bueno; por encima, Excelente si existe volumen.",
        0.50,
    ),

    # --- Umbrales de liquidez ---
    SettingDef(
        "liquidez_excelente_max", "Umbrales de liquidez", "Techo de liquidez 'Excelente'",
        "Posición deseada vs. volumen diario real por debajo de este valor (ej. 0.10 = 10%) es "
        "Excelente liquidez.", 0.10,
    ),
    SettingDef(
        "liquidez_buena_max", "Umbrales de liquidez", "Techo de liquidez 'Buena'",
        "Por debajo de este valor la liquidez es Buena.", 0.25,
    ),
    SettingDef(
        "liquidez_aceptable_max", "Umbrales de liquidez", "Techo de liquidez 'Aceptable'",
        "Por debajo de este valor la liquidez es Aceptable.", 0.50,
    ),
    SettingDef(
        "liquidez_cuidado_max", "Umbrales de liquidez", "Techo de liquidez 'Cuidado'",
        "Por debajo de este valor la liquidez es Cuidado; por encima, Muy lenta para tu capital "
        "(el ítem queda DESCARTADO).", 1.00,
    ),

    # --- Tamaño de posición (wallet) ---
    SettingDef(
        "position_size_pct_wallet", "Tamaño de posición", "% del wallet por posición",
        "Porcentaje de tu wallet actual que se sugiere invertir en cada oportunidad nueva "
        "(ej. 0.10 = 10%).", 0.10,
    ),
    SettingDef(
        "volumen_deseado_fallback", "Tamaño de posición", "Volumen fijo si no hay wallet",
        "Unidades a usar como posición deseada SOLO si todavía no autorizaste el scope de "
        "wallet (sin OAuth).", 100.0,
    ),

    # --- Recomendación de volumen ---
    SettingDef(
        "recomendacion_techo_pct", "Recomendación de volumen",
        "% del volumen diario como techo seguro",
        "Con liquidez Excelente o Aceptable, tope de unidades sugerido = este % del volumen "
        "diario real del ítem.", 0.25,
    ),
    SettingDef(
        "recomendacion_objetivo_pct", "Recomendación de volumen",
        "% del volumen diario como objetivo de recorte",
        "Con liquidez Cuidado, el volumen objetivo sugerido baja a este % del volumen diario "
        "real del ítem.", 0.40,
    ),

    # --- Filtro de órdenes basura ---
    SettingDef(
        "sanity_min_ratio", "Filtro de órdenes basura", "Ratio mínimo vs. precio de referencia",
        "best_buy no puede ser menor a este % (ej. 0.2 = 20%) del precio histórico mediano "
        "reciente, o se descarta como orden basura.", 0.2,
    ),
    SettingDef(
        "sanity_max_ratio", "Filtro de órdenes basura", "Ratio máximo vs. precio de referencia",
        "best_sell no puede ser mayor a este % (ej. 5.0 = 500%) del precio histórico mediano "
        "reciente, o se descarta como orden basura.", 5.0,
    ),
    # --- Tendencia de precio ---
    SettingDef(
        "trend_noise_multiplier", "Tendencia de precio", "Múltiplo del ruido del ítem",
        "Una tendencia solo cuenta como 'sube' o 'baja' si supera este múltiplo del ruido "
        "propio del ítem (variación típica entre dos semanas). Más alto = menos señales, más firmes.",
        1.5,
    ),
    SettingDef(
        "trend_min_change_pct", "Tendencia de precio", "Cambio mínimo (fracción, 0.05 = 5 %)",
        "Suelo del umbral: ningún cambio menor a este % se considera tendencia, aunque el ítem "
        "sea muy estable.", 0.05,
    ),
    SettingDef(
        "trend_min_ops_per_day", "Tendencia de precio", "Operaciones mínimas por día",
        "Con menos operaciones diarias (promedio de la última semana) la tendencia se marca como "
        "'poca liquidez' porque la cifra no es fiable.", 5.0,
    ),
    SettingDef(
        "trend_alert_min_ops_per_day", "Tendencia de precio", "Operaciones mínimas para avisar por Telegram",
        "Solo se avisa del cambio de tendencia de ítems con una orden activa tuya y al menos estas "
        "operaciones diarias (promedio 7 días).", 20.0,
    ),

    # --- Puntaje de oportunidad (0-100) ---
    SettingDef(
        "score_w_profitability", "Puntaje", "Peso: rentabilidad neta",
        "Peso de la rentabilidad (ROI neto) en el puntaje 0-100. Los seis pesos se normalizan para sumar 1.",
        0.25,
    ),
    SettingDef(
        "score_w_liquidity", "Puntaje", "Peso: liquidez",
        "Peso de la liquidez (posición de referencia frente al volumen diario).", 0.20,
    ),
    SettingDef(
        "score_w_volume", "Puntaje", "Peso: volumen negociado",
        "Peso del volumen negociado en ISK al día (7 días).", 0.15,
    ),
    SettingDef(
        "score_w_book", "Puntaje", "Peso: libro y actividad",
        "Peso de las operaciones por día y de la profundidad del libro de órdenes (la competencia).", 0.15,
    ),
    SettingDef(
        "score_w_stability", "Puntaje", "Peso: estabilidad",
        "Peso de la estabilidad del precio y del volumen (inversa del riesgo).", 0.15,
    ),
    SettingDef(
        "score_w_capital", "Puntaje", "Peso: eficiencia del capital",
        "Peso del ROI diario según los días de rotación de la posición de referencia.", 0.10,
    ),
    SettingDef(
        "score_reference_capital", "Puntaje", "Capital de referencia (ISK)",
        "Capital con el que se mide la liquidez y la eficiencia del capital en el puntaje guardado "
        "(posición = este capital x el % por posición de Ajustes). El puntaje por usuario llegará después.",
        1_000_000_000.0,
    ),
    SettingDef(
        "capture_participation_rate", "Puntaje", "Participación capturable del volumen",
        "Parte del volumen diario que se supone capturable al estimar los días de rotación "
        "(0.10 = 10 %). Es un supuesto, no un dato observado.", 0.10,
    ),
    SettingDef(
        "score_atypical_roi", "Puntaje", "ROI atípico (fracción)",
        "Por encima de este ROI neto (1.0 = 100 %) el puntaje queda limitado al tope de ROI atípico.", 1.0,
    ),
    SettingDef(
        "score_atypical_cap", "Puntaje", "Tope del puntaje con ROI atípico",
        "Puntaje máximo de un ítem con ROI atípico.", 64.0,
    ),
    SettingDef(
        "score_discarded_cap", "Puntaje", "Tope del puntaje de un ítem descartado",
        "Puntaje máximo de un ítem en estado DESCARTADO.", 29.0,
    ),
    SettingDef(
        "min_opportunity_score", "Puntaje", "Puntaje mínimo para recomendar",
        "Un ítem elegible solo es RECOMMENDED (BUY_CANDIDATE) si alcanza este puntaje.", 65.0,
    ),
    SettingDef(
        "min_net_roi", "Puntaje", "ROI neto mínimo para recomendar (fracción)",
        "ROI neto mínimo (0.05 = 5 %) para que un ítem sea candidato a compra.", 0.05,
    ),
    SettingDef(
        "min_net_profit", "Puntaje", "Beneficio neto mínimo (ISK)",
        "Beneficio neto mínimo de la posición de referencia; por debajo, el ítem no es elegible.", 100_000.0,
    ),
    SettingDef(
        "min_liquidity_score", "Puntaje", "Liquidez mínima para recomendar (0-100)",
        "Puntuación de liquidez mínima para ser candidato a compra.", 60.0,
    ),
    SettingDef(
        "max_risk_score", "Puntaje", "Riesgo máximo permitido (0-100)",
        "Riesgo = 100 - estabilidad. Por encima de este valor el ítem no es elegible.", 60.0,
    ),
    SettingDef(
        "min_depth_ratio", "Puntaje", "Profundidad mínima del libro (× posición)",
        "Unidades dentro del 5 % del mejor precio (el lado con menos) frente a la cantidad de la posición de "
        "referencia, en la región. Por debajo el ítem no es elegible; 0 desactiva el filtro.", 0.10,
    ),
    SettingDef(
        "max_holding_days", "Puntaje", "Días máximos de rotación",
        "Días estimados máximos para vender la posición de referencia y ser candidato a compra.", 7.0,
    ),
    SettingDef(
        "max_market_data_age_min", "Puntaje", "Antigüedad máxima de los datos (min)",
        "Con datos de órdenes más viejos que esto la recomendación es esperar (WAIT).", 30.0,
    ),
]

SETTINGS_BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTINGS}

# Parámetros que nunca pueden apagarse en 0 — el resto
# solo se valida como >= 0.
STRICTLY_POSITIVE_KEYS = {"min_daily_order_count_7d", "sales_tax_factor", "buy_fee_factor"}
