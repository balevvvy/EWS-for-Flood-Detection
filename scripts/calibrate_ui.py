"""
Skrip kalibrasi visual untuk menentukan batas piksel Y garis Kuning (Waspada)
dan garis Merah (Siaga) pada papan duga.

Layout fisik papan duga (dari atas ke bawah):
  ┌──────────┐
  │  MERAH   │  ← Siaga (Darurat) — Y piksel KECIL (atas gambar)
  ├──────────┤
  │  KUNING  │  ← Waspada — Y piksel SEDANG
  ├──────────┤
  │  (air)   │  ← Normal — Y piksel BESAR (bawah gambar)
  └──────────┘

Cara pakai:
  python scripts/calibrate_ui.py

Hasilnya disimpan ke config/cv_thresholds.json
"""

import cv2
import os
import json


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    image_path = os.path.join(base_dir, "test_frame.jpg")
    config_path = os.path.join(base_dir, "config", "cv_thresholds.json")

    if not os.path.exists(image_path):
        print(f"Error: Gambar {image_path} tidak ditemukan.")
        print("Pastikan Anda memiliki 'test_frame.jpg' di root proyek.")
        return

    img_original = cv2.imread(image_path)
    orig_h, orig_w = img_original.shape[:2]

    # Resize agar muat di layar (max 900 piksel tinggi)
    max_display_h = 850
    if orig_h > max_display_h:
        scale = max_display_h / orig_h
        display_w = int(orig_w * scale)
        display_h = int(orig_h * scale)
    else:
        scale = 1.0
        display_w = orig_w
        display_h = orig_h

    img = cv2.resize(img_original, (display_w, display_h))
    clone = img.copy()

    points_display = []  # koordinat Y pada gambar yang ditampilkan (sudah di-resize)
    labels = ["KUNING (Waspada)", "MERAH (Siaga)"]
    colors = [(0, 255, 255), (0, 0, 255)]  # BGR: kuning, merah

    def click_and_pick(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(points_display) >= 2:
                print(">>> Sudah 2 titik terpilih. Tekan 'r' untuk reset, atau 's' untuk simpan.")
                return
            idx = len(points_display)
            points_display.append(y)
            # Hitung koordinat asli (sebelum resize)
            y_original = int(y / scale)
            cv2.line(img, (0, y), (img.shape[1], y), colors[idx], 2)
            cv2.putText(img, f"{labels[idx]}: Y={y_original} (asli)", (10, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[idx], 2)
            cv2.imshow("Kalibrasi Papan Duga", img)
            print(f">>> Titik {idx+1} ({labels[idx]}): Y display={y}, Y asli={y_original}")

    cv2.namedWindow("Kalibrasi Papan Duga")
    cv2.setMouseCallback("Kalibrasi Papan Duga", click_and_pick)

    print("=" * 60)
    print("KALIBRASI VISUAL PAPAN DUGA")
    print(f"Gambar asli: {orig_w}x{orig_h}, ditampilkan: {display_w}x{display_h} (skala {scale:.2f})")
    print("=" * 60)
    print("Layout papan duga: MERAH (atas) — KUNING (bawah)")
    print()
    print("Langkah:")
    print("  1. Klik pada batas BAWAH pita KUNING")
    print("     (garis di mana air mulai masuk zona Waspada)")
    print("  2. Klik pada batas BAWAH pita MERAH")
    print("     (garis di mana air mulai masuk zona Siaga/Darurat)")
    print()
    print("Tombol:")
    print("  's' = Simpan dan keluar")
    print("  'r' = Reset pilihan")
    print("  'q' / ESC = Keluar tanpa menyimpan")
    print("=" * 60)

    while True:
        cv2.imshow("Kalibrasi Papan Duga", img)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("r"):
            img = clone.copy()
            points_display.clear()
            print(">>> Pilihan direset.")
        elif key == ord("s"):
            if len(points_display) >= 2:
                # Konversi dari koordinat display ke koordinat gambar asli
                y_waspada = int(points_display[0] / scale)
                y_siaga = int(points_display[1] / scale)

                # Validasi: kuning di bawah merah secara fisik
                # → y_waspada HARUS lebih besar dari y_siaga dalam piksel
                if y_waspada < y_siaga:
                    print("=" * 60)
                    print("PERINGATAN: Y Kuning lebih kecil dari Y Merah.")
                    print("Ini berarti Anda mengklik kuning LEBIH ATAS dari merah,")
                    print("padahal secara fisik kuning harusnya di BAWAH merah.")
                    print("Kemungkinan urutan klik Anda terbalik.")
                    print("Tekan 'r' untuk reset dan coba lagi,")
                    print("atau 's' lagi jika Anda yakin sudah benar.")
                    print("=" * 60)
                    continue

                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump({
                        "y_waspada": y_waspada,
                        "y_siaga": y_siaga,
                        "_keterangan": "y_waspada = batas bawah kuning, y_siaga = batas bawah merah (koordinat piksel asli)"
                    }, f, indent=4)

                print(f">>> TERSIMPAN ke {config_path}")
                print(f">>>   Y Waspada (Kuning) = {y_waspada}")
                print(f">>>   Y Siaga   (Merah)  = {y_siaga}")
                break
            else:
                print(f">>> Baru {len(points_display)} titik terpilih. Butuh 2 titik (Kuning lalu Merah).")
        elif key == ord("q") or key == 27:
            print(">>> Dibatalkan tanpa menyimpan.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
