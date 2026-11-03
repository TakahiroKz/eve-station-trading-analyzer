"""Rutas de datos de la aplicacion.

Distingue dos tipos de ubicacion porque, una vez empaquetada con PyInstaller, el codigo
se ejecuta desde una carpeta temporal de solo lectura:

- Recursos empaquetados (config/default_config.json): se leen desde el bundle (sys._MEIPASS
  en modo --onefile, o la carpeta del ejecutable en --onedir). Nunca se escriben.
- Datos persistentes del usuario (user_config.json, base de datos SQLite): se guardan en una
  carpeta de datos de usuario que sobrevive entre ejecuciones y actualizaciones del programa.

En modo desarrollo (ejecutando `python main.py` desde el repo) ambas coinciden con la carpeta
del proyecto, para no ensuciar el sistema con datos de prueba.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IS_FROZEN = getattr(sys, "frozen", False)


def _bundle_root() -> Path:
    """Carpeta de solo lectura donde PyInstaller deja los recursos empaquetados (--add-data)."""
    if IS_FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return PROJECT_ROOT


def _user_data_root() -> Path:
    """Carpeta persistente y escribible para configuracion de usuario y base de datos."""
    if not IS_FROZEN:
        return PROJECT_ROOT
    base = os.getenv("APPDATA") or str(Path.home())
    return Path(base) / "EVEStationTradingAnalyzer"


CONFIG_DIR = _bundle_root() / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default_config.json"

USER_DATA_DIR = _user_data_root()
USER_CONFIG_PATH = USER_DATA_DIR / "config" / "user_config.json"
DATA_DIR = USER_DATA_DIR / "data"
DB_PATH = DATA_DIR / "station_trading.db"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
