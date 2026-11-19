"""Puntaje de oportunidad 0-100, determinista y explicable.

Complementa a analytics.classification (los estados POTENCIAL / ... no cambian): el puntaje responde
"¿cuánto mejor es esta operación que otra?" y se descompone en factores, cada uno con los puntos
obtenidos sobre los máximos, el valor medido y una frase. El total es la suma de los puntos, así que la
explicación ES el cálculo (mismo principio que eve_calculator.recomendar: texto y número salen de la
misma cuenta). Sin E/S ni IA: mismos datos y misma configuración => mismo resultado.

Dimensiones y pesos iniciales (los de EF-01.06, configurables en Ajustes):
rentabilidad 25, liquidez 20, volumen 15, libro y actividad 15 (la "competencia"), estabilidad 15 y
eficiencia del capital 10. Las curvas se calibraron con 42.926 ítems reales de los cinco mercados
(2026-11-19): el ROI deja de sumar por encima del 40 % y baja a partir del 60 %, porque en libros
finos un ROI de cientos de por ciento casi siempre es ruido y no una oportunidad.

El capital de referencia fija la posición con la que se mide liquidez y eficiencia del capital
(la posición por usuario llegará en una fase posterior); la profundidad de libro, también.
"""
import hashlib
import math
from dataclasses import dataclass, field, fields

SCORING_VERSION = "1.0.0"

# Bandas de clasificación (EF-01.06): límite inferior de cada una.
CLASS_BANDS = [(90, "EXCELLENT"), (80, "HIGH"), (65, "MODERATE"), (50, "LOW"), (0, "DISCARDED")]

# Curvas: puntos (x, y) con interpolación lineal; fuera del rango se mantiene el valor extremo.
PROFIT_CURVE = [(0, 0), (0.05, 20), (0.12, 60), (0.20, 100), (0.40, 100), (0.60, 80), (1.0, 45), (2.0, 10), (3.0, 0)]
LIQUIDITY_CURVE = [(0, 100), (0.10, 95), (0.25, 70), (0.50, 40), (1.0, 15), (2.0, 0)]  # posición / volumen diario
VOLUME_CURVE = [(6, 0), (7, 30), (8, 60), (9, 85), (10, 100)]  # log10(ISK negociados al día)
ACTIVITY_CURVE = [(3, 20), (10, 60), (30, 90), (100, 100)]  # operaciones por día (7 d)
CV_CURVE = [(0, 100), (0.05, 100), (0.15, 60), (0.40, 0)]  # coeficiente de variación del precio (30 d)
RATIO_CURVE = [(0, 0), (0.4, 30), (0.7, 100), (1.4, 100), (2.5, 40), (4, 0)]  # volumen 7 d / volumen 30 d
EFFICIENCY_CURVE = [(0, 0), (0.005, 30), (0.02, 70), (0.05, 100)]  # ROI diario (ROI acotado / días de rotación)

THIN_BOOK_MIN_ORDERS = 3      # menos órdenes que esto en un lado: el libro se considera fino
THIN_BOOK_FACTOR = 0.5
NO_DATA_SCORE = 50.0          # factor sin dato suficiente: neutro, y así se dice en la explicación

# Códigos estables que viajan en la explicación; la web los traduce (frontend/app/src/i18n: score.note.*,
# score.cap.*). Un test comprueba que cada uno tiene su texto en los cinco idiomas.
NOTE_CODES = (
    "ROI_SUSTAINABLE", "ROI_VERY_HIGH", "ROI_THIN", "POSITION_ABSORBABLE", "POSITION_SLOW", "VOLUME_ISK",
    "BOOK_THIN", "BOOK_ACTIVE", "STABLE", "UNSTABLE", "NO_VOLATILITY_DATA", "FAST_RECOVERY", "SLOW_ROTATION",
    "NO_RECENT_VOLUME",
)
CAP_CODES = ("CLASSIFIED_DISCARDED", "ATYPICAL_ROI", "INSUFFICIENT_DATA")

WEIGHT_KEYS = {
    "profitability": "score_w_profitability",
    "liquidity": "score_w_liquidity",
    "volume": "score_w_volume",
    "book": "score_w_book",
    "stability": "score_w_stability",
    "capital": "score_w_capital",
}
FACTOR_LABELS = {
    "profitability": "Rentabilidad neta",
    "liquidity": "Liquidez",
    "volume": "Volumen negociado",
    "book": "Libro y actividad",
    "stability": "Estabilidad",
    "capital": "Eficiencia del capital",
}


@dataclass
class ScoreConfig:
    """Los nombres de campo son claves de app_settings (storage/settings_registry.py)."""
    score_w_profitability: float = 0.25
    score_w_liquidity: float = 0.20
    score_w_volume: float = 0.15
    score_w_book: float = 0.15
    score_w_stability: float = 0.15
    score_w_capital: float = 0.10
    score_reference_capital: float = 1_000_000_000.0  # ISK de referencia para medir liquidez y capital
    position_size_pct_wallet: float = 0.10            # fracción del capital por posición (misma que el wallet)
    capture_participation_rate: float = 0.10          # parte del volumen diario que se supone capturable
    score_atypical_roi: float = 1.0                   # ROI neto por encima del cual se limita el puntaje
    score_atypical_cap: float = 64.0
    score_discarded_cap: float = 29.0


def interp(x: float, curve: list[tuple[float, float]]) -> float:
    if x <= curve[0][0]:
        return float(curve[0][1])
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return float(curve[-1][1])


@dataclass
class ScoreInputs:
    roi: float                   # ROI neto (fracción: 0,25 = 25 %)
    best_buy: float
    volume_7d: float             # unidades/día, promedio 7 d (histórico regional)
    volume_30d: float            # unidades/día, promedio 30 d
    ops_7d: float                # operaciones/día, promedio 7 d
    buy_orders: int
    sell_orders: int
    status: str                  # estado de classify(): POTENCIAL, ..., DESCARTADO
    price_cv: float | None = None  # coeficiente de variación del precio medio diario (30 d)


@dataclass
class Factor:
    key: str
    label: str
    points: float        # puntos obtenidos (0 .. max)
    max: float           # puntos máximos = peso x 100
    score: float         # puntuación de la dimensión, 0-100
    value: str           # lo medido, en texto (español; la web usa metrics para traducirlo)
    note: str            # frase de explicación (español; la web usa code para traducirla)
    code: str = ""       # código estable de la frase de explicación, p. ej. ROI_SUSTAINABLE
    metrics: dict = field(default_factory=dict)  # las cifras medidas, para que la web arme su propio texto


@dataclass
class ScoreResult:
    total: float | None
    classification: str
    factors: list[Factor] = field(default_factory=list)
    caps: list[dict] = field(default_factory=list)
    reference: dict = field(default_factory=dict)
    version: str = SCORING_VERSION

    @property
    def score(self) -> int | None:
        return None if self.total is None else int(round(self.total))

    def to_dict(self) -> dict:
        return {
            "total": None if self.total is None else round(self.total, 1),
            "classification": self.classification,
            "version": self.version,
            "reference": self.reference,
            "factors": [
                {"key": f.key, "label": f.label, "points": round(f.points, 1), "max": round(f.max, 1),
                 "score": round(f.score, 1), "value": f.value, "note": f.note, "code": f.code, "metrics": f.metrics}
                for f in self.factors
            ],
            "caps": self.caps,
        }


def normalized_weights(config: ScoreConfig) -> dict[str, float]:
    """Pesos que suman 1. Pesos inválidos (negativos o todos en 0) vuelven a los valores por defecto."""
    raw = {k: getattr(config, attr) for k, attr in WEIGHT_KEYS.items()}
    if any(v < 0 for v in raw.values()) or sum(raw.values()) <= 0:
        raw = {k: getattr(ScoreConfig(), attr) for k, attr in WEIGHT_KEYS.items()}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def validate_weights(values: dict[str, float]) -> str | None:
    """Mensaje de error si los pesos propuestos no sirven; None si son válidos (EF-01.06)."""
    weights = [values[a] for a in WEIGHT_KEYS.values() if a in values]
    if any(not 0 <= w <= 1 for w in weights):
        return "Cada peso del puntaje debe estar entre 0 y 1."
    if len(weights) == len(WEIGHT_KEYS) and abs(sum(weights) - 1) > 0.001:
        return f"Los pesos del puntaje deben sumar 1 (ahora suman {sum(weights):.3f})."
    return None


def config_version(config: ScoreConfig) -> str:
    """Versión del algoritmo + huella de la configuración: cambia si alguien toca pesos o límites, y cada
    evaluación guarda la versión con la que se calculó."""
    payload = ",".join(f"{f.name}={getattr(config, f.name):g}" for f in fields(config))
    return f"{SCORING_VERSION}-{hashlib.sha1(payload.encode()).hexdigest()[:6]}"


def reference_position(config: ScoreConfig, best_buy: float) -> dict:
    """Posición de referencia: capital x fracción por posición, en unidades al precio de compra."""
    position_isk = config.score_reference_capital * config.position_size_pct_wallet
    quantity = position_isk / best_buy if best_buy > 0 else 0.0
    return {"capital": config.score_reference_capital, "position_isk": position_isk, "quantity": quantity}


def holding_days(quantity: float, volume_7d: float, config: ScoreConfig) -> float | None:
    """Días estimados para rotar la posición: cantidad / (volumen diario x participación capturable).
    La participación capturable es un supuesto configurable, no un dato observado."""
    capturable = volume_7d * config.capture_participation_rate
    return quantity / capturable if capturable > 0 else None


def classification_for(total: float) -> str:
    for floor, name in CLASS_BANDS:
        if total >= floor:
            return name
    return "DISCARDED"


def score_opportunity(inputs: ScoreInputs, config: ScoreConfig | None = None) -> ScoreResult:
    config = config or ScoreConfig()
    version = config_version(config)
    if inputs.best_buy <= 0 or inputs.volume_30d <= 0:
        return ScoreResult(None, "DISCARDED", version=version, caps=[
            {"code": "INSUFFICIENT_DATA", "limit": None, "note": "Sin precio de compra o sin volumen histórico."}])

    weights = normalized_weights(config)
    ref = reference_position(config, inputs.best_buy)
    days = holding_days(ref["quantity"], inputs.volume_7d, config)
    ref["holding_days"] = None if days is None else round(days, 2)

    # factor -> (puntuación 0-100, valor en texto, frase, código de la frase, cifras medidas)
    scores: dict[str, tuple[float, str, str, str, dict]] = {}

    roi = inputs.roi
    if 0.12 <= roi <= 0.60:
        note, code = "Zona de rentabilidad sostenible.", "ROI_SUSTAINABLE"
    elif roi > 0.60:
        note, code = "ROI muy alto: en libros finos suele ser ruido; deja de sumar.", "ROI_VERY_HIGH"
    else:
        note, code = "Margen estrecho tras comisiones e impuestos.", "ROI_THIN"
    scores["profitability"] = (interp(roi, PROFIT_CURVE), f"ROI neto {roi:.1%}", note, code, {"roi": round(roi, 4)})

    position = ref["quantity"] / inputs.volume_30d
    fast = position < 0.25
    scores["liquidity"] = (
        interp(position, LIQUIDITY_CURVE), f"posición {position:.1%} del volumen diario",
        "La posición de referencia se vende rápido." if fast else
        "La posición de referencia tardaría en venderse: capital inmovilizado.",
        "POSITION_ABSORBABLE" if fast else "POSITION_SLOW", {"position": round(position, 4)})

    turnover = inputs.volume_7d * inputs.best_buy
    volume_score = interp(math.log10(turnover), VOLUME_CURVE) if turnover > 0 else 0.0
    scores["volume"] = (volume_score, f"{turnover:,.0f} ISK/día (7 d)",
                        "Volumen negociado en ISK; ítems de poco flujo puntúan menos.",
                        "VOLUME_ISK", {"turnover": round(turnover)})

    book_score = interp(inputs.ops_7d, ACTIVITY_CURVE)
    thin = min(inputs.buy_orders, inputs.sell_orders) < THIN_BOOK_MIN_ORDERS
    if thin:
        book_score *= THIN_BOOK_FACTOR
    scores["book"] = (
        book_score, f"{inputs.ops_7d:.1f} operaciones/día, libro {inputs.buy_orders}/{inputs.sell_orders}",
        "Libro fino (menos de 3 órdenes en un lado): se reduce a la mitad." if thin else
        "Actividad de operaciones distintas y libro con competidores reales.",
        "BOOK_THIN" if thin else "BOOK_ACTIVE",
        {"ops": round(inputs.ops_7d, 1), "buy_orders": inputs.buy_orders, "sell_orders": inputs.sell_orders})

    ratio = inputs.volume_7d / inputs.volume_30d
    ratio_score = interp(ratio, RATIO_CURVE)
    if inputs.price_cv is None:
        stability, value, note = NO_DATA_SCORE * 0.6 + ratio_score * 0.4, f"volumen 7 d / 30 d = {ratio:.2f}", (
            "Sin precio histórico suficiente: la parte de volatilidad se toma neutra (50).")
        code, metrics = "NO_VOLATILITY_DATA", {"cv": None, "ratio": round(ratio, 2)}
    else:
        cv_score = interp(inputs.price_cv, CV_CURVE)
        stability = cv_score * 0.6 + ratio_score * 0.4
        value = f"volatilidad {inputs.price_cv:.1%}, volumen 7 d / 30 d = {ratio:.2f}"
        note, code = (("Precio y volumen estables.", "STABLE") if stability >= 70 else
                      ("Precio volátil o volumen fuera de su nivel habitual (posible pico o caída).", "UNSTABLE"))
        metrics = {"cv": round(inputs.price_cv, 4), "ratio": round(ratio, 2)}
    scores["stability"] = (stability, value, note, code, metrics)

    if days is None:
        scores["capital"] = (NO_DATA_SCORE, "sin volumen 7 d", "Sin volumen reciente: eficiencia neutra (50).",
                             "NO_RECENT_VOLUME", {"days": None, "daily": None})
    else:
        rotation = max(days, 1.0)
        daily = min(max(roi, 0.0), 0.60) / rotation
        quick = rotation <= 2
        scores["capital"] = (
            interp(daily, EFFICIENCY_CURVE), f"{days:.1f} días de rotación, {daily:.2%} diario",
            "Recupera el capital con rapidez." if quick else "Rotación lenta: el ROI se diluye en días.",
            "FAST_RECOVERY" if quick else "SLOW_ROTATION", {"days": round(days, 2), "daily": round(daily, 4)})

    factors = []
    total = 0.0
    for key in WEIGHT_KEYS:
        value_score, value, note, code, metrics = scores[key]
        max_points = weights[key] * 100
        points = value_score * weights[key]
        total += points
        factors.append(Factor(key, FACTOR_LABELS[key], points, max_points, value_score, value, note, code, metrics))

    caps: list[dict] = []
    if inputs.status == "DESCARTADO" and total > config.score_discarded_cap:
        total = config.score_discarded_cap
        caps.append({"code": "CLASSIFIED_DISCARDED", "limit": config.score_discarded_cap,
                     "note": "El estado es DESCARTADO: el puntaje no puede superar este tope."})
    elif roi > config.score_atypical_roi and total > config.score_atypical_cap:
        total = config.score_atypical_cap
        caps.append({"code": "ATYPICAL_ROI", "limit": config.score_atypical_cap, "roi": round(roi, 4),
                     "note": f"ROI neto {roi:.0%}: atípico, probablemente un libro fino o un precio aislado."})

    ref = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in ref.items()}
    return ScoreResult(total, classification_for(total), factors, caps, ref, version)
