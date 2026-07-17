"""
Script untuk:
1. Membaca koordinat Pan/Tilt/Zoom kamera SAAT INI (saat mengarah ke papan threshold)
2. Menyimpan koordinat itu ke file
3. (Kamu geser kamera manual pakai fitur bawaan kamera / web interface / joystick)
4. Membaca file koordinat tadi, lalu mengirim kamera kembali PERSIS ke koordinat itu
   menggunakan command PositionABS (bukan Preset)

=====================================================================
PERBAIKAN vs versi sebelumnya
=====================================================================
Versi sebelumnya membaca field `status.AbsPosition[x]` dan mengirimkannya
langsung sebagai argumen ke PositionABS. Ternyata itu SALAH SKALA.

Berdasarkan laporan beberapa pengguna Dahua lain yang membandingkan kedua
field dari getStatus secara berdampingan:

    status.AbsPosition[0] = 9694        status.Postion[0] = 96.940000
    status.AbsPosition[1] = 426         status.Postion[1] = 4.260000

-> AbsPosition adalah skala internal (kira-kira 100x lebih besar untuk
   pan/tilt), BUKAN skala yang dipakai command PositionABS.

-> Command PositionABS ternyata menerima nilai DERAJAT DESIMAL LANGSUNG,
   persis seperti yang muncul di field `status.Postion[x]` (perhatikan:
   nama field dari kamera memang "Postion", bukan "Position" - ini typo
   bawaan firmware Dahua, bukan typo di script ini). Contoh request yang
   terbukti berhasil dari pengguna lain:

    ...ptz.cgi?action=start&code=PositionABS&arg1=156.945&arg2=24.68&arg3=12.0

Jadi perbaikannya: parsing `status.Postion[x]` (bukan AbsPosition), dan
kirim apa adanya (boleh desimal, tidak perlu dikonversi/dibagi/dikali)
ke PositionABS.

CATATAN PENTING: field dan skala CGI Dahua ini tidak resmi didokumentasikan
dan bisa berbeda antar model/firmware. Makanya di bawah ada MODE 4 (uji
round-trip) untuk memverifikasi di kamera kamu sendiri sebelum dipakai
untuk kerja beneran. Jalankan mode 4 dulu sebelum percaya penuh ke mode 3.
=====================================================================
"""

import requests
import re
import json
import time
import yaml
import os

# ==================== KONFIGURASI ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")

with open(CONFIG_PATH, "r") as f:
    config_data = yaml.safe_load(f)

cam_conf = config_data.get("camera", {})
IP = cam_conf.get("ip", "10.52.9.101")
USERNAME = cam_conf.get("username", "admin")
PASSWORD = cam_conf.get("password", "Admin123.")
CHANNEL = cam_conf.get("channel", 0)
FILE_KOORDINAT = os.path.join(BASE_DIR, "config", "koordinat_threshold.json")

BASE_URL = f"http://{IP}/cgi-bin/ptz.cgi"
AUTH = requests.auth.HTTPDigestAuth(USERNAME, PASSWORD)


def get_status():
    """
    Baca status PTZ kamera saat ini, termasuk koordinat Pan/Tilt/Zoom.
    Mengembalikan dict: {"pan": ..., "tilt": ..., "zoom": ...} (float, derajat desimal)

    PENTING (lihat catatan perbaikan di atas file):
    - status.Postion[x]     -> derajat desimal, INI YANG DIPAKAI PositionABS
    - status.AbsPosition[x] -> skala internal, JANGAN dipakai sebagai argumen PositionABS
    """
    params = {"action": "getStatus"}
    try:
        response = requests.get(BASE_URL, params=params, auth=AUTH, timeout=5)
        text = response.text
        print("--- Raw response getStatus ---")
        print(text)
        print("-------------------------------")

        # Parsing dari Postion (derajat desimal) - field yang benar untuk PositionABS
        pan = re.search(r"status\.Postion\[0\]=([\-\d\.]+)", text)
        tilt = re.search(r"status\.Postion\[1\]=([\-\d\.]+)", text)
        zoom = re.search(r"status\.Postion\[2\]=([\-\d\.]+)", text)

        if not (pan and tilt and zoom):
            print(">>> Gagal parsing Postion dari response. Cek format response di atas.")
            print(">>> Kalau nama field di response ternyata beda (misal 'Position' tanpa typo,")
            print(">>> atau ada namespace lain), sesuaikan regex di atas dengan nama field aslinya.")
            return None

        pan_abs = re.search(r"status\.AbsPosition\[0\]=([\-\d\.]+)", text)
        tilt_abs = re.search(r"status\.AbsPosition\[1\]=([\-\d\.]+)", text)
        zoom_abs = re.search(r"status\.AbsPosition\[2\]=([\-\d\.]+)", text)

        koordinat = {
            "pan": float(pan.group(1)),
            "tilt": float(tilt.group(1)),
            "zoom": float(zoom.group(1)),
        }
        koordinat["_pan_abs"] = float(pan_abs.group(1)) if pan_abs else None
        koordinat["_tilt_abs"] = float(tilt_abs.group(1)) if tilt_abs else None
        koordinat["_zoom_abs"] = float(zoom_abs.group(1)) if zoom_abs else None

        # --- Info tambahan untuk diagnosis, TIDAK dipakai sebagai argumen PositionABS,
        #     tapi berguna untuk membandingkan apakah zoom benar-benar balik sama persis.
        zoom_value = re.search(r"status\.ZoomValue=([\-\d\.]+)", text)
        zoom_map = re.search(r"status\.ZoomMapValue=([\-\d\.]+)", text)
        focus_pos = re.search(r"status\.Focus\.FocusPosition=([\-\d\.]+)", text)

        koordinat["_zoom_value"] = float(zoom_value.group(1)) if zoom_value else None
        koordinat["_zoom_map"] = float(zoom_map.group(1)) if zoom_map else None
        koordinat["_focus_position"] = float(focus_pos.group(1)) if focus_pos else None
        koordinat["_raw_text"] = text

        return koordinat
    except requests.exceptions.RequestException as e:
        print(f">>> Gagal koneksi getStatus: {e}")
        return None


def simpan_koordinat(koordinat, filename=FILE_KOORDINAT):
    with open(filename, "w") as f:
        json.dump(koordinat, f, indent=2)
    print(f">>> Koordinat disimpan ke {filename}: {koordinat}")


def baca_koordinat_tersimpan(filename=FILE_KOORDINAT):
    with open(filename, "r") as f:
        return json.load(f)


def goto_position_abs(pan, tilt, zoom, speed=5):
    """
    Gerakkan kamera ke koordinat absolut pan/tilt/zoom yang spesifik (derajat desimal,
    sama seperti yang dibaca dari status.Postion[x]).
    """
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
        print(f">>> PositionABS dikirim (pan={pan}, tilt={tilt}, zoom={zoom}) | Status: {response.status_code}")
        print(f">>> Response body: {response.text.strip()}")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f">>> Gagal kirim PositionABS: {e}")
        return False


def move_direction(direction, speed=5, duration=2):
    """Simulasi kamera digeser manual (untuk testing tanpa perlu geser fisik/web)."""
    print(f"\n>>> Simulasi geser kamera: {direction} selama {duration}s...")
    params_start = {"action": "start", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": speed, "arg3": 0, "arg4": 0}
    params_stop = {"action": "stop", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": speed, "arg3": 0, "arg4": 0}
    r1 = requests.get(BASE_URL, params=params_start, auth=AUTH)
    print(f">>>   start '{direction}' | Status: {r1.status_code} | Body: {r1.text.strip()}")
    time.sleep(duration)
    r2 = requests.get(BASE_URL, params=params_stop, auth=AUTH)
    print(f">>>   stop '{direction}' | Status: {r2.status_code} | Body: {r2.text.strip()}")


def axis_nudge_closed_loop(axis_label, get_value, target_value, code_a, code_b,
                            tolerance=0.5, max_iterations=15, base_speed=4,
                            calibration_duration=0.8, gain=0.85,
                            min_duration=0.12, max_duration=6.0):
    """
    Kontrol satu axis (tilt ATAU zoom) secara closed-loop pakai continuous move,
    BUKAN PositionABS - karena di kamera ini PositionABS terbukti tidak bisa
    diandalkan untuk tilt (nol respons) maupun zoom (ada efek samping / drift
    walau nilai yang dikirim sama dengan posisi sekarang).

    Durasi tiap nudge dihitung otomatis dari KECEPATAN ASLI axis ini (diukur
    langsung dari hasil nudge kalibrasi), bukan angka tebakan tetap - karena
    tilt dan zoom bisa punya kecepatan motor yang sangat berbeda di kamera yang
    sama (contoh nyata: zoom ~37 unit/detik, tilt cuma ~4.7 unit/detik).
    'gain' <1 sengaja dipakai supaya tiap nudge menutup ~85% sisa jarak, biar
    tidak overshoot kalau kecepatan riil sedikit meleset dari hasil kalibrasi.

    axis_label : nama buat print, misal "tilt" atau "zoom"
    get_value  : fungsi yang menerima dict status dan mengembalikan nilai axis ybs,
                 misal lambda s: s["tilt"]
    code_a/b   : dua kode continuous-move yang berlawanan arah,
                 misal ("Up","Down") untuk tilt, atau ("ZoomTele","ZoomWide") untuk zoom
    """
    status = get_status()
    if not status:
        print(f">>> [{axis_label}] Gagal baca status awal, batalkan koreksi.")
        return False

    current = get_value(status)
    diff = target_value - current
    if abs(diff) <= tolerance:
        print(f">>> [{axis_label}] Sudah dekat target ({current} vs {target_value}), tidak perlu koreksi.")
        return True

    # Kalibrasi arah SEKALIGUS kecepatan: nudge singkat ke code_a, ukur seberapa jauh
    # nilai berubah per detik - itu jadi dasar hitung durasi nudge berikutnya.
    print(f">>> [{axis_label}] Kalibrasi arah & kecepatan: nudge singkat '{code_a}' selama {calibration_duration}s...")
    params_start = {"action": "start", "channel": CHANNEL, "code": code_a, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
    params_stop = {"action": "stop", "channel": CHANNEL, "code": code_a, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
    r1 = requests.get(BASE_URL, params=params_start, auth=AUTH)
    print(f">>> [{axis_label}]   start '{code_a}' | Status: {r1.status_code} | Body: {r1.text.strip()}")
    time.sleep(calibration_duration)
    r2 = requests.get(BASE_URL, params=params_stop, auth=AUTH)
    print(f">>> [{axis_label}]   stop '{code_a}' | Status: {r2.status_code} | Body: {r2.text.strip()}")
    time.sleep(0.8)

    status2 = get_status()
    if not status2:
        print(f">>> [{axis_label}] Gagal baca status kalibrasi.")
        return False

    delta_from_test = get_value(status2) - current
    print(f">>> [{axis_label}] Setelah nudge '{code_a}': {current} -> {get_value(status2)} (delta={delta_from_test:.3f})")

    if abs(delta_from_test) < 0.05:
        print(f">>> [{axis_label}] Kalibrasi TIDAK menghasilkan perubahan terukur.")
        print(f">>>   Kemungkinan: (a) durasi kalibrasi kurang lama untuk motor axis ini, atau")
        print(f">>>   (b) code '{code_a}'/'{code_b}' bukan kode yang benar untuk axis ini di kamera ini.")
        return False

    a_increases = delta_from_test > 0
    rate_per_sec = abs(delta_from_test) / calibration_duration
    print(f">>> [{axis_label}] Kalibrasi selesai: '{code_a}' {'menambah' if a_increases else 'mengurangi'} nilai. "
          f"Kecepatan terukur: {rate_per_sec:.2f} unit/detik.")
    current = get_value(status2)

    for i in range(max_iterations):
        diff = target_value - current
        if abs(diff) <= tolerance:
            print(f">>> [{axis_label}] BERHASIL. Nilai akhir: {current:.3f} (target: {target_value})")
            return True

        need_increase = diff > 0
        if need_increase:
            direction = code_a if a_increases else code_b
        else:
            direction = code_b if a_increases else code_a

        duration = min(max((abs(diff) / rate_per_sec) * gain, min_duration), max_duration)
        print(f">>> [{axis_label}] Iterasi {i+1}: sekarang={current:.3f} target={target_value} "
              f"diff={diff:.3f} -> nudge {direction} {duration:.2f}s")

        params_start = {"action": "start", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
        params_stop = {"action": "stop", "channel": CHANNEL, "code": direction, "arg1": 0, "arg2": base_speed, "arg3": 0, "arg4": 0}
        requests.get(BASE_URL, params=params_start, auth=AUTH)
        time.sleep(duration)
        r_stop = requests.get(BASE_URL, params=params_stop, auth=AUTH)
        if r_stop.status_code != 200 or "OK" not in r_stop.text:
            print(f">>> [{axis_label}]   (respon stop tidak OK: {r_stop.status_code} | {r_stop.text.strip()})")
        time.sleep(0.6)

        status_n = get_status()
        if not status_n:
            print(f">>> [{axis_label}] Gagal baca status, berhenti.")
            return False
        current = get_value(status_n)

    print(f">>> [{axis_label}] Selesai {max_iterations} iterasi, nilai akhir={current:.3f} "
          f"(target={target_value}), belum masuk toleransi tapi sudah sedekat mungkin.")
    return False


def tilt_nudge_closed_loop(target_tilt, tolerance=0.5, max_iterations=15, base_speed=4):
    """Wrapper axis_nudge_closed_loop khusus tilt (code Up/Down)."""
    return axis_nudge_closed_loop(
        "tilt", lambda s: s["tilt"], target_tilt, "Up", "Down",
        tolerance=tolerance, max_iterations=max_iterations, base_speed=base_speed,
    )


def zoom_nudge_closed_loop(target_zoom, tolerance=0.3, max_iterations=15, base_speed=4):
    """Wrapper axis_nudge_closed_loop khusus zoom (code ZoomTele/ZoomWide - kode
    continuous-zoom standar Dahua; kalau kamera ini pakai nama kode lain, kalibrasi
    di atas akan langsung ketahuan lewat pesan 'tidak menghasilkan perubahan terukur')."""
    return axis_nudge_closed_loop(
        "zoom", lambda s: s["zoom"], target_zoom, "ZoomTele", "ZoomWide",
        tolerance=tolerance, max_iterations=max_iterations, base_speed=base_speed,
    )


# ==================== MODE 1: BACA & SIMPAN KOORDINAT SEKARANG ====================
def mode_simpan():
    print("=" * 60)
    print("MODE: BACA & SIMPAN KOORDINAT THRESHOLD SAAT INI")
    print("=" * 60)
    input("Pastikan kamera SEDANG mengarah ke papan threshold, lalu tekan Enter...")

    koordinat = get_status()
    if koordinat:
        simpan_koordinat(koordinat)
        print("\n>>> BERHASIL. Koordinat threshold sudah tersimpan.")
        print(f">>> (info tambahan) ZoomValue={koordinat.get('_zoom_value')} | "
              f"ZoomMapValue={koordinat.get('_zoom_map')} | "
              f"FocusPosition={koordinat.get('_focus_position')}")
        print(">>> Sekarang kamu bisa geser kamera bebas pakai web interface/joystick.")
    else:
        print("\n>>> GAGAL membaca koordinat. Cek koneksi/kredensial, atau format response berbeda.")


# ==================== MODE 2: KEMBALIKAN KE KOORDINAT TERSIMPAN ====================
def mode_kembali():
    print("=" * 60)
    print("MODE: KEMBALIKAN KAMERA KE KOORDINAT THRESHOLD TERSIMPAN")
    print("=" * 60)
    try:
        koordinat = baca_koordinat_tersimpan()
    except FileNotFoundError:
        print(f">>> File {FILE_KOORDINAT} tidak ditemukan. Jalankan mode_simpan() dulu.")
        return

    print(f">>> Koordinat tersimpan (TITIK 1 - threshold asli): {koordinat}")

    print(">>> Membaca posisi SEBELUM goto (TITIK 2 - setelah kamu geser manual)...")
    posisi_sebelum = get_status()
    if not posisi_sebelum:
        print(">>> Gagal baca posisi sebelum goto, batalkan.")
        return

    # Langkah 1: HANYA pan lewat PositionABS (satu-satunya axis yang terbukti akurat
    # lewat command ini). Tilt & zoom SENGAJA dikirim = posisi SEKARANG (bukan target),
    # untuk meminimalkan efek samping - lihat catatan di axis_nudge_closed_loop.
    print(">>> Langkah 1: kirim pan lewat PositionABS...")
    goto_position_abs(koordinat["pan"], posisi_sebelum["tilt"], posisi_sebelum["zoom"])
    print(">>> Menunggu settle (3 detik)...")
    time.sleep(3)

    # Langkah 2 & 3: tilt & zoom lewat closed-loop nudge (continuous move).
    print(">>> Langkah 2: koreksi tilt pakai closed-loop nudge...")
    tilt_nudge_closed_loop(koordinat["tilt"])
    print(">>> Langkah 3: koreksi zoom pakai closed-loop nudge...")
    zoom_nudge_closed_loop(koordinat["zoom"])

    posisi_sekarang = get_status()  # TITIK 3 - hasil mode 3

    if koordinat and posisi_sebelum and posisi_sekarang:
        print("\n" + "=" * 70)
        print("RINGKASAN 3 TITIK (semua dalam derajat / skala Postion, biar mudah dibaca)")
        print("=" * 70)
        print(f"{'':25}{'pan':>12}{'tilt':>12}{'zoom':>12}")
        print(f"{'TITIK 1 - threshold asli':25}{koordinat['pan']:>12}{koordinat['tilt']:>12}{koordinat['zoom']:>12}")
        print(f"{'TITIK 2 - setelah geser':25}{posisi_sebelum['pan']:>12}{posisi_sebelum['tilt']:>12}{posisi_sebelum['zoom']:>12}")
        print(f"{'TITIK 3 - hasil mode 3':25}{posisi_sekarang['pan']:>12}{posisi_sekarang['tilt']:>12}{posisi_sekarang['zoom']:>12}")
        print("-" * 70)
        print(f"{'Selisih T3 vs T1 (target)':25}"
              f"{abs(posisi_sekarang['pan']-koordinat['pan']):>12.3f}"
              f"{abs(posisi_sekarang['tilt']-koordinat['tilt']):>12.3f}"
              f"{abs(posisi_sekarang['zoom']-koordinat['zoom']):>12.3f}")
        print("=" * 70)
    else:
        print(">>> Salah satu pembacaan status gagal, tidak bisa membuat ringkasan lengkap.")


# ==================== MODE 4: UJI ROUND-TRIP (DIAGNOSTIK) ====================
def mode_uji_roundtrip():
    """
    Tes ini TIDAK melibatkan geser kamera manual sama sekali.
    Tujuannya mengisolasi murni apakah skala baca (getStatus) dan skala
    tulis (PositionABS) sudah nyambung, tanpa variabel lain.

    Alur:
    1. Baca posisi sekarang (di posisi manapun kamera saat ini).
    2. LANGSUNG kirim goto_position_abs() dengan angka yang barusan dibaca.
    3. Baca ulang. Kalau skalanya benar, kamera harusnya TIDAK bergerak sama
       sekali (atau bergerak sangat kecil), karena kita menyuruhnya pergi
       ke tempat dia sudah berada.
    4. Kalau kamera malah lompat jauh, berarti masih ada mismatch skala/field
       untuk model kamera kamu, dan regex/field di get_status() perlu
       disesuaikan lagi (cek raw response yang di-print, cari nama field
       lain yang formatnya derajat desimal).
    """
    print("=" * 60)
    print("MODE: UJI ROUND-TRIP (tanpa geser manual)")
    print("=" * 60)

    print(">>> Membaca posisi awal...")
    posisi_awal = get_status()
    if not posisi_awal:
        print(">>> Gagal baca posisi awal, berhenti.")
        return
    print(f">>> Posisi awal: {posisi_awal}")

    print(">>> Mengirim PositionABS dengan angka yang sama persis...")
    goto_position_abs(posisi_awal["pan"], posisi_awal["tilt"], posisi_awal["zoom"])

    print(">>> Menunggu settle (3 detik)...")
    time.sleep(3)

    posisi_akhir = get_status()
    if not posisi_akhir:
        print(">>> Gagal baca posisi akhir.")
        return

    selisih_pan = abs(posisi_akhir["pan"] - posisi_awal["pan"])
    selisih_tilt = abs(posisi_akhir["tilt"] - posisi_awal["tilt"])
    selisih_zoom = abs(posisi_akhir["zoom"] - posisi_awal["zoom"])

    print(f"\n>>> Posisi awal : {posisi_awal}")
    print(f">>> Posisi akhir: {posisi_akhir}")
    print(f">>> Selisih pan={selisih_pan:.3f} | tilt={selisih_tilt:.3f} | zoom={selisih_zoom:.3f}")

    if selisih_pan < 1 and selisih_tilt < 1:
        print("\n>>> HASIL: Selisih kecil -> skala getStatus <-> PositionABS SUDAH NYAMBUNG.")
        print(">>> Aman lanjut pakai mode 1 & mode 3.")
    else:
        print("\n>>> HASIL: Selisih besar -> masih ada mismatch untuk kamera/firmware kamu.")
        print(">>> Cek raw response di atas, cari field lain yang isinya derajat desimal")
        print(">>> (bukan angka ribuan), lalu ganti nama field di regex get_status().")


# ==================== MODE 5: PROBE MANUAL (cari batas tilt) ====================
def mode_probe_manual():
    """
    Coba kirim angka pan/tilt/zoom sembarang (misal beberapa nilai tilt: 30, 40, 50,
    64.07) satu-satu untuk memetakan di titik berapa kamera berhenti nurut.
    Berguna khusus untuk kasus tilt yang mentok seperti yang dialami sekarang.
    """
    print("=" * 60)
    print("MODE: PROBE MANUAL")
    print("=" * 60)
    try:
        pan = float(input("Masukkan target pan (derajat): ").strip())
        tilt = float(input("Masukkan target tilt (derajat): ").strip())
        zoom = float(input("Masukkan target zoom: ").strip())
    except ValueError:
        print(">>> Input tidak valid.")
        return

    print(">>> Posisi sebelum:")
    sebelum = get_status()
    if sebelum:
        print(f">>>   pan={sebelum['pan']} tilt={sebelum['tilt']} zoom={sebelum['zoom']}")

    goto_position_abs(pan, tilt, zoom)
    print(">>> Menunggu 4 detik...")
    time.sleep(4)

    sesudah = get_status()
    if sesudah:
        print(f">>> Target dikirim : pan={pan} tilt={tilt} zoom={zoom}")
        print(f">>> Hasil aktual   : pan={sesudah['pan']} tilt={sesudah['tilt']} zoom={sesudah['zoom']}")
        print(f">>> Selisih tilt   : {abs(sesudah['tilt'] - tilt):.3f} derajat")


if __name__ == "__main__":
    print("Pilih mode:")
    print("1 = Simpan koordinat threshold saat ini")
    print("2 = Simulasi geser kamera (testing)")
    print("3 = Kembalikan kamera ke koordinat threshold tersimpan")
    print("4 = Uji round-trip (diagnostik, tanpa geser manual)")
    print("5 = Probe manual (coba angka pan/tilt/zoom sembarang, buat cari batas mentok)")
    pilihan = input("Masukkan pilihan (1/2/3/4/5): ").strip()

    if pilihan == "1":
        mode_simpan()
    elif pilihan == "2":
        move_direction("Right", speed=5, duration=3)
        move_direction("Up", speed=5, duration=2)
        print(">>> Kamera sudah digeser (simulasi). Sekarang jalankan mode 3 untuk kembali.")
    elif pilihan == "3":
        mode_kembali()
    elif pilihan == "4":
        mode_uji_roundtrip()
    elif pilihan == "5":
        mode_probe_manual()
    else:
        print("Pilihan tidak valid.")