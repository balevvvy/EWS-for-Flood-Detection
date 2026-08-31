"""
Modul Database SQLite untuk EWS Banjir.
Menyimpan riwayat pembacaan ketinggian air dan log alert.
"""

import sqlite3
import os
import time
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "data", "ews.db")

# Lock untuk thread-safety (FastAPI berjalan multi-thread)
_lock = threading.Lock()


def get_connection():
    """Buat koneksi SQLite baru (per-thread)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging untuk performa
    return conn


def init_db():
    """Buat tabel jika belum ada. Panggil sekali saat server startup."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_ketinggian_air (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            water_y INTEGER,
            status TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS log_alert (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            pesan TEXT,
            timestamp REAL NOT NULL
        )
    """)

    # Index untuk query berdasarkan waktu
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ketinggian_timestamp 
        ON log_ketinggian_air(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_alert_timestamp 
        ON log_alert(timestamp)
    """)

    conn.commit()
    conn.close()
    print(f"[Database] Inisialisasi selesai: {DB_PATH}")


def insert_reading(water_y: int | None, status: str):
    """Simpan satu pembacaan ketinggian air."""
    with _lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO log_ketinggian_air (water_y, status, timestamp) VALUES (?, ?, ?)",
            (water_y, status, time.time())
        )
        conn.commit()
        conn.close()


def insert_alert(status: str, pesan: str):
    """Simpan log alert yang telah dikonfirmasi."""
    with _lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO log_alert (status, pesan, timestamp) VALUES (?, ?, ?)",
            (status, pesan, time.time())
        )
        conn.commit()
        conn.close()


def get_history(hours: float = 24, limit: int = 1000) -> list[dict]:
    """
    Ambil riwayat pembacaan ketinggian air dalam N jam terakhir.
    Mengembalikan list of dict: [{water_y, status, timestamp}, ...]
    """
    since = time.time() - (hours * 3600)
    conn = get_connection()
    rows = conn.execute(
        "SELECT water_y, status, timestamp FROM log_ketinggian_air "
        "WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT ?",
        (since, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_alerts(hours: float = 24, limit: int = 100) -> list[dict]:
    """Ambil riwayat alert dalam N jam terakhir."""
    since = time.time() - (hours * 3600)
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, pesan, timestamp FROM log_alert "
        "WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
        (since, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_alert_count() -> dict:
    """Hitung jumlah alert per status (untuk ringkasan dashboard)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as count FROM log_alert GROUP BY status"
    ).fetchall()
    conn.close()
    return {r["status"]: r["count"] for r in rows}
