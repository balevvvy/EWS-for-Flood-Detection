"""
Script testing kontrol PTZ kamera Dahua via CGI API.
Cocok untuk kamera DH-SD5A225XA-HNR (dan model Dahua PTZ lainnya).

Cara pakai:
1. Ganti IP, USERNAME, PASSWORD sesuai kamera kamu
2. Jalankan script ini
3. Kamera akan bergerak sesuai urutan test (kanan, kiri, atas, bawah, zoom, stop)
4. Amati apakah kamera benar-benar bergerak di live view (buka browser terpisah ke IP kamera)
"""

import requests
import time

# ==================== KONFIGURASI ====================
IP = "10.52.9.101"
USERNAME = "admin"
PASSWORD = "Admin123."  # ganti sesuai password kamera
CHANNEL = 1  # channel 1 untuk kamera standalone

BASE_URL = f"http://{IP}/cgi-bin/ptz.cgi"


def ptz_command(action, code, arg1=0, arg2=0, arg3=0, arg4=0):
    """
    Kirim command PTZ ke kamera Dahua.
    action: 'start' atau 'stop'
    code: nama perintah, misal 'Right', 'Left', 'Up', 'Down', 'ZoomTele', 'GotoPreset'
    """
    params = {
        "action": action,
        "channel": CHANNEL,
        "code": code,
        "arg1": arg1,
        "arg2": arg2,
        "arg3": arg3,
        "arg4": arg4,
    }
    try:
        response = requests.get(
            BASE_URL,
            params=params,
            auth=requests.auth.HTTPDigestAuth(USERNAME, PASSWORD),
            timeout=5,
        )
        print(f"[{code}] Status: {response.status_code} | Response: {response.text.strip()}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"[{code}] Gagal koneksi: {e}")
        return False


def move_direction(direction, speed=5, duration=2):
    """
    Gerakkan kamera ke arah tertentu selama beberapa detik, lalu stop.
    direction: 'Left', 'Right', 'Up', 'Down', 'LeftUp', 'LeftDown', 'RightUp', 'RightDown'
    speed: 1-8
    duration: lama gerak dalam detik
    """
    print(f"\n--- Menggerakkan kamera: {direction} (speed={speed}, durasi={duration}s) ---")
    ptz_command("start", direction, arg1=0, arg2=speed, arg3=0)
    time.sleep(duration)
    ptz_command("stop", direction, arg1=0, arg2=speed, arg3=0)


def zoom(zoom_type="ZoomTele", speed=3, duration=1):
    """
    zoom_type: 'ZoomTele' (zoom in) atau 'ZoomWide' (zoom out)
    """
    print(f"\n--- Zoom: {zoom_type} (durasi={duration}s) ---")
    ptz_command("start", zoom_type, arg1=0, arg2=speed, arg3=0)
    time.sleep(duration)
    ptz_command("stop", zoom_type, arg1=0, arg2=speed, arg3=0)


def goto_preset(preset_no=1):
    """Gerakkan kamera ke posisi preset yang sudah disimpan sebelumnya."""
    print(f"\n--- Menuju Preset {preset_no} ---")
    ptz_command("start", "GotoPreset", arg1=0, arg2=preset_no, arg3=0)


def set_preset(preset_no=1):
    """Simpan posisi kamera saat ini sebagai preset."""
    print(f"\n--- Menyimpan posisi saat ini sebagai Preset {preset_no} ---")
    ptz_command("start", "SetPreset", arg1=0, arg2=preset_no, arg3=0)


def test_koneksi():
    """Test apakah kamera bisa diakses dan merespon command PTZ."""
    print("=== Testing koneksi PTZ ===")
    ok = ptz_command("start", "Right", arg1=0, arg2=1, arg3=0)
    time.sleep(0.5)
    ptz_command("stop", "Right", arg1=0, arg2=1, arg3=0)
    if ok:
        print(">> Koneksi PTZ berhasil, kamera merespon command.\n")
    else:
        print(">> Koneksi PTZ GAGAL. Cek IP, username, password, atau apakah CGI PTZ didukung/aktif.\n")
    return ok


if __name__ == "__main__":
    # 1. Test koneksi dasar dulu
    if not test_koneksi():
        print("Berhenti - koneksi PTZ gagal. Perbaiki dulu sebelum lanjut test gerak penuh.")
        exit()

    time.sleep(1)

    # 2. Test gerak ke berbagai arah (amati langsung di live view browser)
    move_direction("Right", speed=5, duration=2)
    time.sleep(1)

    move_direction("Left", speed=5, duration=2)
    time.sleep(1)

    move_direction("Up", speed=5, duration=1)
    time.sleep(1)

    move_direction("Down", speed=5, duration=1)
    time.sleep(1)

    # 3. Test zoom
    zoom("ZoomTele", duration=1)
    time.sleep(1)
    zoom("ZoomWide", duration=1)
    time.sleep(1)

    # 4. Test simpan & panggil preset
    print("\n--- Simpan posisi sekarang sebagai Preset 1 ---")
    set_preset(1)
    time.sleep(2)

    move_direction("Right", speed=5, duration=2)  # geser dulu biar beda posisi
    time.sleep(1)

    print("\n--- Kembali ke Preset 1 ---")
    goto_preset(1)
    time.sleep(2)

    print("\n=== Testing selesai ===")