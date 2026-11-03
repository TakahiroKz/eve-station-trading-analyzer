"""Clasifica cada ítem en POTENCIAL / POTENCIAL_SIN_ORDENES / DESCARTADO / EN_OBSERVACION
en cada recategorización.

Regla (DERIVADA de los umbrales de EveCalculator que el usuario definió, no dictada
explícitamente por él — ajustable si el screening resulta demasiado laxo/estricto):

- DESCARTADO: spread en pérdida, o liquidez "Muy lenta para tu capital" (fundamentalmente
  no viable con los datos actuales).
- Si spread "Buen margen" o mejor Y liquidez "Buena"/"Excelente" (cumple ambos criterios
  de razón deseada-vs-diaria):
    - POTENCIAL_SIN_ORDENES si la actividad REAL de mercado (histórico de transacciones
      ejecutadas, ESI /markets/{region_id}/history/, últimos 7 días) es insuficiente:
      volumen diario promedio o cantidad de operaciones/día por debajo del mínimo. Esto
      es deliberadamente distinto de contar órdenes abiertas en el libro actual — una
      sola orden grande de una ballena no demuestra flujo real de compradores distintos,
      mientras que el histórico de transacciones ejecutadas sí lo refleja.
    - POTENCIAL en caso contrario.
- EN_OBSERVACION: todo lo demás — spread o liquidez borderline, se necesita más historial.
"""
GOOD_SPREADS = {"🟢 Buen margen", "🟢🟢 Muy bueno", "🟢🟢🟢 Excelente, si existe volumen"}
GOOD_LIQUIDITY = {"Excelente liquidez", "Buena"}
BAD_SPREADS = {"❌ Pérdida"}
BAD_LIQUIDITY = {"Muy lenta para tu capital"}

MIN_DAILY_VOLUME_7D = 10        # unidades/día promedio (últimos 7 días) para considerar flujo real
MIN_DAILY_ORDER_COUNT_7D = 3    # operaciones distintas/día promedio, para descartar "una sola ballena"
# Los dos de arriba son los DEFAULTS — el valor efectivo es configurable en runtime
# (AlertRules: storage.db.classification_settings, editable vía PUT /api/settings/
# classification o la PWA) y se pasa explícitamente a classify() en cada corrida.
#
# min_daily_volume_7d en 0 (o menos) DESACTIVA ese criterio: el volumen de un ítem está
# directamente atado a su costo (ítems caros rotan pocas unidades/día aunque tengan
# demanda real), así que a diferencia de min_daily_order_count_7d —indispensable,
# siempre se evalúa— el usuario puede apagar el filtro de volumen sin apagar el de
# cantidad de operaciones.


def classify(evaluacion_spread: str, liquidez: str,
             avg_daily_volume_7d: float, avg_daily_order_count_7d: float,
             min_daily_volume_7d: float = MIN_DAILY_VOLUME_7D,
             min_daily_order_count_7d: float = MIN_DAILY_ORDER_COUNT_7D) -> tuple[str, str]:
    if evaluacion_spread in BAD_SPREADS or liquidez in BAD_LIQUIDITY:
        return "DESCARTADO", f"Spread '{evaluacion_spread}' y/o liquidez '{liquidez}' no viables."

    if evaluacion_spread in GOOD_SPREADS and liquidez in GOOD_LIQUIDITY:
        volume_checked = min_daily_volume_7d > 0
        volume_ok = not volume_checked or avg_daily_volume_7d >= min_daily_volume_7d
        orders_ok = avg_daily_order_count_7d >= min_daily_order_count_7d

        if not volume_ok or not orders_ok:
            fallas = []
            if not volume_ok:
                fallas.append(f"{avg_daily_volume_7d:.1f} unidades/día (mínimo {min_daily_volume_7d:g})")
            if not orders_ok:
                fallas.append(f"{avg_daily_order_count_7d:.1f} operaciones/día (mínimo {min_daily_order_count_7d:g})")
            return "POTENCIAL_SIN_ORDENES", (
                f"Spread '{evaluacion_spread}' y liquidez '{liquidez}' cumplen, pero el histórico de "
                f"transacciones (7 días) no alcanza: {' y '.join(fallas)}. No hay evidencia de flujo real "
                f"de compradores."
            )
        return "POTENCIAL", f"Spread '{evaluacion_spread}' con liquidez '{liquidez}': cumple ambos criterios."

    return "EN_OBSERVACION", (
        f"Spread '{evaluacion_spread}' / liquidez '{liquidez}': borderline, requiere más historial."
    )
