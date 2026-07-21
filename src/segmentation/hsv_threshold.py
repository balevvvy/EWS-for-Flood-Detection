import cv2
import numpy as np

class HSVThresholdSegmenter:
    def __init__(self, lower_hsv=None, upper_hsv=None):
        """
        Segmentasi air berdasarkan rentang warna HSV.
        """
        # Nilai default (bisa disesuaikan nanti dengan kondisi air sungai/kanal nyata)
        self.lower_hsv = lower_hsv if lower_hsv is not None else np.array([0, 0, 0])
        self.upper_hsv = upper_hsv if upper_hsv is not None else np.array([179, 255, 100]) # Contoh: mendeteksi area gelap/keruh
        
    def get_mask(self, frame):
        """
        Memproses frame dan mengembalikan binary mask (0 atau 255).
        """
        if frame is None:
            return None
            
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.lower_hsv, self.upper_hsv)
        
        # Cleaning noise dengan morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        
        return mask
