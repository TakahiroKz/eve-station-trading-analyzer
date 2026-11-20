#!/usr/bin/env python3
"""Pruebas de mutación del perfil y capital del jugador (lectura de ESI, perfil efectivo y rutas /api/me)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_check as mc  # noqa: E402

mc.TESTS = ["tests/test_profile.py"]
E, U, M = "ingestion/esi_profile.py", "finance/user_profile.py", "backend/api/me.py"
mc.MUTATIONS = [
    ("las habilidades se releen cada 24 días", E, "REFRESH_AFTER = timedelta(hours=24)", "REFRESH_AFTER = timedelta(days=24)"),
    ("sin límite entre intentos", E, "if gap is not None and gap < MIN_ATTEMPT_GAP and (force or profile[\"sync_status\"] != \"OK\"):", "if False:"),
    ("la actualización manual no se frena tras una lectura correcta", E, "(force or profile[\"sync_status\"] != \"OK\")", "(profile[\"sync_status\"] != \"OK\")"),
    ("un fallo no frena el reintento inmediato", E, "(force or profile[\"sync_status\"] != \"OK\")", "force"),
    ("el saldo casi no se cachea", E, "WALLET_TTL = timedelta(minutes=5)", "WALLET_TTL = timedelta(seconds=1)"),
    ("el aviso de perfil viejo tarda 20 días", E, "STALE_AFTER = timedelta(hours=48)", "STALE_AFTER = timedelta(hours=480)"),
    ("id equivocado de Broker Relations", E, "3446: \"broker_relations\"", "3447: \"broker_relations\""),
    ("id equivocado de Accounting", E, "16622: \"accounting\"", "16623: \"accounting\""),
    ("usa el nivel entrenado en vez del activo", E, "item.get(\"active_skill_level\")", "item.get(\"trained_skill_level\")"),
    ("una habilidad sin entrenar no se rellena a 0", E,
     "return {name: trained.get(name, 0) for name in SKILL_IDS.values()}", "return trained"),
    ("los agentes cuentan como corporación", E,
     "{\"faction\": \"faction\", \"npc_corp\": \"corp\"}", "{\"faction\": \"faction\", \"npc_corp\": \"corp\", \"agent\": \"corp\"}"),
    ("se aceptan standings fuera de rango", E, "if value.is_finite() and abs(value) <= 10:", "if value.is_finite():"),
    ("se acepta un saldo negativo", E, "if not value.is_finite() or value < 0:", "if not value.is_finite():"),
    ("un 403 de ESI no se reconoce", E, "if response.status_code == 403:", "if response.status_code == 999:"),
    ("cualquier 400 del SSO cuenta como revocado", E, "if exc.response.json().get(\"error\") == \"invalid_grant\":", "if True:"),
    ("un token revocado no se marca", E, "users_db.set_token_status(conn, character_id, \"REVOKED\", now)", "pass"),
    ("el refresh token rotado no se guarda", E, "if new_refresh and new_refresh != refresh:", "if False:"),
    ("se piden standings sin comprobar el permiso", E, "if SCOPE_STANDINGS in scopes:", "if True:"),
    ("se relee ESI en cada visita", E, "if not force and not needs_sync(profile, now, want_wallet):", "if False:"),
    ("el intento fallido no se registra", E, "users_db.save_sync_result(conn, character_id, status, now)", "pass"),
    ("el dato manual no gana al de ESI", U, "if m is not None:\n            out[field]", "if False:\n            out[field]"),
    ("un perfil con datos manuales se marca como ESI", U, "source=\"ESI\" if all_esi else \"MANUAL\"", "source=\"ESI\""),
    ("un nivel corrupto fuera de rango se acepta", U, "or not 0 <= raw <= DEFAULT_RULES.max_skill_level", "or False"),
    ("un standing corrupto fuera de rango se acepta", U, "abs(value) > DEFAULT_RULES.max_standing", "False"),
    ("Rens apunta a la facción equivocada", "finance/hubs.py", "1000049, \"Brutor Tribe\", FACTION_MINMATAR)", "1000049, \"Brutor Tribe\", FACTION_AMARR)"),
    ("guardar correcciones no comprueba el origen", M,
     "check_same_origin(request)\n    conn, user, _client_id, _secret = _session(request)", "conn, user, _client_id, _secret = _session(request)"),
    ("actualizar no comprueba el origen", M,
     "def refresh_profile(request: Request):\n    check_same_origin(request)", "def refresh_profile(request: Request):\n    pass"),
    ("no se exige el consentimiento vigente", M, "if user[\"consent_version\"] != CONSENT_VERSION:", "if False:"),
    ("el límite de actualización manual no responde 429", M, "if status == \"THROTTLED\":", "if False:"),
    ("las respuestas del perfil se pueden cachear", M,
     "headers={**NO_STORE, **(headers or {})})", "headers=(headers or {}))"),
    ("se aceptan mercados inventados", M, "if market_id not in HUB_BY_MARKET:", "if False:"),
    ("se aceptan campos desconocidos", M, "model_config = ConfigDict(extra=\"forbid\")", "model_config = ConfigDict()"),
    ("el nivel de Accounting no se acota", M, "accounting: int | None = Field(None, ge=0, le=5)", "accounting: int | None = Field(None)"),
    ("la exportación omite el perfil", "storage/users_db.py", "\"profile\": dict(profile) if profile else None,", "\"profile\": None,"),
    ("el perfil sobrevive al borrado del usuario", "storage/users_db.py",
     "character_id INTEGER PRIMARY KEY REFERENCES user(character_id) ON DELETE CASCADE,\n    skills_json",
     "character_id INTEGER PRIMARY KEY,\n    skills_json"),
]

if __name__ == "__main__":
    sys.exit(mc.main())
