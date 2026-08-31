"""
EWS Banjir Main Pipeline - Production Mode
  (Deteksi Level Air Real-Time via Classical CV)

Mode penggunaan:
  1. Standalone (debug/kalibrasi):
       python scripts/main_detector.py
     Memunculkan jendela OpenCV dengan trackbar untuk tuning.

  2. Diimpor oleh Web Server:
       from scripts.main_detector import WaterLevelDetector
     Class WaterLevelDetector menyediakan method process_frame()
     yang mengembalikan frame + status tanpa cv2.imshow().

Tombol (mode standalone):
  'q' / ESC = Keluar
  'r' = Reset referensi ke frame saat ini
  'n' = Pilih ROI baru
"""

import cv2
import numpy as np
import json
import os
import sys
import time
import threading
from collections import deque

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.camera.config_loader import load_camera_config

# ==================== KONFIGURASI ====================
_cam_config = load_camera_config()
IP = _cam_config["ip"]
USERNAME = _cam_config["username"]
PASSWORD = _cam_config["password"]
CHANNEL = _cam_config["channel"]
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{IP}:554/cam/realmonitor?channel={CHANNEL}&subtype=0"

THRESHOLDS_PATH = os.path.join(BASE_DIR, "config", "cv_thresholds.json")
REF_IMAGE_PATH = os.path.join(BASE_DIR, "test_frame.jpg")
ROI_PATH = os.path.join(BASE_DIR, "config", "roi.json")

# ===== Konfigurasi Debouncing =====
# 5 detik = untuk demo (ubah ke 300 untuk lapangan).
DEBOUNCE_DURATION_SEC = 5


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

    display_h = 700
    scale = display_h / frame.shape[0]
    display_w = int(frame.shape[1] * scale)
    display = cv2.resize(frame, (display_w, display_h))

    roi_rect = cv2.selectROI("Pilih Area Botol/Papan Duga", display, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Pilih Area Botol/Papan Duga")

    if roi_rect[2] == 0 or roi_rect[3] == 0:
        print("ROI dibatalkan.")
        return None

    x = int(roi_rect[0] / scale)
    y = int(roi_rect[1] / scale)
    w = int(roi_rect[2] / scale)
    h = int(roi_rect[3] / scale)

    roi = {"x": x, "y": y, "w": w, "h": h}
    save_roi(roi)
    return roi


# ==================== AUTO-ALIGNMENT ====================
def build_alignment_template(ref_gray, roi):
    """
    Ambil potongan gambar (template) dari area ROI di foto referensi.
    Template ini akan dipakai setiap frame untuk mencari posisi papan duga.
    """
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    template = ref_gray[y:y+h, x:x+w].copy()
    print(f">>> Template Auto-Alignment dibuat dari ROI ({x},{y},{w},{h})")
    return template


def compute_alignment_shift(frame_gray, template, roi, search_padding=50):
    """
    Cari letak template (papan duga) di dalam frame baru menggunakan Template Matching.
    Pencarian dibatasi di area sekitar ROI + margin (search_padding piksel) agar lebih cepat.
    Mengembalikan (dx, dy): selisih piksel pergeseran dari posisi asli.
    """
    h_img, w_img = frame_gray.shape
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]

    sx = max(0, x - search_padding)
    sy = max(0, y - search_padding)
    ex = min(w_img, x + w + search_padding)
    ey = min(h_img, y + h + search_padding)

    search_area = frame_gray[sy:ey, sx:ex]

    if search_area.shape[0] < template.shape[0] or search_area.shape[1] < template.shape[1]:
        return 0, 0

    result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < 0.4:
        return 0, 0

    found_x_in_search = max_loc[0]
    found_y_in_search = max_loc[1]

    found_x_in_frame = sx + found_x_in_search
    found_y_in_frame = sy + found_y_in_search

    dx = x - found_x_in_frame
    dy = y - found_y_in_frame

    return dx, dy


def apply_alignment(frame, dx, dy):
    """
    Geser (warp) frame secara digital sebesar dx, dy agar kembali sejajar
    dengan foto referensi.
    """
    if dx == 0 and dy == 0:
        return frame
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    aligned = cv2.warpAffine(frame, M, (frame.shape[1], frame.shape[0]))
    return aligned


# ==================== DETEKSI AIR ====================
def get_water_level_y(mask, roi, min_row_coverage=0.15, max_gap=20, min_water_height=10, max_bottom_offset=0.40):
    """
    Deteksi tinggi permukaan air menggunakan Bottom-Up Row Scanning.
    Memindai baris piksel ROI dari DASAR BOTOL (bawah) naik ke atas.

    Keunggulan:
    - Kebal terhadap pantulan/kilatan cahaya di leher botol (karena pemindaian berhenti di permukaan air).
    - Memastikan air yang terdeteksi bersambung dari dasar botol ke atas.

    Parameter:
    - min_row_coverage: Minimum persentase piksel perbedaan per baris (default 15% dari lebar ROI).
    - max_gap: Toleransi baris kosong berturut-turut (misal pantulan kecil di tengah air).
    - min_water_height: Tinggi air minimum (piksel) agar valid.
    - max_bottom_offset: Batas maksimal titik awal air dari dasar ROI (default 40% tinggi ROI).
    """
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    roi_mask = mask[y:y+h, x:x+w]

    # Hitung jumlah piksel putih di tiap baris horizontal (panjang array = h)
    row_counts = np.count_nonzero(roi_mask, axis=1)
    min_pixels = max(int(w * min_row_coverage), 4)

    water_top_rel_y = None
    first_water_r = None
    gap_count = 0
    in_water = False

    # Pindai dari bawah (h-1) ke atas (0)
    for r in range(h - 1, -1, -1):
        if row_counts[r] >= min_pixels:
            if not in_water:
                # Titik pertama air ditemukan (harus berada di area dasar botol)
                first_water_r = r
                if (h - 1 - first_water_r) > (h * max_bottom_offset):
                    # Jika deteksi pertama dimulai terlalu tinggi (misal di leher botol), abaikan
                    continue
                in_water = True

            water_top_rel_y = r
            gap_count = 0
        else:
            if in_water:
                gap_count += 1
                if gap_count > max_gap:
                    # Sudah keluar dari kolom air melewati toleransi gap
                    break

    if in_water and water_top_rel_y is not None and first_water_r is not None:
        detected_height = first_water_r - water_top_rel_y
        if detected_height >= min_water_height:
            return y + water_top_rel_y

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


# ==================== DEBOUNCING ====================
class DebounceAlertManager:
    """
    Manajer Debouncing: Status baru hanya dinyatakan RESMI jika bertahan
    stabil selama DEBOUNCE_DURATION_SEC detik berturut-turut.

    Ini mencegah false alarm dari cipratan air, hujan, atau burung lewat.
    """
    def __init__(self, duration_sec=DEBOUNCE_DURATION_SEC):
        self.duration_sec = duration_sec
        self.confirmed_status = "NORMAL"
        self.pending_status = "NORMAL"
        self.pending_since = time.time()
        self.alarm_fired = set()

    def update(self, raw_status):
        """
        Panggil fungsi ini setiap frame dengan status mentah dari deteksi.
        Mengembalikan (confirmed_status, just_confirmed).
        """
        now = time.time()

        if raw_status != self.pending_status:
            self.pending_status = raw_status
            self.pending_since = now
            return self.confirmed_status, False

        elapsed = now - self.pending_since
        if elapsed >= self.duration_sec and self.pending_status != self.confirmed_status:
            self.confirmed_status = self.pending_status
            just_confirmed = True

            if self.confirmed_status not in self.alarm_fired or self.confirmed_status == "NORMAL":
                self.alarm_fired = {self.confirmed_status}
                self._trigger_alert(self.confirmed_status)

            return self.confirmed_status, just_confirmed

        return self.confirmed_status, False

    def _trigger_alert(self, status):
        """Log alert. Nanti ganti dengan Telegram API call."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if status == "SIAGA":
            print(f"\n{'='*60}")
            print(f"[{ts}] !!! ALARM RESMI: SIAGA - Air mencapai zona MERAH !!!")
            print(f"{'='*60}\n")
        elif status == "WASPADA":
            print(f"\n[{ts}] ⚠ PERINGATAN RESMI: WASPADA - Air mendekati batas merah.")
        elif status == "NORMAL":
            print(f"\n[{ts}] ✓ INFO: Air kembali ke level NORMAL.")


# ==================== CLASS UTAMA (untuk diimpor Web Server) ====================
class WaterLevelDetector:
    """
    Class pembungkus seluruh pipeline deteksi air.
    Bisa diimpor oleh FastAPI app.py untuk streaming video dan membaca status.
    """

    def __init__(self, sensitivity=30, blur_size=21, debounce_sec=DEBOUNCE_DURATION_SEC):
        self.sensitivity = sensitivity
        self.blur_size = blur_size
        self.debounce = DebounceAlertManager(duration_sec=debounce_sec)

        # State publik yang bisa dibaca oleh web server
        self.confirmed_status = "NORMAL"
        self.raw_status = "NORMAL"
        self.water_y = None
        self.last_dx = 0
        self.last_dy = 0
        self.camera_connected = False
        self.last_frame_time = 0

        # Internal state
        self._cap = None
        self._ref_gray = None
        self._align_template = None
        self._roi = None
        self._y_waspada = None
        self._y_siaga = None
        self._y_history = deque(maxlen=15)
        self._no_detect_count = 0
        self._latest_display_frame = None
        self._lock = threading.Lock()
        self._running = False

        # Callback opsional untuk menyimpan ke database
        self.on_reading = None    # callback(water_y, status)
        self.on_alert = None      # callback(status, pesan)

    def initialize(self) -> bool:
        """
        Muat kalibrasi dan referensi. 
        Mengembalikan True jika berhasil, False jika belum dikalibrasi.
        """
        self._y_waspada, self._y_siaga = load_thresholds()
        if self._y_waspada is None or self._y_siaga is None:
            print("ERROR: Belum ada kalibrasi. Jalankan 'python scripts/calibrate_ui.py' dulu.")
            return False

        # Muat/capture referensi
        if not os.path.exists(REF_IMAGE_PATH):
            print(f"Referensi {REF_IMAGE_PATH} tidak ditemukan. Mengambil dari kamera...")
            cap = cv2.VideoCapture(RTSP_URL)
            if not cap.isOpened():
                print("GAGAL konek ke kamera RTSP untuk capture referensi.")
                return False
            ret, ref_frame = cap.read()
            cap.release()
            if not ret:
                print("Gagal membaca frame kamera.")
                return False
            cv2.imwrite(REF_IMAGE_PATH, ref_frame)
        else:
            ref_frame = cv2.imread(REF_IMAGE_PATH)

        print(f"Referensi dimuat: {ref_frame.shape}")
        print(f"Kalibrasi: Y Waspada={self._y_waspada}, Y Siaga={self._y_siaga}")

        # Muat ROI
        self._roi = load_roi()
        if self._roi is None:
            print("ERROR: Belum ada ROI tersimpan. Jalankan mode standalone dulu.")
            return False
        print(f"ROI dimuat: {self._roi}")

        self._ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
        self._ref_gray = cv2.GaussianBlur(self._ref_gray, (21, 21), 0)
        self._align_template = build_alignment_template(self._ref_gray, self._roi)

        return True

    def start_capture(self):
        """Mulai thread background untuk membaca RTSP dan memproses frame."""
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._capture_loop, daemon=True)
        thread.start()
        print("[WaterLevelDetector] Capture thread dimulai.")

    def stop(self):
        """Hentikan capture loop."""
        self._running = False
        if self._cap:
            self._cap.release()

    def _capture_loop(self):
        """Loop utama yang berjalan di background thread."""
        # Retry koneksi RTSP hingga berhasil
        while self._running:
            self._cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
            self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
            self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if self._cap.isOpened():
                break
            print("[WaterLevelDetector] Gagal konek RTSP, retry dalam 5 detik...")
            self.camera_connected = False
            self._cap.release()
            time.sleep(5)

        self.camera_connected = True
        print("[WaterLevelDetector] Stream RTSP terbuka.")

        last_db_save = 0

        while self._running:
            # Buang frame lama dari buffer agar selalu dapat frame terbaru
            for _ in range(2):
                self._cap.grab()

            ret, frame = self._cap.read()
            if not ret:
                self.camera_connected = False
                print("[WaterLevelDetector] Frame gagal, reconnect...")
                self._cap.release()
                time.sleep(2)
                self._cap = cv2.VideoCapture(RTSP_URL)
                if self._cap.isOpened():
                    self.camera_connected = True
                continue

            self.camera_connected = True
            self.last_frame_time = time.time()

            # Proses frame
            display_frame = self._process_frame(frame)

            # Simpan frame terakhir (thread-safe)
            with self._lock:
                self._latest_display_frame = display_frame

            # Simpan ke database setiap 10 detik (hanya jika air terdeteksi)
            now = time.time()
            if now - last_db_save >= 10.0 and self.water_y is not None:
                last_db_save = now
                if self.on_reading:
                    self.on_reading(self.water_y, self.confirmed_status)

            # Limit FPS (~15 fps)
            time.sleep(0.066)

        if self._cap:
            self._cap.release()

    def _process_frame(self, frame) -> np.ndarray:
        """Proses satu frame: alignment, differencing, deteksi, overlay."""
        roi = self._roi
        sensitivity = self.sensitivity
        blur_size = self.blur_size
        blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        blur_size = max(blur_size, 3)

        # Frame langsung (Auto-Alignment dinonaktifkan agar video 100% stabil)
        frame_aligned = frame

        # Background differencing
        gray = cv2.cvtColor(frame_aligned, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        diff = cv2.absdiff(self._ref_gray, gray)
        _, mask = cv2.threshold(diff, sensitivity, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        raw_water_y = get_water_level_y(mask, roi)

        # Temporal smoothing — update jika ada deteksi, reset jika kosong beberapa frame
        if raw_water_y is not None:
            self._y_history.append(raw_water_y)
            self._no_detect_count = 0
            self.water_y = int(np.median(self._y_history))
        else:
            self._no_detect_count += 1
            if self._no_detect_count > 10:
                self._y_history.clear()
                self.water_y = None

        # Status
        self.raw_status, _ = get_status(self.water_y, self._y_waspada, self._y_siaga)
        self.confirmed_status, just_confirmed = self.debounce.update(self.raw_status)

        # Alert callback
        if just_confirmed and self.on_alert:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            if self.confirmed_status == "SIAGA":
                self.on_alert("SIAGA", f"[{ts}] Air mencapai zona MERAH!")
            elif self.confirmed_status == "WASPADA":
                self.on_alert("WASPADA", f"[{ts}] Air mendekati batas merah.")
            elif self.confirmed_status == "NORMAL":
                self.on_alert("NORMAL", f"[{ts}] Air kembali ke level normal.")

        # Build overlay
        display = frame_aligned.copy()
        rx, ry, rw, rh = roi["x"], roi["y"], roi["w"], roi["h"]
        cv2.rectangle(display, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)

        status_color = {"NORMAL": (0, 200, 0), "WASPADA": (0, 220, 255), "SIAGA": (0, 0, 255)}.get(self.confirmed_status, (0, 200, 0))

        # Garis batas WASPADA dan SIAGA
        cv2.line(display, (rx, self._y_waspada), (rx + rw, self._y_waspada), (0, 255, 255), 2)
        cv2.putText(display, "WASPADA", (rx + rw + 5, self._y_waspada + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.line(display, (rx, self._y_siaga), (rx + rw, self._y_siaga), (0, 0, 255), 2)
        cv2.putText(display, "SIAGA", (rx + rw + 5, self._y_siaga + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Garis air
        if self.water_y is not None:
            cv2.line(display, (rx, self.water_y), (rx + rw, self.water_y), (255, 100, 0), 3)
            cv2.putText(display, f"Air: Y={self.water_y}", (rx + rw + 5, self.water_y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 100, 0), 2)

        # Status banner
        cv2.rectangle(display, (0, 0), (350, 80), status_color, -1)
        cv2.putText(display, self.confirmed_status, (15, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)

        # Debounce timer
        elapsed = time.time() - self.debounce.pending_since
        remaining = max(0, DEBOUNCE_DURATION_SEC - elapsed)
        if self.debounce.pending_status != self.debounce.confirmed_status:
            cv2.putText(display, f"Menunggu: {remaining:.1f}s", (0, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 2)

        return display

    def get_latest_frame_bytes(self) -> bytes | None:
        """
        Ambil frame terakhir yang sudah diproses sebagai JPG bytes.
        Dipakai untuk MJPEG streaming ke browser.
        """
        with self._lock:
            frame = self._latest_display_frame

        if frame is None:
            return None

        # Resize untuk web (720p)
        h, w = frame.shape[:2]
        target_h = 720
        scale = target_h / h
        resized = cv2.resize(frame, (int(w * scale), target_h))

        ret, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            return buffer.tobytes()
        return None

    def get_status_dict(self) -> dict:
        """Mengembalikan status terkini sebagai dict (untuk API JSON)."""
        return {
            "status": self.confirmed_status,
            "raw_status": self.raw_status,
            "water_y": self.water_y,
            "camera_connected": self.camera_connected,
            "last_dx": self.last_dx,
            "last_dy": self.last_dy,
            "timestamp": self.last_frame_time,
        }


# ==================== MODE STANDALONE (DEBUG/KALIBRASI) ====================
def nothing(x):
    pass


def main():
    y_waspada, y_siaga = load_thresholds()
    if y_waspada is None or y_siaga is None:
        print("ERROR: Belum ada kalibrasi. Jalankan 'python scripts\\calibrate_ui.py' dulu.")
        return

    if not os.path.exists(REF_IMAGE_PATH):
        print(f"Referensi {REF_IMAGE_PATH} tidak ditemukan. Mengambil gambar pertama dari kamera...")
        cap = cv2.VideoCapture(RTSP_URL)
        if not cap.isOpened():
            print("GAGAL konek ke kamera RTSP!")
            return
        ret, ref_frame = cap.read()
        cap.release()
        if not ret:
            print("Gagal membaca frame kamera.")
            return
        cv2.imwrite(REF_IMAGE_PATH, ref_frame)
    else:
        ref_frame = cv2.imread(REF_IMAGE_PATH)
    print(f"Referensi dimuat: {ref_frame.shape}")
    print(f"Kalibrasi: Y Waspada={y_waspada}, Y Siaga={y_siaga}")
    print(f"Debounce  : {DEBOUNCE_DURATION_SEC} detik (ubah DEBOUNCE_DURATION_SEC untuk produksi)")

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

    ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
    ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)

    align_template = build_alignment_template(ref_gray, roi)

    debounce = DebounceAlertManager(duration_sec=DEBOUNCE_DURATION_SEC)

    cv2.namedWindow("Settings", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Settings", 400, 120)
    cv2.createTrackbar("Sensitivity", "Settings", 30, 100, nothing)
    cv2.createTrackbar("Blur", "Settings", 21, 51, nothing)

    print("Connecting to RTSP stream...")
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        print("GAGAL konek ke kamera!")
        return
    print("Stream terbuka. Tuang air perlahan...")
    print("Tombol: 'q'=keluar, 'r'=reset referensi, 'n'=pilih ROI baru")

    display_h = 600
    y_history = deque(maxlen=15)
    no_detect_count = 0
    water_y = None
    last_printed_confirmed = None
    last_dx, last_dy = 0, 0

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

        sensitivity = cv2.getTrackbarPos("Sensitivity", "Settings")
        blur_size = cv2.getTrackbarPos("Blur", "Settings")
        blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        blur_size = max(blur_size, 3)

        # Frame langsung (Auto-Alignment dinonaktifkan agar video 100% stabil)
        frame_aligned = frame

        # ===== BACKGROUND DIFFERENCING =====
        gray = cv2.cvtColor(frame_aligned, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        diff = cv2.absdiff(ref_gray, gray)
        _, mask = cv2.threshold(diff, sensitivity, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        raw_water_y = get_water_level_y(mask, roi)

        if raw_water_y is not None:
            y_history.append(raw_water_y)
            no_detect_count = 0
            water_y = int(np.median(y_history))
        else:
            no_detect_count += 1
            if no_detect_count > 10:
                y_history.clear()
                water_y = None

        raw_status, _ = get_status(water_y, y_waspada, y_siaga)
        confirmed_status, just_confirmed = debounce.update(raw_status)

        if confirmed_status != last_printed_confirmed:
            print(f">>> STATUS TERKONFIRMASI: {confirmed_status} (water Y={water_y})")
            last_printed_confirmed = confirmed_status

        status_color = {"NORMAL": (0, 200, 0), "WASPADA": (0, 220, 255), "SIAGA": (0, 0, 255)}.get(confirmed_status, (0, 200, 0))

        # ===== OVERLAY =====
        display = frame_aligned.copy()
        rx, ry, rw, rh = roi["x"], roi["y"], roi["w"], roi["h"]
        cv2.rectangle(display, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)
        cv2.putText(display, "ROI", (rx, ry - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        align_color = (0, 255, 0) if abs(last_dx) < 5 and abs(last_dy) < 5 else (0, 165, 255)
        cv2.putText(display, f"Align dx={last_dx} dy={last_dy}", (10, display.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, align_color, 2)
        cv2.putText(display, f"Raw: {raw_status}", (10, display.shape[0] - 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

        cv2.line(display, (rx, y_waspada), (rx + rw, y_waspada), (0, 255, 255), 2)
        cv2.putText(display, "WASPADA", (rx + rw + 5, y_waspada + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.line(display, (rx, y_siaga), (rx + rw, y_siaga), (0, 0, 255), 2)
        cv2.putText(display, "SIAGA", (rx + rw + 5, y_siaga + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if water_y is not None:
            cv2.line(display, (rx, water_y), (rx + rw, water_y), (255, 100, 0), 3)
            cv2.putText(display, f"Air: Y={water_y}", (rx + rw + 5, water_y + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 100, 0), 2)

        cv2.rectangle(display, (0, 0), (350, 80), status_color, -1)
        cv2.putText(display, confirmed_status, (15, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)

        elapsed = time.time() - debounce.pending_since
        remaining = max(0, DEBOUNCE_DURATION_SEC - elapsed)
        if debounce.pending_status != debounce.confirmed_status:
            cv2.putText(display, f"Menunggu: {remaining:.1f}s", (0, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 0), 2)

        display_resized = cv2.resize(display, (display_w, display_h))

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
            ref_gray_new = cv2.cvtColor(frame_aligned, cv2.COLOR_BGR2GRAY)
            ref_gray = cv2.GaussianBlur(ref_gray_new, (21, 21), 0)
            align_template = build_alignment_template(ref_gray, roi)
            y_history.clear()
            print(">>> Referensi & Template di-reset ke frame saat ini.")
        elif key == ord("n"):
            cap.release()
            roi = select_roi(frame)
            if roi is None:
                print("ROI dibatalkan, pakai yang lama.")
                roi = load_roi()
            else:
                align_template = build_alignment_template(ref_gray, roi)
            cap = cv2.VideoCapture(RTSP_URL)

    cap.release()
    cv2.destroyAllWindows()
    print("Selesai.")


if __name__ == "__main__":
    main()
