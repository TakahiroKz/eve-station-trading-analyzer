"""Sincroniza cada fila del registro con el Google Sheet 'EveCalculator - Registro'.

Degrada sin bloquear el pipeline si no hay credenciales/conector disponible: loguea
la fila pendiente de sincronizar y continúa. El próximo cálculo vuelve a intentarlo,
no se abandona el intento solo porque falló una vez.
"""
import logging
import os
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

HEADERS = [
    "Fecha", "Item", "Buy", "Sell", "Volumen deseado", "Volumen diario real",
    "Beneficio", "Spread bruto", "Precio min venta", "ROI",
    "Evaluación del spread", "Posición vs volumen diario", "Liquidez", "Recomendación",
]

PENDING_LOG_PATH = Path("reporting/pending_gsheets_sync.log")

_worksheet_cache = None  # evita reabrir el Sheet por nombre (round-trip a la API) en cada fila


def _get_worksheet():
    """Devuelve la worksheet ya abierta (cacheada por proceso), o None si no hay credenciales."""
    global _worksheet_cache
    if _worksheet_cache is not None:
        return _worksheet_cache

    creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_path or not Path(creds_path).exists():
        return None

    import gspread

    client = gspread.service_account(filename=creds_path)
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "EveCalculator - Registro")
    try:
        sh = client.open(sheet_name)
    except Exception:
        sh = client.create(sheet_name)
        sh.sheet1.append_row(HEADERS)

    _worksheet_cache = sh.sheet1
    return _worksheet_cache


def _log_pending(row: list) -> None:
    PENDING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(",".join(str(v) for v in row) + "\n")
    logger.warning("Google Sheets no disponible: fila registrada en %s para sync posterior", PENDING_LOG_PATH)


def append_opportunity_row(result_row: list) -> bool:
    """result_row: [item, buy, sell, vol_deseado, vol_real, beneficio, spread, precio_min,
    roi, eval_spread, posicion, liquidez, recomendacion] (sin fecha, se antepone aquí).

    Devuelve True si sincronizó, False si degradó (quedó pendiente).
    """
    row = [date.today().isoformat(), *result_row]

    worksheet = _get_worksheet()
    if worksheet is None:
        _log_pending(row)
        return False

    try:
        worksheet.append_row(row)
        return True
    except Exception:
        logger.exception("Fallo al sincronizar con Google Sheets, degradando a log local")
        _log_pending(row)
        return False
