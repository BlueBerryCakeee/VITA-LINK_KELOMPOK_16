# VITA-Link - Telemetry & Web GIS Server (FastAPI + WebSocket)
# Kelompok 16 - Desain Proyek FTUI

import asyncio
import json
import os
import random
import sqlite3
import sys
import time
import webbrowser
from contextlib import asynccontextmanager
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

DIR_PATH = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(DIR_PATH, "vitalink.db")
SCHEMA_FILE = os.path.join(DIR_PATH, "schema.sql")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if os.path.exists(SCHEMA_FILE):
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            cursor.executescript(f.read())
        conn.commit()
    conn.close()

init_db()

# Data Master Pasien
victims_state = {
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
        "statusText": "MERAH - Kritis",
        "notes": "Desaturasi Oksigen Berat",
        "is_hardware": False
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
        "statusText": "KUNING - Pengawasan",
        "notes": "Fraktur femur kanan",
        "is_hardware": False
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
        "notes": "Luka abrasi ringan",
        "is_hardware": False
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
        "statusText": "KUNING - Hipotermia",
        "notes": "Suhu tubuh rendah",
        "is_hardware": False
    }
}

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WS] Web client terhubung. Total client: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WS] Web client terputus. Total client: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

def compute_triage(spo2, bpm, temp, man_down, is_hardware=False, max_ok=True, finger=True):
    if man_down:
        return "red", "MERAH - Kritis (Jatuh / Man-Down)"
    
    # Penanganan hardware fisik jika sensor belum terpasang / belum mengukur
    if is_hardware:
        if not max_ok:
            return "yellow", "KUNING - Sensor Belum Terpasang"
        if not finger:
            return "yellow", "KUNING - Menunggu Jari di Sensor"

    if (spo2 > 0 and spo2 < 85) or bpm > 130 or temp > 39.0:
        return "red", "MERAH - Kritis"
    elif (spo2 > 0 and spo2 < 94) or bpm > 100 or temp > 38.0 or (temp > 0 and temp < 35.5):
        return "yellow", "KUNING - Pengawasan"
    else:
        return "green", "HIJAU - Stabil"

def save_telemetry_to_db(dev_id, spo2, bpm, temp, man_down, lat, lng, rssi=None):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO telemetry_logs (device_id, spo2, heart_rate, body_temperature, is_man_down, rssi, snr) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dev_id, spo2, bpm, temp, 1 if man_down else 0, rssi or -85, 5.0)
        )
        cursor.execute(
            "INSERT INTO gps_logs (device_id, latitude, longitude, altitude) VALUES (?, ?, ?, ?)",
            (dev_id, lat, lng, 35.0)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")

# Background Worker: Hanya mensimulasikan perangkat non-hardware
async def telemetry_stream_loop():
    while True:
        await asyncio.sleep(2.5)

        # Pilih perangkat yang BUKAN hardware fisik
        sim_candidates = [k for k, v in victims_state.items() if not v.get("is_hardware")]
        if not sim_candidates:
            continue

        dev_id = random.choice(sim_candidates)
        v = victims_state[dev_id]

        v["lat"] += (random.random() - 0.5) * 0.0002
        v["lng"] += (random.random() - 0.5) * 0.0002
        v["spo2"] = min(100, max(75, v["spo2"] + random.randint(-2, 2)))
        v["bpm"] = min(160, max(50, v["bpm"] + random.randint(-4, 4)))
        v["temp"] = round(min(41.0, max(34.5, v["temp"] + random.uniform(-0.2, 0.2))), 1)
        v["rssi"] = random.randint(-110, -70)
        v["manDown"] = random.random() < 0.05

        status, status_text = compute_triage(v["spo2"], v["bpm"], v["temp"], v["manDown"])
        v["status"] = status
        v["statusText"] = status_text

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(telemetry_stream_loop())
    print("=" * 68)
    print("VITA-Link Telemetry & Web GIS Server Aktif")
    print("    URL Dashboard   : http://localhost:8000")
    print("    WebSocket API   : ws://localhost:8000/ws/telemetry")
    print("    Hardware Ingest : POST http://localhost:8000/api/telemetry/inject")
    print("=" * 68)
    yield
    task.cancel()

app = FastAPI(title="VITA-Link Telemetry Server", version="2.6", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(DIR_PATH, "index.html"))

@app.get("/api/victims")
async def get_victims():
    return JSONResponse(list(victims_state.values()))

@app.post("/api/telemetry/inject")
async def inject_telemetry(payload: dict):
    """Menerima data fisik nyata dari ESP32 Hardware via Serial Bridge"""
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
            "notes": "Data Diterima dari ESP32 Hardware",
            "is_hardware": True
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

    v = victims_state[dev_id]
    max_ok = v.get("max30102_ok", False)
    finger = v.get("finger", False)

    if v.get("manDown"):
        v["notes"] = "[DARURAT] Terdeteksi Jatuh / Benturan (ADXL345 Man-Down)"
    elif not max_ok:
        v["notes"] = "[INFO] Sensor MAX30102 belum terpasang di pin 21/22 (BPM & SpO2 belum terbaca)"
    elif not finger:
        v["notes"] = "[INFO] Sensor MAX30102 aktif: Tempelkan jari di sensor"
    elif v.get("notes", "").startswith("[DARURAT] Terdeteksi Jatuh") or "belum terpasang" in v.get("notes", ""):
        v["notes"] = "Kondisi fisik normal terpantau"

    status, status_text = compute_triage(
        v["spo2"], v["bpm"], v["temp"], v.get("manDown", False),
        is_hardware=True,
        max_ok=max_ok,
        finger=finger
    )
    v["status"] = status
    v["statusText"] = status_text
    
    save_telemetry_to_db(dev_id, v["spo2"], v["bpm"], v["temp"], v.get("manDown", False), v["lat"], v["lng"], v.get("rssi"))

    await manager.broadcast({
        "type": "TELEMETRY_UPDATE",
        "timestamp": time.time(),
        "source": "HARDWARE_PHYSICAL",
        "updated_device": dev_id,
        "victim": v,
        "all_victims": list(victims_state.values())
    })
    
    mandown_str = "[DARURAT] YA (Jatuh)" if v.get("manDown") else "Normal"
    print(f"[HARDWARE INGEST COM23] {dev_id} -> Suhu: {v['temp']}°C | SpO2: {v['spo2']}% | BPM: {v['bpm']} | ManDown: {mandown_str} | Triage: {status.upper()} (LIVE UPDATE)")
    return {"status": "success", "message": "Hardware telemetry ingested"}

@app.post("/api/victims/{dev_id}/action")
async def update_victim_action(dev_id: str, payload: dict):
    """Memperbarui status evakuasi lapangan korban (DISPATCHED, EVACUATED, RESET)"""
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
    return JSONResponse(status_code=404, content={"status": "error", "message": "Device not found"})



@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_json({
        "type": "INITIAL_STATE",
        "all_victims": list(victims_state.values())
    })
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)