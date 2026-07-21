import cv2
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FrameGrabber")

# ==================== KONFIGURASI ====================
# Sama persis dengan ptz_control.py — satu sumber kebenaran
IP = "10.52.9.101"
USERNAME = "admin"
PASSWORD = "Admin123."      # ganti sesuai password kamera
CHANNEL = 1                 # RTSP Dahua pakai channel=1 (berbeda dari PTZ CGI yang pakai 0)

# Dahua RTSP URL format:
# rtsp://user:pwd@ip:554/cam/realmonitor?channel=1&subtype=0
# subtype=0 = main stream, subtype=1 = sub stream (resolusi lebih kecil, bandwidth lebih ringan)
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{IP}:554/cam/realmonitor?channel={CHANNEL}&subtype=0"


class StreamGrabber:
    def __init__(self, rtsp_url=None):
        """
        Inisialisasi Stream Grabber untuk mengambil frame dari kamera Dahua via RTSP.
        """
        self.stream_url = rtsp_url if rtsp_url else RTSP_URL
        self.cap = None

    def connect(self):
        """Mencoba terhubung ke stream RTSP."""
        if self.cap is not None:
            self.cap.release()
            
        logger.info(f"Connecting to RTSP stream...")
        # Optional: reduce buffer size for lower latency if needed
        # os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|analyzeduration;100000|probesize;100000"
        
        self.cap = cv2.VideoCapture(self.stream_url)
        if not self.cap.isOpened():
            logger.error("Gagal membuka RTSP stream.")
            return False
        logger.info("RTSP stream berhasil dibuka.")
        return True

    def get_frame(self, max_retries=5, retry_delay=2.0):
        """
        Membaca frame tunggal dari stream.
        Jika stream putus, otomatis mencoba reconnect hingga max_retries.
        """
        if self.cap is None or not self.cap.isOpened():
            if not self.connect():
                return None

        retries = 0
        while retries < max_retries:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return frame
            
            logger.warning(f"Frame kosong/gagal dibaca. Reconnecting (percobaan {retries+1}/{max_retries})...")
            time.sleep(retry_delay)
            self.connect()
            retries += 1
            
        logger.error("Gagal mengambil frame setelah beberapa kali percobaan.")
        return None

    def release(self):
        """Melepaskan resource kamera."""
        if self.cap:
            self.cap.release()
            self.cap = None
            logger.info("Kamera di-release.")

if __name__ == "__main__":
    # Test script sederhana
    grabber = StreamGrabber()
    frame = grabber.get_frame()
    if frame is not None:
        print(f"Berhasil mengambil frame dengan ukuran: {frame.shape}")
        # cv2.imwrite("test_grab.jpg", frame)
    else:
        print("Gagal mengambil frame.")
