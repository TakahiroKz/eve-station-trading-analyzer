"""Motor de fórmulas EveCalculator para evaluar oportunidades de station trading.

Todos los umbrales/factores de este módulo son parámetros configurables (ver
storage/settings_registry.py y la pantalla "Ajustes" de la PWA) — `EveCalculatorConfig`
agrupa los que en algún momento fueron constantes fijas dadas por el usuario (0.901
sales tax, 1.024 buy fee) junto con los umbrales derivados (spread, liquidez,
recomendación de volumen). DEFAULT_CONFIG mantiene esos valores originales como default
de cada parámetro: nada cambia de comportamiento hasta que alguien los edite en Ajustes.
"""
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields


@dataclass
class EveCalculatorConfig:
    sales_tax_factor: float = 0.901
    buy_fee_factor: float = 1.024
    spread_perdida_max: float = 0.14
    spread_casi_cero_max: float = 0.15
    spread_pequeno_max: float = 0.20
    spread_buen_margen_max: float = 0.30
    spread_muy_bueno_max: float = 0.50
    liquidez_excelente_max: float = 0.10
    liquidez_buena_max: float = 0.25
    liquidez_aceptable_max: float = 0.50
    liquidez_cuidado_max: float = 1.00
    recomendacion_techo_pct: float = 0.25
    recomendacion_objetivo_pct: float = 0.40


DEFAULT_CONFIG = EveCalculatorConfig()


@dataclass
class EveCalculatorResult:
    item: str
    buy: float
    sell: float
    volumen_deseado: float
    volumen_diario_real: float
    beneficio: float
    spread_bruto: float
    precio_min_venta: float
    roi: float
    evaluacion_spread: str
    posicion_vs_volumen: float
    liquidez: str
    recomendacion: str
    unidades_sugeridas: int


def beneficio_unitario(buy: float, sell: float, config: EveCalculatorConfig = DEFAULT_CONFIG) -> float:
    return (sell * config.sales_tax_factor) - (buy * config.buy_fee_factor)


def spread_bruto(buy: float, sell: float) -> float:
    return (sell / buy) - 1


def precio_min_venta(buy: float, config: EveCalculatorConfig = DEFAULT_CONFIG) -> float:
    return (buy * config.buy_fee_factor) / config.sales_tax_factor


def roi(spread: float, config: EveCalculatorConfig = DEFAULT_CONFIG) -> float:
    return ((1 + spread) * config.sales_tax_factor / config.buy_fee_factor) - 1


def posicion_vs_volumen(volumen_deseado: float, volumen_diario_real: float) -> float:
    return volumen_deseado / volumen_diario_real


def evaluar_spread(spread: float, config: EveCalculatorConfig = DEFAULT_CONFIG) -> str:
    if spread < config.spread_perdida_max:
        return "❌ Pérdida"
    if spread < config.spread_casi_cero_max:
        return "🟡 Casi cero"
    if spread < config.spread_pequeno_max:
        return "🟢 Pequeño beneficio"
    if spread < config.spread_buen_margen_max:
        return "🟢 Buen margen"
    if spread < config.spread_muy_bueno_max:
        return "🟢🟢 Muy bueno"
    return "🟢🟢🟢 Excelente, si existe volumen"


def evaluar_liquidez(posicion: float, config: EveCalculatorConfig = DEFAULT_CONFIG) -> str:
    if posicion < config.liquidez_excelente_max:
        return "Excelente liquidez"
    if posicion < config.liquidez_buena_max:
        return "Buena"
    if posicion < config.liquidez_aceptable_max:
        return "Aceptable"
    if posicion < config.liquidez_cuidado_max:
        return "Cuidado"
    return "Muy lenta para tu capital"


def recomendar(spread_eval: str, liquidez: str, posicion: float, volumen_diario_real: float,
                volumen_deseado: float, config: EveCalculatorConfig = DEFAULT_CONFIG) -> tuple[str, int]:
    """Devuelve (texto, unidades_sugeridas). Las mismas cuentas alimentan las dos —
    nunca puede haber un desacuerdo entre lo que dice el texto y el número final
    (ej. notify_new_opportunity) porque salen del mismo cálculo, no de dos por separado.
    `unidades_sugeridas` nunca supera volumen_deseado (el 10% del wallet ya es el techo
    de riesgo): cuando la liquidez del ítem obliga a recortar, se usa lo menor de los
    dos — el capital disponible nunca es motivo para comprar más de lo que el volumen
    diario real del ítem puede absorber con seguridad.
    """
    if spread_eval in ("❌ Pérdida", "🟡 Casi cero"):
        return "No ejecutar el trade con estos precios: el spread no cubre costos de forma consistente.", 0

    if liquidez == "Excelente liquidez" and spread_eval in (
        "🟢 Buen margen", "🟢🟢 Muy bueno", "🟢🟢🟢 Excelente, si existe volumen",
    ):
        techo = round(volumen_diario_real * config.recomendacion_techo_pct)
        return (
            f"Hay margen para escalar el volumen deseado hasta ~{techo:,} unidades "
            f"({config.recomendacion_techo_pct:.0%} del volumen diario) sin salir de una liquidez 'Buena'."
        ), round(volumen_deseado)

    if liquidez == "Buena":
        return "El volumen deseado está bien calibrado; mantenerlo.", round(volumen_deseado)

    if liquidez == "Aceptable":
        if spread_eval in ("🟢🟢 Muy bueno", "🟢🟢🟢 Excelente, si existe volumen"):
            return (
                "Spread muy favorable: se puede tolerar algo más de posición pese a la liquidez aceptable.",
                round(volumen_deseado),
            )
        objetivo = round(volumen_diario_real * config.recomendacion_techo_pct)
        return (
            f"Recorta el volumen hacia ~{objetivo:,} unidades "
            f"({config.recomendacion_techo_pct:.0%} del volumen diario) para mejorar la rotación.",
            objetivo,
        )

    objetivo = round(volumen_diario_real * config.recomendacion_objetivo_pct)
    return (
        f"Baja el volumen objetivo a ~{objetivo:,} unidades "
        f"({config.recomendacion_objetivo_pct:.0%} del volumen diario). "
        f"Con {posicion:.0%} del volumen diario el capital puede quedar inmovilizado varios días."
    ), objetivo


def resolve_volumen_deseado(buy_price: float, wallet_balance: float | None, position_pct: float,
                             fallback: float) -> float:
    """10% (o el % configurado) del ISK del wallet, convertido a unidades al precio de compra
    del ítem. Si no hay wallet disponible (SSO sin autorizar todavía), usa el fallback fijo.
    Compartida entre el motor de mercado (scheduler/run.py, una vez por corrida de 4h) y la
    API (backend/api/main.py, en cada consulta de detalle de ítem) — esta última la llama con
    un wallet recién pedido a la ESI para que la recomendación mostrada nunca dependa de un
    snapshot de hace horas.
    """
    if wallet_balance is None or buy_price <= 0:
        return fallback
    return max((wallet_balance * position_pct) / buy_price, 1)


def config_from_settings(config_cls, settings: dict[str, float]):
    """Arma un EveCalculatorConfig/SanityConfig filtrando del dict de app_settings solo
    las keys que ese dataclass declara — los nombres de campo son iguales a las keys
    del registro (storage/settings_registry.py) a propósito, ver ahí."""
    field_names = {f.name for f in dataclass_fields(config_cls)}
    return config_cls(**{k: v for k, v in settings.items() if k in field_names})


def evaluar_oportunidad(item: str, buy: float, sell: float, volumen_deseado: float,
                         volumen_diario_real: float,
                         config: EveCalculatorConfig = DEFAULT_CONFIG) -> EveCalculatorResult:
    spread = spread_bruto(buy, sell)
    posicion = posicion_vs_volumen(volumen_deseado, volumen_diario_real)
    spread_eval = evaluar_spread(spread, config)
    liquidez = evaluar_liquidez(posicion, config)
    recomendacion, unidades_sugeridas = recomendar(
        spread_eval, liquidez, posicion, volumen_diario_real, volumen_deseado, config,
    )

    return EveCalculatorResult(
        item=item,
        buy=buy,
        sell=sell,
        volumen_deseado=volumen_deseado,
        volumen_diario_real=volumen_diario_real,
        beneficio=round(beneficio_unitario(buy, sell, config), 2),
        spread_bruto=round(spread, 4),
        precio_min_venta=round(precio_min_venta(buy, config), 2),
        roi=round(roi(spread, config), 4),
        evaluacion_spread=spread_eval,
        posicion_vs_volumen=round(posicion, 4),
        liquidez=liquidez,
        recomendacion=recomendacion,
        unidades_sugeridas=unidades_sugeridas,
    )
