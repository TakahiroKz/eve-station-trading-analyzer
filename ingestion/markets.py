"""Mercados que procesa el motor: los activos de la tabla `market` o los que pida `--markets`.

Cada mercado es una región de EVE (como Jita desde el principio). La tabla `market` (storage/db.py,
MARKETS_SEED) dice cuáles están activos; activar o desactivar uno es cambiar `enabled`, sin tocar código.
"""
from dataclasses import dataclass

from storage.db import get_connection


class UnknownMarketError(ValueError):
    """Se pidió un mercado que no existe en la tabla `market`."""


@dataclass(frozen=True)
class Market:
    market_id: str
    name: str
    region_id: int


def list_markets(db_path: str, only: list[str] | None = None) -> list[Market]:
    """Mercados a procesar, en el orden de `sort_order`. Con `only` se devuelven esos mercados (aunque
    estén desactivados: sirve para rellenar el histórico de uno antes de activarlo), en el orden pedido."""
    conn = get_connection(db_path)
    try:
        if only is None:
            rows = conn.execute(
                "SELECT market_id, name, region_id FROM market WHERE enabled = 1 ORDER BY sort_order, market_id"
            ).fetchall()
            return [Market(r["market_id"], r["name"], r["region_id"]) for r in rows]
        markets: list[Market] = []
        for market_id in only:
            row = conn.execute(
                "SELECT market_id, name, region_id FROM market WHERE market_id = ?", (market_id,),
            ).fetchone()
            if row is None:
                raise UnknownMarketError(f"El mercado '{market_id}' no existe en la tabla market")
            if all(m.market_id != row["market_id"] for m in markets):
                markets.append(Market(row["market_id"], row["name"], row["region_id"]))
        return markets
    finally:
        conn.close()
