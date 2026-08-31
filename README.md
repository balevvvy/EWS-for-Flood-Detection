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
│       └── templates/             # Template antarmuka web (Jinja2)
├── requirements.txt
└── test_frame.jpg                 # Gambar referensi baseline kondisi normal
```

---

## Instalasi

1. Clone repositori:
   ```bash
   git clone https://github.com/balevvvy/EWS-for-Flood-Detection.git
   cd EWS-for-Flood-Detection
   ```

2. Buat dan aktifkan virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

3. Install dependensi:
   ```bash
   pip install -r requirements.txt
   ```

4. Buat file konfigurasi kamera dari template:
   ```bash
   cp config/config.example.yaml config/config.yaml
   ```
   Edit `config/config.yaml` dan sesuaikan IP, username, dan password kamera fisik Anda.

---

## Penggunaan

### 1. Kalibrasi Visual Garis Ambang Batas
Jalankan tool kalibrasi untuk menentukan letak garis batas WASPADA (kuning) dan SIAGA (merah) pada gambar papan duga:
```bash
python scripts/calibrate_ui.py
```
* Klik pada batas bawah zona kuning, lalu klik pada batas bawah zona merah. Tekan `s` untuk menyimpan.

### 2. Kalibrasi Posisi Kamera PTZ
Untuk menyimpan posisi awal kamera mengarah ke papan duga:
```bash
python src/camera/ptz_control.py
```
* Pilih menu `1` untuk membaca dan menyimpan koordinat PTZ saat ini.

### 3. Menjalankan Dashboard Web
Jalankan web server FastAPI:
```bash
python -m uvicorn src.web.app:app --host 0.0.0.0 --port 8000
```
* Buka browser di `http://localhost:8000` untuk Dashboard Publik.
* Buka `http://localhost:8000/login` untuk masuk ke Dashboard Operator (`username: operator`, `password: ews2026`).

---

## Spesifikasi Teknis

- **Metode Pengolahan Citra**: Classical CV (Frame Differencing, Morphological Filtering, Bottom-Up Projection).
- **Backend & Web**: FastAPI, Uvicorn, Jinja2, SQLite, Chart.js.
- **Protokol Kamera**: RTSP (Real-Time Streaming Protocol) H.264 & Dahua HTTP CGI API.
