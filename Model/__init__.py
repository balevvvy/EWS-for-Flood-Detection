"""
__init__.py — Public API untuk package Model (EWS Water Level Detection).

Import ringkas dari luar:
    from Model.water_level_detector import WaterLevelDetector
    from Model.calibration import GaugeCalibration
    from Model.alert import AlertEngine, AlertStatus
    from Model.segmentation import GaugeSegmentor, SegmentationResult
"""

from .alert import AlertEngine, AlertStatus, callback_log, callback_print_json
from .calibration import GaugeCalibration, CalibrationError
from .segmentation import GaugeSegmentor, SegmentationResult
from .water_level_detector import WaterLevelDetector, WaterLevelReading

__version__ = "0.1.0"
__all__ = [
    # Pipeline utama
    "WaterLevelDetector",
    "WaterLevelReading",
    # Sub-modul
    "GaugeSegmentor",
    "SegmentationResult",
    "GaugeCalibration",
    "CalibrationError",
    "AlertEngine",
    "AlertStatus",
    # Callbacks bawaan
    "callback_log",
    "callback_print_json",
]
