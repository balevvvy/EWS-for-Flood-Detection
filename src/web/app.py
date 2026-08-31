"""
FastAPI Web Server untuk Dashboard EWS Banjir.
Menghubungkan pipeline deteksi air (main_detector.py) dengan frontend web.

Jalankan:
    uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000
    
Atau:
    python -m src.web.app
"""

import sys
import os
import time
import json

# Tambahkan root project ke sys.path agar bisa import scripts/main_detector
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi import FastAPI, Request, Response, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web import database, auth

# Import detector dan PTZ
from scripts.main_detector import WaterLevelDetector

# ==================== INISIALISASI ====================
app = FastAPI(title="EWS Banjir Dashboard", version="1.0")

# Static files & templates
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

# Inisialisasi detector (singleton global)
detector = WaterLevelDetector(sensitivity=30, blur_size=21, debounce_sec=5)

# PTZ module path
PTZ_MODULE_DIR = os.path.join(ROOT_DIR, "src", "camera")
sys.path.insert(0, PTZ_MODULE_DIR)


# ==================== STARTUP ====================
@app.on_event("startup")
def startup():
    """Inisialisasi database dan mulai pipeline deteksi."""
    database.init_db()

    # Set callback untuk menyimpan pembacaan ke database
    detector.on_reading = database.insert_reading
    detector.on_alert = database.insert_alert

    # Coba inisialisasi detector
    if detector.initialize():
        detector.start_capture()
        print("[Server] Pipeline deteksi air dimulai.")
    else:
        print("[Server] Pipeline deteksi GAGAL diinisialisasi.")
        print("[Server] Dashboard tetap berjalan tapi tanpa data live.")


@app.on_event("shutdown")
def shutdown():
    """Hentikan pipeline deteksi saat server dimatikan."""
    detector.stop()
    print("[Server] Pipeline deteksi dihentikan.")


# ==================== HELPER ====================
def get_operator(session_token: str | None) -> dict | None:
    """Validasi session token dan kembalikan info operator."""
    if not session_token:
        return None
    return auth.validate_session(session_token)


# ==================== HALAMAN PUBLIK ====================
@app.get("/", response_class=HTMLResponse)
async def halaman_publik(request: Request):
    """Halaman utama publik: video stream + status + grafik."""
    return templates.TemplateResponse("index.html", {"request": request})


# ==================== HALAMAN LOGIN ====================
@app.get("/login", response_class=HTMLResponse)
async def halaman_login(request: Request, error: str = ""):
    """Form login operator."""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error
    })


@app.post("/login")
async def proses_login(username: str = Form(...), password: str = Form(...)):
    """Proses form login."""
    token = auth.authenticate(username, password)
    if not token:
        return RedirectResponse(url="/login?error=Username atau password salah", status_code=303)

    response = RedirectResponse(url="/operator", status_code=303)
    response.set_cookie(key="session_token", value=token, httponly=True, max_age=auth.SESSION_DURATION)
    return response


@app.get("/logout")
async def proses_logout(session_token: str = Cookie(default=None)):
    """Logout operator."""
    if session_token:
        auth.logout(session_token)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session_token")
    return response


# ==================== HALAMAN OPERATOR ====================
@app.get("/operator", response_class=HTMLResponse)
async def halaman_operator(request: Request, session_token: str = Cookie(default=None)):
    """Dashboard operator: semua fitur publik + kontrol PTZ + log."""
    operator = get_operator(session_token)
    if not operator:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse("operator.html", {
        "request": request,
        "operator": operator
    })


# ==================== API: VIDEO STREAM (MJPEG) ====================
@app.get("/video_feed")
async def video_feed():
    """
    Streaming MJPEG: mengirim deretan gambar JPG secara terus-menerus.
    Browser menampilkannya sebagai video via tag <img src="/video_feed">.
    """
    def generate():
        while True:
            frame_bytes = detector.get_latest_frame_bytes()
            if frame_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            else:
                # Kirim frame kosong (1x1 pixel hitam) jika tidak ada data
                import cv2
                import numpy as np
                blank = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(blank, "Kamera Tidak Terhubung", (350, 360),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.5, (100, 100, 100), 3)
                _, buf = cv2.imencode('.jpg', blank)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                )
            time.sleep(0.066)  # ~15 FPS

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ==================== API: STATUS ====================
@app.get("/api/status")
async def api_status():
    """Mengembalikan status deteksi terkini sebagai JSON, dengan water_pct."""
    status_data = detector.get_status_dict()

    # Konversi water_y ke persentase
    water_pct = None
    if status_data.get("water_y") is not None and detector._roi:
        roi = detector._roi
        roi_bottom = roi["y"] + roi["h"]
        water_pct = round((roi_bottom - status_data["water_y"]) / roi["h"] * 100, 1)
        water_pct = max(0, min(100, water_pct))  # clamp 0-100

    status_data["water_pct"] = water_pct
    return JSONResponse(status_data)


# ==================== API: HISTORY ====================
@app.get("/api/history")
async def api_history(hours: float = 1):
    """Mengembalikan riwayat pembacaan ketinggian air (dengan persentase)."""
    data = database.get_history(hours=hours)

    # Konversi water_y ke persentase
    if detector._roi:
        roi = detector._roi
        roi_bottom = roi["y"] + roi["h"]
        for row in data:
            if row.get("water_y") is not None:
                pct = round((roi_bottom - row["water_y"]) / roi["h"] * 100, 1)
                row["water_pct"] = max(0, min(100, pct))
            else:
                row["water_pct"] = None

    return JSONResponse(data)


@app.get("/api/alerts")
async def api_alerts(hours: float = 24):
    """Mengembalikan riwayat alert."""
    data = database.get_alerts(hours=hours)
    return JSONResponse(data)


# ==================== API: SETTINGS (HANYA OPERATOR) ====================
@app.get("/api/settings")
async def api_get_settings():
    """Mengembalikan setting sensitivitas dan blur saat ini."""
    return JSONResponse({
        "sensitivity": detector.sensitivity,
        "blur_size": detector.blur_size
    })


@app.post("/api/settings")
async def api_post_settings(request: Request, session_token: str = Cookie(default=None)):
    """Update setting sensitivitas/blur dari dashboard operator."""
    operator = get_operator(session_token)
    if not operator:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    if "sensitivity" in body:
        detector.sensitivity = int(body["sensitivity"])
    if "blur_size" in body:
        detector.blur_size = int(body["blur_size"])

    return JSONResponse({"ok": True, "sensitivity": detector.sensitivity, "blur_size": detector.blur_size})


# ==================== API: PTZ RESET (HANYA OPERATOR) ====================
@app.post("/api/ptz/reset")
async def api_ptz_reset(session_token: str = Cookie(default=None)):
    """Kembalikan kamera ke posisi papan duga (koordinat tersimpan)."""
    operator = get_operator(session_token)
    if not operator:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        from src.camera import ptz_control

        koordinat = ptz_control.baca_koordinat_tersimpan()
        pan = koordinat["pan"]
        tilt = koordinat["tilt"]
        zoom = koordinat["zoom"]

        # Step 1: Pan (PositionABS bekerja untuk pan)
        ptz_control.goto_position_abs(pan, tilt, zoom)
        time.sleep(3)

        # Step 2: Koreksi tilt via closed-loop nudge
        ptz_control.axis_nudge_closed_loop(
            "tilt", lambda s: s["tilt"], tilt,
            "Up", "Down", tolerance=0.5
        )

        # Step 3: Koreksi zoom via closed-loop nudge
        ptz_control.axis_nudge_closed_loop(
            "zoom", lambda s: s["zoom"], zoom,
            "ZoomTele", "ZoomWide", tolerance=0.5
        )

        return JSONResponse({"ok": True, "message": "Kamera dikembalikan ke posisi papan duga."})
    except FileNotFoundError:
        return JSONResponse({"error": "File koordinat tidak ditemukan. Jalankan kalibrasi PTZ dulu."}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ==================== MAIN (untuk menjalankan langsung) ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=True)
