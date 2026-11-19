"""La frase y las unidades del motor (analytics/eve_calculator.py::recomendar) nunca se contradicen.

Pruebas exhaustivas y aleatorias (con semilla fija) sobre todas las combinaciones de etiquetas de spread y de
liquidez: las unidades no superan lo deseado, el número que cita la frase es el que se devuelve y las frases de
«capital inmovilizado» solo salen con liquidez mala. Se añadieron al encontrar, con datos reales, que «Excelente
liquidez» con un spread pequeño caía en la rama de liquidez mala (decía «Baja el volumen…» con una posición del
1 % del volumen diario y sugería más unidades de las deseadas).
"""
import random
import re

import pytest

from analytics.eve_calculator import evaluar_liquidez, evaluar_oportunidad, evaluar_spread, recomendar

SPREADS = ["❌ Pérdida", "🟡 Casi cero", "🟢 Pequeño beneficio", "🟢 Buen margen", "🟢🟢 Muy bueno",
           "🟢🟢🟢 Excelente, si existe volumen"]
LIQUIDITIES = ["Excelente liquidez", "Buena", "Aceptable", "Cuidado", "Muy lenta para tu capital"]
POOR = {"Cuidado", "Muy lenta para tu capital"}
QUOTED = re.compile(r"~([\d,]+) unidades")


def position_for(label: str) -> float:
    return {"Excelente liquidez": 0.05, "Buena": 0.15, "Aceptable": 0.35, "Cuidado": 0.7,
            "Muy lenta para tu capital": 1.5}[label]


@pytest.mark.parametrize("spread", SPREADS)
@pytest.mark.parametrize("liquidity", LIQUIDITIES)
def test_every_combination_keeps_text_and_units_consistent(spread, liquidity):
    volume, position = 100_000.0, position_for(liquidity)
    desired = position * volume

    text, units = recomendar(spread, liquidity, position, volume, desired)

    assert units >= 0
    if spread in ("❌ Pérdida", "🟡 Casi cero"):
        assert units == 0 and "No ejecutar" in text
        return
    assert units <= round(desired), "las unidades sugeridas nunca superan lo deseado"
    quoted = QUOTED.search(text)
    if quoted and not text.startswith("Hay margen para escalar"):
        assert int(quoted.group(1).replace(",", "")) == units, "la frase cita las unidades que devuelve"
    if "inmovilizado" in text or "Baja el volumen" in text:
        assert liquidity in POOR, "solo una liquidez mala habla de capital inmovilizado"
    if liquidity in ("Excelente liquidez", "Buena"):
        assert units == round(desired), "con buena liquidez se mantiene lo deseado"


def test_excellent_liquidity_with_a_small_spread_is_kept_not_cut():
    # El caso real que fallaba: posición del 1 % del volumen, spread 17 % (pequeño beneficio).
    text, units = recomendar("🟢 Pequeño beneficio", "Excelente liquidez", 0.0085, 235, 2)

    assert units == 2
    assert text == "El volumen deseado está bien calibrado; mantenerlo."
    assert "inmovilizado" not in text and "Baja el volumen" not in text


def test_randomized_end_to_end_consistency_over_many_markets():
    rng = random.Random(20261119)
    for _ in range(20_000):
        buy = 10 ** rng.uniform(-1, 9)
        spread = rng.choice([rng.uniform(-0.3, 0.14), rng.uniform(0.14, 0.2), rng.uniform(0.2, 0.6), rng.uniform(0.6, 5)])
        sell = buy * (1 + spread)
        volume = 10 ** rng.uniform(0, 9)
        desired = max(1.0, 10 ** rng.uniform(0, 9))

        result = evaluar_oportunidad("x", buy, sell, desired, volume)
        position = desired / volume

        assert result.unidades_sugeridas >= 0
        assert result.unidades_sugeridas <= round(desired), (buy, sell, desired, volume, result.recomendacion)
        quoted = QUOTED.search(result.recomendacion)
        if quoted and not result.recomendacion.startswith("Hay margen para escalar"):
            assert int(quoted.group(1).replace(",", "")) == result.unidades_sugeridas
        if "inmovilizado" in result.recomendacion:
            assert position >= 0.5, f"dice inmovilizado con posición {position:.2%}"
        if evaluar_spread(spread) in ("❌ Pérdida", "🟡 Casi cero"):
            assert result.unidades_sugeridas == 0
        assert evaluar_liquidez(position) == result.liquidez


def test_the_scale_sentence_cap_is_a_ceiling_never_below_the_suggestion():
    rng = random.Random(7)
    for _ in range(5_000):
        volume = 10 ** rng.uniform(2, 9)
        desired = volume * rng.uniform(0.001, 0.099)          # liquidez excelente
        text, units = recomendar("🟢🟢 Muy bueno", "Excelente liquidez", desired / volume, volume, desired)

        ceiling = int(QUOTED.search(text).group(1).replace(",", ""))
        assert units <= ceiling
