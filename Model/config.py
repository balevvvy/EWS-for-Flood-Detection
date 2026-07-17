"""
config.py — Konfigurasi terpusat untuk modul segmentasi + kalibrasi EWS.

Semua konstanta (warna HSV papan duga, batas siaga, profile siang/malam)
disimpan di sini agar modul lain tidak hardcode nilai.
"""

import os

# ─────────────────────────────────────────────────────────────────────────────
# PATH
# ─────────────────────────────────────────────────────────────────────────────
MODEL_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(MODEL_DIR)

# File JSON tempat konfigurasi kalibrasi per-preset disimpan
CALIBRATION_CONFIG_PATH = os.path.join(MODEL_DIR, "calibration_presets.json")

# ─────────────────────────────────────────────────────────────────────────────
# HSV COLOR THRESHOLDS — papan duga merah & kuning
# Diukur dari foto referensi; bisa di-tune lewat test_with_photo.py
#
# Format: (H_min, S_min, V_min), (H_max, S_max, V_max)
# OpenCV HSV range: H 0-179, S 0-255, V 0-255
# ─────────────────────────────────────────────────────────────────────────────

# Merah (hue wraps, jadi pakai dua range)
HSV_RED_LOWER1 = (  0, 120,  60)
HSV_RED_UPPER1 = ( 10, 255, 255)
HSV_RED_LOWER2 = (160, 120,  60)
HSV_RED_UPPER2 = (179, 255, 255)

# Kuning
HSV_YELLOW_LOWER = ( 18, 100,  80)
HSV_YELLOW_UPPER = ( 38, 255, 255)

# Hitam (strip pemisah di papan duga)
HSV_BLACK_LOWER = (  0,   0,   0)
HSV_BLACK_UPPER = (179,  80,  60)

# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND SUBTRACTION
# ─────────────────────────────────────────────────────────────────────────────
MOG2_HISTORY          = 500    # jumlah frame untuk membangun model BG
MOG2_VAR_THRESHOLD    = 40     # sensitivitas deteksi perubahan
MOG2_DETECT_SHADOWS   = False  # bayangan diabaikan (bisa noise)

# Frame differencing — threshold pixel-level (0-255)
FRAME_DIFF_THRESHOLD  = 25

# ─────────────────────────────────────────────────────────────────────────────
# MORPHOLOGICAL OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
MORPH_KERNEL_SIZE     = (5, 5)   # kernel erosi/dilasi
MORPH_CLOSE_ITER      = 3        # iterasi closing untuk mengisi lubang kecil
MORPH_OPEN_ITER       = 2        # iterasi opening untuk buang noise kecil

# ─────────────────────────────────────────────────────────────────────────────
# GAUGE ROI (Region of Interest) — koordinat relatif [0.0-1.0]
# Setiap preset PTZ bisa override nilai ini di PRESET_CONFIGS di bawah.
# Default: pakai seluruh frame
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_ROI = {
    "x_min": 0.0,  # fraksi lebar frame
    "x_max": 1.0,
    "y_min": 0.0,  # fraksi tinggi frame
    "y_max": 1.0,
}

# ─────────────────────────────────────────────────────────────────────────────
# SIAGA ALERT THRESHOLDS (dalam cm)
# Sesuaikan dengan karakteristik lokasi / peraturan BMKG
# ─────────────────────────────────────────────────────────────────────────────
ALERT_LEVELS = {
    "NORMAL":  {"max": 150, "color_rgb": (0, 200, 80),   "label": "Normal"},
    "WASPADA": {"max": 200, "color_rgb": (255, 200, 0),  "label": "Waspada"},
    "SIAGA":   {"max": 250, "color_rgb": (255, 120, 0),  "label": "Siaga"},
    "AWAS":    {"max": 9999,"color_rgb": (220, 30,  30), "label": "AWAS!"},
}

# Urutan evaluasi (dari yang paling rendah ke tinggi)
ALERT_ORDER = ["NORMAL", "WASPADA", "SIAGA", "AWAS"]

# ─────────────────────────────────────────────────────────────────────────────
# CAMERA PROFILE SWITCHING
# Kamera DH-SD5A225XA-HNR: 0.005 lux warna; 0.0005 lux B&W; 0 lux IR
# ─────────────────────────────────────────────────────────────────────────────
CAMERA_PROFILES = {
    "day": {
        "description": "Mode siang / warna — HSV thresholding aktif penuh",
        "use_hsv": True,
        "use_background_subtraction": True,
        "edge_sensitivity": "medium",
        "min_contour_area": 800,
    },
    "night_color": {
        "description": "Mode malam dengan Starlight (warna, cahaya rendah)",
        "use_hsv": True,
        "use_background_subtraction": True,
        "edge_sensitivity": "high",
        "min_contour_area": 600,
    },
    "night_bw": {
        "description": "Mode IR / B&W — HSV dinonaktifkan, andalkan edge + BG subtraction",
        "use_hsv": False,
        "use_background_subtraction": True,
        "edge_sensitivity": "high",
        "min_contour_area": 600,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# PRESET PTZ CONFIGS
# ─────────────────────────────────────────────────────────────────────────────
PRESET_CONFIGS = {
    "papan_duga_utama": {
        "description": "Preset papan duga lokasi utama (kalibrasi awal dari foto referensi)",
        "ptz_ref_file": os.path.join(PROJECT_DIR, "koordinat_threshold.json"),
        "roi": {
            "x_min": 0.30,
            "x_max": 0.70,
            "y_min": 0.10,
            "y_max": 0.90,
        },
        "settle_delay_sec": 3.0,
        "profile_default": "day",
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# SAM / EdgeSAM — opsional, aktifkan kalau model tersedia di server
# ─────────────────────────────────────────────────────────────────────────────
SAM_CONFIG = {
    "enabled": False,
    "model_type": "vit_b",              # "vit_h" | "vit_l" | "vit_b" | "edge_sam"
    "checkpoint_path": os.path.join(MODEL_DIR, "weights", "sam_vit_b.pth"),
    "device": "cpu",                    # "cuda" kalau server punya GPU
    "prompt_strategy": "waterline",
    "fallback_to_rulebased": True,
    "timeout_sec": 30,
}
