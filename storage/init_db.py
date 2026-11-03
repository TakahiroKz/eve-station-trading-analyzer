"""Inicializa el esquema SQLite en DB_PATH (crea las tablas si no existen)."""
import os
import sys

from dotenv import load_dotenv

from storage.db import init_db


def main() -> int:
    load_dotenv()
    db_path = os.environ.get("DB_PATH", "./storage/market.db")
    init_db(db_path)
    print(f"OK: esquema inicializado en {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
