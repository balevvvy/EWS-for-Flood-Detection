"""
Modul kontrol PTZ kamera Dahua via HTTP CGI API.
Menyediakan fitur pembacaan status, penyimpanan posisi, dan kalibrasi closed-loop.
"""

import os
import sys
import re
import json
import time
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.camera.config_loader import load_camera_config

_cam_config = load_camera_config()
IP = _cam_config["ip"]
USERNAME = _cam_config["username"]
PASSWORD = _cam_config["password"]
CHANNEL = 0
FILE_KOORDINAT = os.path.join(BASE_DIR, "config", "koordinat_threshold.json")

BASE_URL = f"http://{IP}/cgi-bin/ptz.cgi"
AUTH = requests.auth.HTTPDigestAuth(USERNAME, PASSWORD)


def get_status():
    """Membaca koordinat Pan/Tilt/Zoom kamera saat ini."""
    params = {"action": "getStatus"}
    try:
        response = requests.get(BASE_URL, params=params, auth=AUTH, timeout=5)
        text = response.text

        pan = re.search(r"status\.Postion\[0\]=([\-\d\.]+)", text)
        tilt = re.search(r"status\.Postion\[1\]=([\-\d\.]+)", text)
        zoom = re.search(r"status\.Postion\[2\]=([\-\d\.]+)", text)

        if not (pan and tilt and zoom):
            return None

        pan_abs = re.search(r"status\.AbsPosition\[0\]=([\-\d\.]+)", text)
        tilt_abs = re.search(r"status\.AbsPosition\[1\]=([\-\d\.]+)", text)
        zoom_abs = re.search(r"status\.AbsPosition\[2\]=([\-\d\.]+)", text)
        zoom_value = re.search(r"status\.ZoomValue=([\-\d\.]+)", text)
        zoom_map = re.search(r"status\.ZoomMapValue=([\-\d\.]+)", text)
        focus_pos = re.search(r"status\.Focus\.FocusPosition=([\-\d\.]+)", text)

        return {
            "pan": float(pan.group(1)),
            "tilt": float(tilt.group(1)),
            "zoom": float(zoom.group(1)),
            "_pan_abs": float(pan_abs.group(1)) if pan_abs else None,
            "_tilt_abs": float(tilt_abs.group(1)) if tilt_abs else None,
            "_zoom_abs": float(zoom_abs.group(1)) if zoom_abs else None,
            "_zoom_value": float(zoom_value.group(1)) if zoom_value else None,
            "_zoom_map": float(zoom_map.group(1)) if zoom_map else None,
            "_focus_position": float(focus_pos.group(1)) if focus_pos else None,
            "_raw_text": text,
        }
    except requests.exceptions.RequestException:
        return None


def simpan_koordinat(koordinat, filename=FILE_KOORDINAT):
    with open(filename, "w") as f:
        json.dump(koordinat, f, indent=2)


def baca_koordinat_tersimpan(filename=FILE_KOORDINAT):
    with open(filename, "r") as f:
        return json.load(f)


def goto_position_abs(pan, tilt, zoom, speed=5):
    params = {
        "action": "start",
        "channel": CHANNEL,
        "code": "PositionABS",
        "arg1": pan,
        "arg2": tilt,
        "arg3": zoom,
        "arg4": speed,
    }
    try:
        response = requests.get(BASE_URL, params=params, auth=AUTH, timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def move_direction(direction, speed=5, duration=2):
    params_start = {"action": "start", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": speed, "arg3": 0, "arg4": 0}
    params_stop = {"action": "stop", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": speed, "arg3": 0, "arg4": 0}
    try:
        requests.get(BASE_URL, params=params_start, auth=AUTH, timeout=5)
        time.sleep(duration)
        requests.get(BASE_URL, params=params_stop, auth=AUTH, timeout=5)
    except requests.exceptions.RequestException:
        pass


def axis_nudge_closed_loop(axis_label, get_value, target_value, code_a, code_b,
                            tolerance=0.5, max_iterations=15, base_speed=4,
                            calibration_duration=0.8, gain=0.85,
                            min_duration=0.12, max_duration=6.0):
    status = get_status()
    if not status:
        return False

    current = get_value(status)
    diff = target_value - current
    if abs(diff) <= tolerance:
        return True

    params_start = {"action": "start", "channel": CHANNEL, "code": code_a, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
    params_stop = {"action": "stop", "channel": CHANNEL, "code": code_a, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
    try:
        requests.get(BASE_URL, params=params_start, auth=AUTH, timeout=5)
        time.sleep(calibration_duration)
        requests.get(BASE_URL, params=params_stop, auth=AUTH, timeout=5)
    except requests.exceptions.RequestException:
        return False

    time.sleep(0.8)
    status2 = get_status()
    if not status2:
        return False

    delta_from_test = get_value(status2) - current
    if abs(delta_from_test) < 0.05:
        return False

    a_increases = delta_from_test > 0
    rate_per_sec = abs(delta_from_test) / calibration_duration
    current = get_value(status2)

    for _ in range(max_iterations):
        diff = target_value - current
        if abs(diff) <= tolerance:
            return True

        direction = code_a if (diff > 0 if a_increases else diff <= 0) else code_b
        duration = min(max((abs(diff) / rate_per_sec) * gain, min_duration), max_duration)

        p_start = {"action": "start", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
        p_stop = {"action": "stop", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
        try:
            requests.get(BASE_URL, params=p_start, auth=AUTH, timeout=5)
            time.sleep(duration)
            requests.get(BASE_URL, params=p_stop, auth=AUTH, timeout=5)
        except requests.exceptions.RequestException:
            return False

        time.sleep(0.6)
        status_n = get_status()
        if not status_n:
            return False
        current = get_value(status_n)

    return abs(target_value - current) <= tolerance


def tilt_nudge_closed_loop(target_tilt, tolerance=0.5, max_iterations=15, base_speed=4):
    return axis_nudge_closed_loop("tilt", lambda s: s["tilt"], target_tilt, "Up", "Down", tolerance=tolerance, max_iterations=max_iterations, base_speed=base_speed)


def zoom_nudge_closed_loop(target_zoom, tolerance=0.3, max_iterations=15, base_speed=4):
    return axis_nudge_closed_loop("zoom", lambda s: s["zoom"], target_zoom, "ZoomTele", "ZoomWide", tolerance=tolerance, max_iterations=max_iterations, base_speed=base_speed)


def mode_simpan():
    input("Arahkan kamera ke papan threshold, lalu tekan Enter...")
    koordinat = get_status()
    if koordinat:
        simpan_koordinat(koordinat)
        print("Koordinat berhasil disimpan.")
    else:
        print("Gagal membaca koordinat kamera.")


def mode_kembali():
    try:
        koordinat = baca_koordinat_tersimpan()
    except FileNotFoundError:
        print(f"File {FILE_KOORDINAT} tidak ditemukan.")
        return

    posisi_sebelum = get_status()
    if not posisi_sebelum:
        print("Gagal membaca posisi kamera.")
        return

    goto_position_abs(koordinat["pan"], posisi_sebelum["tilt"], posisi_sebelum["zoom"])
    time.sleep(3)

    tilt_nudge_closed_loop(koordinat["tilt"])
    zoom_nudge_closed_loop(koordinat["zoom"])

    posisi_sekarang = get_status()
    if posisi_sekarang:
        print(f"Posisi akhir: Pan={posisi_sekarang['pan']}, Tilt={posisi_sekarang['tilt']}, Zoom={posisi_sekarang['zoom']}")


def mode_uji_roundtrip():
    posisi_awal = get_status()
    if not posisi_awal:
        print("Gagal membaca status.")
        return

    goto_position_abs(posisi_awal["pan"], posisi_awal["tilt"], posisi_awal["zoom"])
    time.sleep(3)

    posisi_akhir = get_status()
    if posisi_akhir:
        selisih_pan = abs(posisi_akhir["pan"] - posisi_awal["pan"])
        selisih_tilt = abs(posisi_akhir["tilt"] - posisi_awal["tilt"])
        print(f"Selisih: Pan={selisih_pan:.3f}, Tilt={selisih_tilt:.3f}")


def mode_probe_manual():
    try:
        pan = float(input("Target pan (derajat): ").strip())
        tilt = float(input("Target tilt (derajat): ").strip())
        zoom = float(input("Target zoom: ").strip())
    except ValueError:
        return

    goto_position_abs(pan, tilt, zoom)
    time.sleep(4)
    status = get_status()
    if status:
        print(f"Hasil: Pan={status['pan']}, Tilt={status['tilt']}, Zoom={status['zoom']}")


if __name__ == "__main__":
    print("1 = Simpan koordinat saat ini")
    print("2 = Simulasi geser kamera")
    print("3 = Kembalikan kamera ke koordinat tersimpan")
    print("4 = Uji round-trip")
    print("5 = Probe manual")
    pilihan = input("Pilihan (1-5): ").strip()

    if pilihan == "1":
        mode_simpan()
    elif pilihan == "2":
        move_direction("Right", speed=5, duration=3)
        move_direction("Up", speed=5, duration=2)
    elif pilihan == "3":
        mode_kembali()
    elif pilihan == "4":
        mode_uji_roundtrip()
    elif pilihan == "5":
        mode_probe_manual()