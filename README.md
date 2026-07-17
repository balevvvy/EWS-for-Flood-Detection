# EWS Banjir (Early Warning System)

Sistem deteksi dini banjir berbasis computer vision. Proyek ini mendeteksi tinggi air menggunakan kamera PTZ dengan pendekatan segmentasi dan kalibrasi ke papan duga fisik.

## Setup

1. Clone repositori ini.
2. Buat virtual environment: `python -m venv venv`
3. Aktifkan venv:
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`
4. Install dependensi: `pip install -r requirements.txt`
5. Copy `config/config.example.yaml` menjadi `config/config.yaml` dan isi dengan kredensial kamera.

## Struktur Proyek

- `config/`: Konfigurasi proyek dan kamera (tidak di-commit ke Git).
- `src/`: Source code utama (modul kamera, segmentasi, kalibrasi, alert).
- `scripts/`: Entry point untuk menjalankan pipeline utama.
- `tests/`: Unit test untuk modul-modul.
- `data/`: Folder data untuk raw images, archive, dan sampel kalibrasi.
- `logs/`: Folder penyimpanan log.

## Status Pengerjaan

- Fase 1 (Sedang berjalan): Modul kontrol PTZ (menyimpan dan mengembalikan kamera secara presisi ke posisi papan duga) sudah selesai dan teruji (`src/camera/ptz_control.py`). Modul Computer Vision (segmentasi, kalibrasi, alert) masih berupa placeholder dan akan diimplementasikan pada tahap selanjutnya.
- Catatan: Proyek ini merupakan hasil PKL selama 2 bulan, didesain dengan arsitektur modular agar mudah dilanjutkan dan dikembangkan pada fase berikutnya.
