import os
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PixelToStatus")

class PixelToStatusMapper:
    def __init__(self, config_path=None):
        """
        Mapper dari koordinat piksel Y (ketinggian air teratas) ke Status Siaga.

        Layout fisik papan duga (dari atas ke bawah):
            MERAH  (Siaga/Darurat) — y_siaga   — Y piksel KECIL (atas gambar)
            KUNING (Waspada)       — y_waspada  — Y piksel SEDANG
            AIR    (Normal)                     — Y piksel BESAR (bawah gambar)

        Ketika air NAIK secara fisik, koordinat Y piksel permukaan air MENURUN.
        """
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, "config", "cv_thresholds.json")
            
        self.config_path = config_path
        self.y_waspada = None
        self.y_siaga = None
        self.load_config()
        
    def load_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                self.y_waspada = data.get("y_waspada")
                self.y_siaga = data.get("y_siaga")
                logger.info(f"Loaded threshold: Waspada (Kuning)={self.y_waspada}, Siaga (Merah)={self.y_siaga}")
            else:
                logger.warning(f"File config {self.config_path} tidak ditemukan. Gunakan skrip kalibrasi untuk menetapkan nilai.")
        except Exception as e:
            logger.error(f"Gagal memuat config kalibrasi: {e}")

    def save_config(self, y_waspada, y_siaga):
        self.y_waspada = y_waspada
        self.y_siaga = y_siaga
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump({"y_waspada": y_waspada, "y_siaga": y_siaga}, f, indent=4)
            logger.info("Config batas siaga berhasil disimpan.")
        except Exception as e:
            logger.error(f"Gagal menyimpan config kalibrasi: {e}")

    def get_status(self, water_level_y):
        """
        Menentukan status berdasarkan batas Y piksel dari hasil segmentasi air.
        
        Logika (ingat, koordinat Y membesar ke bawah):
        - Jika water_level_y <= y_siaga (posisi air mencapai atau melampaui batas merah ke atas): SIAGA
        - Jika water_level_y <= y_waspada (posisi air mencapai kuning tapi belum sampai merah): WASPADA
        - Jika water_level_y > y_waspada (air berada di bawah batas kuning): NORMAL
        """
        if self.y_waspada is None or self.y_siaga is None:
            return "UNKNOWN (Belum Dikalibrasi)"
            
        if water_level_y <= self.y_siaga:
            return "SIAGA"
        elif water_level_y <= self.y_waspada:
            return "WASPADA"
        else:
            return "NORMAL"
