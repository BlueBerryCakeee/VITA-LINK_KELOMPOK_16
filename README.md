# VITA-Link: Sistem Pemantau Cerdas & Triage GIS Korban Bencana

Proyek Desain Proyek Kelompok 16 - Departemen Teknik Elektro & Komputer FTUI.

---

## 1. Struktur Repositori

```text
VITA-LINK_KELOMPOK_16/
├── src/
│   └── main.cpp                        # Firmware ESP32 (Untuk pengguna VS Code + PlatformIO)
├── platformio.ini                      # Konfigurasi PlatformIO (Board & Library ESP32)
├── firmware_arduino/
│   └── esp32_gps_adxl345_tester/
│       └── esp32_gps_adxl345_tester.ino # Firmware ESP32 (Untuk pengguna Arduino IDE)
├── serial_bridge.py                    # Gateway pembaca serial USB ESP32 -> Kirim ke Web GIS
├── server.py                           # Backend Web GIS Server (FastAPI + WebSocket)
├── index.html                          # Frontend Tactical Dashboard Web GIS
├── schema.sql                          # Skema database SQLite telemetri
└── requirements.txt                    # Dependensi Python
```

---

## 2. Diagram Perkabelan Sensor ke ESP32

| Modul Sensor | Pin Sensor | Terhubung ke ESP32 | Keterangan |
| :--- | :--- | :--- | :--- |
| **GPS NEO-6M** | **VCC** | **VIN (5V USB)** | Wajib 5V/VIN agar modul stabil |
| | **GND** | **GND** | Ground bersama |
| | **TX** | **GPIO 16 (RX2)** | Data keluar GPS masuk ke RX2 ESP32 |
| | **RX** | **GPIO 17 (TX2)** | Opsional / NC |
| **I2C Bus Bersama** | **SDA** | **GPIO 21 (SDA)** | Terhubung paralel ke SDA semua sensor |
| | **SCL** | **GPIO 22 (SCL)** | Terhubung paralel ke SCL semua sensor |
| **ADXL345** | **VCC** | **3V3** | Tegangan logika 3.3V |
| | **GND** | **GND** | Ground |
| | **CS** | **3V3** | Memilih mode I2C |
| | **SDO** | **GND** | Alamat I2C 0x53 |
| **MAX30102** | **VIN** | **3V3 / 5V** | Sensor SpO2 & Heart Rate |
| | **GND** | **GND** | Ground |
| **MLX90614** | **VIN** | **3V3** | Sensor Suhu Inframerah |
| | **GND** | **GND** | Ground |

---

## 3. Cara Upload Firmware

### Opsi A: Menggunakan VS Code + PlatformIO
1. Buka folder ini di **VS Code** dengan ekstensi **PlatformIO**.
2. Hubungkan ESP32 via kabel USB Type-C ke laptop.
3. Klik tombol centang (**Build**), lalu klik panah kanan (**Upload**).

### Opsi B: Menggunakan Arduino IDE
1. Buka file `firmware_arduino/esp32_gps_adxl345_tester/esp32_gps_adxl345_tester.ino` di **Arduino IDE**.
2. Pilih Board: **DOIT ESP32 DEVKIT V1**.
3. Pilih Port COM yang sesuai.
4. Klik tombol **Upload**.

---

## 4. Cara Menjalankan Pengiriman Data (Serial Bridge)

1. Pasang dependensi:
   ```bash
   pip install -r requirements.txt
   ```
2. Jalankan jembatan serial ke IP laptop server:
   ```bash
   python serial_bridge.py --server http://<IP_LAPTOP_SERVER>:8000
   ```
   *(Port COM ESP32 akan terdeteksi otomatis).*

---

## 5. Menjalankan Server Web GIS Sendiri (Opsional)
```bash
python server.py
```
Buka browser di `http://localhost:8000`.
