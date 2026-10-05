-- ==========================================================
-- PROYEK: VITA-Link (Smart Monitoring Bracelet System)
-- MODUL: Skema Database Telemetri Medis & Log Triage Posko
-- PIC: Ahmad Fariz Khairi (2306211370) - Bidang Software / Data
-- ==========================================================

-- 1. Tabel Master Pasien / Korban Bencana
CREATE TABLE IF NOT EXISTS patients (
    patient_id VARCHAR(20) PRIMARY KEY,
    device_id VARCHAR(50) UNIQUE NOT NULL,
    patient_name VARCHAR(100) DEFAULT 'Korban Anonim',
    age INTEGER,
    gender VARCHAR(10),
    assigned_triage VARCHAR(10) DEFAULT 'GREEN', -- 'RED', 'YELLOW', 'GREEN', 'BLACK'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Tabel Log Telemetri Medis Real-Time (SpO2, BPM, Suhu Tubuh)
CREATE TABLE IF NOT EXISTS telemetry_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id VARCHAR(50) NOT NULL,
    spo2 FLOAT NOT NULL,                    -- Saturasi Oksigen (%)
    heart_rate INTEGER NOT NULL,            -- Denyut Nadi (BPM)
    body_temperature FLOAT NOT NULL,        -- Suhu Tubuh (Celsius)
    is_man_down BOOLEAN DEFAULT 0,          -- Status Jatuh / Man-Down (0 = Normal, 1 = Jatuh)
    rssi INTEGER,                           -- Kuat Sinyal LoRa (dBm)
    snr FLOAT,                              -- Signal-to-Noise Ratio (dB)
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(device_id) REFERENCES patients(device_id)
);

-- 3. Tabel Log Koordinat GPS & Riwayat Pelacakan Lokasi
CREATE TABLE IF NOT EXISTS gps_logs (
    gps_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id VARCHAR(50) NOT NULL,
    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,
    altitude FLOAT,
    speed FLOAT,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(device_id) REFERENCES patients(device_id)
);

-- 4. Tabel Histori Perubahan Skor Triage (Early Warning Score - EWS)
CREATE TABLE IF NOT EXISTS triage_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id VARCHAR(50) NOT NULL,
    ews_score INTEGER NOT NULL,
    triage_color VARCHAR(10) NOT NULL,      -- 'RED', 'YELLOW', 'GREEN', 'BLACK'
    trigger_reason VARCHAR(255),            -- Alasan perubahan status
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(device_id) REFERENCES patients(device_id)
);

-- Inisialisasi Data Dummy Pasien
INSERT OR IGNORE INTO patients (patient_id, device_id, patient_name, age, gender, assigned_triage, notes) VALUES
('P-01', 'BRACELET-01', 'Korban A (Trauma Dada)', 45, 'Pria', 'RED', 'Trauma dada berat, sesak napas'),
('P-02', 'BRACELET-02', 'Korban B (Fraktur Kaki)', 32, 'Wanita', 'YELLOW', 'Fraktur femur tertutup, hemodinamik stabil'),
('P-03', 'BRACELET-03', 'Korban C (Luka Ringan)', 21, 'Pria', 'GREEN', 'Luka abrasi ringan, sadar penuh'),
('P-04', 'BRACELET-04', 'Korban D (Hipotermia)', 58, 'Pria', 'YELLOW', 'Kedinginan di area reruntuhan baseline SpO2 93%');
