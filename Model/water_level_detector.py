"""
water_level_detector.py — Pipeline utama EWS: segmentasi → kalibrasi → alert.

Kelas ini mengintegrasikan tiga modul:
    - GaugeSegmentor  (segmentation.py)
    - GaugeCalibration (calibration.py)
    - AlertEngine     (alert.py)

Dan menangani:
    - PTZ settle delay (tunggu kamera berhenti + exposure stabil)
    - Day/night profile switching otomatis
    - Arsip frame + hasil ke folder output
    - Logging terstruktur

CARA PAKAI (satu foto / off-line test):

    from water_level_detector import WaterLevelDetector
    import cv2

    det = WaterLevelDetector(preset_name="papan_duga_utama")
    frame = cv2.imread("foto_papan.jpg")
    result = det.process_frame(frame)
    print(result)

CARA PAKAI (live dari RTSP / OpenCV VideoCapture):

    det = WaterLevelDetector(preset_name="papan_duga_utama")
    cap = cv2.VideoCapture("rtsp://admin:pass@10.52.9.101/cam/realmonitor?...")
    ret, frame = cap.read()
    if ret:
        result = det.process_frame(frame, save_annotated=True)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

from alert import AlertEngine, AlertStatus, callback_log
from calibration import GaugeCalibration
from config import CAMERA_PROFILES, PRESET_CONFIGS, SAM_CONFIG
from segmentation import GaugeSegmentor, SegmentationResult

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WaterLevelReading:
    """Hasil lengkap satu siklus pembacaan."""
    timestamp         : datetime
    preset_name       : str
    water_cm          : Optional[float]        # None kalau gagal deteksi
    waterline_y_px    : Optional[int]
    alert_status      : Optional[AlertStatus]
    seg_result        : SegmentationResult
    camera_profile    : str
    annotated_path    : Optional[str] = None   # path file gambar ternotasi
    raw_frame_path    : Optional[str] = None

    def __str__(self) -> str:
        ts    = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        cm    = f"{self.water_cm:.1f} cm" if self.water_cm is not None else "N/A"
        level = self.alert_status.level if self.alert_status else "N/A"
        return f"[{ts}] {self.preset_name} | {cm} | {level} | conf={self.seg_result.confidence:.2f}"

    def to_dict(self) -> dict:
        return {
            "timestamp"      : self.timestamp.isoformat(),
            "preset"         : self.preset_name,
            "water_cm"       : self.water_cm,
            "waterline_y_px" : self.waterline_y_px,
            "alert"          : self.alert_status.to_dict() if self.alert_status else None,
            "confidence"     : self.seg_result.confidence,
            "method"         : self.seg_result.method_used,
            "camera_profile" : self.camera_profile,
            "processing_ms"  : self.seg_result.processing_time_ms,
            "annotated_path" : self.annotated_path,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN DETECTOR CLASS
# ─────────────────────────────────────────────────────────────────────────────

class WaterLevelDetector:
    """
    Pipeline lengkap deteksi tinggi muka air dari frame kamera PTZ.

    Parameters
    ----------
    preset_name : str
        Nama preset PTZ (harus ada di config.PRESET_CONFIGS).
    output_dir : str | None
        Direktori untuk menyimpan frame ternotasi dan log JSON.
        Default: Model/output/<preset_name>/
    camera_profile : str | None
        Override profile kamera. Kalau None, pakai default dari preset config.
    dry_ref_frame : np.ndarray | None
        Frame referensi "papan kering" untuk frame differencing.
    alert_callbacks : list | None
        Callback notifikasi tambahan selain log default.
    """

    def __init__(
        self,
        preset_name      : str  = "papan_duga_utama",
        output_dir       : Optional[str] = None,
        camera_profile   : Optional[str] = None,
        dry_ref_frame    : Optional[np.ndarray] = None,
        alert_callbacks  : Optional[list] = None,
    ):
        self.preset_name   = preset_name
        self._preset_cfg   = PRESET_CONFIGS.get(preset_name, {})

        # Tentukan profile kamera
        self.camera_profile = (
            camera_profile
            or self._preset_cfg.get("profile_default", "day")
        )

        # Output dir
        model_dir         = os.path.dirname(os.path.abspath(__file__))
        self.output_dir   = output_dir or os.path.join(model_dir, "output", preset_name)
        os.makedirs(self.output_dir, exist_ok=True)

        # Sub-modul
        roi = self._preset_cfg.get("roi", None)
        self._segmentor = GaugeSegmentor(
            camera_profile   = self.camera_profile,
            roi              = roi,
            calibration_frame= dry_ref_frame,
            use_sam          = SAM_CONFIG.get("enabled", False),
        )

        self._calibration = GaugeCalibration(preset_name=preset_name)

        callbacks = [callback_log] + (alert_callbacks or [])
        self._alert_engine = AlertEngine(notify_callbacks=callbacks)

        # Log file JSON
        self._log_path = os.path.join(self.output_dir, "readings_log.jsonl")

        logger.info(
            f"[Detector] Init preset='{preset_name}' | "
            f"profile='{self.camera_profile}' | "
            f"calibration_ready={self._calibration.is_ready()} | "
            f"output='{self.output_dir}'"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def process_frame(
        self,
        frame           : np.ndarray,
        save_annotated  : bool = True,
        save_raw        : bool = False,
        debug_layers    : bool = False,
    ) -> WaterLevelReading:
        """
        Proses satu frame dan kembalikan WaterLevelReading lengkap.

        Parameters
        ----------
        frame          : np.ndarray  — frame BGR dari OpenCV
        save_annotated : bool        — simpan gambar dengan overlay
        save_raw       : bool        — simpan frame mentah
        debug_layers   : bool        — simpan semua intermediate mask

        Returns
        -------
        WaterLevelReading
        """
        ts = datetime.now()

        # ── Deteksi mode warna kamera (day/night switch) ──────────────────────
        self._auto_switch_profile(frame)

        # ── Segmentasi ────────────────────────────────────────────────────────
        seg = self._segmentor.process(frame, save_debug=debug_layers)

        # ── Konversi piksel → cm ──────────────────────────────────────────────
        water_cm   : Optional[float] = None
        alert_stat : Optional[AlertStatus] = None

        if seg.waterline_y is not None and self._calibration.is_ready():
            try:
                water_cm   = self._calibration.pixel_to_cm(seg.waterline_y)
                alert_stat = self._alert_engine.evaluate(
                    water_cm   = water_cm,
                    confidence = seg.confidence,
                    source     = "cv",
                )
            except Exception as e:
                logger.error(f"[Detector] Gagal konversi piksel→cm: {e}")
        elif seg.waterline_y is not None and not self._calibration.is_ready():
            logger.warning(
                "[Detector] Waterline terdeteksi tapi kalibrasi belum siap. "
                "Jalankan kalibrasi dulu via calibration.py atau test_with_photo.py"
            )

        reading = WaterLevelReading(
            timestamp      = ts,
            preset_name    = self.preset_name,
            water_cm       = water_cm,
            waterline_y_px = seg.waterline_y,
            alert_status   = alert_stat,
            seg_result     = seg,
            camera_profile = self.camera_profile,
        )

        # ── Simpan output ─────────────────────────────────────────────────────
        stamp = ts.strftime("%Y%m%d_%H%M%S")

        if save_raw:
            raw_path           = os.path.join(self.output_dir, f"raw_{stamp}.jpg")
            cv2.imwrite(raw_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            reading.raw_frame_path = raw_path

        if save_annotated:
            annotated          = self._draw_overlay(frame, reading)
            ann_path           = os.path.join(self.output_dir, f"annotated_{stamp}.jpg")
            cv2.imwrite(ann_path, annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
            reading.annotated_path = ann_path

        if debug_layers and seg.debug_layers:
            self._save_debug_layers(seg.debug_layers, stamp)

        # ── Append ke JSONL log ───────────────────────────────────────────────
        self._append_log(reading)

        logger.info(str(reading))
        return reading

    def set_calibration(
        self,
        mark1_cm: float, y1_pixel: int,
        mark2_cm: float, y2_pixel: int,
    ) -> None:
        """
        Set kalibrasi dua titik secara programmatik dan simpan ke file.

        Parameters
        ----------
        mark1_cm, y1_pixel : marka pertama (misal 300 cm, piksel-y marka 300)
        mark2_cm, y2_pixel : marka kedua  (misal 200 cm, piksel-y marka 200)
        """
        self._calibration.set_reference_point(mark_cm=mark1_cm, y_pixel=y1_pixel)
        self._calibration.set_reference_point(mark_cm=mark2_cm, y_pixel=y2_pixel)
        self._calibration.fit()
        self._calibration.save()
        logger.info(
            f"[Detector] Kalibrasi diset: {mark1_cm}cm@y={y1_pixel}px, "
            f"{mark2_cm}cm@y={y2_pixel}px"
        )

    def set_dry_reference(self, frame: np.ndarray) -> None:
        """Set frame referensi papan kering untuk frame differencing."""
        self._segmentor.set_calibration_frame(frame)

    def set_camera_profile(self, profile: str) -> None:
        """Override profile kamera (day / night_color / night_bw)."""
        self._segmentor.update_profile(profile)
        self.camera_profile = profile

    def calibration_summary(self) -> dict:
        """Return ringkasan state kalibrasi saat ini."""
        return self._calibration.summary()

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — AUTO PROFILE SWITCH
    # ─────────────────────────────────────────────────────────────────────────

    def _auto_switch_profile(self, frame: np.ndarray) -> None:
        """
        Deteksi otomatis apakah frame berwarna atau B&W (IR mode).
        Switch profile kamera kalau diperlukan.

        DH-SD5A225XA-HNR: kalau ICR aktif → frame jadi monokrom.
        Kita bisa deteksi ini dari variance antar channel BGR.
        """
        if len(frame.shape) < 3:
            target = "night_bw"
        else:
            # Hitung selisih std dev antar channel
            b_std = float(np.std(frame[:, :, 0]))
            g_std = float(np.std(frame[:, :, 1]))
            r_std = float(np.std(frame[:, :, 2]))
            channel_diff = abs(b_std - r_std) + abs(b_std - g_std)

            if channel_diff < 5.0:
                # Frame monokrom (IR mode)
                target = "night_bw"
            elif np.mean(frame) < 60:
                # Frame sangat gelap → kemungkinan malam dengan warna
                target = "night_color"
            else:
                target = "day"

        if target != self.camera_profile:
            logger.info(f"[Detector] Auto-switch profile: {self.camera_profile} → {target}")
            self.set_camera_profile(target)

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — OVERLAY VISUALISASI
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_overlay(self, frame: np.ndarray, reading: WaterLevelReading) -> np.ndarray:
        """Render overlay lengkap: waterline, bbox, info panel, alert banner."""
        vis = self._segmentor.visualize(frame, reading.seg_result)

        h, w = vis.shape[:2]

        # ── Info panel kiri bawah ─────────────────────────────────────────────
        panel_y = h - 130
        overlay = vis.copy()
        cv2.rectangle(overlay, (0, panel_y), (400, h), (20, 20, 20), cv2.FILLED)
        cv2.addWeighted(overlay, 0.7, vis, 0.3, 0, vis)

        texts = [
            f"Waktu  : {reading.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Tinggi : {f'{reading.water_cm:.1f} cm' if reading.water_cm else 'N/A'}",
            f"Profile: {reading.camera_profile}",
            f"Metode : {reading.seg_result.method_used}",
            f"Conf   : {reading.seg_result.confidence:.2f}",
        ]
        for i, txt in enumerate(texts):
            cv2.putText(vis, txt, (10, panel_y + 22 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (240, 240, 240), 1, cv2.LINE_AA)

        # ── Alert banner atas ─────────────────────────────────────────────────
        if reading.alert_status:
            level  = reading.alert_status.level
            label  = reading.alert_status.label
            color  = reading.alert_status.color_rgb       # (R, G, B)
            color_bgr = (color[2], color[1], color[0])    # → BGR

            banner_h = 50
            cv2.rectangle(vis, (0, 0), (w, banner_h), color_bgr, cv2.FILLED)
            banner_text = f"STATUS: {label.upper()}  —  {reading.water_cm:.1f} cm"
            cv2.putText(vis, banner_text, (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

        # ── Garis kalibrasi (kalau ada) ────────────────────────────────────────
        if self._calibration.is_ready():
            for mark_cm in [300, 250, 200, 150, 100]:
                try:
                    y_mark = int(self._calibration.cm_to_pixel(mark_cm))
                    if 0 <= y_mark < h:
                        cv2.line(vis, (0, y_mark), (60, y_mark), (200, 200, 60), 1)
                        cv2.putText(vis, f"{mark_cm}", (2, y_mark - 3),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 60), 1)
                except Exception:
                    pass

        return vis

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — FILE I/O
    # ─────────────────────────────────────────────────────────────────────────

    def _append_log(self, reading: WaterLevelReading) -> None:
        """Append satu pembacaan ke file JSONL (newline-delimited JSON)."""
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(reading.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[Detector] Gagal tulis log: {e}")

    def _save_debug_layers(self, layers: dict, stamp: str) -> None:
        """Simpan semua intermediate mask ke subfolder debug."""
        debug_dir = os.path.join(self.output_dir, "debug", stamp)
        os.makedirs(debug_dir, exist_ok=True)
        for name, img in layers.items():
            if img is not None:
                path = os.path.join(debug_dir, f"{name}.png")
                cv2.imwrite(path, img)
        logger.info(f"[Detector] Debug layers saved → {debug_dir}")
