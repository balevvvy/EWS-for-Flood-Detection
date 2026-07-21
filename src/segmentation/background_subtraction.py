import cv2
import numpy as np

class BackgroundSubtractionSegmenter:
    def __init__(self, history=500, varThreshold=16, detectShadows=True):
        """
        Segmentasi air berdasarkan pergerakan aliran menggunakan MOG2.
        Tembok dan papan duga akan menjadi background statis,
        sementara riak/aliran air menjadi foreground.
        """
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history,
            varThreshold=varThreshold,
            detectShadows=detectShadows
        )
        
    def get_mask(self, frame, learning_rate=-1):
        """
        Memproses frame dan mengembalikan binary mask foreground.
        """
        if frame is None:
            return None
            
        fg_mask = self.bg_subtractor.apply(frame, learningRate=learning_rate)
        
        # MOG2 menghasilkan bayangan sebagai nilai abu-abu (127). 
        # Kita thresholding ulang agar mask benar-benar binary (0 dan 255).
        _, fg_mask = cv2.threshold(fg_mask, 254, 255, cv2.THRESH_BINARY)
        
        # Membersihkan noise titik-titik kecil
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        
        return fg_mask
