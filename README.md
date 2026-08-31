# Early Warning System (EWS) Deteksi Banjir

Sistem monitoring ketinggian air dan deteksi dini banjir berbasis *classical computer vision* menggunakan kamera PTZ (Pan-Tilt-Zoom) Dahua dan dashboard web terintegrasi.

---

## Fitur Utama

- **Deteksi Ketinggian Air Real-Time**: Menggunakan metode *Bottom-Up Frame Differencing* untuk mendeteksi kenaikan air dari dasar papan duga secara akurat dan kebal terhadap pantulan cahaya/noise.
- **Debounced Status Alert**: Klasifikasi status berjenjang (`NORMAL`, `WASPADA`, `SIAGA`) dengan filter durasi stabilitas (*debouncing*) untuk mencegah *false alarm*.
- **Kontrol PTZ & Auto-Reset**: Integrasi HTTP CGI Dahua untuk mengembalikan posisi kamera secara presisi ke koordinat papan duga menggunakan koreksi *closed-loop nudge*.
- **Dashboard Web Terintegrasi**: 
  - Tampilan publik dengan live video feed, status peringatan, dan grafik tren ketinggian air (Chart.js).
  - Portal operator berotentikasi untuk kontrol reset kamera, penyesuaian sensitivitas deteksi, log alert, dan export data ke CSV.
- **Manajemen Konfigurasi Aman**: Pemisahan kredensial kamera dari source code menggunakan konfigurasi YAML lokal.

---

## Struktur Direktori

```text
├── config/
│   ├── config.example.yaml        # Template konfigurasi kredensial kamera
│   ├── cv_thresholds.json         # Batas piksel Y untuk status Waspada & Siaga
│   ├── koordinat_threshold.json   # Koordinat PTZ papan duga
│   └── roi.json                   # Koordinat Region of Interest (ROI)
├── data/                          # Penyimpanan database SQLite (ews.db)
├── scripts/
│   ├── calibrate_ui.py            # Tool kalibrasi visual garis batas Waspada & Siaga
│   └── main_detector.py           # Pipeline utama deteksi computer vision
├── src/
│   ├── camera/
│   │   ├── config_loader.py       # Loader konfigurasi kamera terpusat
│   │   ├── frame_grabber.py       # Handler streaming RTSP
│   │   └── ptz_control.py         # Modul kontrol dan kalibrasi PTZ Dahua
│   └── web/
│       ├── app.py                 # Backend server FastAPI
│       ├── auth.py                # Manajemen autentikasi operator
│       ├── database.py            # Handler database SQLite
│       ├── static/                # Asset CSS dan JavaScript dashboard
│       └── templates/             # Template antarmuka web 
├── requirements.txt
└── test_frame.jpg                 # Gambar referensi baseline kondisi normal
```
## Spesifikasi Teknis

- **Metode Pengolahan Citra**: Classical CV (Frame Differencing, Morphological Filtering, Bottom-Up Projection).
- **Backend & Web**: FastAPI, Uvicorn, Jinja2, SQLite, Chart.js.
- **Protokol Kamera**: RTSP (Real-Time Streaming Protocol) H.264 & Dahua HTTP CGI API.
