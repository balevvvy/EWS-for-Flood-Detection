"""
Modul Autentikasi sederhana untuk EWS Banjir.
Menggunakan session cookie untuk membedakan Publik vs Operator.
"""

import hashlib
import secrets
import time

OPERATORS = {
    "operator": {
        "password_hash": hashlib.sha256("ews2026".encode()).hexdigest(),
        "nama": "Operator EWS"
    }
}

# Penyimpanan session in-memory (reset saat server restart)
_sessions: dict[str, dict] = {}

# Durasi session: 8 jam
SESSION_DURATION = 8 * 3600


def authenticate(username: str, password: str) -> str | None:
    """
    Verifikasi username dan password.
    Mengembalikan session_token jika berhasil, None jika gagal.
    """
    user = OPERATORS.get(username)
    if not user:
        return None

    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if password_hash != user["password_hash"]:
        return None

    # Buat session token
    token = secrets.token_hex(32)
    _sessions[token] = {
        "username": username,
        "nama": user["nama"],
        "created_at": time.time()
    }
    return token


def validate_session(token: str) -> dict | None:
    """
    Validasi session token.
    Mengembalikan info user jika valid, None jika expired/tidak ada.
    """
    if not token:
        return None

    session = _sessions.get(token)
    if not session:
        return None

    # Cek apakah sudah expired
    if time.time() - session["created_at"] > SESSION_DURATION:
        _sessions.pop(token, None)
        return None

    return session


def logout(token: str):
    """Hapus session."""
    _sessions.pop(token, None)
