#!/usr/bin/env python3
"""Pruebas de mutación del simulador financiero (libro de la estación, /api/finance y escenarios guardados)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_check as mc  # noqa: E402

mc.TESTS = ["tests/test_simulator.py"]
B, F, U = "ingestion/station_book.py", "backend/api/finance.py", "storage/users_db.py"
mc.MUTATIONS = [
    ("el libro mezcla órdenes de otras estaciones", B, "if order.get(\"location_id\") != station_id or ", "if "),
    ("el libro mezcla compras con ventas", B, "bool(order.get(\"is_buy_order\")) != is_buy:", "False:"),
    ("las compras no van de la más cara a la más barata", B, "reverse=is_buy)[:MAX_LEVELS]", "reverse=False)[:MAX_LEVELS]"),
    ("no se limita el número de niveles", B, "[:MAX_LEVELS]", "[:MAX_LEVELS * 10]"),
    ("el libro no se cachea", B, "CACHE_TTL = 60.0", "CACHE_TTL = 0.0"),
    ("solo se lee la primera página", B, "while page <= pages and page <= MAX_PAGES:", "while page <= 1:"),
    ("un 404 se trata como caída de ESI", B, "if response.status_code == 404:", "if response.status_code == 999:"),
    ("se aceptan niveles sin volumen", B, "if price <= 0 or volume <= 0 or not price.is_finite():", "if not price.is_finite():"),
    ("los niveles con el mismo precio no se suman", B, "levels[price] = levels.get(price, 0) + volume", "levels[price] = volume"),
    ("evaluar no comprueba el origen", F, "def evaluate_route(body: EvaluateIn, request: Request):\n    check_same_origin(request)",
     "def evaluate_route(body: EvaluateIn, request: Request):\n    pass"),
    ("comparar no comprueba el origen", F, "def compare_route(body: CompareIn, request: Request):\n    check_same_origin(request)",
     "def compare_route(body: CompareIn, request: Request):\n    pass"),
    ("el libro en vivo usa siempre la región de Jita", F, "REGION_BY_MARKET[req.market_id]", "REGION_BY_MARKET[\"jita\"]"),
    ("el libro en vivo usa siempre la estación de Jita", F, "hub.station_id, req.type_id)", "60003760, req.type_id)"),
    ("el error del libro filtra el detalle interno", F, "\"El libro de órdenes no está disponible ahora mismo.\"",
     "f\"El libro de órdenes no está disponible ahora mismo. {exc}\""),
    ("el perfil propio ignora las correcciones manuales", F, "(_loads(row[\"override_json\"]) if row else None) or {})", "{})"),
    ("el saldo del wallet nunca se usa", F, "wallet = Decimal(row[\"wallet_isk\"]) if (req.use_wallet and row and row[\"wallet_isk\"]) else None",
     "wallet = None"),
    ("el saldo gana al capital escrito a mano", F, "capital = req.available_capital if req.available_capital is not None else wallet",
     "capital = wallet if wallet is not None else req.available_capital"),
    ("el ROI objetivo no se pasa de % a fracción", F, "target_roi=Decimal(str(req.target_roi_percent)) / 100", "target_roi=Decimal(str(req.target_roi_percent))"),
    ("la comisión del dueño no se pasa de % a fracción", F, "Decimal(str(req.owner_fee_percent)) / 100", "Decimal(str(req.owner_fee_percent))"),
    ("la foto guarda la consulta en vivo en vez del libro", F, "use_live_book=False, use_wallet=False,", "use_live_book=req.use_live_book, use_wallet=False,"),
    ("la foto guarda el modo de perfil en vez del perfil", F, "profile_mode=\"manual\",\n        manual_profile=", "profile_mode=req.profile_mode,\n        manual_profile="),
    ("la foto no congela el capital del wallet", F, "if result[\"capital_source\"] == \"WALLET\":", "if False:"),
    ("el nombre del escenario no se recorta", F, "body.name.strip()", "body.name"),
    ("las comparaciones se ordenan de peor a mejor", F, "key=roi, reverse=True)", "key=roi, reverse=False)"),
    ("use_wallet se acepta sin perfil propio", F, "if self.use_wallet and self.profile_mode != \"mine\":", "if False:"),
    ("el perfil manual no exige datos", F, "if self.profile_mode == \"manual\" and self.manual_profile is None:", "if False:"),
    ("el libro en vivo se acepta en estructuras", F, "if self.use_live_book and (self.venue != \"NPC\" or self.type_id is None):", "if False:"),
    ("no hay tope de niveles escritos a mano", F, "MAX_LEVELS = 200", "MAX_LEVELS = 20000"),
    ("no hay tope de escenarios a comparar", F, "MAX_COMPARE = 6", "MAX_COMPARE = 60"),
    ("no hay tope de escenarios guardados", U, "if count_scenarios(conn, character_id) >= MAX_SCENARIOS:", "if False:"),
    ("se puede borrar el escenario de otro", U, "\"DELETE FROM financial_scenario WHERE id = ? AND character_id = ?\"",
     "\"DELETE FROM financial_scenario WHERE id = ? AND ? IS NOT NULL\""),
    ("se listan los escenarios de otros", U, "\"SELECT * FROM financial_scenario WHERE character_id = ? ORDER BY id DESC\"",
     "\"SELECT * FROM financial_scenario WHERE ? IS NOT NULL ORDER BY id DESC\""),
    ("los escenarios sobreviven al borrado del usuario", U,
     "character_id INTEGER NOT NULL REFERENCES user(character_id) ON DELETE CASCADE,\n    name TEXT NOT NULL,",
     "character_id INTEGER NOT NULL,\n    name TEXT NOT NULL,"),
    ("la exportación omite los escenarios", U, "\"scenarios\": [dict(s) for s in list_scenarios(conn, character_id)]}", "\"scenarios\": []}"),
]

if __name__ == "__main__":
    sys.exit(mc.main())
