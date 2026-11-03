from analytics.classification import MIN_DAILY_ORDER_COUNT_7D, MIN_DAILY_VOLUME_7D, classify


def test_good_spread_and_liquidity_with_real_flow_is_potencial():
    status, _ = classify("🟢🟢 Muy bueno", "Buena", avg_daily_volume_7d=500, avg_daily_order_count_7d=15)
    assert status == "POTENCIAL"


def test_good_spread_and_liquidity_with_low_volume_is_sin_ordenes():
    status, reason = classify(
        "🟢🟢🟢 Excelente, si existe volumen", "Excelente liquidez",
        avg_daily_volume_7d=2, avg_daily_order_count_7d=15,
    )
    assert status == "POTENCIAL_SIN_ORDENES"
    assert "2.0 unidades" in reason


def test_good_spread_and_liquidity_but_single_whale_order_is_sin_ordenes():
    """Alto volumen pero de una sola operación (una ballena) no cuenta como flujo real."""
    status, _ = classify("🟢 Buen margen", "Buena", avg_daily_volume_7d=1000, avg_daily_order_count_7d=1)
    assert status == "POTENCIAL_SIN_ORDENES"


def test_exactly_at_threshold_counts_as_real_flow():
    status, _ = classify(
        "🟢 Buen margen", "Buena",
        avg_daily_volume_7d=MIN_DAILY_VOLUME_7D, avg_daily_order_count_7d=MIN_DAILY_ORDER_COUNT_7D,
    )
    assert status == "POTENCIAL"


def test_bad_spread_is_descartado_regardless_of_volume():
    status, _ = classify("❌ Pérdida", "Excelente liquidez", avg_daily_volume_7d=10000, avg_daily_order_count_7d=100)
    assert status == "DESCARTADO"


def test_bad_liquidity_is_descartado_regardless_of_volume():
    status, _ = classify(
        "🟢🟢 Muy bueno", "Muy lenta para tu capital",
        avg_daily_volume_7d=10000, avg_daily_order_count_7d=100,
    )
    assert status == "DESCARTADO"


def test_borderline_spread_is_en_observacion():
    status, _ = classify("🟡 Casi cero", "Buena", avg_daily_volume_7d=10000, avg_daily_order_count_7d=100)
    assert status == "EN_OBSERVACION"


def test_min_daily_volume_zero_disables_volume_criterion():
    """min_daily_volume_7d=0: el volumen (atado al costo del ítem) deja de evaluarse —
    ni siquiera un volumen bajísimo tumba el resultado si las operaciones/día alcanzan."""
    status, reason = classify(
        "🟢 Buen margen", "Buena",
        avg_daily_volume_7d=0.001, avg_daily_order_count_7d=15,
        min_daily_volume_7d=0, min_daily_order_count_7d=3,
    )
    assert status == "POTENCIAL"
    assert "unidades" not in reason


def test_min_daily_volume_zero_still_gates_on_order_count():
    """Desactivar el criterio de volumen no desactiva el de operaciones/día (indispensable)."""
    status, reason = classify(
        "🟢 Buen margen", "Buena",
        avg_daily_volume_7d=0, avg_daily_order_count_7d=1,
        min_daily_volume_7d=0, min_daily_order_count_7d=3,
    )
    assert status == "POTENCIAL_SIN_ORDENES"
    assert "unidades" not in reason
    assert "1.0 operaciones" in reason
