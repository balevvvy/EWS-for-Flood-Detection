"""
alert.py — Logic status siaga dan skema notifikasi EWS.

INPUT : angka tinggi muka air (cm)
OUTPUT: status level (NORMAL/WASPADA/SIAGA/AWAS) + payload alert

Seluruh logic ini murni matematika, tidak butuh kamera / OpenCV.
Bisa di-unit-test sekarang dengan angka dummy.

Cara pakai:
    from alert import AlertEngine

    engine = AlertEngine()
    status = engine.evaluate(water_cm=230)
    print(status)
    # AlertStatus(level='SIAGA', cm=230, label='Siaga', ...)

    # Cek apakah perlu kirim notifikasi (hysteresis: jangan spam kalau nilai
    # naik-turun di sekitar threshold)
    if engine.should_notify(status):
        engine.send(status)
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from config import ALERT_LEVELS, ALERT_ORDER

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AlertStatus:
    """Hasil evaluasi satu pembacaan tinggi muka air."""
    level      : str                  # "NORMAL" | "WASPADA" | "SIAGA" | "AWAS"
    cm         : float                # tinggi muka air dalam cm
    label      : str                  # label yang ramah user
    color_rgb  : tuple                # (R, G, B) untuk visualisasi
    threshold  : float                # batas maksimum level ini (cm)
    timestamp  : datetime = field(default_factory=datetime.now)
    confidence : float    = 1.0       # dari SegmentationResult.confidence
    source     : str      = "cv"      # "cv" | "manual" | "dummy"

    def __str__(self) -> str:
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"[{ts}] {self.label.upper():8s} | "
            f"{self.cm:.1f} cm | conf={self.confidence:.2f} | src={self.source}"
        )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level":     self.level,
            "label":     self.label,
            "cm":        self.cm,
            "confidence":self.confidence,
            "source":    self.source,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ALERT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class AlertEngine:
    """
    Evaluasi tinggi muka air dan tentukan status siaga.

    Parameters
    ----------
    hysteresis_cm : float
        Zona dead-band di sekitar threshold (cm).
        Mencegah notifikasi berulang kalau nilai naik-turun tepat di batas.
        Default: 5 cm.
    cooldown_sec : float
        Jeda minimum antar notifikasi untuk level yang SAMA (detik).
        Default: 300 detik (5 menit).
    notify_callbacks : list[Callable]
        Daftar fungsi yang dipanggil saat status berubah atau eskalasi.
        Signature: callback(status: AlertStatus) -> None
    """

    def __init__(
        self,
        hysteresis_cm : float = 5.0,
        cooldown_sec  : float = 300.0,
        notify_callbacks: Optional[list[Callable]] = None,
    ):
        self.hysteresis_cm    = hysteresis_cm
        self.cooldown_sec     = cooldown_sec
        self._callbacks       = notify_callbacks or []

        # State tracking
        self._last_level      : Optional[str]   = None
        self._last_notify_ts  : dict[str, float]= {}   # level → last notify time
        self._history         : list[AlertStatus] = []

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        water_cm   : float,
        confidence : float = 1.0,
        source     : str   = "cv",
    ) -> AlertStatus:
        """
        Tentukan status siaga dari nilai ketinggian air.

        Parameters
        ----------
        water_cm   : float  — tinggi muka air (cm)
        confidence : float  — skor keyakinan segmentasi (0.0–1.0)
        source     : str    — "cv" | "manual" | "dummy"

        Returns
        -------
        AlertStatus
        """
        level_key = self._classify(water_cm)
        cfg       = ALERT_LEVELS[level_key]

        status = AlertStatus(
            level      = level_key,
            cm         = water_cm,
            label      = cfg["label"],
            color_rgb  = cfg["color_rgb"],
            threshold  = cfg["max"],
            confidence = confidence,
            source     = source,
        )

        self._history.append(status)
        logger.info(str(status))

        # Auto-notify kalau perlu
        if self.should_notify(status):
            self._trigger(status)

        return status

    def should_notify(self, status: AlertStatus) -> bool:
        """
        Tentukan apakah notifikasi perlu dikirim.

        Aturan:
        1. Eskalasi level (lebih tinggi dari sebelumnya) → selalu notify.
        2. Deeskalasi → notify sekali (informasional).
        3. Level sama → cek cooldown.
        4. Confidence < 0.3 → tahan notifikasi (data tidak yakin).
        """
        if status.confidence < 0.3:
            logger.warning(
                f"[Alert] Confidence rendah ({status.confidence:.2f}), "
                "notifikasi ditahan."
            )
            return False

        level      = status.level
        prev_level = self._last_level

        # Eskalasi → langsung notify
        if prev_level and self._level_index(level) > self._level_index(prev_level):
            return True

        # Deeskalasi → notify (tapi dengan cooldown lebih panjang: 2x)
        if prev_level and self._level_index(level) < self._level_index(prev_level):
            last_ts = self._last_notify_ts.get(level, 0.0)
            return (time.time() - last_ts) >= (self.cooldown_sec * 2)

        # Level sama → cooldown biasa
        last_ts = self._last_notify_ts.get(level, 0.0)
        return (time.time() - last_ts) >= self.cooldown_sec

    def add_callback(self, fn: Callable) -> None:
        """Daftarkan callback notifikasi (email, Telegram, webhook, dll)."""
        self._callbacks.append(fn)

    def history(self, n: int = 10) -> list[AlertStatus]:
        """Kembalikan n pembacaan terakhir."""
        return self._history[-n:]

    def summary(self) -> dict:
        """Ringkasan state engine saat ini."""
        return {
            "last_level"     : self._last_level,
            "total_readings" : len(self._history),
            "callbacks"      : len(self._callbacks),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────────────────────────────────────

    def _classify(self, cm: float) -> str:
        """Klasifikasikan nilai cm ke level siaga dengan hysteresis."""
        # Tanpa hysteresis dulu — cari level pertama yang max-nya >= cm
        for level in ALERT_ORDER:
            if cm <= ALERT_LEVELS[level]["max"]:
                # Hysteresis: kalau sedang di level lebih tinggi dan cm baru
                # masih dalam zona dead-band, pertahankan level lama
                if (
                    self._last_level is not None
                    and self._level_index(self._last_level) > self._level_index(level)
                ):
                    higher_max = ALERT_LEVELS[self._last_level]["max"]
                    if cm >= (higher_max - self.hysteresis_cm):
                        return self._last_level   # tetap di level lama
                return level

        return ALERT_ORDER[-1]   # fallback: AWAS

    def _trigger(self, status: AlertStatus) -> None:
        """Panggil semua callback dan update state."""
        self._last_level                      = status.level
        self._last_notify_ts[status.level]    = time.time()

        for cb in self._callbacks:
            try:
                cb(status)
            except Exception as e:
                logger.error(f"[Alert] Callback error: {e}")

    @staticmethod
    def _level_index(level: str) -> int:
        return ALERT_ORDER.index(level) if level in ALERT_ORDER else -1


# ─────────────────────────────────────────────────────────────────────────────
# BUILT-IN CALLBACK EXAMPLES
# ─────────────────────────────────────────────────────────────────────────────

def callback_log(status: AlertStatus) -> None:
    """Callback sederhana: cetak ke log (selalu aktif sebagai baseline)."""
    border = "!" * 60 if status.level == "AWAS" else "-" * 50
    print(f"\n{border}")
    print(f"  ALERT: {status.label.upper()}")
    print(f"  Tinggi Air : {status.cm:.1f} cm")
    print(f"  Waktu      : {status.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Confidence : {status.confidence:.2f}")
    print(border + "\n")


def callback_print_json(status: AlertStatus) -> None:
    """Callback: print payload JSON (siap dikirim ke webhook/API)."""
    import json
    print(json.dumps(status.to_dict(), indent=2, ensure_ascii=False))


# ─────────────────────────────────────────────────────────────────────────────
# QUICK SELF-TEST (python alert.py)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    print("=" * 60)
    print("  SELF-TEST: AlertEngine")
    print("=" * 60)

    engine = AlertEngine(
        hysteresis_cm = 5.0,
        cooldown_sec  = 0,   # matikan cooldown untuk test
        notify_callbacks = [callback_log],
    )

    # Simulasi serangkaian pembacaan (naik → puncak → turun)
    test_readings = [
        (100, "Normal"),
        (140, "Mendekati batas Normal"),
        (155, "Masuk Waspada"),
        (195, "Mendekati batas Waspada"),
        (210, "Masuk Siaga"),
        (255, "Masuk AWAS"),
        (270, "AWAS tinggi"),
        (240, "Turun ke Siaga"),
        (180, "Turun ke Waspada"),
        (120, "Kembali Normal"),
    ]

    print(f"\n{'CM':>6}  {'Exp.Level':15}  {'Result':15}  {'OK?'}")
    print("-" * 55)

    for cm, desc in test_readings:
        status = engine.evaluate(water_cm=cm, confidence=0.9, source="dummy")
        ok     = "OK" if status.level != "NORMAL" or cm <= 150 else "?"
        print(f"{cm:6.1f}  {desc:15}  {status.level:15}  {ok}")

    print(f"\nHistory ({len(engine.history(100))} pembacaan):")
    for s in engine.history(100):
        print(f"  {s}")

    print("\n[OK] Self-test selesai.")
