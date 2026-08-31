"""
Module loader konfigurasi kamera terpusat.
Membaca file config/config.yaml jika tersedia (lokal, diabaikan oleh Git).
Jika tidak ada, menggunakan environment variable atau nilai placeholder aman.
"""

import os
import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")


def load_camera_config() -> dict:
    """
    Memuat kredensial kamera secara aman.
    Prioritas:
    1. config/config.yaml (file lokal ter-ignore git)
    2. Environment variables (CAMERA_IP, CAMERA_USER, CAMERA_PASSWORD)
    3. Nilai default placeholder
    """
    config = {
        "ip": os.getenv("CAMERA_IP", "192.168.1.100"),
        "username": os.getenv("CAMERA_USER", "admin"),
        "password": os.getenv("CAMERA_PASSWORD", "your_password"),
        "channel": 1,
    }

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = yaml.safe_load(f)
                if data and "camera" in data:
                    cam = data["camera"]
                    config["ip"] = str(cam.get("ip", config["ip"]))
                    config["username"] = str(cam.get("username", config["username"]))
                    config["password"] = str(cam.get("password", config["password"]))
                    config["channel"] = int(cam.get("channel", config["channel"]))
        except Exception as e:
            print(f"[config_loader] Gagal membaca config.yaml: {e}")

    return config
