import os
import sys
import time
import logging
import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.camera.config_loader import load_camera_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FrameGrabber")

_cam_config = load_camera_config()
IP = _cam_config["ip"]
USERNAME = _cam_config["username"]
PASSWORD = _cam_config["password"]
CHANNEL = 1

RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{IP}:554/cam/realmonitor?channel={CHANNEL}&subtype=0"


class StreamGrabber:
    def __init__(self, rtsp_url=None):
        self.stream_url = rtsp_url if rtsp_url else RTSP_URL
        self.cap = None

    def connect(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(self.stream_url)
        if not self.cap.isOpened():
            logger.error("Gagal membuka RTSP stream.")
            return False
        return True

    def get_frame(self, max_retries=5, retry_delay=2.0):
        if self.cap is None or not self.cap.isOpened():
            if not self.connect():
                return None

        retries = 0
        while retries < max_retries:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return frame

            time.sleep(retry_delay)
            self.connect()
            retries += 1

        return None

    def release(self):
        if self.cap:
            self.cap.release()
            self.cap = None


if __name__ == "__main__":
    grabber = StreamGrabber()
    frame = grabber.get_frame()
    if frame is not None:
        print(f"Frame OK: {frame.shape}")
    else:
        print("Frame GAGAL")
