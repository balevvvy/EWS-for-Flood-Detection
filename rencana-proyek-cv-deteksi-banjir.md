# Rencana Proyek: Sistem Deteksi Dini Banjir Berbasis Computer Vision

*Dokumen ini merangkum konteks, tujuan, persiapan, timeline, dan pembagian tugas untuk proyek selama periode PKL 2 bulan — sekaligus jadi referensi awal untuk siapa pun yang melanjutkan proyek ini setelahnya.*

## 1. Konteks Proyek

Lokasi proyek adalah sebuah sungai/kanal yang sudah punya papan duga (staff gauge) fisik terpasang di tembok penahan, dengan kode warna siaga banjir standar Indonesia — pita kuning di marka 200 dan pita merah di marka 300 (kemungkinan ada zona hijau di bawah 200 yang saat ini tertutup vegetasi/permukaan air).

Hardware yang sudah tersedia: kamera **Dahua DH-SD5A225XA-HNR** — Network PTZ Camera 2MP, optical zoom 25x, sensor Starlight (mempertahankan warna sampai 0.005 lux, baru jatuh ke mode IR/monokrom di kegelapan total 0 lux), mendukung ONVIF dan RTSP. Kamera saat ini masih berada di kantor, belum dipasang di lokasi sungai.

Arsitektur yang dipilih: **semua pemrosesan CV berjalan di server**, kamera di lapangan hanya bertugas streaming — tidak ada edge device.

Kendala utama proyek:
- Belum ada dataset sama sekali.
- Karena sedang musim kemarau, data kondisi banjir sungguhan tidak mungkin dikumpulkan selama masa PKL.
- Masa kerja di tempat ini hanya 2 bulan, dan proyek kemungkinan besar akan dilanjutkan orang lain setelahnya.

Pendekatan CV yang sudah disepakati: pipeline dua fase. **Fase 1** (dikerjakan sekarang) memakai computer vision berbasis aturan — HSV thresholding + background subtraction, ditambah opsi Segment Anything Model (SAM) sebagai zero-shot segmenter — dikalibrasi terhadap marka papan duga, tanpa perlu dataset. **Fase 2** (nanti, oleh penerus) upgrade ke model segmentasi supervised begitu data riil, termasuk kondisi banjir, sudah terkumpul dari hasil monitoring jangka panjang.

## 2. Tujuan & Ruang Lingkup

**Tujuan:**
- Estimasi tinggi muka air (TMA) otomatis dari live feed kamera, direferensikan ke marka papan duga.
- Klasifikasi status siaga (normal/waspada/siaga/awas) otomatis dari level air yang terdeteksi, plus pemicu alert.
- Sistem berjalan mandiri 24/7 termasuk malam hari, seluruhnya di server (tanpa edge device).
- Meninggalkan fondasi kode + data + dokumentasi yang siap dilanjutkan setelah PKL selesai.

**Di luar ruang lingkup untuk fase PKL ini:**
- Logic preset PTZ (auto-return kamera ke papan duga tiap 5 menit) — dikerjakan sendiri, terpisah dari task list di bawah.
- Model deep learning supervised penuh (Fase 2) — realistanya di luar jangkauan 2 bulan karena butuh data kondisi banjir riil.
- Integrasi notifikasi resmi ke masyarakat (WhatsApp/SMS gateway) — stretch goal, bukan prioritas inti.

## 3. Yang Perlu Dipersiapkan

**Teknis / software**
- Environment development: Python + OpenCV + dependency terkait, virtual environment, repo Git (penting karena akan diteruskan orang lain).
- Kredensial & akses RTSP/ONVIF kamera (sudah ada, tinggal didokumentasikan di config terpisah dari kode).
- Konfirmasi spesifikasi server pemrosesan (CPU/GPU, RAM) — menentukan apakah SAM/SAM2 realistis dipakai atau cukup classical CV saja.
- Materi uji: foto papan duga yang sudah ada, idealnya ditambah beberapa foto dari sudut/waktu berbeda, atau mockup fisik air + papan kecil di kantor.

**Data & dokumentasi lapangan**
- Konfirmasi skala penuh papan duga ke pembimbing lapangan — bukan cuma marka 200 & 300 yang terlihat di foto, tapi rentang lengkap (batas bawah, batas atas, satuan pasti) supaya kalibrasi akurat.
- Definisi ambang siaga resmi yang dipakai instansi setempat, supaya logic alert match dengan standar mereka, bukan asumsi sendiri.
- Riwayat data TMA manual di lokasi ini kalau ada (log pencatatan petugas) — berguna sebagai referensi/validasi meski tanpa gambar.

**Lapangan / organisasi**
- Jadwal target pemasangan kamera ke lokasi sungai.
- Konektivitas jaringan di lokasi sungai ke server pemrosesan — krusial karena arsitektur "tanpa edge device" berarti kamera wajib punya jalur streaming yang stabil.
- Sumber daya listrik di lokasi pemasangan.
- Kejelasan siapa/tim yang akan melanjutkan proyek setelah PKL, supaya dokumentasi di Fase 6 diarahkan ke audiens yang tepat.

## 4. Fase Pengerjaan & Timeline Besar

| Fase | Minggu | Fokus Utama |
|---|---|---|
| 1. Fondasi & Modul Inti CV | 1–2 | Modul segmentasi, kalibrasi, frame-grab — dites di kantor |
| 2. Integrasi Pipeline & Alert Logic | 3 | Gabung semua modul + logic status siaga |
| 3. Dry-Run & Hardening | 4 | Jalankan sistem lengkap tanpa henti, cari bug stabilitas |
| 4. Deployment Lapangan & Kalibrasi Riil | 5 | Pasang di sungai, kalibrasi ulang dengan kondisi asli |
| 5. Tuning & Monitoring Lapangan | 6–7 | Perbaiki threshold berdasar data riil siang/malam |
| 6. Dokumentasi & Serah Terima | 8 | Dokumentasi lengkap + handoff |

## 5. Jobdesk per Fase

### Fase 1 — Fondasi & Modul Inti CV (Minggu 1–2)
- Setup repo Git + struktur folder proyek + dependency (OpenCV, numpy, dst.).
- Bangun modul frame-grab dari RTSP/ONVIF, termasuk auto-reconnect kalau stream putus/timeout.
- Bangun modul segmentasi air vs papan (HSV thresholding + `cv2.createBackgroundSubtractorMOG2`), uji pakai foto papan duga yang sudah ada + mockup fisik kalau memungkinkan.
- (Opsional bila waktu ada) uji layer tambahan SAM/SAM2 sebagai prompted segmenter, bandingkan dengan hasil threshold manual.
- Bangun fungsi kalibrasi piksel → cm dari dua titik marka (200 & 300), lengkap unit test.
- *Paralel (dikerjakan sendiri): skrip preset PTZ auto-return ke papan duga tiap 5 menit.*

### Fase 2 — Integrasi Pipeline & Alert Logic (Minggu 3)
- Bangun logic klasifikasi status siaga dari input cm, sesuai ambang resmi yang sudah dikonfirmasi ke instansi.
- Bangun mekanisme alert dasar (minimal logging ke file/database; notifikasi webhook/Telegram sebagai stretch goal kalau waktu ada).
- Sambungkan frame-grab → segmentasi → kalibrasi → status siaga jadi satu pipeline utuh, jalankan end-to-end pertama kali.
- Tambahkan deteksi mode day/night kamera (color vs B/W IR) supaya threshold bisa switch profile otomatis.

### Fase 3 — Dry-Run & Hardening (Minggu 4)
- Jalankan pipeline lengkap tanpa henti selama beberapa hari di kantor, pantau crash/memory leak/RTSP drop.
- Perbaiki bug stabilitas yang ditemukan — fase ini penting karena akses debugging jadi lebih terbatas begitu kamera di lapangan.
- Bangun pipeline arsip frame otomatis (timestamp + estimasi level sebagai pseudo-label), jalankan bareng dry-run.
- Siapkan dokumentasi konfigurasi awal (README teknis, cara menjalankan, daftar config/environment variable).

### Fase 4 — Deployment Lapangan & Kalibrasi Riil (Minggu 5)
- Koordinasi pemasangan fisik kamera ke lokasi sungai dengan pihak terkait.
- Konfirmasi konektivitas kamera-ke-server di lokasi asli.
- *Paralel (dikerjakan sendiri): aktivasi preset PTZ di lokasi asli.*
- Kalibrasi ulang piksel → cm pakai frame asli dari lapangan (framing bisa sedikit berbeda dari foto awal).
- Validasi awal: bandingkan estimasi sistem vs pembacaan manual langsung di papan duga, di beberapa waktu berbeda dalam sehari.

### Fase 5 — Tuning & Monitoring Lapangan (Minggu 6–7)
- Kumpulkan & tinjau footage siang dan malam dari lokasi asli, sesuaikan threshold HSV/background subtraction sesuai kondisi nyata (silau, bayangan, mode IR malam).
- Tangani false positive lapangan (kotoran lensa, serangga, riak air, tetesan hujan).
- Pantau data arsip yang terkumpul, evaluasi representativitas pseudo-label.
- Lanjutkan validasi akurasi terhadap pembacaan manual secara berkala.

### Fase 6 — Dokumentasi & Serah Terima (Minggu 8)
- Tulis dokumentasi lengkap: arsitektur sistem, metodologi kalibrasi, cara rekalibrasi kalau kamera/preset berubah, keterbatasan yang diketahui, roadmap Fase 2.
- Rapikan repo (README, comment, config terpisah dari kode).
- Siapkan laporan akhir PKL + sesi serah terima.
- Susun daftar open items untuk penerus, termasuk kapan & bagaimana mulai fine-tune model supervised begitu data musim hujan terkumpul.
