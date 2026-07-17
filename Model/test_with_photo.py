"""
test_with_photo.py — Test runner interaktif untuk modul segmentasi + kalibrasi EWS.

CARA PAKAI:
    cd "d:/Antigravity/EWS project/Model"
    python test_with_photo.py --image ../test_frame.jpg

ALUR:
    1. Buka foto papan duga
    2. [MODE KALIBRASI] Klik marka "300" → klik marka "200" → simpan kalibrasi
    3. [MODE SEGMENTASI] Jalankan pipeline hybrid → lihat overlay + nilai cm
    4. Simpan gambar hasil ke folder output/

KEYBOARD SHORTCUTS (saat window OpenCV terbuka):
    c  = mode kalibrasi (klik 2 titik referensi)
    s  = jalankan segmentasi
    d  = toggle debug layers
    p  = print summary ke console
    q  = keluar

DEPENDENSI:
    pip install opencv-python numpy
    (SAM opsional: pip install segment-anything torch torchvision)
"""

import argparse
import json
import logging
import os
import sys
import time

import cv2
import numpy as np

# ── Pastikan bisa import modul Model walau dijalankan dari luar folder ────────
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
if MODEL_DIR not in sys.path:
    sys.path.insert(0, MODEL_DIR)

from calibration import GaugeCalibration
from config import PRESET_CONFIGS
from segmentation import GaugeSegmentor
from water_level_detector import WaterLevelDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE CALIBRATION (klik 2 titik di gambar)
# ─────────────────────────────────────────────────────────────────────────────

class InteractiveCalibrator:
    """
    Tampilkan gambar dan minta pengguna klik marka-marka yang diketahui nilainya.

    Urutan klik:
        Klik pertama  → marka mark1_cm (default: 300 cm)
        Klik kedua    → marka mark2_cm (default: 200 cm)
    """

    WINDOW = "KALIBRASI — Klik marka 300 lalu 200 | [q]=batal"

    def __init__(self, frame: np.ndarray, mark1_cm: float = 300, mark2_cm: float = 200):
        self.frame    = frame.copy()
        self.mark_cms = [mark1_cm, mark2_cm]
        self.clicks   : list[tuple[int, int]] = []
        self._done    = False

    def run(self) -> Optional[tuple]:
        """
        Buka window, tunggu 2 klik, kembalikan
        ((mark1_cm, y1), (mark2_cm, y2)) atau None kalau dibatalkan.
        """
        cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.WINDOW, 700, 900)
        cv2.setMouseCallback(self.WINDOW, self._on_click)

        self._render()

        while not self._done:
            key = cv2.waitKey(50) & 0xFF
            if key == ord('q'):
                cv2.destroyWindow(self.WINDOW)
                return None
            self._render()

        cv2.destroyWindow(self.WINDOW)
        return (
            (self.mark_cms[0], self.clicks[0][1]),
            (self.mark_cms[1], self.clicks[1][1]),
        )

    def _on_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(self.clicks) < 2:
            self.clicks.append((x, y))
            logger.info(
                f"[Kalibrasi] Klik {len(self.clicks)}: "
                f"marka={self.mark_cms[len(self.clicks)-1]} cm  →  y={y} px"
            )
            if len(self.clicks) == 2:
                self._done = True

    def _render(self):
        display = self.frame.copy()
        h, w    = display.shape[:2]

        # Instruksi
        labels = [
            "KALIBRASI PAPAN DUGA",
            f"Klik {len(self.clicks)+1}/2: marka {self.mark_cms[len(self.clicks)]} cm",
            "(tekan q untuk batal)",
        ]
        for i, txt in enumerate(labels):
            cv2.putText(display, txt, (10, 30 + i * 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)

        # Tampilkan titik yang sudah diklik
        colors = [(0, 200, 255), (0, 255, 100)]
        for idx, (cx, cy) in enumerate(self.clicks):
            cv2.drawMarker(display, (cx, cy), colors[idx],
                           cv2.MARKER_CROSS, markerSize=30, thickness=2)
            cv2.line(display, (0, cy), (w, cy), colors[idx], 1, cv2.LINE_AA)
            cv2.putText(display, f"{self.mark_cms[idx]} cm  y={cy}px",
                        (cx + 5, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[idx], 2)

        cv2.imshow(self.WINDOW, display)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TEST RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test segmentasi + kalibrasi papan duga EWS (foto mode)"
    )
    parser.add_argument(
        "--image", "-i",
        default=os.path.join(os.path.dirname(MODEL_DIR), "test_frame.jpg"),
        help="Path ke foto papan duga (default: ../test_frame.jpg)",
    )
    parser.add_argument(
        "--preset", "-p",
        default="papan_duga_utama",
        help="Nama preset PTZ (default: papan_duga_utama)",
    )
    parser.add_argument(
        "--mark1", type=float, default=300,
        help="Nilai marka pertama dalam cm (default: 300)",
    )
    parser.add_argument(
        "--mark2", type=float, default=200,
        help="Nilai marka kedua dalam cm (default: 200)",
    )
    parser.add_argument(
        "--dry-ref", default=None,
        help="Path foto papan kering (referensi background subtraction)",
    )
    parser.add_argument(
        "--profile", default=None,
        choices=["day", "night_color", "night_bw"],
        help="Override camera profile",
    )
    parser.add_argument(
        "--no-gui", action="store_true",
        help="Jalankan headless (tanpa window OpenCV, cocok untuk server)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Simpan semua intermediate mask ke folder debug/",
    )
    parser.add_argument(
        "--skip-calibration", action="store_true",
        help="Lewati langkah kalibrasi interaktif (pakai data yang sudah tersimpan)",
    )
    args = parser.parse_args()

    # ── Load foto ─────────────────────────────────────────────────────────────
    if not os.path.exists(args.image):
        print(f"[ERROR] File tidak ditemukan: {args.image}")
        print(f"        Pastikan ada foto papan duga di path tersebut.")
        sys.exit(1)

    frame = cv2.imread(args.image)
    if frame is None:
        print(f"[ERROR] Gagal membaca gambar: {args.image}")
        sys.exit(1)

    print(f"\n{'='*65}")
    print(f"  EWS — Test Segmentasi + Kalibrasi Papan Duga")
    print(f"{'='*65}")
    print(f"  Gambar  : {args.image}")
    print(f"  Ukuran  : {frame.shape[1]}x{frame.shape[0]} px")
    print(f"  Preset  : {args.preset}")
    print(f"{'='*65}\n")

    # ── Load frame referensi (papan kering) jika ada ─────────────────────────
    dry_ref = None
    if args.dry_ref and os.path.exists(args.dry_ref):
        dry_ref = cv2.imread(args.dry_ref)
        logger.info(f"[Test] Dry reference loaded: {args.dry_ref}")

    # ── Inisialisasi Detector ─────────────────────────────────────────────────
    detector = WaterLevelDetector(
        preset_name    = args.preset,
        camera_profile = args.profile,
        dry_ref_frame  = dry_ref,
    )

    # ── LANGKAH 1: KALIBRASI ──────────────────────────────────────────────────
    cal = GaugeCalibration(preset_name=args.preset)

    if args.skip_calibration:
        print("[*] --skip-calibration aktif. Menggunakan kalibrasi tersimpan.")
        if not cal.is_ready():
            print("[WARN] Kalibrasi belum tersimpan! Hasilnya mungkin tidak akurat.")
    elif args.no_gui:
        # Mode headless: minta koordinat piksel via stdin
        print("[*] Mode headless — masukkan koordinat piksel secara manual.")
        try:
            y1 = int(input(f"  Koordinat piksel Y untuk marka {args.mark1} cm: ").strip())
            y2 = int(input(f"  Koordinat piksel Y untuk marka {args.mark2} cm: ").strip())
            detector.set_calibration(args.mark1, y1, args.mark2, y2)
            print(f"[OK] Kalibrasi: {args.mark1}cm@y={y1}, {args.mark2}cm@y={y2}")
        except (ValueError, KeyboardInterrupt):
            print("[WARN] Input kalibrasi tidak valid. Lanjut tanpa kalibrasi.")
    else:
        # Mode GUI: klik interaktif
        print("[*] Membuka window kalibrasi...")
        print(f"    Klik marka {args.mark1} cm (atas) → klik marka {args.mark2} cm (bawah)")
        print(f"    Tekan 'q' untuk lewati kalibrasi interaktif.\n")

        calibrator = InteractiveCalibrator(frame, mark1_cm=args.mark1, mark2_cm=args.mark2)
        cal_result = calibrator.run()

        if cal_result:
            (m1, y1), (m2, y2) = cal_result
            detector.set_calibration(m1, y1, m2, y2)
            print(f"\n[OK] Kalibrasi tersimpan:")
            print(f"     {m1} cm → y={y1} px")
            print(f"     {m2} cm → y={y2} px")
            summary = detector.calibration_summary()
            if summary.get("coeff"):
                print(f"     Slope  : {summary['coeff']['slope']:.6f} cm/px")
                print(f"     cm/px  : {summary.get('cm_per_pixel', 0):.4f}")
        else:
            print("[*] Kalibrasi dilewati. Pakai data tersimpan (kalau ada).")

    # ── LANGKAH 2: SEGMENTASI ─────────────────────────────────────────────────
    print(f"\n[*] Menjalankan segmentasi pada: {os.path.basename(args.image)}")
    t0      = time.perf_counter()
    reading = detector.process_frame(
        frame,
        save_annotated = True,
        save_raw       = False,
        debug_layers   = args.debug,
    )
    elapsed = (time.perf_counter() - t0) * 1000

    # ── HASIL ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  HASIL DETEKSI")
    print(f"{'='*65}")
    print(f"  Waterline piksel : {reading.waterline_y_px} px")
    print(f"  Tinggi muka air  : {f'{reading.water_cm:.1f} cm' if reading.water_cm else 'N/A (kalibrasi belum ada)'}")
    print(f"  Status siaga     : {reading.alert_status.label if reading.alert_status else 'N/A'}")
    print(f"  Confidence       : {reading.seg_result.confidence:.2f}")
    print(f"  Metode           : {reading.seg_result.method_used}")
    print(f"  Profile kamera   : {reading.camera_profile}")
    print(f"  Waktu proses     : {elapsed:.1f} ms")
    if reading.annotated_path:
        print(f"  Output disimpan  : {reading.annotated_path}")
    print(f"{'='*65}\n")

    # ── TAMPILKAN HASIL (GUI) ─────────────────────────────────────────────────
    if not args.no_gui and reading.annotated_path:
        annotated = cv2.imread(reading.annotated_path)
        if annotated is not None:
            win_name = "HASIL SEGMENTASI — tekan q untuk keluar | d = debug"
            cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(win_name, 700, 900)

            show_debug = False
            debug_keys = list(reading.seg_result.debug_layers.keys())
            debug_idx  = 0

            while True:
                if show_debug and debug_keys:
                    dk  = debug_keys[debug_idx % len(debug_keys)]
                    img = reading.seg_result.debug_layers[dk]
                    if img is not None:
                        # Convert mask ke BGR kalau grayscale
                        if len(img.shape) == 2:
                            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                        # Label nama layer
                        display = img.copy()
                        cv2.putText(display, f"Debug: {dk}  ({debug_idx+1}/{len(debug_keys)})",
                                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                    (0, 255, 255), 2, cv2.LINE_AA)
                        cv2.putText(display, "d=next  q=keluar",
                                    (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    (200, 200, 200), 1)
                        cv2.imshow(win_name, display)
                else:
                    cv2.imshow(win_name, annotated)

                key = cv2.waitKey(50) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('d'):
                    if debug_keys:
                        if show_debug:
                            debug_idx = (debug_idx + 1) % len(debug_keys)
                        show_debug = not show_debug if debug_idx == 0 else True
                elif key == ord('p'):
                    print(json.dumps(reading.to_dict(), indent=2, ensure_ascii=False))

            cv2.destroyAllWindows()

    # ── TEST MODUL KALIBRASI (standalone) ─────────────────────────────────────
    print("[*] Menjalankan self-test kalibrasi ...")
    cal_summary = detector.calibration_summary()
    if cal_summary["is_ready"]:
        coeff = cal_summary["coeff"]
        print(f"    Slope    = {coeff['slope']:.6f} cm/px")
        print(f"    Intercept= {coeff['intercept']:.2f} cm")
        print(f"    cm/pixel = {cal_summary.get('cm_per_pixel', 0):.4f}")

        # Round-trip test
        print("\n    Round-trip test piksel -> cm -> piksel:")
        for test_y in [100, 200, 300, 400, 500]:
            if test_y < frame.shape[0]:
                cm_val = detector._calibration.pixel_to_cm(test_y)
                y_back = detector._calibration.cm_to_pixel(cm_val)
                err    = abs(test_y - y_back)
                print(f"      y={test_y:4d}px -> {cm_val:7.2f}cm -> y~{y_back:6.1f}px  (err={err:.2f}px)")
    else:
        print("    [!] Kalibrasi belum tersedia. Jalankan dulu dengan klik dua titik marka.")

    print("\n[DONE] Test selesai.\n")


# ─────────────────────────────────────────────────────────────────────────────
# TYPE HINT HACK (Optional tidak di-import di atas karena file panjang)
# ─────────────────────────────────────────────────────────────────────────────
from typing import Optional  # noqa: E402  (diletakkan di bawah agar tidak konflik)


if __name__ == "__main__":
    main()
