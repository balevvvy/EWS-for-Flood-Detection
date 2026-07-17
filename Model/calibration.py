"""
calibration.py — Modul kalibrasi piksel → sentimeter untuk papan duga EWS.

KONSEP:
    Papan duga bersifat linear secara fisik (tiap cm = jarak piksel tetap di sumbu Y).
    Cukup dua titik referensi (misal marka "300" dan "200") untuk membangun fungsi
    linear piksel ↔ cm.

    y_pixel  →  cm = a * y_pixel + b
    (fungsi inverse juga tersedia: cm → y_pixel)

PENGGUNAAN:
    cal = GaugeCalibration(preset_name="papan_duga_utama")
    # Tandai 2 titik dari foto (bisa lewat interactive picker di test_with_photo.py)
    cal.set_reference_point(mark_cm=300, y_pixel=145)
    cal.set_reference_point(mark_cm=200, y_pixel=412)
    cal.save()

    # Saat inferensi
    water_cm = cal.pixel_to_cm(y_pixel=380)
    print(f"Tinggi muka air: {water_cm:.1f} cm")

CATATAN:
    - Koordinat piksel Y bertambah KE BAWAH (konvensi OpenCV).
    - Marka yang lebih TINGGI di dunia nyata (cm besar) akan berada di Y LEBIH KECIL
      di gambar (posisi lebih atas).
    - Minimal 2 titik; kalau lebih dari 2, difit dengan numpy.polyfit (least-squares).
"""

import json
import os
import logging
from typing import Optional

import numpy as np

from config import CALIBRATION_CONFIG_PATH

logger = logging.getLogger(__name__)


class CalibrationError(Exception):
    """Raised kalau kalibrasi belum siap atau data tidak valid."""
    pass


class GaugeCalibration:
    """
    Menyimpan dan menggunakan kalibrasi linear piksel ↔ cm untuk satu preset PTZ.

    Attributes
    ----------
    preset_name : str
        Nama preset (key di PRESET_CONFIGS di config.py).
    _ref_points : list[dict]
        List titik referensi: [{"mark_cm": float, "y_pixel": int}, ...]
    _coeff : tuple[float, float] | None
        (slope a, intercept b) dari regresi linear. None sebelum fit.
    """

    MIN_POINTS_REQUIRED = 2

    def __init__(self, preset_name: str = "papan_duga_utama"):
        self.preset_name    = preset_name
        self._ref_points: list[dict] = []
        self._coeff: Optional[tuple[float, float]] = None

        # Coba load konfigurasi yang sudah ada
        self._try_load()

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def set_reference_point(self, mark_cm: float, y_pixel: int) -> None:
        """
        Tambahkan atau update satu titik referensi kalibrasi.

        Parameters
        ----------
        mark_cm : float
            Nilai marka di papan duga dalam sentimeter (e.g., 300, 200).
        y_pixel : int
            Koordinat piksel Y pada gambar yang bersesuaian dengan marka tsb.
        """
        # Hapus titik lama dengan mark_cm yang sama (update)
        self._ref_points = [p for p in self._ref_points if p["mark_cm"] != mark_cm]
        self._ref_points.append({"mark_cm": float(mark_cm), "y_pixel": int(y_pixel)})
        self._ref_points.sort(key=lambda p: p["mark_cm"])
        self._coeff = None  # invalidate cached fit
        logger.info(f"[Calibration] Set ref point: {mark_cm} cm -> y_pixel={y_pixel}")

    def fit(self) -> tuple[float, float]:
        """
        Hitung koefisien regresi linear dari titik-titik referensi.

        Returns
        -------
        (slope, intercept) : tuple[float, float]
            cm = slope * y_pixel + intercept
        """
        if len(self._ref_points) < self.MIN_POINTS_REQUIRED:
            raise CalibrationError(
                f"Butuh minimal {self.MIN_POINTS_REQUIRED} titik referensi, "
                f"sekarang hanya ada {len(self._ref_points)}."
            )

        y_pixels = np.array([p["y_pixel"] for p in self._ref_points], dtype=float)
        cm_vals  = np.array([p["mark_cm"] for p in self._ref_points], dtype=float)

        # polyfit degree=1 → least-squares linear fit
        slope, intercept = np.polyfit(y_pixels, cm_vals, deg=1)
        self._coeff = (float(slope), float(intercept))

        # Hitung R² untuk validasi kualitas fit
        cm_pred = slope * y_pixels + intercept
        ss_res  = np.sum((cm_vals - cm_pred) ** 2)
        ss_tot  = np.sum((cm_vals - cm_vals.mean()) ** 2)
        r2      = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0

        logger.info(
            f"[Calibration] Fit: cm = {slope:.6f} * y_pixel + {intercept:.4f}  |  R2={r2:.4f}"
        )
        return self._coeff

    def pixel_to_cm(self, y_pixel: float) -> float:
        """
        Konversi koordinat piksel Y ke nilai tinggi muka air (cm).

        Parameters
        ----------
        y_pixel : float
            Koordinat piksel Y dari hasil deteksi garis air.

        Returns
        -------
        float
            Estimasi tinggi muka air dalam cm.
        """
        slope, intercept = self._get_coeff()
        return slope * y_pixel + intercept

    def cm_to_pixel(self, cm: float) -> float:
        """
        Konversi nilai cm ke estimasi koordinat piksel Y (berguna untuk visualisasi).

        Parameters
        ----------
        cm : float
            Nilai ketinggian dalam cm.

        Returns
        -------
        float
            Estimasi koordinat piksel Y.
        """
        slope, intercept = self._get_coeff()
        if abs(slope) < 1e-9:
            raise CalibrationError("Slope kalibrasi mendekati nol — data referensi tidak valid.")
        return (cm - intercept) / slope

    def is_ready(self) -> bool:
        """Return True kalau ada minimal 2 titik referensi dan sudah di-fit."""
        return len(self._ref_points) >= self.MIN_POINTS_REQUIRED

    def summary(self) -> dict:
        """Return ringkasan state kalibrasi."""
        info = {
            "preset_name": self.preset_name,
            "ref_points": self._ref_points,
            "is_ready": self.is_ready(),
            "coeff": None,
        }
        if self.is_ready():
            try:
                slope, intercept = self.fit()
                info["coeff"] = {"slope": slope, "intercept": intercept}
                # Tambahkan cm/pixel ratio untuk referensi
                info["cm_per_pixel"] = abs(slope)
            except CalibrationError:
                pass
        return info

    # ─────────────────────────────────────────────────────────────────────────
    # SAVE / LOAD
    # ─────────────────────────────────────────────────────────────────────────

    def save(self) -> None:
        """
        Simpan konfigurasi kalibrasi preset ini ke file JSON bersama.
        File berisi mapping preset_name → data kalibrasi.
        """
        all_configs = self._load_all_configs()
        all_configs[self.preset_name] = {
            "ref_points": self._ref_points,
        }
        with open(CALIBRATION_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(all_configs, f, indent=2, ensure_ascii=False)
        logger.info(f"[Calibration] Saved preset '{self.preset_name}' → {CALIBRATION_CONFIG_PATH}")

    def _try_load(self) -> None:
        """Load konfigurasi preset ini dari file JSON kalau ada."""
        all_configs = self._load_all_configs()
        if self.preset_name in all_configs:
            data = all_configs[self.preset_name]
            self._ref_points = data.get("ref_points", [])
            logger.info(
                f"[Calibration] Loaded preset '{self.preset_name}': "
                f"{len(self._ref_points)} ref point(s)"
            )

    @staticmethod
    def _load_all_configs() -> dict:
        if os.path.exists(CALIBRATION_CONFIG_PATH):
            with open(CALIBRATION_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _get_coeff(self) -> tuple[float, float]:
        """Kembalikan koefisien; fit otomatis kalau belum di-fit."""
        if self._coeff is None:
            self.fit()
        return self._coeff  # type: ignore[return-value]

    # ─────────────────────────────────────────────────────────────────────────
    # CONVENIENCE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_two_points(
        cls,
        preset_name: str,
        mark1_cm: float, y1_pixel: int,
        mark2_cm: float, y2_pixel: int,
        auto_save: bool = True,
    ) -> "GaugeCalibration":
        """
        Shortcut: buat kalibrasi langsung dari dua titik dan simpan.

        Example
        -------
        cal = GaugeCalibration.from_two_points(
            preset_name="papan_duga_utama",
            mark1_cm=300, y1_pixel=145,
            mark2_cm=200, y2_pixel=412,
        )
        print(cal.pixel_to_cm(380))  # → ~ 215 cm
        """
        cal = cls(preset_name=preset_name)
        cal.set_reference_point(mark_cm=mark1_cm, y_pixel=y1_pixel)
        cal.set_reference_point(mark_cm=mark2_cm, y_pixel=y2_pixel)
        cal.fit()
        if auto_save:
            cal.save()
        return cal


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SELF-TEST (jalankan: python calibration.py)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    print("=" * 60)
    print("  SELF-TEST: GaugeCalibration")
    print("=" * 60)

    # Simulasi: marka 300 cm ada di y=145px; marka 200 cm ada di y=412px
    # (Angka ini placeholder — nanti diganti dari hasil klik foto di test_with_photo.py)
    cal = GaugeCalibration.from_two_points(
        preset_name="test_preset",
        mark1_cm=300, y1_pixel=145,
        mark2_cm=200, y2_pixel=412,
        auto_save=False,
    )

    print(f"\nKoefisien: {cal.summary()['coeff']}")
    print(f"cm per pixel: {cal.summary()['cm_per_pixel']:.4f}")

    # Verifikasi round-trip
    test_cases = [
        (145, 300),   # titik kalibrasi sendiri harus tepat
        (412, 200),
        (278, None),  # titik tengah (~250 cm teoritis)
    ]

    print("\nVerifikasi piksel -> cm:")
    for y_px, expected in test_cases:
        result = cal.pixel_to_cm(y_px)
        tag = f"  (expected={expected})" if expected else ""
        print(f"  y={y_px:4d}px -> {result:.2f} cm{tag}")

    print("\nVerifikasi cm -> piksel:")
    for cm_val in [300, 250, 200, 150]:
        y_est = cal.cm_to_pixel(cm_val)
        print(f"  {cm_val} cm -> y approx {y_est:.1f}px")

    print("\n[OK] Self-test selesai.")
