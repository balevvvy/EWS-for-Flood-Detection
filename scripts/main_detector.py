"""
Pipeline Utama Deteksi Ketinggian Air EWS Banjir.
Menggunakan metode classical computer vision (Bottom-Up Frame Differencing).
"""

import os
import sys
import json
import time
import threading
from collections import deque
import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.camera.config_loader import load_camera_config

# Konfigurasi Kamera & Path
_cam_config = load_camera_config()
IP = _cam_config["ip"]
USERNAME = _cam_config["username"]
PASSWORD = _cam_config["password"]
CHANNEL = 1
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{IP}:554/cam/realmonitor?channel={CHANNEL}&subtype=0"

THRESHOLDS_PATH = os.path.join(BASE_DIR, "config", "cv_thresholds.json")
REF_IMAGE_PATH = os.path.join(BASE_DIR, "test_frame.jpg")
ROI_PATH = os.path.join(BASE_DIR, "config", "roi.json")
DEBOUNCE_DURATION_SEC = 5


def load_thresholds():
    if os.path.exists(THRESHOLDS_PATH):
        with open(THRESHOLDS_PATH, "r") as f:
            data = json.load(f)
        return data.get("y_waspada"), data.get("y_siaga")
    return None, None


def load_roi():
    if os.path.exists(ROI_PATH):
        with open(ROI_PATH, "r") as f:
            return json.load(f)
    return None


def save_roi(roi):
    os.makedirs(os.path.dirname(ROI_PATH), exist_ok=True)
    with open(ROI_PATH, "w") as f:
        json.dump(roi, f, indent=4)


def select_roi(frame):
    display_h = 700
    scale = display_h / frame.shape[0]
    display_w = int(frame.shape[1] * scale)
    display = cv2.resize(frame, (display_w, display_h))

    roi_rect = cv2.selectROI("Pilih Area Botol/Papan Duga", display, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Pilih Area Botol/Papan Duga")

    if roi_rect[2] == 0 or roi_rect[3] == 0:
        return None

    roi = {
        "x": int(roi_rect[0] / scale),
        "y": int(roi_rect[1] / scale),
        "w": int(roi_rect[2] / scale),
        "h": int(roi_rect[3] / scale),
    }
    save_roi(roi)
    return roi


def get_water_level_y(mask, roi, min_row_coverage=0.15, max_gap=20, min_water_height=10, max_bottom_offset=0.40):
    """
    Deteksi tinggi permukaan air dengan memindai baris dari dasar ROI ke atas.
    """
    x, y, w, h = roi["x"], roi["y"], roi["w"], roi["h"]
    roi_mask = mask[y:y+h, x:x+w]

    row_counts = np.count_nonzero(roi_mask, axis=1)
    min_pixels = max(int(w * min_row_coverage), 4)

    water_top_rel_y = None
    first_water_r = None
    gap_count = 0
    in_water = False

    for r in range(h - 1, -1, -1):
        if row_counts[r] >= min_pixels:
            if not in_water:
                first_water_r = r
                if (h - 1 - first_water_r) > (h * max_bottom_offset):
                    continue
                in_water = True
            water_top_rel_y = r
            gap_count = 0
        else:
            if in_water:
                gap_count += 1
                if gap_count > max_gap:
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


class DebounceAlertManager:
    def __init__(self, duration_sec=DEBOUNCE_DURATION_SEC):
        self.duration_sec = duration_sec
        self.confirmed_status = "NORMAL"
        self.pending_status = "NORMAL"
        self.pending_since = time.time()
        self.alarm_fired = set()

    def update(self, raw_status):
        now = time.time()
        if raw_status != self.pending_status:
            self.pending_status = raw_status
            self.pending_since = now
            return self.confirmed_status, False

        elapsed = now - self.pending_since
        if elapsed >= self.duration_sec and self.pending_status != self.confirmed_status:
            self.confirmed_status = self.pending_status
            if self.confirmed_status not in self.alarm_fired or self.confirmed_status == "NORMAL":
                self.alarm_fired = {self.confirmed_status}
                self._trigger_alert(self.confirmed_status)
            return self.confirmed_status, True

        return self.confirmed_status, False

    def _trigger_alert(self, status):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if status == "SIAGA":
            print(f"[{ts}] SIAGA: Air mencapai zona merah")
        elif status == "WASPADA":
            print(f"[{ts}] WASPADA: Air mendekati batas siaga")
        elif status == "NORMAL":
            print(f"[{ts}] INFO: Air pada level normal")


class WaterLevelDetector:
    def __init__(self, sensitivity=30, blur_size=21, debounce_sec=DEBOUNCE_DURATION_SEC):
        self.sensitivity = sensitivity
        self.blur_size = blur_size
        self.debounce = DebounceAlertManager(duration_sec=debounce_sec)

        self.confirmed_status = "NORMAL"
        self.raw_status = "NORMAL"
        self.water_y = None
        self.camera_connected = False
        self.last_frame_time = 0

        self._cap = None
        self._ref_gray = None
        self._roi = None
        self._y_waspada = None
        self._y_siaga = None
        self._y_history = deque(maxlen=15)
        self._no_detect_count = 0
        self._latest_display_frame = None
        self._lock = threading.Lock()
        self._running = False

        self.on_reading = None
        self.on_alert = None

    def initialize(self) -> bool:
        self._y_waspada, self._y_siaga = load_thresholds()
        if self._y_waspada is None or self._y_siaga is None:
            return False

        if not os.path.exists(REF_IMAGE_PATH):
            cap = cv2.VideoCapture(RTSP_URL)
            if not cap.isOpened():
                return False
            ret, ref_frame = cap.read()
            cap.release()
            if not ret:
                return False
            cv2.imwrite(REF_IMAGE_PATH, ref_frame)
        else:
            ref_frame = cv2.imread(REF_IMAGE_PATH)

        self._roi = load_roi()
        if self._roi is None:
            return False

        self._ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
        self._ref_gray = cv2.GaussianBlur(self._ref_gray, (21, 21), 0)
        return True

    def start_capture(self):
        if self._running:
            return
        self._running = True
        thread = threading.Thread(target=self._capture_loop, daemon=True)
        thread.start()

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()

    def _capture_loop(self):
        while self._running:
            self._cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
            self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
            self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if self._cap.isOpened():
                break
            self.camera_connected = False
            self._cap.release()
            time.sleep(5)

        self.camera_connected = True
        last_db_save = 0

        while self._running:
            for _ in range(2):
                self._cap.grab()

            ret, frame = self._cap.read()
            if not ret:
                self.camera_connected = False
                self._cap.release()
                time.sleep(2)
                self._cap = cv2.VideoCapture(RTSP_URL)
                if self._cap.isOpened():
                    self.camera_connected = True
                continue

            self.camera_connected = True
            self.last_frame_time = time.time()
            display_frame = self._process_frame(frame)

            with self._lock:
                self._latest_display_frame = display_frame

            now = time.time()
            if now - last_db_save >= 10.0 and self.water_y is not None:
                last_db_save = now
                if self.on_reading:
                    self.on_reading(self.water_y, self.confirmed_status)

            time.sleep(0.066)

        if self._cap:
            self._cap.release()

    def _process_frame(self, frame) -> np.ndarray:
        roi = self._roi
        sensitivity = self.sensitivity
        blur_size = self.blur_size
        blur_size = blur_size if blur_size % 2 == 1 else blur_size + 1
        blur_size = max(blur_size, 3)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        diff = cv2.absdiff(self._ref_gray, gray)
        _, mask = cv2.threshold(diff, sensitivity, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

        raw_water_y = get_water_level_y(mask, roi)

        if raw_water_y is not None:
            self._y_history.append(raw_water_y)
            self._no_detect_count = 0
            self.water_y = int(np.median(self._y_history))
        else:
            self._no_detect_count += 1
            if self._no_detect_count > 10:
                self._y_history.clear()
                self.water_y = None

        self.raw_status, _ = get_status(self.water_y, self._y_waspada, self._y_siaga)
        self.confirmed_status, just_confirmed = self.debounce.update(self.raw_status)

        if just_confirmed and self.on_alert:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            if self.confirmed_status == "SIAGA":
                self.on_alert("SIAGA", f"[{ts}] Air mencapai zona MERAH!")
            elif self.confirmed_status == "WASPADA":
                self.on_alert("WASPADA", f"[{ts}] Air mendekati batas merah.")
            elif self.confirmed_status == "NORMAL":
                self.on_alert("NORMAL", f"[{ts}] Air kembali ke level normal.")

        display = frame.copy()
        rx, ry, rw, rh = roi["x"], roi["y"], roi["w"], roi["h"]
        cv2.rectangle(display, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)

        status_color = {"NORMAL": (0, 200, 0), "WASPADA": (0, 220, 255), "SIAGA": (0, 0, 255)}.get(self.confirmed_status, (0, 200, 0))

        cv2.line(display, (rx, self._y_waspada), (rx + rw, self._y_waspada), (0, 255, 255), 2)
        cv2.putText(display, "WASPADA", (rx + rw + 5, self._y_waspada + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.line(display, (rx, self._y_siaga), (rx + rw, self._y_siaga), (0, 0, 255), 2)
        cv2.putText(display, "SIAGA", (rx + rw + 5, self._y_siaga + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if self.water_y is not None:
            cv2.line(display, (rx, self.water_y), (rx + rw, self.water_y), (255, 100, 0), 3)
            cv2.putText(display, f"Air: Y={self.water_y}", (rx + rw + 5, self.water_y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 100, 0), 2)

        cv2.rectangle(display, (0, 0), (350, 80), status_color, -1)
        cv2.putText(display, self.confirmed_status, (15, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 3)

        return display

    def get_latest_frame_bytes(self) -> bytes | None:
        with self._lock:
            frame = self._latest_display_frame
        if frame is None:
            return None

        h, w = frame.shape[:2]
        target_h = 720
        scale = target_h / h
        resized = cv2.resize(frame, (int(w * scale), target_h))

        ret, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            return buffer.tobytes()
        return None

    def get_status_dict(self) -> dict:
        return {
            "status": self.confirmed_status,
            "raw_status": self.raw_status,
            "water_y": self.water_y,
            "camera_connected": self.camera_connected,
            "timestamp": self.last_frame_time,
        }


def nothing(x):
    pass


def main():
    y_waspada, y_siaga = load_thresholds()
    if y_waspada is None or y_siaga is None:
        print("Error: Threshold belum dikalibrasi.")
        return

    if not os.path.exists(REF_IMAGE_PATH):
        cap = cv2.VideoCapture(RTSP_URL)
        if not cap.isOpened():
            print("Gagal menghubungkan RTSP.")
            return
        ret, ref_frame = cap.read()
        cap.release()
        if not ret:
            return
        cv2.imwrite(REF_IMAGE_PATH, ref_frame)
    else:
        ref_frame = cv2.imread(REF_IMAGE_PATH)

    roi = load_roi()
    if roi is None:
        roi = select_roi(ref_frame)
        if roi is None:
            return

    ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY)
    ref_gray = cv2.GaussianBlur(ref_gray, (21, 21), 0)

    debounce = DebounceAlertManager(duration_sec=DEBOUNCE_DURATION_SEC)

    cv2.namedWindow("Settings", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Settings", 400, 120)
    cv2.createTrackbar("Sensitivity", "Settings", 30, 100, nothing)
    cv2.createTrackbar("Blur", "Settings", 21, 51, nothing)

    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        print("Gagal membuka stream RTSP.")
        return

    display_h = 600
    y_history = deque(maxlen=15)
    no_detect_count = 0
    water_y = None
    last_printed_confirmed = None

    while True:
        ret, frame = cap.read()
        if not ret:
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

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
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
            last_printed_confirmed = confirmed_status

        status_color = {"NORMAL": (0, 200, 0), "WASPADA": (0, 220, 255), "SIAGA": (0, 0, 255)}.get(confirmed_status, (0, 200, 0))

        display = frame.copy()
        rx, ry, rw, rh = roi["x"], roi["y"], roi["w"], roi["h"]
        cv2.rectangle(display, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)

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

        display_resized = cv2.resize(display, (display_w, display_h))
        mask_vis = np.zeros_like(mask)
        mask_vis[ry:ry+rh, rx:rx+rw] = mask[ry:ry+rh, rx:rx+rw]
        mask_colored = cv2.cvtColor(mask_vis, cv2.COLOR_GRAY2BGR)
        mask_resized = cv2.resize(mask_colored, (display_w, display_h))

        combined = np.hstack([display_resized, mask_resized])
        cv2.imshow("EWS Banjir", combined)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break
        elif key == ord("r"):
            ref_gray_new = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ref_gray = cv2.GaussianBlur(ref_gray_new, (21, 21), 0)
            y_history.clear()
        elif key == ord("n"):
            cap.release()
            roi = select_roi(frame)
            if roi is None:
                roi = load_roi()
            cap = cv2.VideoCapture(RTSP_URL)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
