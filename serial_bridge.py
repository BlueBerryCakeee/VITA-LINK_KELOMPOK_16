# VITA-Link - Serial Port Bridge Gateway (ESP32 -> Server)
# Kelompok 16 - Desain Proyek FTUI

import argparse
import json
import os
import sys
import threading
import time
import requests
import serial
import serial.tools.list_ports

DEFAULT_SERVER_URL = "http://localhost:8000/api/telemetry/inject"

def list_available_ports():
    ports = serial.tools.list_ports.comports()
    print("\n=== DAFTAR PORT SERIAL TERDETEKSI ===")
    for p in ports:
        print(f"  • {p.device:<8} : {p.description}")
    print("=====================================\n")
    return ports

def auto_detect_esp32_port(preferred_port=None):
    ports = serial.tools.list_ports.comports()
    if not ports:
        return preferred_port or "COM23"
    
    port_devices = [p.device.upper() for p in ports]
    if preferred_port and preferred_port.upper() in port_devices:
        return preferred_port
        
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if any(keyword in desc or keyword in hwid for keyword in ["ch340", "cp210", "usb-serial", "uart", "esp32"]):
            return p.device
            
    return ports[0].device

def parse_telemetry_line(raw_line):
    raw_line = raw_line.strip()
    if not raw_line:
        return None

    # Format JSON terstruktur dari ESP32
    if raw_line.startswith("{") and raw_line.endswith("}"):
        try:
            return json.loads(raw_line)
        except Exception:
            pass

    # Format CSV: device_id,spo2,bpm,temp,man_down,lat,lng,rssi
    parts = raw_line.split(",")
    if len(parts) >= 8:
        try:
            return {
                "device_id": parts[0].strip(),
                "spo2": float(parts[1]),
                "bpm": int(float(parts[2])),
                "temp": float(parts[3]),
                "manDown": bool(int(parts[4])),
                "lat": float(parts[5]),
                "lng": float(parts[6]),
                "rssi": int(float(parts[7]))
            }
        except Exception:
            pass

    return None

def console_input_loop(ser):
    """Thread latar belakang untuk mengirimkan input interaktif jika pengguna mengetik angka atau perintah"""
    while True:
        try:
            user_input = sys.stdin.readline().strip()
            if user_input and ser and ser.is_open:
                ser.write((user_input + "\n").encode("utf-8"))
                print(f"  [PERINTAH DIKIRIM KE ESP32] -> {user_input}")
        except Exception:
            break

def run_serial_bridge(port_name="auto", baud_rate=115200, server_url=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    target_port = auto_detect_esp32_port(port_name if port_name and port_name.lower() != "auto" else None)
    inject_url = server_url or DEFAULT_SERVER_URL
    if not inject_url.endswith("/api/telemetry/inject"):
        inject_url = inject_url.rstrip("/") + "/api/telemetry/inject"

    print("\n========================================================")
    print(f"VITA-Link Serial Bridge Gateway")
    print(f"Target Port  : {target_port} (Baudrate: {baud_rate})")
    print(f"Target Server: {inject_url}")
    print("========================================================")
    print("Petunjuk Kontrol:")
    print("  - Tombol BOOT di ESP32 : Memicu alarm Man-Down (Jatuh)")
    print("  - Ketik 'jatuh' / 'm'  : Simulasi Man-Down")
    print("  - Ketik 'swap' / 'pin' : Alihkan pin UART GPS")
    print("  - Ketik 'baud'         : Ganti baudrate GPS (9600/38400/115200/4800)")
    print("  - Ketik angka suhu     : Ubah suhu tubuh (misal: 38.5)")
    print("========================================================\n", flush=True)

    while True:
        ser = None
        try:
            print(f"[*] Menghubungkan ke port {target_port}...", flush=True)
            ser = serial.Serial(target_port, baud_rate, timeout=1.0)
            time.sleep(1.5)
            print(f"[OK] Terhubung ke {target_port}. ESP32 siap berkomunikasi.\n", flush=True)

            # Mulai thread input console jika belum aktif
            input_thread = threading.Thread(target=console_input_loop, args=(ser,), daemon=True)
            input_thread.start()

            while True:
                if ser.in_waiting > 0:
                    raw = ser.readline().decode("utf-8", errors="replace").strip().replace("\r", "")
                    if not raw:
                        continue

                    # Tampilkan notifikasi event penting dari ESP32
                    if raw.startswith("[CMD]") or raw.startswith("[ALERT]") or raw.startswith("[GPS") or raw.startswith("[I2C HOTPLUG]"):
                        print(f"[EVENT] {raw}\n", flush=True)
                        continue

                    # Saring baris header atau debug mentah agar tidak menumpuk di terminal
                    if (raw.startswith("---") or raw.startswith("===") or "VITA-Link" in raw or 
                        "STATUS DETEKSI" in raw or "Departemen" in raw or raw.startswith("- Akselerometer") or 
                        raw.startswith("- Sensor") or raw.startswith("- GPS") or raw.startswith("[DATA TELEMETRI]") or 
                        raw.startswith("  SPO2") or raw.startswith("  BPM") or raw.startswith("  Suhu") or 
                        raw.startswith("  GPS") or raw.startswith("  Status") or raw.startswith("  Gerak")):
                        continue

                    data = parse_telemetry_line(raw)
                    if data:
                        bpm_val    = data.get('bpm', 0)
                        spo2_val   = data.get('spo2', 0)
                        temp_val   = data.get('temp', 0)
                        lat_val    = data.get('lat', 0.0)
                        lng_val    = data.get('lng', 0.0)
                        gps_fixed  = data.get('gps_fixed', False)
                        gps_bytes  = data.get('gps_bytes', 0)
                        nmea_valid = data.get('nmea_valid', False)
                        gps_baud   = data.get('gps_baud', 9600)
                        sats_seen  = data.get('satellites', 0)
                        adxl_ok    = data.get('adxl345_ok', False) or data.get('adxl_ok', False)
                        max_ok     = data.get('max30102_ok', False)
                        finger     = data.get('finger', False)
                        man_down   = data.get('manDown', False)
                        gps_pin    = data.get('gps_pin', 16)

                        if max_ok and finger:
                            if bpm_val > 0:
                                spo2_str = f"{spo2_val:.1f} %"
                                bpm_str  = f"{bpm_val} bpm"
                            else:
                                spo2_str = "Mengukur Denyut..."
                                bpm_str  = "Mengukur Denyut..."
                        elif max_ok and not finger:
                            spo2_str = "-- (Tempelkan Jari)"
                            bpm_str  = "-- (Tempelkan Jari)"
                        else:
                            spo2_str = "-- (Belum Terpasang)"
                            bpm_str  = "-- (Belum Terpasang)"

                        mlx_ok = data.get('mlx90614_ok', False)
                        temp_manual = data.get('temp_manual', False)
                        if mlx_ok:
                            temp_str = f"{temp_val:.1f} C"
                        elif temp_manual:
                            temp_str = f"{temp_val:.1f} C (Manual)"
                        else:
                            temp_str = "-- (Belum Terpasang)"

                        if gps_fixed and lat_val != 0.0:
                            gps_str = f"{lat_val:.6f}, {lng_val:.6f} (FIX - Satelit: {sats_seen})"
                        elif nmea_valid:
                            gps_str = f"Sinyal NMEA Aktif ({gps_bytes} byte di Pin {gps_pin}, {gps_baud} bps) - Menunggu Kunci Satelit"
                        elif gps_bytes > 10:
                            gps_str = f"Menerima Data UART ({gps_bytes} byte di Pin {gps_pin}) - Mencari Baudrate/NMEA"
                        else:
                            gps_str = f"Menunggu Sinyal UART (0 byte di Pin {gps_pin})"

                        status_str = "[ALERT] MAN-DOWN (JATUH)" if man_down else "[OK] Normal"

                        # Kirim ke backend Web GIS
                        web_status = ""
                        try:
                            res = requests.post(inject_url, json=data, timeout=1.5)
                            if res.status_code == 200:
                                web_status = "[OK] Terkirim ke Web GIS"
                        except requests.exceptions.ConnectionError:
                            web_status = "[WARN] Server offline"
                        except Exception as err:
                            web_status = f"[ERROR] {err}"

                        # Tampilkan telemetri dalam format baris vertikal yang rapi
                        print("--------------------------------------------------")
                        print("[DATA TELEMETRI]")
                        print(f"  SPO2   : {spo2_str}")
                        print(f"  BPM    : {bpm_str}")
                        print(f"  Suhu   : {temp_str}")
                        print(f"  GPS    : {gps_str}")
                        print(f"  Status : {status_str}")
                        print(f"  Server : {web_status}")
                        print("--------------------------------------------------\n", flush=True)
                    else:
                        print(f"[RAW] {raw}")
                time.sleep(0.02)

        except serial.serialutil.SerialException as se:
            print(f"\n[WARN] Port terkunci atau terputus: {se}")
            print("       Tutup Serial Monitor di Arduino IDE jika masih terbuka.")
            print("       Mencoba menghubungkan kembali dalam 3 detik...\n")
            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass
            time.sleep(3)
        except KeyboardInterrupt:
            print("\n[*] Menutup serial bridge atas permintaan pengguna.")
            if ser and ser.is_open:
                ser.close()
            break
        except Exception as e:
            print(f"[ERROR] Terjadi error: {e}. Mengulang dalam 3 detik...")
            time.sleep(3)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VITA-Link Serial Port Ingestion Bridge")
    parser.add_argument("--port", type=str, default="auto", help="Nama port COM ESP32 (default: auto-detect)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--server", type=str, default=DEFAULT_SERVER_URL, help="URL Backend Web GIS (misal: http://192.168.1.10:8000)")
    args = parser.parse_args()

    run_serial_bridge(args.port, args.baud, args.server)