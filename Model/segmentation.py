"""
segmentation.py — Hybrid segmentation module untuk deteksi garis air pada papan duga EWS.

ARSITEKTUR:
    Layer 1 — Rule-based (selalu aktif):
        a) HSV color thresholding → isolasi area merah/kuning papan duga
        b) Background subtraction (MOG2 atau frame differencing) → pisahkan foreground
        c) Edge detection (Canny) → deteksi transisi tajam air/papan
        d) Morphological cleanup → buang noise, isi lubang
        e) Waterline scan → cari batas terbawah papan duga yang masih kering

    Layer 2 — SAM/EdgeSAM (opsional, server-side):
        - Diaktifkan kalau config SAM_CONFIG["enabled"] = True
        - Prompt point berasal dari estimasi garis air Layer 1
        - Fallback ke Layer 1 kalau SAM gagal/timeout

    Profile siang/malam:
        - Otomatis switch parameter berdasarkan deteksi mode kamera
        - Mode B&W (IR): HSV dinonaktifkan, edge + BG subtraction jadi andalan utama

REFERENSI:
    - "Robust water level measurement using adaptive prompt staff gauge image
      segmentation based on EdgeSAM" (ScienceDirect, 2025)
    - "Improving image-based water-level monitoring by coupling water-line detection
      techniques and the segment anything model" (ScienceDirect, 2025)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from config import (
    HSV_RED_LOWER1, HSV_RED_UPPER1,
    HSV_RED_LOWER2, HSV_RED_UPPER2,
    HSV_YELLOW_LOWER, HSV_YELLOW_UPPER,
    HSV_BLACK_LOWER, HSV_BLACK_UPPER,
    MOG2_HISTORY, MOG2_VAR_THRESHOLD, MOG2_DETECT_SHADOWS,
    FRAME_DIFF_THRESHOLD,
    MORPH_KERNEL_SIZE, MORPH_CLOSE_ITER, MORPH_OPEN_ITER,
    CAMERA_PROFILES, SAM_CONFIG,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SegmentationResult:
    """
    Hasil segmentasi satu frame.

    Attributes
    ----------
    waterline_y : int | None
        Koordinat piksel Y dari garis air yang terdeteksi.
        None kalau papan tidak terdeteksi.
    gauge_bbox : tuple | None
        Bounding box papan duga (x, y, w, h) dalam piksel.
    gauge_mask : np.ndarray | None
        Binary mask area papan duga (uint8, 0/255).
    water_mask : np.ndarray | None
        Binary mask area air (uint8, 0/255).
    method_used : str
        Metode yang dipakai: "hsv_edge", "bg_subtraction", "sam", "combined".
    confidence : float
        Skor kepercayaan 0.0–1.0 (heuristik dari luas contour & konsistensi edge).
    debug_layers : dict
        Intermediate images untuk visualisasi debug.
    processing_time_ms : float
        Waktu pemrosesan dalam milidetik.
    """
    waterline_y        : Optional[int]           = None
    gauge_bbox         : Optional[tuple]         = None
    gauge_mask         : Optional[np.ndarray]    = None
    water_mask         : Optional[np.ndarray]    = None
    method_used        : str                     = "none"
    confidence         : float                   = 0.0
    debug_layers       : dict                    = field(default_factory=dict)
    processing_time_ms : float                   = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class GaugeSegmentor:
    """
    Segmentor hybrid (rule-based + opsional SAM) untuk papan duga.

    Parameters
    ----------
    camera_profile : str
        "day" | "night_color" | "night_bw" — pilih dari config.CAMERA_PROFILES.
    roi : dict | None
        Region of interest dalam koordinat relatif {x_min, x_max, y_min, y_max}.
        None = seluruh frame.
    calibration_frame : np.ndarray | None
        Foto "papan kering" (tanpa air) untuk frame differencing. Opsional.
    use_sam : bool
        Override untuk mengaktifkan/menonaktifkan SAM layer.
    """

    def __init__(
        self,
        camera_profile: str = "day",
        roi: Optional[dict] = None,
        calibration_frame: Optional[np.ndarray] = None,
        use_sam: bool = False,
    ):
        self.camera_profile = camera_profile
        self.roi            = roi
        self.use_sam        = use_sam and SAM_CONFIG.get("enabled", False)

        # MOG2 background subtractor (untuk stream mode)
        self._mog2 = cv2.createBackgroundSubtractorMOG2(
            history=MOG2_HISTORY,
            varThreshold=MOG2_VAR_THRESHOLD,
            detectShadows=MOG2_DETECT_SHADOWS,
        )

        # Frame referensi untuk differencing (foto kalibrasi "papan kering")
        self._ref_frame: Optional[np.ndarray] = None
        if calibration_frame is not None:
            self.set_calibration_frame(calibration_frame)

        # SAM wrapper — hanya di-import kalau diaktifkan
        self._sam = None
        if self.use_sam:
            self._init_sam()

        # Morfologi kernel
        self._kernel = np.ones(MORPH_KERNEL_SIZE, np.uint8)

        logger.info(
            f"[Segmentor] Init | profile={camera_profile} | "
            f"ROI={roi} | SAM={'ON' if self.use_sam else 'OFF'}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def process(self, frame: np.ndarray, save_debug: bool = False) -> SegmentationResult:
        """
        Proses satu frame dan kembalikan SegmentationResult.

        Parameters
        ----------
        frame : np.ndarray
            Frame BGR dari OpenCV.
        save_debug : bool
            Kalau True, simpan intermediate images di result.debug_layers.

        Returns
        -------
        SegmentationResult
        """
        t0 = time.perf_counter()
        result = SegmentationResult()

        # 1. Crop ke ROI
        frame_roi, offset = self._apply_roi(frame)

        # 2. Tentukan apakah gambar berwarna atau grayscale (IR mode)
        is_color = self._is_color_frame(frame_roi)
        profile  = CAMERA_PROFILES.get(self.camera_profile, CAMERA_PROFILES["day"])

        debug = {}

        # ── LAYER 1A: HSV color thresholding ─────────────────────────────────
        gauge_mask_hsv = None
        if profile["use_hsv"] and is_color:
            gauge_mask_hsv = self._hsv_gauge_mask(frame_roi)
            if save_debug:
                debug["hsv_mask"] = gauge_mask_hsv.copy()

        # ── LAYER 1B: Background subtraction / frame differencing ─────────────
        fg_mask = self._foreground_mask(frame_roi)
        if save_debug:
            debug["fg_mask"] = fg_mask.copy()

        # ── LAYER 1C: Edge detection pada grayscale ───────────────────────────
        edge_mask = self._edge_mask(frame_roi, profile["edge_sensitivity"])
        if save_debug:
            debug["edge_mask"] = edge_mask.copy()

        # ── LAYER 1D: Combine masks ───────────────────────────────────────────
        combined = self._combine_masks(gauge_mask_hsv, fg_mask, edge_mask)
        if save_debug:
            debug["combined_mask"] = combined.copy()

        # ── LAYER 1E: Morphological cleanup ───────────────────────────────────
        clean = self._morph_cleanup(combined)
        if save_debug:
            debug["clean_mask"] = clean.copy()

        # ── LAYER 1F: Deteksi papan duga (bounding box terbesar) ──────────────
        gauge_bbox, gauge_mask_final = self._detect_gauge_bbox(
            clean, min_area=profile["min_contour_area"]
        )

        if gauge_bbox is None:
            logger.warning("[Segmentor] Papan duga tidak terdeteksi pada frame ini.")
            result.method_used        = "rule_based"
            result.confidence         = 0.0
            result.debug_layers       = debug
            result.processing_time_ms = (time.perf_counter() - t0) * 1000
            return result

        # ── LAYER 1G: Scan waterline dalam ROI papan ──────────────────────────
        waterline_y_roi, water_mask, confidence = self._detect_waterline(
            frame_roi, gauge_bbox, gauge_mask_final
        )

        # ── LAYER 2: SAM (opsional) ───────────────────────────────────────────
        if self.use_sam and self._sam is not None and waterline_y_roi is not None:
            sam_result = self._run_sam(frame_roi, waterline_y_roi, gauge_bbox)
            if sam_result is not None:
                waterline_y_roi, water_mask, confidence = sam_result
                result.method_used = "combined_sam"
            else:
                result.method_used = "rule_based"
        else:
            result.method_used = "hsv_edge" if (gauge_mask_hsv is not None) else "bg_subtraction"

        # ── Translate balik ke koordinat frame penuh ──────────────────────────
        waterline_y_full = None
        bbox_full        = None
        if waterline_y_roi is not None:
            roi_y = offset[1]
            waterline_y_full = waterline_y_roi + roi_y

        if gauge_bbox is not None:
            x, y, w, h      = gauge_bbox
            roi_x, roi_y    = offset
            bbox_full        = (x + roi_x, y + roi_y, w, h)

        result.waterline_y        = waterline_y_full
        result.gauge_bbox         = bbox_full
        result.gauge_mask         = gauge_mask_final
        result.water_mask         = water_mask
        result.confidence         = confidence
        result.debug_layers       = debug
        result.processing_time_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            f"[Segmentor] waterline_y={waterline_y_full}px | "
            f"conf={confidence:.2f} | method={result.method_used} | "
            f"time={result.processing_time_ms:.1f}ms"
        )
        return result

    def set_calibration_frame(self, frame: np.ndarray) -> None:
        """
        Set foto referensi "papan kering" untuk frame differencing.

        Frame akan dikonversi ke grayscale dan di-blur untuk mengurangi noise.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        self._ref_frame = cv2.GaussianBlur(gray, (5, 5), 0)
        logger.info("[Segmentor] Calibration frame (dry board reference) set.")

    def update_profile(self, profile_name: str) -> None:
        """Switch camera profile (day / night_color / night_bw)."""
        if profile_name not in CAMERA_PROFILES:
            raise ValueError(f"Profile '{profile_name}' tidak ada. Pilih dari: {list(CAMERA_PROFILES)}")
        self.camera_profile = profile_name
        logger.info(f"[Segmentor] Profile switched → {profile_name}")

    def visualize(self, frame: np.ndarray, result: SegmentationResult) -> np.ndarray:
        """
        Render overlay visualisasi pada frame (BGR).

        Returns
        -------
        np.ndarray
            Frame dengan overlay (garis air, bounding box, label).
        """
        vis = frame.copy()

        # Bounding box papan duga (biru)
        if result.gauge_bbox is not None:
            x, y, w, h = result.gauge_bbox
            cv2.rectangle(vis, (x, y), (x + w, y + h), (255, 140, 0), 2)
            cv2.putText(vis, "Papan Duga", (x, y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 140, 0), 2)

        # Garis air (cyan, tebal)
        if result.waterline_y is not None:
            wy = result.waterline_y
            cv2.line(vis, (0, wy), (vis.shape[1], wy), (0, 255, 220), 3)
            label = f"Garis Air  [{result.confidence:.2f}]  {result.method_used}"
            cv2.putText(vis, label, (10, wy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 220), 2)

        # Watermark metode
        cv2.putText(vis, f"Profile: {self.camera_profile}",
                    (10, vis.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        return vis

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — HSV
    # ─────────────────────────────────────────────────────────────────────────

    def _hsv_gauge_mask(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Buat binary mask area warna papan duga (merah + kuning)."""
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

        # Merah (hue wrap-around)
        m_red1 = cv2.inRange(hsv,
                              np.array(HSV_RED_LOWER1), np.array(HSV_RED_UPPER1))
        m_red2 = cv2.inRange(hsv,
                              np.array(HSV_RED_LOWER2), np.array(HSV_RED_UPPER2))
        m_red  = cv2.bitwise_or(m_red1, m_red2)

        # Kuning
        m_yellow = cv2.inRange(hsv,
                                np.array(HSV_YELLOW_LOWER), np.array(HSV_YELLOW_UPPER))

        # Gabungkan
        gauge_mask = cv2.bitwise_or(m_red, m_yellow)

        # Cleanup ringan
        gauge_mask = cv2.morphologyEx(gauge_mask, cv2.MORPH_CLOSE, self._kernel, iterations=2)
        gauge_mask = cv2.morphologyEx(gauge_mask, cv2.MORPH_OPEN,  self._kernel, iterations=1)
        return gauge_mask

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — BACKGROUND SUBTRACTION
    # ─────────────────────────────────────────────────────────────────────────

    def _foreground_mask(self, frame_bgr: np.ndarray) -> np.ndarray:
        """
        Hasilkan foreground mask.
        - Kalau ada ref_frame: frame differencing terhadap foto kalibrasi.
        - Kalau tidak ada: pakai MOG2 (kurang berguna untuk foto tunggal).
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if len(frame_bgr.shape) == 3 else frame_bgr
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._ref_frame is not None:
            # Frame differencing terhadap foto kalibrasi
            ref_resized = cv2.resize(self._ref_frame, (gray.shape[1], gray.shape[0]))
            diff = cv2.absdiff(gray, ref_resized)
            _, fg = cv2.threshold(diff, FRAME_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
        else:
            # MOG2 (butuh beberapa frame untuk warm-up; untuk foto tunggal hasilnya nol)
            fg = self._mog2.apply(frame_bgr)
            # MOG2 keluarkan 127 untuk shadow, 255 untuk foreground
            _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)

        return fg

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — EDGE DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _edge_mask(self, frame_bgr: np.ndarray, sensitivity: str = "medium") -> np.ndarray:
        """Deteksi tepi dengan Canny; sensitivitas dikontrol via profile."""
        params = {
            "low": (80, 200),
            "medium": (50, 150),
            "high": (30, 100),
        }
        t_low, t_high = params.get(sensitivity, params["medium"])

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if len(frame_bgr.shape) == 3 else frame_bgr
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, t_low, t_high)

        # Dilasi ringan agar garis tepi sedikit lebih tebal
        edges = cv2.dilate(edges, self._kernel, iterations=1)
        return edges

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — COMBINE & CLEANUP
    # ─────────────────────────────────────────────────────────────────────────

    def _combine_masks(
        self,
        hsv_mask: Optional[np.ndarray],
        fg_mask: np.ndarray,
        edge_mask: np.ndarray,
    ) -> np.ndarray:
        """
        Gabungkan layer mask dengan bobot:
        - HSV (kalau ada): anchor utama lokasi papan
        - Edge: perkuat batas
        - FG: tambahkan kalau ada ref_frame
        """
        h, w = fg_mask.shape[:2]

        # Normalisasi ke float
        fg_f   = fg_mask.astype(np.float32) / 255.0
        edge_f = edge_mask.astype(np.float32) / 255.0

        if hsv_mask is not None:
            hsv_f   = hsv_mask.astype(np.float32) / 255.0
            combined = 0.50 * hsv_f + 0.30 * edge_f + 0.20 * fg_f
        else:
            # Mode B&W: edge jadi andalan utama
            combined = 0.60 * edge_f + 0.40 * fg_f

        # Threshold akhir
        _, result = cv2.threshold(
            (combined * 255).astype(np.uint8), 50, 255, cv2.THRESH_BINARY
        )
        return result

    def _morph_cleanup(self, mask: np.ndarray) -> np.ndarray:
        """Closing untuk mengisi lubang, Opening untuk buang noise kecil."""
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel,
                                iterations=MORPH_CLOSE_ITER)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._kernel,
                                iterations=MORPH_OPEN_ITER)
        return mask

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — GAUGE DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_gauge_bbox(
        self, mask: np.ndarray, min_area: int = 800
    ) -> tuple[Optional[tuple], Optional[np.ndarray]]:
        """
        Cari bounding box papan duga dari contour terbesar di mask.

        Returns
        -------
        (bbox, gauge_mask) | (None, None)
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, None

        # Filter berdasarkan luas minimum
        valid = [c for c in contours if cv2.contourArea(c) >= min_area]
        if not valid:
            return None, None

        # Cari contour dengan aspect ratio paling tinggi (papan duga itu vertikal)
        def score(c):
            x, y, w, h = cv2.boundingRect(c)
            area        = cv2.contourArea(c)
            aspect      = h / max(w, 1)   # papan duga: h >> w
            return area * aspect

        best = max(valid, key=score)
        bbox = cv2.boundingRect(best)  # (x, y, w, h)

        # Buat mask dari contour terpilih
        gauge_mask = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(gauge_mask, [best], -1, 255, thickness=cv2.FILLED)

        return bbox, gauge_mask

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — WATERLINE DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_waterline(
        self,
        frame_bgr: np.ndarray,
        gauge_bbox: tuple,
        gauge_mask: np.ndarray,
    ) -> tuple[Optional[int], Optional[np.ndarray], float]:
        """
        Deteksi garis air (waterline) di dalam area papan duga.

        Strategi:
        1. Crop ke bounding box papan duga.
        2. Scan horizontal dari bawah ke atas.
        3. Di setiap baris, hitung skor berdasarkan:
           - Pixel merah/kuning (papan di atas air)
           - Pixel warna air (coklat/hijau muda/abu → HSV water range)
           - Edge strength
        4. Garis air = titik transisi maksimum antara zona air dan zona papan.

        Returns
        -------
        (waterline_y, water_mask, confidence) atau (None, None, 0.0)
        """
        x, y, w, h = gauge_bbox

        # Tambahkan sedikit margin ke bounding box
        margin    = 10
        x1        = max(0, x - margin)
        y1        = max(0, y - margin)
        x2        = min(frame_bgr.shape[1], x + w + margin)
        y2        = min(frame_bgr.shape[0], y + h + margin)
        crop      = frame_bgr[y1:y2, x1:x2]

        if crop.size == 0:
            return None, None, 0.0

        hsv_crop  = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        # ── Buat row score ──────────────────────────────────────────────────
        # Skor per baris: papan_score - water_score
        # Transisi maksimum dari negatif ke positif = garis air

        # Papan duga mask (merah/kuning) dalam crop
        m_red1   = cv2.inRange(hsv_crop,
                               np.array(HSV_RED_LOWER1), np.array(HSV_RED_UPPER1))
        m_red2   = cv2.inRange(hsv_crop,
                               np.array(HSV_RED_LOWER2), np.array(HSV_RED_UPPER2))
        m_yellow = cv2.inRange(hsv_crop,
                               np.array(HSV_YELLOW_LOWER), np.array(HSV_YELLOW_UPPER))
        m_gauge  = cv2.bitwise_or(cv2.bitwise_or(m_red1, m_red2), m_yellow)

        # Water mask — warna air sungai (coklat keruh, hijau alga, abu-abu)
        # Rentang HSV untuk air keruh coklat: S rendah-sedang, V sedang
        m_water_brown = cv2.inRange(hsv_crop,
                                    np.array((10, 20, 60)), np.array((40, 180, 200)))
        m_water_gray  = cv2.inRange(hsv_crop,
                                    np.array((0, 0, 50)),  np.array((179, 50, 200)))
        m_water       = cv2.bitwise_or(m_water_brown, m_water_gray)

        # Edge strength per baris
        edges_crop = cv2.Canny(gray_crop, 30, 100)

        # Row-wise skor
        rows         = crop.shape[0]
        gauge_score  = np.sum(m_gauge,  axis=1).astype(float)   # lebih tinggi = lebih banyak papan
        water_score  = np.sum(m_water,  axis=1).astype(float)
        edge_score   = np.sum(edges_crop, axis=1).astype(float)

        # Normalkan
        def safe_norm(arr):
            mx = arr.max()
            return arr / mx if mx > 0 else arr

        gauge_n = safe_norm(gauge_score)
        water_n = safe_norm(water_score)
        edge_n  = safe_norm(edge_score)

        # Differential: positif di zona papan, negatif di zona air
        diff = gauge_n - water_n + 0.3 * edge_n

        # Cari garis transisi (dari bawah ke atas): baris paling bawah
        # di mana diff mulai positif secara konsisten
        waterline_y_crop = None
        window           = 5    # smoothing window
        smoothed         = np.convolve(diff, np.ones(window) / window, mode="same")

        # Scan dari bawah: cari perubahan negatif→positif pertama
        for row_idx in range(rows - 1, window, -1):
            if smoothed[row_idx] < 0.0 and smoothed[row_idx - window] > 0.0:
                waterline_y_crop = row_idx
                break

        # Fallback: kalau scan gagal, pakai titik tertinggi edge di crop
        if waterline_y_crop is None:
            top_edge_rows = np.where(edge_score > edge_score.max() * 0.5)[0]
            if len(top_edge_rows) > 0:
                waterline_y_crop = int(np.median(top_edge_rows))

        if waterline_y_crop is None:
            return None, None, 0.0

        # Translate ke koordinat frame_roi
        waterline_y_roi = y1 + waterline_y_crop

        # Buat water_mask (area di bawah garis air dalam frame_roi)
        water_mask_full = np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
        water_mask_full[waterline_y_roi:, :] = 255

        # Confidence heuristik
        gauge_pixels = float(np.sum(m_gauge > 0))
        total_pixels = float(crop.shape[0] * crop.shape[1])
        conf = min(1.0, gauge_pixels / max(total_pixels * 0.01, 1))

        return waterline_y_roi, water_mask_full, conf

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — UTILITIES
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_roi(self, frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
        """
        Crop frame ke ROI.

        Returns
        -------
        (cropped_frame, (offset_x, offset_y))
        """
        if self.roi is None:
            return frame, (0, 0)

        h, w   = frame.shape[:2]
        x1     = int(self.roi["x_min"] * w)
        x2     = int(self.roi["x_max"] * w)
        y1     = int(self.roi["y_min"] * h)
        y2     = int(self.roi["y_max"] * h)
        return frame[y1:y2, x1:x2], (x1, y1)

    @staticmethod
    def _is_color_frame(frame: np.ndarray) -> bool:
        """
        Deteksi apakah frame berwarna (RGB) atau monokrom (IR/B&W).

        Cara: bandingkan std dev channel B dan R. Kalau hampir sama → grayscale.
        """
        if len(frame.shape) < 3 or frame.shape[2] < 3:
            return False
        b_std = float(np.std(frame[:, :, 0]))
        g_std = float(np.std(frame[:, :, 1]))
        r_std = float(np.std(frame[:, :, 2]))
        # Kalau ketiga channel sangat mirip → frame monokrom yang di-cast ke BGR
        channel_diff = abs(b_std - r_std) + abs(b_std - g_std)
        return channel_diff > 5.0

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE — SAM (OPSIONAL)
    # ─────────────────────────────────────────────────────────────────────────

    def _init_sam(self) -> None:
        """Import dan inisialisasi SAM. Gagal secara halus kalau tidak tersedia."""
        try:
            from segment_anything import sam_model_registry, SamPredictor  # type: ignore
            model_type      = SAM_CONFIG["model_type"]
            checkpoint      = SAM_CONFIG["checkpoint_path"]
            device          = SAM_CONFIG["device"]
            sam_model       = sam_model_registry[model_type](checkpoint=checkpoint)
            sam_model.to(device=device)
            self._sam       = SamPredictor(sam_model)
            logger.info(f"[Segmentor] SAM loaded: {model_type} on {device}")
        except ImportError:
            logger.warning("[Segmentor] 'segment_anything' tidak ter-install. SAM dinonaktifkan.")
            self._sam   = None
            self.use_sam = False
        except Exception as e:
            logger.error(f"[Segmentor] Gagal load SAM: {e}. Fallback ke rule-based.")
            self._sam   = None
            self.use_sam = False

    def _run_sam(
        self,
        frame_bgr: np.ndarray,
        waterline_y_est: int,
        gauge_bbox: tuple,
    ) -> Optional[tuple[int, np.ndarray, float]]:
        """
        Jalankan SAM dengan prompt point di estimasi garis air.

        Prompt strategy (adaptive, mengikuti paper EdgeSAM 2025):
        - Point di tengah horizontal papan duga, tepat di atas garis air estimasi
          (zona papan kering) → label POSITIVE
        - Point di tengah horizontal, tepat di bawah garis air estimasi
          (zona air) → label NEGATIVE

        Returns
        -------
        (waterline_y, water_mask, confidence) atau None kalau gagal
        """
        if self._sam is None:
            return None

        try:
            import torch  # type: ignore

            x, y, w, h = gauge_bbox
            cx         = x + w // 2

            # Prompt points: atas garis air (dry) dan bawah (wet)
            point_dry  = [cx, waterline_y_est - 20]
            point_wet  = [cx, waterline_y_est + 20]
            points     = np.array([point_dry, point_wet])
            labels     = np.array([1, 0])   # 1=positive (papan), 0=negative (air)

            # Set image
            frame_rgb  = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            self._sam.set_image(frame_rgb)

            masks, scores, _ = self._sam.predict(
                point_coords=points,
                point_labels=labels,
                multimask_output=True,
            )

            # Ambil mask dengan score tertinggi
            best_idx   = int(np.argmax(scores))
            gauge_mask = masks[best_idx].astype(np.uint8) * 255
            confidence = float(scores[best_idx])

            # Waterline = batas bawah mask papan (baris terbawah yang masih putih)
            rows_with_gauge = np.where(gauge_mask.any(axis=1))[0]
            if len(rows_with_gauge) == 0:
                return None

            waterline_y     = int(rows_with_gauge.max())
            water_mask      = np.zeros_like(gauge_mask)
            water_mask[waterline_y:, :] = 255

            return waterline_y, water_mask, confidence

        except Exception as e:
            logger.error(f"[Segmentor] SAM error: {e}")
            return None
