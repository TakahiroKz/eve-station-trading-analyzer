#!/usr/bin/env python3
"""Pruebas de mutación de las cuentas (cifrado, users.db, JWT y rutas /api/auth). Ver scripts/mutation_check.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_check as mc  # noqa: E402

mc.TESTS = ["tests/test_accounts.py"]
A = "backend/api/auth.py"
mc.MUTATIONS = [
    ("el character_id deja de ir como dato asociado del cifrado", "storage/token_crypto.py",
     "nonce, plaintext.encode(\"utf-8\"), str(character_id).encode())", "nonce, plaintext.encode(\"utf-8\"), None)"),
    ("el descifrado ignora el character_id", "storage/token_crypto.py",
     "AESGCM(key).decrypt(nonce, body, str(character_id).encode())", "AESGCM(key).decrypt(nonce, body, None)"),
    ("el nonce es fijo", "storage/token_crypto.py", "nonce = secrets.token_bytes(12)", "nonce = b\"0\" * 12"),
    ("sin claves el cifrado no falla", "storage/token_crypto.py",
     "    if not keys:\n        raise CryptoError(\"USERS_ENC_KEYS no está configurada\")", "    pass"),
    ("la sesión guarda el token en claro", "storage/users_db.py", "(_hash(raw), character_id, iso(now)", "(raw, character_id, iso(now)"),
    ("las sesiones nunca caducan", "storage/users_db.py", "WHERE s.token_hash = ? AND s.expires_at > ?", "WHERE s.token_hash = ? AND s.expires_at > ''"),
    ("sin borrado en cascada de tokens", "storage/users_db.py",
     "character_id INTEGER PRIMARY KEY REFERENCES user(character_id) ON DELETE CASCADE,\n    refresh_token_enc",
     "character_id INTEGER PRIMARY KEY,\n    refresh_token_enc"),
    ("la purga de inactivos borra a todos", "storage/users_db.py", "WHERE last_seen_at < ?\", (cutoff,))", "WHERE last_seen_at < ?\", (\"9999\",))"),
    ("el archivo de usuarios queda legible por otros", "storage/users_db.py", "os.chmod(path, 0o600)", "os.chmod(path, 0o644)"),
    ("el JWT acepta cualquier audiencia", "ingestion/eve_login.py", "audience=client_id,", "options_aud=None,"),
    ("el JWT no exige emisor", "ingestion/eve_login.py", "issuer=ISSUERS, ", ""),
    ("el JWT usa la primera clave aunque el kid no coincida", "ingestion/eve_login.py",
     "match = [k for k in keys if k.get(\"kid\") == header.get(\"kid\") and k.get(\"kty\") == \"RSA\"]", "match = keys[:1]"),
    ("el callback no comprueba el state", A, "or not hmac.compare_digest(state, expected):", "or False:"),
    ("el login no exige consentimiento", A, "if consent != CONSENT_VERSION:", "if False:"),
    ("cerrar sesión deja el token guardado", A, "users_db.delete_token(conn, user[\"character_id\"])", "pass"),
    ("borrar mis datos no borra", A, "users_db.delete_user(conn, user[\"character_id\"])", "pass"),
    ("la cookie de sesión es legible por JavaScript", A,
     "max_age=users_db.SESSION_TTL_DAYS * 86400, httponly=True,", "max_age=users_db.SESSION_TTL_DAYS * 86400, httponly=False,"),
    ("la cookie de estado no es HttpOnly", A, "max_age=STATE_TTL, httponly=True,", "max_age=STATE_TTL, httponly=False,"),
    ("la cookie de estado no se retira tras el flujo", A, "response.delete_cookie(STATE_COOKIE, path=\"/api/auth\")", "pass"),
    ("el token cifrado se guarda en claro", A, "encrypted = token_crypto.encrypt(refresh, character_id)", "encrypted = refresh.encode()"),
    ("las respuestas se pueden cachear", A, 'NO_STORE = {"Cache-Control": "no-store"}', "NO_STORE = {}"),
    ("el logout acepta peticiones de otros sitios", A, "def logout(request: Request):\n    check_same_origin(request)", "def logout(request: Request):\n    pass"),
    ("la exportación incluye el token", "storage/users_db.py", "\"SELECT scopes, status, updated_at FROM user_token", "\"SELECT * FROM user_token"),
]

if __name__ == "__main__":
    sys.exit(mc.main())
