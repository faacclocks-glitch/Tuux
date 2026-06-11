import os
import re
import json
import secrets
import hashlib
import sqlite3
import datetime
from pathlib import Path
import getpass


COMMON_PASSWORDS = {
    "123456", "12345678", "password", "qwerty", "abc123",
    "111111", "123456789", "iloveyou", "admin", "welcome",
    "contraseña"
}


def password_strength(password: str) -> (bool, str):
    """Return (ok, message). Enforces a strong password policy."""
    if len(password) < 12:
        return False, "Debe tener al menos 12 caracteres."
    if password.lower() in COMMON_PASSWORDS:
        return False, "Contraseña demasiado común."
    if not re.search(r"[a-z]", password):
        return False, "Debe contener minúsculas."
    if not re.search(r"[A-Z]", password):
        return False, "Debe contener mayúsculas."
    if not re.search(r"[0-9]", password):
        return False, "Debe contener dígitos."
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Debe contener al menos un símbolo (p. ej. !@#$%)."
    return True, "OK"


def hash_password(password: str, iterations: int = 200_000) -> dict:
    """Hash password using PBKDF2-HMAC-SHA256 with a random salt.

    Returns a dict with hex-encoded salt, hash and iterations.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {"salt": salt.hex(), "hash": dk.hex(), "iterations": iterations}


def verify_password(password: str, salt_hex: str, hash_hex: str, iterations: int) -> bool:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(dk.hex(), hash_hex)


def db_file_path() -> Path:
    # Allow overriding DB path for tests via env var
    env = os.environ.get("USER_ACCOUNT_DB")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "accounts.db"


def db_connect():
    p = db_file_path()
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = db_connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            salt TEXT NOT NULL,
            hash TEXT NOT NULL,
            iterations INTEGER NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'cliente'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
        )
        """
    )
    conn.commit()

    # If the table already existed without the tipo column, add it.
    cur = conn.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cur.fetchall()]
    if 'tipo' not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN tipo TEXT NOT NULL DEFAULT 'cliente'")
        conn.commit()
    conn.close()


def get_user(username: str):
    init_db()
    conn = db_connect()
    cur = conn.execute("SELECT salt, hash, iterations FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_role(username: str):
    init_db()
    conn = db_connect()
    cur = conn.execute("SELECT tipo FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def migrate_from_json(json_path: str = None) -> int:
    """Migrate accounts from a JSON file into the SQLite DB.

    The JSON should be a mapping username -> {salt, hash, iterations}.
    Returns the number of migrated accounts.
    """
    if json_path is None:
        json_path = Path(__file__).resolve().parent / "accounts.json"
    else:
        json_path = Path(json_path)
    if not json_path.exists():
        return 0
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    init_db()
    migrated = 0
    conn = db_connect()
    for username, record in data.items():
        if get_user(username) is not None:
            continue
        try:
            salt = record["salt"]
            hash_hex = record["hash"]
            iterations = int(record.get("iterations", 200000))
        except Exception:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO users (username, salt, hash, iterations) VALUES (?, ?, ?, ?)",
            (username, salt, hash_hex, iterations),
        )
        migrated += 1
    conn.commit()
    conn.close()
    return migrated


def create_account(username: str, password: str, tipo: str = 'cliente') -> (bool, str):
    init_db()
    if get_user(username) is not None:
        return False, "El usuario ya existe."
    ok, msg = password_strength(password)
    if not ok:
        return False, msg
    hashed = hash_password(password)
    conn = db_connect()
    conn.execute(
        "INSERT INTO users (username, salt, hash, iterations, tipo) VALUES (?, ?, ?, ?, ?)",
        (username, hashed["salt"], hashed["hash"], hashed["iterations"], tipo),
    )
    conn.commit()
    conn.close()
    return True, "Cuenta creada correctamente."


def verify_login(username: str, password: str) -> (bool, str):
    row = get_user(username)
    if row is None:
        return False, "Usuario no encontrado."
    salt, hash_hex, iterations = row
    if verify_password(password, salt, hash_hex, iterations):
        return True, "Autenticación correcta."
    return False, "Contraseña incorrecta."


def _clear_expired_reset_tokens(conn):
    expiration = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    conn.execute(
        "DELETE FROM reset_tokens WHERE created_at < ?",
        (expiration.isoformat(),),
    )


def create_reset_token(username: str) -> (bool, str):
    if get_user(username) is None:
        return False, "Usuario no encontrado."
    init_db()
    token = secrets.token_urlsafe(24)
    created_at = datetime.datetime.utcnow().isoformat()
    conn = db_connect()
    with conn:
        _clear_expired_reset_tokens(conn)
        conn.execute(
            "INSERT INTO reset_tokens (username, token, created_at) VALUES (?, ?, ?)",
            (username, token, created_at),
        )
    conn.close()
    return True, token


def verify_reset_token(username: str, token: str) -> bool:
    init_db()
    conn = db_connect()
    _clear_expired_reset_tokens(conn)
    cur = conn.execute(
        "SELECT 1 FROM reset_tokens WHERE username = ? AND token = ?",
        (username, token),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def delete_reset_tokens(username: str):
    init_db()
    conn = db_connect()
    with conn:
        conn.execute("DELETE FROM reset_tokens WHERE username = ?", (username,))
    conn.close()


def reset_password(username: str, new_password: str, token: str) -> (bool, str):
    if get_user(username) is None:
        return False, "Usuario no encontrado."
    if not verify_reset_token(username, token):
        return False, "Token de recuperación inválido o expirado."
    ok, msg = password_strength(new_password)
    if not ok:
        return False, msg
    hashed = hash_password(new_password)
    conn = db_connect()
    with conn:
        conn.execute(
            "UPDATE users SET salt = ?, hash = ?, iterations = ? WHERE username = ?",
            (hashed["salt"], hashed["hash"], hashed["iterations"], username),
        )
        conn.execute("DELETE FROM reset_tokens WHERE username = ?", (username,))
    conn.close()
    return True, "Contraseña actualizada correctamente."


def create_account_interactive():
    print("Crear cuenta de usuario (entrada oculta para contraseñas)")
    username = input("Usuario: ").strip()
    if not username:
        print("Usuario vacío — cancelado.")
        return False
    pwd = getpass.getpass("Contraseña: ")
    pwd2 = getpass.getpass("Confirmar contraseña: ")
    if pwd != pwd2:
        print("Las contraseñas no coinciden.")
        return False
    ok, msg = password_strength(pwd)
    if not ok:
        print(f"Contraseña inválida: {msg}")
        return False
    success, info = create_account(username, pwd)
    print(info)
    return success


def login_interactive():
    print("Iniciar sesión")
    username = input("Usuario: ").strip()
    if not username:
        print("Usuario vacío — cancelado.")
        return False
    pwd = getpass.getpass("Contraseña: ")
    ok, msg = verify_login(username, pwd)
    print(msg)
    return ok


if __name__ == "__main__":
    # Menu simple
    init_db()
    print("Elige una opción: 1) Crear cuenta  2) Iniciar sesión")
    choice = input("Opción (1/2): ").strip()
    if choice == "1":
        create_account_interactive()
    elif choice == "2":
        login_interactive()
    else:
        print("Opción inválida. Salida.")
