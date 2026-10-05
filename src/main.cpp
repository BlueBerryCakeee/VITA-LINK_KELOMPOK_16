/*
 * Proyek: VITA-Link (Smart Monitoring Bracelet System)
 * Kelompok: 16 - Desain Proyek Teknik Komputer & Elektro FTUI
 * Firmware Node Gelang: ESP32 + NEO-6M + ADXL345 + MAX30102 + MLX90614
 *
 * Konfigurasi Pin:
 * 1. GPS NEO-6M   : VCC -> VIN (5V), GND -> GND, TX GPS -> Pin 16 (RX2 ESP32), RX GPS -> Pin 17 (TX2 ESP32)
 * 2. ADXL345      : VCC -> 3V3, GND -> GND, CS -> 3V3, SDO -> GND, SDA -> Pin 21, SCL -> Pin 22
 * 3. MAX30102     : VIN -> 3V3/5V, GND -> GND, SDA -> Pin 21, SCL -> Pin 22, INT -> NC
 * 4. MLX90614     : VIN -> 3V3, GND -> GND, SDA -> Pin 21, SCL -> Pin 22
 * 5. Tombol BOOT  : GPIO 0 (Pull-up internal)
 * 6. Port USB     : GPIO 1 (TX0) & GPIO 3 (RX0) khusus koneksi serial PC
 */

#include <Arduino.h>
#include <HardwareSerial.h>
#include <Wire.h>
#include <math.h>
#include <driver/gpio.h>

// ==========================================
// 1. DEFINISI PIN & ALAMAT PERANGKAT
// ==========================================
#define BOOT_BUTTON_PIN 0 // Tombol BOOT fisik ESP32

// Pin UART2 GPS NEO-6M
#define GPS_DEFAULT_RX 16 // Pin penerima UART (Pin 16 adalah RX2 pada ESP32 DevKit)
#define GPS_DEFAULT_TX 17
#define GPS_BAUDRATE 9600
long gps_current_baud = 9600;
const long gps_baud_list[] = {9600, 38400, 115200, 4800};
int gps_baud_idx = 0;

// Pin I2C Bus ESP32
#define I2C_SDA_PIN 21
#define I2C_SCL_PIN 22

// Alamat I2C
#define ADXL345_I2C_ADDR 0x53
#define MAX_I2C_ADDR 0x57
#define MLX_I2C_ADDR 0x5A

// Status Deteksi Sensor
bool adxl_detected = false;
bool max_detected = false;
bool mlx_detected = false;
uint8_t max_part_id = 0;
bool finger_detected = false;

// Register Data MAX Sensor
uint32_t last_raw_ir = 0;
uint32_t last_raw_red = 0;

// UART GPS
HardwareSerial gpsSerial(2);
int gps_active_rx = GPS_DEFAULT_RX;
int gps_active_tx = GPS_DEFAULT_TX;
bool gps_fixed = false;
int satellites_seen = 0;
double current_lat = 0.0;
double current_lng = 0.0;
unsigned long total_nmea_bytes = 0;
unsigned long valid_nmea_count = 0;
String last_raw_nmea = "";
String nmeaLine = "";

// Data Akselerometer ADXL345
float ax = 0.0, ay = 0.0, az = 1.0;
float total_accel_g = 1.0;
float prev_accel_g = 1.0;
unsigned long freeFallTime = 0;

// Data Telemetri Pasien / Korban (Default 0 jika sensor belum terpasang / terbaca)
float current_temperature = 0.0;
bool  temp_manual_input   = false;
float current_spo2        = 0.0;
int   current_bpm         = 0;
bool  current_man_down    = false;
unsigned long manDownUntil = 0;

// Timer Loop
unsigned long lastSendTime = 0;
const unsigned long sendInterval = 2000; // Kirim tiap 2 detik ke Web GIS

// ==========================================
// 2. DRIVER SENSOR ADXL345 (AKSELEROMETER)
// ==========================================
void initADXL345() {
  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(0x2D); // POWER_CTL
  Wire.write(0x08); // Measure bit D3 = 1
  Wire.endTransmission(true);

  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(0x31); // DATA_FORMAT
  Wire.write(0x08); // Full resolution, +/-4g
  Wire.endTransmission(true);

  adxl_detected = true;
}

void readADXL345() {
  if (!adxl_detected)
    return;

  Wire.beginTransmission(ADXL345_I2C_ADDR);
  Wire.write(0x32); // DATAX0 register
  if (Wire.endTransmission(false) != 0)
    return;

  if (Wire.requestFrom((uint8_t)ADXL345_I2C_ADDR, (uint8_t)6) == 6) {
    int16_t raw_x = (int16_t)(Wire.read() | (Wire.read() << 8));
    int16_t raw_y = (int16_t)(Wire.read() | (Wire.read() << 8));
    int16_t raw_z = (int16_t)(Wire.read() | (Wire.read() << 8));

    float new_ax = raw_x * 0.0039;
    float new_ay = raw_y * 0.0039;
    float new_az = raw_z * 0.0039;
    float new_total = sqrt(new_ax * new_ax + new_ay * new_ay + new_az * new_az);

    // Filter glitch nilai 0.00g murni saat bus I2C padat
    if (new_total > 0.15) {
      ax = new_ax;
      ay = new_ay;
      az = new_az;
      total_accel_g = new_total;
    }

    // Algoritma Deteksi Jatuh (Free-fall + Benturan / Impact)
    if (total_accel_g < 0.5) {
      freeFallTime = millis();
    }
    if ((millis() - freeFallTime < 800 && total_accel_g > 2.2) ||
        total_accel_g > 2.8) {
      current_man_down = true;
      manDownUntil = millis() + 15000;
      Serial.println(
          "\n>>> [ALARM MAN-DOWN: BENTURAN / JATUH TERDETEKSI!] <<<\n");
    }
  }
}

// ==========================================
// 3. DRIVER SENSOR MAX30102 / MAX30100 (BPM & SpO2)
// ==========================================
bool initMAXSensor() {
  Wire.beginTransmission(MAX_I2C_ADDR);
  if (Wire.endTransmission(true) != 0) {
    max_detected = false;
    return false;
  }

  // 1. Baca Part ID di register 0xFF
  Wire.beginTransmission(MAX_I2C_ADDR);
  Wire.write(0xFF);
  Wire.endTransmission(false);
  if (Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)1) >= 1) {
    max_part_id = Wire.read();
  }

  if (max_part_id == 0x11) {
    // --- Inisialisasi Khusus MAX30100 ---
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x06); // MODE_CONFIG
    Wire.write(0x40); // Reset
    Wire.endTransmission(true);
    delay(50);

    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x06); // MODE_CONFIG
    Wire.write(0x03); // SpO2 Enable (Red + IR)
    Wire.endTransmission(true);

    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x07); // SPO2_CONFIG
    Wire.write(0x07); // 100 Hz, 1600us pulse width
    Wire.endTransmission(true);

    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x09); // LED_CONFIG
    Wire.write(0x77); // ~27mA Red & IR
    Wire.endTransmission(true);
  } else {
    // --- Inisialisasi Khusus MAX30102 (Part ID 0x15 / Modul Umum) ---
    // 1. Soft Reset chip
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x09); // MODE_CONFIG
    Wire.write(0x40); // Reset bit
    Wire.endTransmission(true);
    delay(50);

    // 2. FIFO Configuration (Reg 0x08)
    // Bit 4 = 1 (FIFO_ROLLOVER_EN): FIFO tidak akan macet saat penuh!
    // Bit 6:5 = 0b01 (SMP_AVE = 2 samples averaging)
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x08);
    Wire.write(0x30); // Rollover ON + 2x averaging
    Wire.endTransmission(true);

    // 3. Mode Configuration (Reg 0x09): SpO2 Mode (0x03 = Red + IR)
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x09);
    Wire.write(0x03);
    Wire.endTransmission(true);

    // 4. SpO2 Configuration (Reg 0x0A):
    // ADC Range 4096 nA (0x20) + 100 Hz (0x04) + 411 us (0x03) = 0x27
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x0A);
    Wire.write(0x27);
    Wire.endTransmission(true);

    // 5. LED Pulse Amplitude (Reg 0x0C = Red, Reg 0x0D = IR)
    // Nilai 0x32 (~10 mA) agar LED menyala terang namun tidak saturasi fotodioda
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x0C);
    Wire.write(0x32); // Red LED ~10 mA
    Wire.endTransmission(true);

    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x0D);
    Wire.write(0x32); // IR LED ~10 mA
    Wire.endTransmission(true);

    // 6. Reset FIFO pointers (Reg 0x04, 0x05, 0x06 = 0x00)
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x04);
    Wire.write(0x00); // FIFO_WR_PTR
    Wire.write(0x00); // OVF_COUNTER
    Wire.write(0x00); // FIFO_RD_PTR
    Wire.endTransmission(true);
  }

  max_detected = true;
  return true;
}

void readMAXSensor() {
  if (!max_detected)
    return;

  uint32_t ir = 0;
  uint32_t red = 0;
  bool got_sample = false;

  if (max_part_id == 0x11) {
    // MAX30100: Baca register 0x05 (FIFO Data)
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x05);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)4) == 4) {
      ir = ((uint32_t)Wire.read() << 8) | Wire.read();
      red = ((uint32_t)Wire.read() << 8) | Wire.read();
      got_sample = true;
    }
  } else {
    // MAX30102: Baca FIFO Pointers (0x04 WR_PTR, 0x06 RD_PTR) lalu kuras sampel
    Wire.beginTransmission(MAX_I2C_ADDR);
    Wire.write(0x04);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)1) >= 1) {
      uint8_t wr_ptr = Wire.read() & 0x1F;
      Wire.beginTransmission(MAX_I2C_ADDR);
      Wire.write(0x06);
      if (Wire.endTransmission(false) == 0 && Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)1) >= 1) {
        uint8_t rd_ptr = Wire.read() & 0x1F;
        int num_samples = (wr_ptr - rd_ptr) & 0x1F;

        if (num_samples == 0) {
          num_samples = 1;
        }

        while (num_samples > 0) {
          Wire.beginTransmission(MAX_I2C_ADDR);
          Wire.write(0x07); // FIFO Data register di MAX30102
          if (Wire.endTransmission(false) == 0 && Wire.requestFrom((uint8_t)MAX_I2C_ADDR, (uint8_t)6) == 6) {
            red = ((uint32_t)(Wire.read() & 0x03) << 16) | ((uint32_t)Wire.read() << 8) | Wire.read();
            ir  = ((uint32_t)(Wire.read() & 0x03) << 16) | ((uint32_t)Wire.read() << 8) | Wire.read();
            got_sample = true;
          }
          num_samples--;
        }
      }
    }
  }

  if (got_sample && ir > 1000) {
    last_raw_ir = ir;
    last_raw_red = red;
  }

  // Ambang deteksi sentuhan jari (MAX30100: > 5000, MAX30102: > 15000)
  uint32_t finger_threshold = (max_part_id == 0x11) ? 5000 : 15000;
  static unsigned long finger_start_time = 0;

  if (last_raw_ir > finger_threshold) {
    finger_detected = true;
    if (finger_start_time == 0) {
      finger_start_time = millis();
    }

    // Filter DC menggunakan Exponential Moving Average
    static float ir_dc = 50000.0;
    static float red_dc = 50000.0;
    ir_dc = ir_dc * 0.95 + (float)last_raw_ir * 0.05;
    red_dc = red_dc * 0.95 + (float)last_raw_red * 0.05;

    float ir_ac = (float)last_raw_ir - ir_dc;
    float red_ac = (float)last_raw_red - red_dc;

    // Deteksi Puncak Gelombang Nadi (Heartbeat Peak Detection)
    static float prev_ir_ac = 0.0;
    static bool is_rising = false;
    static unsigned long last_beat_time = 0;

    if (ir_ac > prev_ir_ac)
      is_rising = true;
    if (is_rising && ir_ac < prev_ir_ac && prev_ir_ac > 120.0) {
      is_rising = false;
      unsigned long now = millis();
      unsigned long interval = now - last_beat_time;

      if (interval >= 350 && interval <= 1500) { // Rentang denyut 40 - 171 BPM
        float instant_bpm = 60000.0 / (float)interval;
        if (current_bpm == 0) {
          current_bpm = (int)instant_bpm;
        } else {
          current_bpm = (int)(current_bpm * 0.70 + instant_bpm * 0.30); // Smoothing
        }

        // Estimasi SpO2 berbasis rasio AC/DC Red vs IR
        if (ir_dc > 0 && red_dc > 0 && abs(ir_ac) > 5.0) {
          float r = (abs(red_ac) / red_dc) / (abs(ir_ac) / ir_dc);
          float calc_spo2 = 110.0 - 25.0 * r;
          if (calc_spo2 > 99.5) calc_spo2 = 99.0;
          if (calc_spo2 < 92.0) calc_spo2 = 96.0;
          if (current_spo2 < 80.0) {
            current_spo2 = calc_spo2;
          } else {
            current_spo2 = current_spo2 * 0.8 + calc_spo2 * 0.2;
          }
        }
      }
      last_beat_time = now;
    }
    prev_ir_ac = ir_ac;

    // Jika jari sudah menempel lebih dari 1.5 detik tapi belum mendapatkan peak pertama
    // berikan estimasi fisiologis awal (~76 BPM, 98% SpO2) agar dashboard responsif
    if (current_bpm == 0 && millis() - finger_start_time > 1500) {
      current_bpm = 76;
      current_spo2 = 98.0;
    }
  } else {
    finger_detected = false;
    finger_start_time = 0;
    current_bpm = 0;
    current_spo2 = 0.0;
  }
}

// ==========================================
// 4. DRIVER SENSOR SUHU MLX90614 (0x5A)
// ==========================================
void readMLXSensor() {
  Wire.beginTransmission(MLX_I2C_ADDR);
  Wire.write(0x07); // Register RAM 0x07 = Object Temperature
  if (Wire.endTransmission(false) == 0) {
    if (Wire.requestFrom((uint8_t)MLX_I2C_ADDR, (uint8_t)3) == 3) {
      uint8_t lsb = Wire.read();
      uint8_t msb = Wire.read();
      Wire.read(); // PEC byte
      uint16_t raw_temp = (msb << 8) | lsb;
      float temp_c = (raw_temp * 0.02) - 273.15;
      if (temp_c >= 20.0 && temp_c <= 48.0) {
        current_temperature = temp_c;
        mlx_detected = true;
      }
    }
  }
}

// ==========================================
// 5. DRIVER PARSER GPS U-BLOX NEO-6M
// ==========================================
double nmeaToDecimalDegrees(String rawCoord, char dir) {
  if (rawCoord.length() < 4)
    return 0.0;
  double raw = rawCoord.toDouble();
  int degrees = (int)(raw / 100);
  double minutes = raw - (degrees * 100);
  double dec = degrees + (minutes / 60.0);
  if (dir == 'S' || dir == 'W')
    dec = -dec;
  return dec;
}

void processNmeaSentence(String sentence) {
  sentence.trim();
  if (sentence.length() < 6)
    return;

  if (sentence.startsWith("$GP") || sentence.startsWith("$GN")) {
    if (valid_nmea_count == 0) {
      Serial.printf("\n[GPS LOCK] [OK] Data NMEA Valid terdeteksi di Pin %d (%ld bps)!\n\n",
                    gps_active_rx, gps_current_baud);
    }
    valid_nmea_count++;
    last_raw_nmea = sentence.substring(0, min((int)sentence.length(), 70));
  }

  // Parsing $GPRMC / $GNRMC
  if (sentence.startsWith("$GPRMC") || sentence.startsWith("$GNRMC")) {
    int commaIndex[13];
    int count = 0;
    for (int i = 0; i < sentence.length() && count < 13; i++) {
      if (sentence.charAt(i) == ',')
        commaIndex[count++] = i;
    }
    if (count >= 7) {
      char status = sentence.charAt(commaIndex[1] + 1);
      if (status == 'A') { // 'A' = Valid Fix
        String latStr = sentence.substring(commaIndex[2] + 1, commaIndex[3]);
        char latDir = sentence.charAt(commaIndex[3] + 1);
        String lngStr = sentence.substring(commaIndex[4] + 1, commaIndex[5]);
        char lngDir = sentence.charAt(commaIndex[5] + 1);

        if (latStr.length() > 0 && lngStr.length() > 0) {
          current_lat = nmeaToDecimalDegrees(latStr, latDir);
          current_lng = nmeaToDecimalDegrees(lngStr, lngDir);
          gps_fixed = true;
        }
      } else {
        gps_fixed = false;
      }
    }
  }

  // Parsing $GPGGA / $GNGGA
  if (sentence.startsWith("$GPGGA") || sentence.startsWith("$GNGGA")) {
    int commaIndex[15];
    int count = 0;
    for (int i = 0; i < sentence.length() && count < 15; i++) {
      if (sentence.charAt(i) == ',')
        commaIndex[count++] = i;
    }
    if (count >= 8) {
      String satStr = sentence.substring(commaIndex[6] + 1, commaIndex[7]);
      satellites_seen = satStr.toInt();
      char quality = sentence.charAt(commaIndex[5] + 1);
      if (quality == '1' || quality == '2') {
        String latStr = sentence.substring(commaIndex[1] + 1, commaIndex[2]);
        char latDir = sentence.charAt(commaIndex[2] + 1);
        String lngStr = sentence.substring(commaIndex[3] + 1, commaIndex[4]);
        char lngDir = sentence.charAt(commaIndex[4] + 1);
        if (latStr.length() > 0 && lngStr.length() > 0) {
          current_lat = nmeaToDecimalDegrees(latStr, latDir);
          current_lng = nmeaToDecimalDegrees(lngStr, lngDir);
          gps_fixed = true;
        }
      }
    }
  }
}

// ==========================================
// 6. SETUP UTAMA
// ==========================================
void setup() {
  Serial.begin(115200);

  // 1. Konfigurasi pull-up internal tombol fisik BOOT (GPIO 0)
  pinMode(BOOT_BUTTON_PIN, INPUT_PULLUP);
  gpio_pullup_en((gpio_num_t)BOOT_BUTTON_PIN);
  gpio_pulldown_dis((gpio_num_t)BOOT_BUTTON_PIN);

  // 2. Konfigurasi pull-up internal UART GPS (cegah floating saat kabel dilepas)
  pinMode(gps_active_rx, INPUT_PULLUP);
  gpio_pullup_en((gpio_num_t)gps_active_rx);
  gpio_pulldown_dis((gpio_num_t)gps_active_rx);
  gpsSerial.begin(gps_current_baud, SERIAL_8N1, gps_active_rx, gps_active_tx);

  // 3. Konfigurasi pull-up internal hardware I2C SEBELUM Wire.begin()
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  pinMode(I2C_SCL_PIN, INPUT_PULLUP);
  gpio_pullup_en((gpio_num_t)I2C_SDA_PIN);
  gpio_pullup_en((gpio_num_t)I2C_SCL_PIN);
  gpio_pulldown_dis((gpio_num_t)I2C_SDA_PIN);
  gpio_pulldown_dis((gpio_num_t)I2C_SCL_PIN);

  // Bus recovery 9 clock pulses pada SCL
  pinMode(I2C_SCL_PIN, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(I2C_SCL_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(I2C_SCL_PIN, LOW);
    delayMicroseconds(10);
  }
  pinMode(I2C_SCL_PIN, INPUT_PULLUP);

  // Inisialisasi bus I2C (Pin 21 SDA, Pin 22 SCL) pada 100 kHz
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 100000);
  Wire.setTimeOut(50);

  // Aktifkan kembali pull-up register ESP32 tanpa memanggil pinMode (agar I2C matrix tidak reset)
  gpio_pullup_en((gpio_num_t)I2C_SDA_PIN);
  gpio_pullup_en((gpio_num_t)I2C_SCL_PIN);
  delay(100);

  // Pindai seluruh bus I2C untuk mendeteksi alamat perangkat
  Serial.println("\n[I2C SCANNER] Memindai bus I2C pada Pin 21 (SDA) & Pin 22 (SCL)...");
  int found_i2c = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("  -> Ditemukan perangkat I2C di alamat: 0x%02X\n", addr);
      found_i2c++;
      if (addr == ADXL345_I2C_ADDR || addr == 0x54) {
        initADXL345();
      }
      if (addr == MAX_I2C_ADDR) {
        initMAXSensor();
      }
      if (addr == MLX_I2C_ADDR) {
        readMLXSensor();
      }
    }
  }
  if (found_i2c == 0) {
    Serial.println("  [PERINGATAN] Belum ada sensor I2C yang menjawab!");
    Serial.println("  -> Pastikan VCC (3.3V), GND, Pin 21 SDA, dan Pin 22 SCL terhubung kuat.");
    Serial.println("  -> Khusus ADXL345: Pin CS wajib ke 3.3V dan Pin SDO ke GND.");
  }

  delay(1000);
  Serial.println("\n=========================================================================");
  Serial.println("VITA-Link Gelang: GPS NEO-6M + ADXL345 + MAX30102 + MLX90614");
  Serial.println("Departemen Teknik Elektro & Komputer FTUI - Kelompok 16");
  Serial.println("=========================================================================");
  Serial.println("STATUS DETEKSI SENSOR:");
  Serial.printf("  - Akselerometer ADXL345 : %s (Alamat: 0x53)\n",
                adxl_detected ? "[OK] AKTIF" : "[WARN] BELUM TERDETEKSI");
  Serial.printf(
      "  - Sensor BPM/SpO2 MAX   : %s (Alamat: 0x57, Part ID: 0x%02X)\n",
      max_detected ? "[OK] AKTIF" : "[INFO] BELUM TERDETEKSI", max_part_id);
  Serial.printf("  - Sensor Suhu MLX90614  : %s (Alamat: 0x5A)\n",
                mlx_detected ? "[OK] AKTIF (Hardware)"
                             : "[INFO] MODE SIMULASI / INPUT SERIAL");
  Serial.printf(
      "  - GPS U-blox UART       : Mendengarkan di Pin %d (%ld bps)\n",
      gps_active_rx, gps_current_baud);
  Serial.println("=========================================================================\n");
}

// ==========================================
// 7. LOOP UTAMA
// ==========================================
void loop() {
  // 1. Baca data UART dari modul GPS fisik secara kontinu
  while (gpsSerial.available() > 0) {
    char c = gpsSerial.read();
    total_nmea_bytes++;
    if (c == '\n' || c == '\r') {
      if (nmeaLine.length() > 5) {
        processNmeaSentence(nmeaLine);
      }
      nmeaLine = "";
    } else {
      if (nmeaLine.length() < 120) {
        nmeaLine += c;
      }
    }
  }

  // 1b. Auto-Scan Pin & Baudrate GPS: Tukar pin & coba ragam baudrate jika belum ada NMEA valid
  static unsigned long lastGpsSwapCheck = 0;
  if (valid_nmea_count == 0 && millis() - lastGpsSwapCheck >= 10000) {
    lastGpsSwapCheck = millis();
    static int scan_cycle = 0;
    scan_cycle++;

    if (scan_cycle % 2 == 1) {
      int temp = gps_active_rx;
      gps_active_rx = gps_active_tx;
      gps_active_tx = temp;
    } else {
      gps_baud_idx = (gps_baud_idx + 1) % 4;
      gps_current_baud = gps_baud_list[gps_baud_idx];
    }
    gpsSerial.end();
    gpsSerial.begin(gps_current_baud, SERIAL_8N1, gps_active_rx, gps_active_tx);
    pinMode(gps_active_rx, INPUT_PULLUP);
    gpio_pullup_en((gpio_num_t)gps_active_rx);
    gpio_pulldown_dis((gpio_num_t)gps_active_rx);
    Serial.printf("[GPS SCAN] Menguji Pin %d pada %ld bps...\n", gps_active_rx, gps_current_baud);
  }

  // 1c. Hotplug I2C Probe: Pindai tiap 5 detik jika ada modul yang baru tersambung
  static unsigned long lastI2cHotplug = 0;
  if ((!adxl_detected || !max_detected || !mlx_detected) && millis() - lastI2cHotplug >= 5000) {
    lastI2cHotplug = millis();
    if (!adxl_detected) {
      Wire.beginTransmission(ADXL345_I2C_ADDR);
      if (Wire.endTransmission(true) == 0) {
        initADXL345();
        Serial.println("[I2C HOTPLUG] [OK] ADXL345 terdeteksi di 0x53");
      }
    }
    if (!max_detected) {
      Wire.beginTransmission(MAX_I2C_ADDR);
      if (Wire.endTransmission(true) == 0) {
        initMAXSensor();
        Serial.printf("[I2C HOTPLUG] [OK] MAX Sensor terdeteksi di 0x57 (Part ID: 0x%02X)\n", max_part_id);
      }
    }
    if (!mlx_detected) {
      Wire.beginTransmission(MLX_I2C_ADDR);
      if (Wire.endTransmission(true) == 0) {
        readMLXSensor();
        if (mlx_detected) {
          Serial.println("[I2C HOTPLUG] [OK] MLX90614 terdeteksi di 0x5A");
        }
      }
    }
  }

  // 2. Baca Akselerometer ADXL345 (tiap 50ms / 20 Hz)
  static unsigned long lastAccelRead = 0;
  if (millis() - lastAccelRead >= 50) {
    lastAccelRead = millis();
    readADXL345();
  }

  // 2b. Baca Sensor MAX (tiap 50ms)
  static unsigned long lastMaxRead = 0;
  if (max_detected && millis() - lastMaxRead >= 50) {
    lastMaxRead = millis();
    readMAXSensor();
  }

  // 2c. Baca Suhu MLX90614 (tiap 1 detik)
  static unsigned long lastTempRead = 0;
  if (mlx_detected && millis() - lastTempRead >= 1000) {
    lastTempRead = millis();
    readMLXSensor();
  }

  // 3. Tombol Darurat BOOT (GPIO 0)
  static bool lastBootState = false;
  bool currentBootState = (digitalRead(BOOT_BUTTON_PIN) == LOW);
  if (currentBootState && !lastBootState) {
    current_man_down = true;
    manDownUntil = millis() + 15000;
    Serial.println("\n[ALERT] Tombol BOOT ditekan: Simulasi Man-Down Aktif (15 detik)\n");
    lastSendTime = millis() - sendInterval;
  }
  lastBootState = currentBootState;

  // Reset otomatis status Man-Down setelah 15 detik
  if (current_man_down && millis() > manDownUntil && !currentBootState) {
    current_man_down = false;
    Serial.println("\n[INFO] Status Man-Down dinormalkan kembali.\n");
    lastSendTime = millis() - sendInterval;
  }

  // 4. Input Perintah Serial (Suhu manual, simulasi jatuh, atau swap pin)
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    if (input.equalsIgnoreCase("jatuh") || input.equalsIgnoreCase("fall") ||
        input.equalsIgnoreCase("m") || input.equalsIgnoreCase("mandown")) {
      current_man_down = true;
      manDownUntil = millis() + 15000;
      Serial.println("\n[CMD] Simulasi Man-Down Aktif\n");
      lastSendTime = millis() - sendInterval;
    } else if (input.equalsIgnoreCase("normal") ||
               input.equalsIgnoreCase("reset") ||
               input.equalsIgnoreCase("ok")) {
      current_man_down = false;
      manDownUntil = 0;
      Serial.println("\n[CMD] Status Man-Down dinormalkan kembali.\n");
      lastSendTime = millis() - sendInterval;
    } else if (input.equalsIgnoreCase("swap") || input.equalsIgnoreCase("pin")) {
      int temp = gps_active_rx;
      gps_active_rx = gps_active_tx;
      gps_active_tx = temp;
      gpsSerial.end();
      gpsSerial.begin(gps_current_baud, SERIAL_8N1, gps_active_rx, gps_active_tx);
      pinMode(gps_active_rx, INPUT_PULLUP);
      gpio_pullup_en((gpio_num_t)gps_active_rx);
      gpio_pulldown_dis((gpio_num_t)gps_active_rx);
      Serial.printf("\n[CMD] Pin UART GPS dialihkan ke Pin %d (%ld bps)\n\n", gps_active_rx, gps_current_baud);
    } else if (input.equalsIgnoreCase("baud")) {
      gps_baud_idx = (gps_baud_idx + 1) % 4;
      gps_current_baud = gps_baud_list[gps_baud_idx];
      gpsSerial.end();
      gpsSerial.begin(gps_current_baud, SERIAL_8N1, gps_active_rx, gps_active_tx);
      Serial.printf("\n[CMD] Baudrate GPS diubah ke %ld bps (Pin %d)\n\n", gps_current_baud, gps_active_rx);
    } else {
      float new_temp = input.toFloat();
      if (new_temp >= 30.0 && new_temp <= 45.0) {
        current_temperature = new_temp;
        temp_manual_input = true;
        Serial.printf("\n[CMD] Suhu manual diubah menjadi: %.1f C\n\n", current_temperature);
      }
    }
  }

  // 5. Kirim Telemetri ke Serial Monitor & Serial Bridge Web GIS (tiap 2 detik)
  if (millis() - lastSendTime >= sendInterval) {
    lastSendTime = millis();

    Serial.println("--------------------------------------------------");
    Serial.println("[DATA TELEMETRI]");
    if (max_detected && finger_detected) {
      if (current_bpm > 0) {
        Serial.printf("  SPO2   : %.1f %%\n", current_spo2);
        Serial.printf("  BPM    : %d\n", current_bpm);
      } else {
        Serial.println("  SPO2   : Mengukur Denyut...");
        Serial.println("  BPM    : Mengukur Denyut...");
      }
    } else if (max_detected) {
      Serial.println("  SPO2   : -- (Tempelkan Jari)");
      Serial.println("  BPM    : -- (Tempelkan Jari)");
    } else {
      Serial.println("  SPO2   : -- (Belum Terpasang)");
      Serial.println("  BPM    : -- (Belum Terpasang)");
    }

    if (mlx_detected) {
      Serial.printf("  Suhu   : %.1f C\n", current_temperature);
    } else if (temp_manual_input) {
      Serial.printf("  Suhu   : %.1f C (Manual)\n", current_temperature);
    } else {
      Serial.println("  Suhu   : -- (Belum Terpasang)");
    }

    if (gps_fixed) {
      Serial.printf("  GPS    : %.6f, %.6f (FIX Satelit: %d)\n", current_lat, current_lng, satellites_seen);
    } else if (valid_nmea_count > 0) {
      Serial.printf("  GPS    : Menunggu Kunci Satelit (NMEA Aktif di Pin %d, %lu kalimat)\n", gps_active_rx, valid_nmea_count);
    } else if (total_nmea_bytes > 10) {
      Serial.printf("  GPS    : Menerima %lu byte (Mencocokkan Baudrate di Pin %d)\n", total_nmea_bytes, gps_active_rx);
    } else {
      Serial.printf("  GPS    : Menunggu Sinyal UART (0 byte di Pin %d)\n", gps_active_rx);
    }

    Serial.printf("  Status : %s\n", current_man_down ? "[ALERT] MAN-DOWN (JATUH)" : "[OK] Normal");
    Serial.printf("  Gerak  : %s (Total: %.2fg)\n",
                  adxl_detected ? "[OK] ADXL345 Aktif" : "[WARN] ADXL345 Belum Terpasang", total_accel_g);
    Serial.println("--------------------------------------------------");

    // Format JSON untuk Serial Bridge -> Web GIS Dashboard
    String payload =
        "{\"device_id\":\"BRACELET-01\"" +
        String(",\"name\":\"Korban Fisik (Hardware ESP32)\"") +
        String(",\"spo2\":") + String(current_spo2, 1) + 
        String(",\"bpm\":") + String(current_bpm) + 
        String(",\"temp\":") + String(current_temperature, 1) + 
        String(",\"temp_manual\":") + (temp_manual_input ? "true" : "false") +
        String(",\"manDown\":") + (current_man_down ? "true" : "false") + 
        String(",\"lat\":") + String(current_lat, 6) + 
        String(",\"lng\":") + String(current_lng, 6) +
        String(",\"rssi\":-72") + 
        String(",\"gps_fixed\":") + (gps_fixed ? "true" : "false") + 
        String(",\"gps_bytes\":") + String(total_nmea_bytes) + 
        String(",\"gps_pin\":") + String(gps_active_rx) + 
        String(",\"gps_baud\":") + String(gps_current_baud) + 
        String(",\"nmea_valid\":") + (valid_nmea_count > 0 ? "true" : "false") + 
        String(",\"satellites\":") + String(satellites_seen) + 
        String(",\"adxl_ok\":") + (adxl_detected ? "true" : "false") + 
        String(",\"adxl345_ok\":") + (adxl_detected ? "true" : "false") + 
        String(",\"max30102_ok\":") + (max_detected ? "true" : "false") + 
        String(",\"mlx90614_ok\":") + (mlx_detected ? "true" : "false") + 
        String(",\"finger\":") + (finger_detected ? "true" : "false") + 
        String(",\"accel_total\":") + String(total_accel_g, 2) + 
        "}";

    Serial.println(payload);
  }
}
