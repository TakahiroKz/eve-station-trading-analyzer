"""Estaciones NPC de referencia de cada mercado y su dueño (para saber qué standings cuentan en el broker fee).

Los standings que reducen el broker fee de una estación NPC son los del dueño de la estación (corporación NPC) y los de
su facción. Dueños comprobados contra ESI /universe/stations/{id} el 2026-11-19; la facción de cada corporación NPC no
viene en ESI público (faction_id sale vacío), por eso va fija aquí.
"""
from dataclasses import dataclass

FACTION_CALDARI, FACTION_MINMATAR, FACTION_AMARR, FACTION_GALLENTE = 500001, 500002, 500003, 500004


@dataclass(frozen=True)
class Hub:
    market_id: str
    name: str
    station_id: int
    station_name: str
    owner_corp_id: int
    owner_corp_name: str
    faction_id: int


HUBS: tuple[Hub, ...] = (
    Hub("jita", "Jita", 60003760, "Jita IV - Moon 4 - Caldari Navy Assembly Plant", 1000035, "Caldari Navy", FACTION_CALDARI),
    Hub("amarr", "Amarr", 60008494, "Amarr VIII (Oris) - Emperor Family Academy", 1000086, "Emperor Family", FACTION_AMARR),
    Hub("dodixie", "Dodixie", 60011866, "Dodixie IX - Moon 20 - Federation Navy Assembly Plant", 1000120, "Federation Navy",
        FACTION_GALLENTE),
    Hub("rens", "Rens", 60004588, "Rens VI - Moon 8 - Brutor Tribe Treasury", 1000049, "Brutor Tribe", FACTION_MINMATAR),
    Hub("hek", "Hek", 60005686, "Hek VIII - Moon 12 - Boundless Creation Factory", 1000057, "Boundless Creation",
        FACTION_MINMATAR),
)
HUB_BY_MARKET = {hub.market_id: hub for hub in HUBS}


def wanted_standing_ids() -> tuple[set[int], set[int]]:
    """(ids de facción, ids de corporación) cuyos standings hay que guardar; el resto del listado de ESI se descarta."""
    return {h.faction_id for h in HUBS}, {h.owner_corp_id for h in HUBS}
