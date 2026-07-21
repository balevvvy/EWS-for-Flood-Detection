"""
Live Demo Pipeline — Deteksi Level Air Real-Time

Langkah:
  1. Jalankan: python scripts\\live_demo.py
  2. Gambar kotak ROI di sekitar botol/papan duga dengan mouse (drag)
  3. Tekan ENTER/SPACE untuk konfirmasi ROI
  4. Tuang air keruh perlahan

Tombol:
  'q' / ESC = Keluar
  'r' = Reset referensi ke frame saat ini
"""

import cv2
import numpy as np
import json
import os
import time
from collections import deque

# ==================== KONFIGURASI ====================
IP = "10.52.9.101"
USERNAME = "admin"
PASSWORD = "Admin123."
CHANNEL = 1
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{IP}:554/cam/realmonitor?channel={CHANNEL}&subtype=0"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_PATH = os.path.join(BASE_DIR, "config", "cv_thresholds.json")
REF_IMAGE_PATH = os.path.join(BASE_DIR, "test_frame.jpg")
ROI_PATH = os.path.join(BASE_DIR, "config", "roi.json")


def load_thresholds():
    if os.path.exists(THRESHOLDS_PATH):
        with open(THRESHOLDS_PATH, 'r') as f:
            data = json.load(f)
        return data.get("y_waspada"), data.get("y_siaga")
    return None, None


def load_roi():
    if os.path.exists(ROI_PATH):
        with open(ROI_PATH, 'r') as f:
            return json.load(f)
    return None


def save_roi(roi):
    os.makedirs(os.path.dirname(ROI_PATH), exist_ok=True)
    with open(ROI_PATH, 'w') as f:
        json.dump(roi, f, indent=4)
    print(f">>> ROI disimpan: {roi}")


def select_roi(frame):
    """Minta user memilih area ROI di sekitar botol/papan duga."""
    print("=" * 50)
    print("PILIH AREA ROI:")
    print("  Drag mouse untuk menggambar kotak di sekitar")
    print("  BOTOL/PAPAN DUGA saja.")
    print("  Tekan ENTER/SPACE untuk konfirmasi.")
    print("  Tekan C untuk batal/ulang.")
    print("=" * 50)

    # Resize untuk display
    display_h = 700
    scale = display_h / frame.shape[0]
    display_w = int(frame.shape[1] * scale)
    display = cv2.resize(frame, (display_w, display_h))

    roi_rect = cv2.selectROI("Pilih Area Botol/Papan Duga", display, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Pilih Area Botol/Papan Duga")

    if roi_rect[2] == 0 or roi_rect[3] == 0:
        print("ROI dibatalkan.")
        return None

    # Konversi koordinat display ke koordinat asli
    x = int(roi_rect[0] / scale)
    y = int(roi_rect[1] / scale)
    w = int(roi_rect[2] / scale)
    h = int(roi_rect[3] / scale)

    roi = {"x": x, "y": y, "w": w, "h": h}
    save_roi(roi)
    return roi


def get_water_level_y(mask, roi, min_width_ratio=0.05):
    """
    Cari Y permukaan air HANYA di dalam area ROI.
    Mengembalikan koordinat Y dalam frame asli (bukan relatif ROI).
    """
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    roi_mask = mask[y:y+h, x:x+w]

    min_pixels = int(w * min_width_ratio)

    for row in range(roi_mask.shape[0]):
        white_count = np.count_nonzero(roi_mask[row])
        if white_count >= min_pixels:
            return y + row  # Konversi ke koordinat frame asli

    return None


def get_status(water_y, y_waspada, y_siaga):
    if water_y is None:
        return "NORMAL", (0, 200, 0)
    if water_y <= y_siaga:
        return "SIAGA", (0, 0, 255)
    elif water_y <= y_waspada:
        return "WASPADA", (0, 220, 255)
    else:
        return "NORMAL", (0, 200, 0)


def nothing(x):
    pass


def main():
    y_waspada, y_siaga = load_thresholds()
    if y_waspada is None or y_siaga is None:
        print("ERROR: Belum ada kalibrasi. Jalankan 'python scripts\\calibrate_ui.py' dulu.")
        return

    if not os.path.exists(REF_IMAGE_PATH):
        print(f"ERROR: Referensi {REF_IMAGE_PATH} tidak ditemukan.")
        return

    ref_frame = cv2.imread(REF_IMAGE_PATH)
    print(f"Referensi dimuat: {ref_frame.shape}")
    print(f"Kalibrasi: Y Waspada={y_waspada}, Y Siaga={y_siaga}")

    # Cek apakah ROI sudah pernah disimpan
    roi = load_roi()
    if roi is None:
        print("Belum ada ROI tersimpan. Silakan pilih area botol/papan duga...")
        roi = select_roi(ref_frame)
        if roi is None:
            print("Dibatalkan.")
            return
    else:
        print(f"ROI dimuat dari file: {roi}")
        print("(Tekan 'n' saat live untuk pilih ROI baru)")

    # Siapkan referensi (blur di area ROI)
    ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
    ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)

    # Settings window
    cv2.namedWindow("Settings", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Settings", 400, 120)
    cv2.createTrackbar("Sensitivity", "Settings", 30, 100, nothing)
    cv2.createTrackbar("Blur", "Settings", 21, 51, nothing)

    # Konek kamera
    print("Connecting to RTSP stream...")
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        print("GAGAL konek ke kamera!")
        return
    print("Stream terbuka. Tuang air perlahan...")
    print("Tombol: 'q'=keluar, 'r'=reset referensi, 'n'=pilih ROI baru")

    display_h = 600
    last_status = None
    y_history = deque(maxlen=15)  # Simpan 15 frame terakhir untuk smoothing

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Frame gagal, reconnect...")
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(RTSP_URL)
            continue

        orig_h, orig_w = frame.shape[:2]
        scale = display_h / orig_h
        display_w = int(orig_w * scale)

        # Baca settings
        sensitivity = cv2.getTrackbarPos("Sensitivity", "Settings")
        blur_size = cv2.getTrackbarPos("Blur", "Settings")
        blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        blur_size = max(blur_size, 3)

        # Background differencing
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)

        diff = cv2.absdiff(ref_gray, gray)
        _, mask = cv2.threshold(diff, sensitivity, 255, cv2.THRESH_BINARY)

        # Morphological cleaning
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        # Cari level air HANYA di dalam ROI
        raw_water_y = get_water_level_y(mask, roi, min_width_ratio=0.05)
        
        # Smoothing (Median Filter) untuk menghindari garis loncat-loncat
        if raw_water_y is not None:
            y_history.append(raw_water_y)
            
        if len(y_history) > 0:
            water_y = int(np.median(y_history))
        else:
            water_y = None

        status, status_color = get_status(water_y, y_waspada, y_siaga)

        if status != last_status:
            print(f">>> STATUS: {status} (water Y={water_y})")
            last_status = status

        # ===== OVERLAY =====
        display = frame.copy()

        # Gambar ROI box
        rx, ry, rw, rh = roi["x"], roi["y"], roi["w"], roi["h"]
        cv2.rectangle(display, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)
        cv2.putText(display, "ROI", (rx, ry - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Garis kalibrasi (hanya di area ROI)
        cv2.line(display, (rx, y_waspada), (rx + rw, y_waspada), (0, 255, 255), 2)
        cv2.putText(display, "WASPADA", (rx + rw + 5, y_waspada + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        cv2.line(display, (rx, y_siaga), (rx + rw, y_siaga), (0, 0, 255), 2)
        cv2.putText(display, "SIAGA", (rx + rw + 5, y_siaga + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Garis air
        if water_y is not None:
            cv2.line(display, (rx, water_y), (rx + rw, water_y), (255, 100, 0), 3)
            cv2.putText(display, f"Air: Y={water_y}", (rx + rw + 5, water_y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 100, 0), 2)

        # Status box
        cv2.rectangle(display, (0, 0), (350, 80), status_color, -1)
        cv2.putText(display, status, (15, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)

        # Resize
        display_resized = cv2.resize(display, (display_w, display_h))

        # Mask hanya di area ROI (untuk visualisasi)
        mask_vis = np.zeros_like(mask)
        mask_vis[ry:ry+rh, rx:rx+rw] = mask[ry:ry+rh, rx:rx+rw]
        mask_colored = cv2.cvtColor(mask_vis, cv2.COLOR_GRAY2BGR)
        mask_resized = cv2.resize(mask_colored, (display_w, display_h))

        combined = np.hstack([display_resized, mask_resized])
        cv2.imshow("EWS Banjir | Kiri: Kamera | Kanan: Deteksi", combined)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break
        elif key == ord("r"):
            ref_gray = gray.copy()
            print(">>> Referensi di-reset ke frame saat ini.")
        elif key == ord("n"):
            # Pilih ROI baru
            cap.release()
            roi = select_roi(frame)
            if roi is None:
                print("ROI dibatalkan, pakai yang lama.")
                roi = load_roi()
            cap = cv2.VideoCapture(RTSP_URL)

    cap.release()
    cv2.destroyAllWindows()
    print("Selesai.")


if __name__ == "__main__":
    main()
