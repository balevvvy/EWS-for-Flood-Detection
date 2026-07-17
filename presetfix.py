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

# ==================== KONFIGURASI ====================
IP = "10.52.9.101"
USERNAME = "admin"
PASSWORD = "Admin123."      # ganti sesuai password kamera
CHANNEL = 0                     # Dahua biasanya pakai channel=0 untuk PTZ CGI (bukan 1)
FILE_KOORDINAT = "koordinat_threshold.json"

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

        koordinat = {
            "pan": float(pan.group(1)),
            "tilt": float(tilt.group(1)),
            "zoom": float(zoom.group(1)),
        }

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
    requests.get(BASE_URL, params={"action": "start", "channel": CHANNEL, "code": direction, "arg2": speed}, auth=AUTH)
    time.sleep(duration)
    requests.get(BASE_URL, params={"action": "stop", "channel": CHANNEL, "code": direction, "arg2": speed}, auth=AUTH)


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

    print(f">>> Koordinat tersimpan: {koordinat}")

    print(">>> Membaca posisi SEBELUM goto (buat pembanding)...")
    posisi_sebelum = get_status()
    if posisi_sebelum:
        print(f">>> Posisi sebelum goto: pan={posisi_sebelum['pan']} tilt={posisi_sebelum['tilt']} zoom={posisi_sebelum['zoom']}")

    goto_position_abs(koordinat["pan"], koordinat["tilt"], koordinat["zoom"])

    print(">>> Menunggu kamera settle (3 detik)...")
    time.sleep(3)

    # Verifikasi - baca ulang posisi sekarang, bandingkan dengan yang tersimpan
    posisi_sekarang = get_status()
    if posisi_sekarang:
        print(f"\n>>> Posisi sekarang setelah goto: {posisi_sekarang}")
        print(f">>> Posisi target (tersimpan)   : {koordinat}")
        selisih_pan = abs(posisi_sekarang["pan"] - koordinat["pan"])
        selisih_tilt = abs(posisi_sekarang["tilt"] - koordinat["tilt"])
        selisih_zoom = abs(posisi_sekarang["zoom"] - koordinat["zoom"])
        print(f">>> Selisih pan: {selisih_pan:.3f} derajat | Selisih tilt: {selisih_tilt:.3f} derajat | Selisih zoom: {selisih_zoom:.3f}")

        print(f"\n>>> Perbandingan info zoom (target tersimpan vs sekarang):")
        print(f">>>   ZoomValue      : {koordinat.get('_zoom_value')}  ->  {posisi_sekarang.get('_zoom_value')}")
        print(f">>>   ZoomMapValue   : {koordinat.get('_zoom_map')}  ->  {posisi_sekarang.get('_zoom_map')}")
        print(f">>>   FocusPosition  : {koordinat.get('_focus_position')}  ->  {posisi_sekarang.get('_focus_position')}")

        # Cek kedua: apakah posisi masih "merangkak" mendekati target (soal timing/kecepatan)
        # atau sudah benar-benar berhenti di tempat yang sama (soal limit/mentok)?
        if selisih_tilt > 1 or selisih_pan > 1:
            print("\n>>> Selisih masih besar. Menunggu 7 detik lagi untuk cek apakah kamera masih bergerak...")
            time.sleep(7)
            posisi_cek2 = get_status()
            if posisi_cek2:
                gerak_tilt = abs(posisi_cek2["tilt"] - posisi_sekarang["tilt"])
                gerak_pan = abs(posisi_cek2["pan"] - posisi_sekarang["pan"])
                print(f">>> Posisi setelah tunggu tambahan: pan={posisi_cek2['pan']} tilt={posisi_cek2['tilt']}")
                if gerak_tilt < 0.1 and gerak_pan < 0.1:
                    print(">>> HASIL: Posisi TIDAK berubah lagi meski ditunggu lebih lama -> ini bukan soal")
                    print(">>>         timing/kecepatan, kemungkinan besar kamera MENTOK di suatu limit/batas.")
                    print(">>>         Cek menu PTZ di web interface kamera, cari setting 'Limit'/'Boundary'/")
                    print(">>>         batas tilt, dan pastikan tidak membatasi di bawah nilai target kamu.")
                else:
                    print(">>> HASIL: Posisi masih bergerak mendekati target -> ini soal timing/kecepatan,")
                    print(">>>         coba naikkan waktu tunggu (time.sleep) atau naikkan nilai speed.")


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