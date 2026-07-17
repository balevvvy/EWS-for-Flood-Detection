import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import cv2

username = "admin"       # ganti sesuai username login kamera
password = "Admin123."  # ganti sesuai password login kamera
ip = "10.52.9.101"

rtsp_url = f"rtsp://{username}:{password}@{ip}:37777/cam/realmonitor?channel=1&subtype=1"

cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

if not cap.isOpened():
    print("Gagal konek ke stream, cek URL/kredensial")
else:
    print("Berhasil konek!")
    ret, frame = cap.read()
    print("Frame terbaca:", ret)
    if ret:
        cv2.imwrite("test_frame.jpg", frame)
        print("Frame disimpan sebagai test_frame.jpg")

cap.release()