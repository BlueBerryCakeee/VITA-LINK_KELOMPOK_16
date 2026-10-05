# VITA-Link - Tactical Telemetry & Web GIS Backend Server
# Kelompok 16 - Desain Proyek Teknik Komputer & Elektro FTUI
# PIC: Ahmad Fariz Khairi (2306211370)

import asyncio
import csv
import io
import json
import os
import random
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
import uvicorn

# ==========================================================
# 1. KONFIGURASI DATABASE & PATH
# ==========================================================
DIR_PATH = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(DIR_PATH, "vitalink.db")
SCHEMA_FILE = os.path.join(DIR_PATH, "schema.sql")

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        if os.path.exists(SCHEMA_FILE):
            with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
                cursor.executescript(f.read())
            conn.commit()
            print("[DATABASE] Skema SQLite vitalink.db berhasil diinisialisasi.")
        conn.close()
    except Exception as e:
        print(f"[DATABASE ERROR] Inisialisasi gagal: {e}")

init_db()

# ==========================================================
# 2. STATE MASTER TELEMETRI KORBAN (IN-MEMORY CACHE)
# ==========================================================
victims_state: Dict[str, dict] = {
    "BRACELET-01": {
        "id": "BRACELET-01",
        "name": "Budi Santoso",
        "device": "Gelang LoRa #1",
        "lat": -6.3615,
        "lng": 106.8280,
        "spo2": 82,
        "bpm": 138,
        "temp": 39.4,
        "manDown": True,
        "rssi": -88,
        "status": "red",
        "statusText": "MERAH - Kritis (Desaturasi Oksigen)",
        "notes": "Desaturasi Oksigen Berat, curiga trauma inhalasi",
        "evacuation_status": "PENDING",
        "is_hardware": False,
        "last_seen": time.time()
    },
    "BRACELET-02": {
        "id": "BRACELET-02",
        "name": "Siti Aminah",
        "device": "Gelang LoRa #2",
        "lat": -6.3638,
        "lng": 106.8262,
        "spo2": 93,
        "bpm": 102,
        "temp": 37.8,
        "manDown": False,
        "rssi": -94,
        "status": "yellow",
        "statusText": "KUNING - Pengawasan (Takikardia)",
        "notes": "Fraktur femur tertutup, hemodinamik stabil",
        "evacuation_status": "DISPATCHED",
        "is_hardware": False,
        "last_seen": time.time()
    },
    "BRACELET-03": {
        "id": "BRACELET-03",
        "name": "Ahmad Dani",
        "device": "Gelang LoRa #3",
        "lat": -6.3645,
        "lng": 106.8295,
        "spo2": 98,
        "bpm": 76,
        "temp": 36.6,
        "manDown": False,
        "rssi": -82,
        "status": "green",
        "statusText": "HIJAU - Stabil",
        "notes": "Luka abrasi ringan, sadar penuh",
        "evacuation_status": "EVACUATED",
        "is_hardware": False,
        "last_seen": time.time()
    },
    "BRACELET-04": {
        "id": "BRACELET-04",
        "name": "Hendra Wijaya",
        "device": "Gelang LoRa #4",
        "lat": -6.3605,
        "lng": 106.8250,
        "spo2": 92,
        "bpm": 110,
        "temp": 35.4,
        "manDown": False,
        "rssi": -102,
        "status": "yellow",
        "statusText": "KUNING - Hipotermia Ringan",
        "notes": "Kedinginan di area reruntuhan",
        "evacuation_status": "PENDING",
        "is_hardware": False,
        "last_seen": time.time()
    }
}

# ==========================================================
# 3. WEBSOCKET BROADCAST MANAGER
# ==========================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Web client terhubung. Aktif: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WS] Web client terputus. Aktif: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# ==========================================================
# 4. ALGORITMA KLASIFIKASI TRIAGE & SIMPAN LOG DATABASE
# ==========================================================
def compute_triage(spo2, bpm, temp, man_down, is_hardware=False, max_ok=True, finger=True):
    if man_down:
        return "red", "MERAH - Kritis (Jatuh / Man-Down)"
    
    if is_hardware:
        if not max_ok:
            return "yellow", "KUNING - Sensor Belum Terpasang"
        if not finger:
            return "yellow", "KUNING - Menunggu Jari di Sensor"

    if (spo2 > 0 and spo2 < 85) or bpm > 130 or (bpm > 0 and bpm < 40) or temp > 39.0:
        return "red", "MERAH - Kritis"
    elif (spo2 > 0 and spo2 < 94) or bpm > 100 or temp > 38.0 or (temp > 0 and temp < 35.5):
        return "yellow", "KUNING - Pengawasan"
    else:
        return "green", "HIJAU - Stabil"

def save_telemetry_to_db(dev_id, spo2, bpm, temp, man_down, lat, lng, rssi=None):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO telemetry_logs 
               (device_id, spo2, heart_rate, body_temperature, is_man_down, rssi, snr) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (dev_id, float(spo2), int(bpm), float(temp), 1 if man_down else 0, rssi or -85, 5.0)
        )
        cursor.execute(
            """INSERT INTO gps_logs 
               (device_id, latitude, longitude, altitude) 
               VALUES (?, ?, ?, ?)""",
            (dev_id, float(lat), float(lng), 35.0)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB LOG ERROR] {e}")

def record_triage_event(dev_id, color, reason, ews_score=0):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO triage_events 
               (device_id, ews_score, triage_color, trigger_reason) 
               VALUES (?, ?, ?, ?)""",
            (dev_id, ews_score, color.upper(), reason)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[TRIAGE EVENT ERROR] {e}")

# ==========================================================
# 5. SIMULASI BACKGROUND STREAMING
# ==========================================================
async def telemetry_stream_loop():
    while True:
        await asyncio.sleep(2.5)

        # Pilih hanya perangkat simulasi, bukan hardware ESP32 fisik
        sim_candidates = [k for k, v in victims_state.items() if not v.get("is_hardware")]
        if not sim_candidates:
            continue

        dev_id = random.choice(sim_candidates)
        v = victims_state[dev_id]
        old_status = v.get("status")

        v["lat"] += (random.random() - 0.5) * 0.0002
        v["lng"] += (random.random() - 0.5) * 0.0002
        v["spo2"] = min(100, max(75, v["spo2"] + random.randint(-2, 2)))
        v["bpm"] = min(160, max(50, v["bpm"] + random.randint(-4, 4)))
        v["temp"] = round(min(41.0, max(34.5, v["temp"] + random.uniform(-0.2, 0.2))), 1)
        v["rssi"] = random.randint(-110, -70)
        v["last_seen"] = time.time()

        # Peluang kecil simulasi jatuh acak
        if random.random() < 0.04:
            v["manDown"] = True
        elif random.random() < 0.20:
            v["manDown"] = False

        status, status_text = compute_triage(v["spo2"], v["bpm"], v["temp"], v["manDown"])
        v["status"] = status
        v["statusText"] = status_text

        if old_status != status:
            record_triage_event(dev_id, status, f"Perubahan status: {status_text}")

        save_telemetry_to_db(v["id"], v["spo2"], v["bpm"], v["temp"], v["manDown"], v["lat"], v["lng"], v["rssi"])

        packet = {
            "type": "TELEMETRY_UPDATE",
            "timestamp": time.time(),
            "source": "SIMULATION",
            "updated_device": dev_id,
            "victim": v,
            "all_victims": list(victims_state.values())
        }
        await manager.broadcast(packet)

# ==========================================================
# 6. LIFESPAN FASTAPI
# ==========================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(telemetry_stream_loop())
    print("\n" + "=" * 70)
    print("  VITA-Link Tactical Telemetry & GIS Server")
    print("  Kelompok 16 - Desain Proyek FTUI")
    print("=" * 70)
    print("  Dashboard UI     : http://localhost:8000")
    print("  WebSocket Stream : ws://localhost:8000/ws/telemetry")
    print("  REST API Victims : http://localhost:8000/api/victims")
    print("  System Stats     : http://localhost:8000/api/stats")
    print("  Export Data CSV  : http://localhost:8000/api/export/csv")
    print("  Hardware Ingest  : POST http://localhost:8000/api/telemetry")
    print("=" * 70 + "\n")
    yield
    task.cancel()

app = FastAPI(
    title="VITA-Link Tactical GIS Server",
    description="Backend Server Triage GIS & Gateway Telemetri Bencana",
    version="3.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# 7. ROUTE REST API LENGKAP
# ==========================================================

@app.get("/")
async def get_index():
    """Menyajikan Frontend Tactical Command Center HTML"""
    return FileResponse(os.path.join(DIR_PATH, "index.html"))

@app.get("/analytics")
async def get_analytics_page():
    """Menyajikan Halaman Tactical Analytics & Operational Intelligence"""
    analytics_path = os.path.join(DIR_PATH, "analytics.html")
    if os.path.exists(analytics_path):
        return FileResponse(analytics_path)
    return FileResponse(os.path.join(DIR_PATH, "index.html"))

@app.get("/api/victims")
async def get_victims():
    """Mengambil daftar seluruh korban beserta kondisi terkini"""
    return JSONResponse(list(victims_state.values()))

@app.get("/api/events")
async def get_triage_events(limit: int = 50):
    """Mengambil riwayat kejadian darurat dan perubahan status triage dari database"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT event_id, device_id, ews_score, triage_color, trigger_reason, logged_at 
               FROM triage_events 
               ORDER BY event_id DESC LIMIT ?""",
            (limit,)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse([])

@app.get("/api/victims/{dev_id}")
async def get_victim_detail(dev_id: str):
    """Mengambil detail satu korban spesifik"""
    if dev_id in victims_state:
        return JSONResponse(victims_state[dev_id])
    raise HTTPException(status_code=404, detail="Perangkat korban tidak ditemukan")

async def process_telemetry_payload(payload: dict):
    """Fungsi bersama untuk memproses telemetri dari hardware / serial / simulasi"""
    dev_id = payload.get("device_id", "BRACELET-01")

    if dev_id not in victims_state:
        victims_state[dev_id] = {
            "id": dev_id,
            "name": payload.get("name", f"Korban ({dev_id})"),
            "device": "ESP32 Hardware Fisik",
            "lat": payload.get("lat", -6.3627),
            "lng": payload.get("lng", 106.8272),
            "spo2": payload.get("spo2", 0.0),
            "bpm": payload.get("bpm", 0),
            "temp": payload.get("temp", 0.0),
            "manDown": payload.get("manDown", False),
            "rssi": payload.get("rssi", -75),
            "notes": "Data Masuk dari ESP32 Hardware",
            "evacuation_status": "PENDING",
            "is_hardware": True,
            "last_seen": time.time()
        }
    else:
        if not payload.get("gps_fixed", False) and (payload.get("lat") == 0.0 or "lat" not in payload):
            saved_lat = victims_state[dev_id].get("lat", -6.3615)
            saved_lng = victims_state[dev_id].get("lng", 106.8280)
            victims_state[dev_id].update(payload)
            victims_state[dev_id]["lat"] = saved_lat
            victims_state[dev_id]["lng"] = saved_lng
        else:
            victims_state[dev_id].update(payload)
        victims_state[dev_id]["is_hardware"] = True
        victims_state[dev_id]["last_seen"] = time.time()

    v = victims_state[dev_id]
    max_ok = v.get("max30102_ok", False)
    finger = v.get("finger", False)

    if v.get("manDown"):
        v["notes"] = "[DARURAT] Terdeteksi Jatuh / Benturan (ADXL345 Man-Down)"
    elif not max_ok:
        v["notes"] = "[INFO] Sensor MAX30102 belum terpasang di pin 21/22"
    elif not finger:
        v["notes"] = "[INFO] Sensor MAX30102 aktif: Tempelkan jari di sensor"
    elif v.get("notes", "").startswith("[DARURAT] Terdeteksi Jatuh"):
        v["notes"] = "Kondisi fisik normal terpantau"

    old_status = v.get("status")
    status, status_text = compute_triage(
        v["spo2"], v["bpm"], v["temp"], v.get("manDown", False),
        is_hardware=True,
        max_ok=max_ok,
        finger=finger
    )
    v["status"] = status
    v["statusText"] = status_text

    if old_status != status:
        record_triage_event(dev_id, status, f"Perubahan Triage Hardware: {status_text}")

    save_telemetry_to_db(dev_id, v["spo2"], v["bpm"], v["temp"], v.get("manDown", False), v["lat"], v["lng"], v.get("rssi"))

    await manager.broadcast({
        "type": "TELEMETRY_UPDATE",
        "timestamp": time.time(),
        "source": "HARDWARE_PHYSICAL",
        "updated_device": dev_id,
        "victim": v,
        "all_victims": list(victims_state.values())
    })

    mandown_str = "[DARURAT] YA (JATUH)" if v.get("manDown") else "Normal"
    print(f"[INGEST] {dev_id} -> Suhu: {v['temp']}°C | SpO2: {v['spo2']}% | BPM: {v['bpm']} | ManDown: {mandown_str} | Triage: {status.upper()}")
    return {"status": "success", "message": "Hardware telemetry ingested", "device_id": dev_id}

@app.post("/api/telemetry")
async def post_telemetry(payload: dict):
    """Menerima telemetri via /api/telemetry (digunakan oleh Web UI simulation)"""
    return await process_telemetry_payload(payload)

@app.post("/api/telemetry/inject")
async def post_telemetry_inject(payload: dict):
    """Menerima telemetri via /api/telemetry/inject (digunakan oleh serial_bridge.py)"""
    return await process_telemetry_payload(payload)

@app.post("/api/victims/{dev_id}/action")
async def update_victim_action(dev_id: str, payload: dict):
    """Memperbarui status evakuasi SAR (DISPATCHED, EVACUATED, RESET)"""
    action = payload.get("action", "RESET")
    if dev_id in victims_state:
        victims_state[dev_id]["evacuation_status"] = action
        await manager.broadcast({
            "type": "TELEMETRY_UPDATE",
            "timestamp": time.time(),
            "source": "FIELD_OPERATION",
            "updated_device": dev_id,
            "victim": victims_state[dev_id],
            "all_victims": list(victims_state.values())
        })
        return {"status": "success", "device_id": dev_id, "action": action}
    raise HTTPException(status_code=404, detail="Device not found")

@app.post("/api/victims/{dev_id}/notes")
async def update_victim_notes(dev_id: str, payload: dict):
    """Menyimpan catatan medis / SAR dari posko ke database dan broadcast"""
    note = payload.get("notes", "").strip()
    if dev_id in victims_state:
        victims_state[dev_id]["notes"] = note
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE patients SET notes = ? WHERE device_id = ?", (note, dev_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[NOTES DB ERROR] {e}")

        await manager.broadcast({
            "type": "TELEMETRY_UPDATE",
            "timestamp": time.time(),
            "source": "FIELD_NOTE",
            "updated_device": dev_id,
            "victim": victims_state[dev_id],
            "all_victims": list(victims_state.values())
        })
        return {"status": "success", "device_id": dev_id, "notes": note}
    raise HTTPException(status_code=404, detail="Device not found")

@app.get("/api/history/{dev_id}")
async def get_victim_history(dev_id: str, limit: int = 30):
    """Mengambil riwayat log telemetri dari database SQLite untuk analisis tren"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT log_id, spo2, heart_rate, body_temperature, is_man_down, rssi, recorded_at 
               FROM telemetry_logs 
               WHERE device_id = ? 
               ORDER BY log_id DESC LIMIT ?""",
            (dev_id, limit)
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return JSONResponse(list(reversed(rows)))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_dashboard_stats():
    """Mengambil metrik statistik operasional sistem triage"""
    total = len(victims_state)
    red = sum(1 for v in victims_state.values() if v.get("status") == "red")
    yellow = sum(1 for v in victims_state.values() if v.get("status") == "yellow")
    green = sum(1 for v in victims_state.values() if v.get("status") == "green")
    
    evacuated = sum(1 for v in victims_state.values() if v.get("evacuation_status") == "EVACUATED")
    dispatched = sum(1 for v in victims_state.values() if v.get("evacuation_status") == "DISPATCHED")
    pending = total - (evacuated + dispatched)

    hw_active = any(v.get("is_hardware") and (time.time() - v.get("last_seen", 0) < 10) for v in victims_state.values())

    # Hitung total catatan di database
    total_logs = 0
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM telemetry_logs")
        total_logs = cursor.fetchone()[0]
        conn.close()
    except Exception:
        pass

    return {
        "status": "operational",
        "total_victims": total,
        "triage_summary": {
            "red": red,
            "yellow": yellow,
            "green": green
        },
        "evacuation_summary": {
            "evacuated": evacuated,
            "dispatched": dispatched,
            "pending": pending,
            "completion_percentage": round((evacuated / total * 100), 1) if total > 0 else 0
        },
        "hardware_status": {
            "is_connected": hw_active,
            "node_count": sum(1 for v in victims_state.values() if v.get("is_hardware"))
        },
        "database": {
            "total_telemetry_records": total_logs,
            "file": DB_FILE
        },
        "active_websocket_clients": len(manager.active_connections),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/export/csv")
async def export_telemetry_csv():
    """Mengekspor seluruh riwayat telemetri dari SQLite ke format CSV"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT log_id, device_id, spo2, heart_rate, body_temperature, 
                      is_man_down, rssi, snr, recorded_at 
               FROM telemetry_logs 
               ORDER BY log_id ASC"""
        )
        rows = cursor.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Log ID", "Device ID", "SpO2 (%)", "BPM", "Suhu (C)", "Man-Down", "RSSI (dBm)", "SNR (dB)", "Timestamp"])
        for r in rows:
            writer.writerow(list(r))

        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=vitalink_telemetry_{int(time.time())}.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal ekspor CSV: {e}")

@app.post("/api/simulation/reset")
async def reset_simulation():
    """Mengembalikan data korban simulasi ke kondisi awal"""
    for v in victims_state.values():
        if not v.get("is_hardware"):
            v["evacuation_status"] = "PENDING"
            v["manDown"] = False
            v["spo2"] = random.randint(92, 98)
            v["bpm"] = random.randint(70, 95)
            v["temp"] = round(random.uniform(36.4, 37.2), 1)
            v["status"], v["statusText"] = compute_triage(v["spo2"], v["bpm"], v["temp"], False)

    await manager.broadcast({
        "type": "TELEMETRY_UPDATE",
        "timestamp": time.time(),
        "source": "SIMULATION_RESET",
        "all_victims": list(victims_state.values())
    })
    return {"status": "success", "message": "Simulation reset successfully"}

# ==========================================================
# 8. WEBSOCKET REALTIME STREAMING
# ==========================================================
@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_json({
        "type": "INITIAL_STATE",
        "all_victims": list(victims_state.values()),
        "server_time": time.time()
    })
    try:
        while True:
            # Dengarkan pesan atau ping dari klien
            msg = await websocket.receive_text()
            try:
                parsed = json.loads(msg)
                if parsed.get("type") == "PING":
                    await websocket.send_json({"type": "PONG", "timestamp": time.time()})
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ==========================================================
# 9. MAIN RUNNER
# ==========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)