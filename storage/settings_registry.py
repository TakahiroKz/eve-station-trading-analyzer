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
]

SETTINGS_BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTINGS}

# Parámetros que nunca pueden apagarse en 0 — el resto
# solo se valida como >= 0.
STRICTLY_POSITIVE_KEYS = {"min_daily_order_count_7d", "sales_tax_factor", "buy_fee_factor"}
