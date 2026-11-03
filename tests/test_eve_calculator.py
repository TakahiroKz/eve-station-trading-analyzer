import pytest

from analytics.eve_calculator import EveCalculatorConfig, evaluar_oportunidad


def test_tritanium_fixture_matches_documented_example():
    """Caso de regresión: fixture dado por el usuario en la definición de EveCalculator."""
    result = evaluar_oportunidad(
        item="Tritanium",
        buy=100,
        sell=130,
        volumen_deseado=500,
        volumen_diario_real=6000,
    )

    assert result.beneficio == pytest.approx(14.73, abs=0.01)
    assert result.spread_bruto == pytest.approx(0.30, abs=0.001)
    assert result.precio_min_venta == pytest.approx(113.65, abs=0.01)
    assert result.roi == pytest.approx(0.1438, abs=0.001)
    assert result.evaluacion_spread == "🟢🟢 Muy bueno"
    assert result.posicion_vs_volumen == pytest.approx(0.0833, abs=0.001)
    assert result.liquidez == "Excelente liquidez"
    assert "1,500" in result.recomendacion
    # Excelente liquidez: unidades_sugeridas queda en volumen_deseado (el 10% del wallet
    # ya es conservador acá) — el "hasta 1500" del texto es techo de OPORTUNIDAD, no lo
    # que se sugiere comprar ahora.
    assert result.unidades_sugeridas == 500


@pytest.mark.parametrize(
    "spread,expected",
    [
        (0.05, "❌ Pérdida"),
        (0.1399, "❌ Pérdida"),
        (0.14, "🟡 Casi cero"),
        (0.1499, "🟡 Casi cero"),
        (0.15, "🟢 Pequeño beneficio"),
        (0.1999, "🟢 Pequeño beneficio"),
        (0.20, "🟢 Buen margen"),
        (0.2999, "🟢 Buen margen"),
        (0.30, "🟢🟢 Muy bueno"),
        (0.4999, "🟢🟢 Muy bueno"),
        (0.50, "🟢🟢🟢 Excelente, si existe volumen"),
        (1.0, "🟢🟢🟢 Excelente, si existe volumen"),
    ],
)
def test_evaluar_spread_thresholds(spread, expected):
    from analytics.eve_calculator import evaluar_spread

    assert evaluar_spread(spread) == expected


@pytest.mark.parametrize(
    "posicion,expected",
    [
        (0.05, "Excelente liquidez"),
        (0.0999, "Excelente liquidez"),
        (0.10, "Buena"),
        (0.2499, "Buena"),
        (0.25, "Aceptable"),
        (0.4999, "Aceptable"),
        (0.50, "Cuidado"),
        (0.9999, "Cuidado"),
        (1.00, "Muy lenta para tu capital"),
        (2.0, "Muy lenta para tu capital"),
    ],
)
def test_evaluar_liquidez_thresholds(posicion, expected):
    from analytics.eve_calculator import evaluar_liquidez

    assert evaluar_liquidez(posicion) == expected


def test_unidades_sugeridas_caps_to_zero_on_bad_spread():
    from analytics.eve_calculator import recomendar

    _, unidades = recomendar("❌ Pérdida", "Excelente liquidez", 0.05, 1000, 50)
    assert unidades == 0


def test_unidades_sugeridas_stays_at_wallet_amount_when_liquidity_is_safe():
    """Buena/Excelente/Aceptable-con-buen-spread: el 10% del wallet ya es seguro,
    unidades_sugeridas no se recorta."""
    from analytics.eve_calculator import recomendar

    _, unidades = recomendar("🟢 Buen margen", "Buena", 0.15, 1000, 150)
    assert unidades == 150


def test_unidades_sugeridas_matches_recomendacion_cap_when_liquidity_forces_a_cut():
    """Aceptable con spread mediocre: el texto dice 'recortá a ~X' y unidades_sugeridas
    debe ser ese mismo X, no el volumen_deseado original (que sería más agresivo)."""
    from analytics.eve_calculator import recomendar

    texto, unidades = recomendar("🟢 Buen margen", "Aceptable", 0.35, 1000, 350)
    assert unidades == 250  # round(1000 * 0.25)
    assert str(unidades) in texto


def test_unidades_sugeridas_matches_recomendacion_cap_for_cuidado():
    from analytics.eve_calculator import recomendar

    texto, unidades = recomendar("🟢 Buen margen", "Cuidado", 0.7, 1000, 700)
    assert unidades == 400  # round(1000 * 0.4)
    assert str(unidades) in texto


def test_unidades_sugeridas_never_exceeds_volumen_deseado():
    """El capital disponible nunca es motivo para sugerir MÁS de lo que el wallet
    ya calculó como posición — solo puede recortar, nunca escalar."""
    from analytics.eve_calculator import recomendar

    volumen_diario_real = 1000
    for liquidez, posicion in [
        ("Excelente liquidez", 0.05), ("Buena", 0.15),
        ("Aceptable", 0.35), ("Cuidado", 0.7),
    ]:
        volumen_deseado = posicion * volumen_diario_real  # consistente con posicion_vs_volumen()
        _, unidades = recomendar("🟢🟢 Muy bueno", liquidez, posicion, volumen_diario_real, volumen_deseado)
        assert unidades <= volumen_deseado


def test_custom_config_changes_fees():
    """Confirma que evaluar_oportunidad() de verdad usa el config pasado, no las
    constantes de siempre — sales_tax/buy_fee más generosos dan más beneficio."""
    default_result = evaluar_oportunidad(item="X", buy=100, sell=130, volumen_deseado=500, volumen_diario_real=6000)

    generous = EveCalculatorConfig(sales_tax_factor=0.95, buy_fee_factor=1.01)
    result = evaluar_oportunidad(
        item="X", buy=100, sell=130, volumen_deseado=500, volumen_diario_real=6000, config=generous,
    )

    assert result.beneficio > default_result.beneficio


def test_custom_config_changes_spread_labels():
    """Umbrales de spread personalizados: un spread de 30% que hoy da 'Muy bueno'
    pasa a 'Excelente' si se baja el techo correspondiente."""
    from analytics.eve_calculator import evaluar_spread

    custom = EveCalculatorConfig(spread_muy_bueno_max=0.25)
    assert evaluar_spread(0.30, custom) == "🟢🟢🟢 Excelente, si existe volumen"
    assert evaluar_spread(0.30) == "🟢🟢 Muy bueno"  # default sin tocar


def test_custom_config_changes_liquidity_labels():
    from analytics.eve_calculator import evaluar_liquidez

    custom = EveCalculatorConfig(liquidez_excelente_max=0.50)
    assert evaluar_liquidez(0.30, custom) == "Excelente liquidez"
    assert evaluar_liquidez(0.30) == "Aceptable"  # default sin tocar


def test_custom_config_changes_recomendacion_percentage():
    from analytics.eve_calculator import recomendar

    custom = EveCalculatorConfig(recomendacion_objetivo_pct=0.10)
    texto, unidades = recomendar("🟢 Buen margen", "Cuidado", 0.7, 1000, 700, custom)
    assert unidades == 100  # round(1000 * 0.10) en vez del 400 (40%) por default
    assert "100" in texto


def test_resolve_volumen_deseado_uses_fallback_when_wallet_unavailable():
    from analytics.eve_calculator import resolve_volumen_deseado

    assert resolve_volumen_deseado(buy_price=10, wallet_balance=None, position_pct=0.10, fallback=42) == 42


def test_resolve_volumen_deseado_uses_fallback_when_buy_price_not_positive():
    from analytics.eve_calculator import resolve_volumen_deseado

    assert resolve_volumen_deseado(buy_price=0, wallet_balance=100_000, position_pct=0.10, fallback=42) == 42


def test_resolve_volumen_deseado_is_position_pct_of_wallet_over_buy_price():
    from analytics.eve_calculator import resolve_volumen_deseado

    result = resolve_volumen_deseado(buy_price=10, wallet_balance=100_000, position_pct=0.10, fallback=42)
    assert result == pytest.approx(1000)  # 10% de 100.000 ISK / 10 ISK por unidad


def test_resolve_volumen_deseado_never_returns_less_than_one_unit():
    from analytics.eve_calculator import resolve_volumen_deseado

    result = resolve_volumen_deseado(buy_price=1_000_000, wallet_balance=1, position_pct=0.10, fallback=42)
    assert result == 1


def test_resolve_volumen_deseado_reacts_to_a_smaller_live_wallet():
    """Regresión directa de D1: la recomendación debe reflejar el wallet ACTUAL, no uno
    viejo — dos wallets distintos para el mismo ítem deben dar volúmenes distintos."""
    from analytics.eve_calculator import resolve_volumen_deseado

    antes = resolve_volumen_deseado(buy_price=10, wallet_balance=100_000, position_pct=0.10, fallback=42)
    despues_de_comprar = resolve_volumen_deseado(buy_price=10, wallet_balance=40_000, position_pct=0.10, fallback=42)
    assert despues_de_comprar < antes


def test_config_from_settings_filters_to_declared_fields_only():
    from analytics.eve_calculator import config_from_settings

    settings = {
        "sales_tax_factor": 0.95, "buy_fee_factor": 1.01,
        "position_size_pct_wallet": 0.10, "min_daily_volume_7d": 500,
    }
    config = config_from_settings(EveCalculatorConfig, settings)

    assert config.sales_tax_factor == 0.95
    assert config.buy_fee_factor == 1.01
    assert config.spread_perdida_max == EveCalculatorConfig().spread_perdida_max  # no estaba en settings, default
