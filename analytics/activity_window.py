"""Actividad real de mercado medida en días naturales.

La ESI (/markets/{region_id}/history/) no publica fila en los días sin operaciones. Tomar "las últimas 7 filas" de un
ítem poco líquido abarca semanas y lo hace parecer activo (7 operaciones en 40 días salían como 1 operación al día). Aquí
cada ventana son N días del calendario hasta `anchor` (el último día publicado del mercado, no hoy: antes de que la ESI
publique ayer, ese día no debe contar como cero), y los días sin fila cuentan como 0.

Un ítem que empezó a comerciarse hace menos días que la ventana (p. ej. uno lanzado hace 15 días) se divide entre los días
que lleva existiendo, no entre 30: si no, su actividad saldría a la mitad sin que nada haya cambiado. Para eso se pasa
`first_dates` (primer día con operaciones de cada ítem en el mercado).
"""
from datetime import date

import pandas as pd

WINDOW_7D = 7
WINDOW_30D = 30
COLUMNS = ["volumen_diario_real", "avg_daily_volume_7d", "avg_daily_order_count_7d"]


def activity_windows(history: pd.DataFrame, anchor: date | str | None,
                     first_dates: pd.Series | None = None) -> pd.DataFrame:
    """Por type_id: volumen diario medio de 30 días (`volumen_diario_real`) y volumen y operaciones diarias medias de
    7 días, sobre días naturales hasta `anchor` inclusive. Un ítem con histórico pero sin operaciones en la ventana da 0.
    `history` trae type_id, date, volume y order_count; `first_dates` (opcional, por type_id) acorta el divisor de los
    ítems más nuevos que la ventana."""
    if history.empty or anchor is None:
        return pd.DataFrame(columns=COLUMNS, index=pd.Index([], name="type_id"), dtype=float)
    anchor_ts = pd.Timestamp(anchor).normalize()
    age = (anchor_ts - pd.to_datetime(history["date"]).dt.normalize()).dt.days
    items = pd.Index(sorted(history["type_id"].unique()), name="type_id")
    if first_dates is None:
        lived = pd.Series(float("inf"), index=items)
    else:
        first = pd.to_datetime(first_dates.reindex(items)).dt.normalize()
        lived = ((anchor_ts - first).dt.days + 1).clip(lower=1).astype(float).fillna(float("inf"))

    def daily_mean(column: str, days: int) -> pd.Series:
        inside = history[(age >= 0) & (age < days)]
        total = inside.groupby("type_id")[column].sum().reindex(items, fill_value=0).astype(float)
        return total / lived.clip(upper=days)

    return pd.DataFrame({
        "volumen_diario_real": daily_mean("volume", WINDOW_30D),
        "avg_daily_volume_7d": daily_mean("volume", WINDOW_7D),
        "avg_daily_order_count_7d": daily_mean("order_count", WINDOW_7D),
    }, index=items)
