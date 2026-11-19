#!/usr/bin/env python3
"""Mantenimiento de users.db: genkey | rotate | purge.

  python scripts/users_admin.py genkey   # imprime una clave nueva para USERS_ENC_KEYS (anteponla a las existentes)
  python scripts/users_admin.py rotate   # re-cifra todos los tokens con la clave actual (la primera)
  python scripts/users_admin.py purge    # borra sesiones caducadas y usuarios sin uso en 12 meses
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from storage import token_crypto, users_db  # noqa: E402


def rotate(conn) -> int:
    changed = 0
    for row in conn.execute("SELECT character_id, refresh_token_enc FROM user_token").fetchall():
        blob = bytes(row["refresh_token_enc"])
        if token_crypto.needs_rotation(blob):
            plain = token_crypto.decrypt(blob, row["character_id"])
            conn.execute("UPDATE user_token SET refresh_token_enc = ? WHERE character_id = ?",
                         (token_crypto.encrypt(plain, row["character_id"]), row["character_id"]))
            changed += 1
    conn.commit()
    return changed


def main(argv: list[str]) -> int:
    load_dotenv()
    command = argv[1] if len(argv) > 1 else ""
    if command == "genkey":
        print(token_crypto.generate_key())
        return 0
    if command not in ("rotate", "purge"):
        print(__doc__)
        return 2
    users_db.init_users_db()
    conn = users_db.connect()
    try:
        if command == "rotate":
            print(f"tokens re-cifrados: {rotate(conn)}")
        else:
            now = users_db.utcnow()
            sessions = users_db.purge_expired_sessions(conn, now)
            users = users_db.purge_inactive_users(conn, now)
            conn.commit()
            print(f"sesiones caducadas borradas: {sessions}; usuarios inactivos borrados: {users}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
