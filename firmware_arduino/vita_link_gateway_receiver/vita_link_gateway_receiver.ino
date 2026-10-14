/*
 * VITA-Link Gateway LoRa Receiver (Posko Base Station)
 * Kelompok 16 - Desain Proyek FTUI
 *
 * Pinout SPI SX1276:
 * SCK: 18, MISO: 19, MOSI: 23, NSS: 5, RST: 2, DIO0: 4
 * Frekuensi: 915 MHz
 */

#include <Arduino.h>
#include <SPI.h>

#define LORA_SCK_PIN   18
#define LORA_MISO_PIN  19
#define LORA_MOSI_PIN  23
#define LORA_SS_PIN    5
#define LORA_RST_PIN   2
#define LORA_DIO0_PIN  4
#define LORA_FREQUENCY 915E6 // 915 MHz (Frekuensi Indonesia SDPPI)

// Register SX1276 LoRa
#define LORA_REG_FIFO                 0x00
#define LORA_REG_OP_MODE              0x01
#define LORA_REG_FRF_MSB              0x06
#define LORA_REG_FRF_MID              0x07
#define LORA_REG_FRF_LSB              0x08
#define LORA_REG_PA_CONFIG            0x09
#define LORA_REG_FIFO_ADDR_PTR        0x0D
#define LORA_REG_FIFO_TX_BASE_ADDR    0x0E
#define LORA_REG_FIFO_RX_BASE_ADDR    0x0F
#define LORA_REG_FIFO_RX_CURRENT_ADDR 0x10
#define LORA_REG_IRQ_FLAGS            0x12
#define LORA_REG_RX_NB_BYTES          0x13
#define LORA_REG_PKT_SNR_VALUE        0x19
#define LORA_REG_PKT_RSSI_VALUE       0x1A
#define LORA_REG_MODEM_CONFIG_1       0x1D
#define LORA_REG_MODEM_CONFIG_2       0x1E
#define LORA_REG_PREAMBLE_MSB         0x20
#define LORA_REG_PREAMBLE_LSB         0x21
#define LORA_REG_MODEM_CONFIG_3       0x26
#define LORA_REG_SYNC_WORD            0x39
#define LORA_REG_VERSION              0x42

// Mode Operasi
#define LORA_MODE_LONG_RANGE          0x80
#define LORA_MODE_SLEEP               0x00
#define LORA_MODE_STDBY               0x01
#define LORA_MODE_RX_CONTINUOUS       0x05

bool lora_ok = false;
unsigned long packets_received = 0;

uint8_t loraReadRegister(uint8_t address) {
  digitalWrite(LORA_SS_PIN, LOW);
  SPI.transfer(address & 0x7F);
  uint8_t val = SPI.transfer(0x00);
  digitalWrite(LORA_SS_PIN, HIGH);
  return val;
}

void loraWriteRegister(uint8_t address, uint8_t val) {
  digitalWrite(LORA_SS_PIN, LOW);
  SPI.transfer(address | 0x80);
  SPI.transfer(val);
  digitalWrite(LORA_SS_PIN, HIGH);
}

bool initLoRaReceiver() {
  pinMode(LORA_SS_PIN, OUTPUT);
  pinMode(LORA_RST_PIN, OUTPUT);
  digitalWrite(LORA_SS_PIN, HIGH);

  // Reset Hardware
  digitalWrite(LORA_RST_PIN, LOW);
  delay(10);
  digitalWrite(LORA_RST_PIN, HIGH);
  delay(10);

  SPI.begin(LORA_SCK_PIN, LORA_MISO_PIN, LORA_MOSI_PIN, LORA_SS_PIN);

  uint8_t version = loraReadRegister(LORA_REG_VERSION);
  if (version != 0x12) {
    Serial.printf("[GATEWAY] Chip ID terbaca 0x%02X (diharapkan 0x12). Modul LoRa belum terdeteksi!\n", version);
    return false;
  }

  // Masuk Sleep Mode
  loraWriteRegister(LORA_REG_OP_MODE, LORA_MODE_LONG_RANGE | LORA_MODE_SLEEP);
  delay(10);

  // Set Frekuensi
  uint64_t frf = ((uint64_t)LORA_FREQUENCY << 19) / 32000000;
  loraWriteRegister(LORA_REG_FRF_MSB, (uint8_t)(frf >> 16));
  loraWriteRegister(LORA_REG_FRF_MID, (uint8_t)(frf >> 8));
  loraWriteRegister(LORA_REG_FRF_LSB, (uint8_t)(frf >> 0));

  // FIFO Base Address
  loraWriteRegister(LORA_REG_FIFO_TX_BASE_ADDR, 0x00);
  loraWriteRegister(LORA_REG_FIFO_RX_BASE_ADDR, 0x00);

  // PA Config
  loraWriteRegister(LORA_REG_PA_CONFIG, 0x8F);

  // Modem Config: BW 125kHz, CR 4/5, SF7, CRC On
  loraWriteRegister(LORA_REG_MODEM_CONFIG_1, 0x72);
  loraWriteRegister(LORA_REG_MODEM_CONFIG_2, 0x74);
  loraWriteRegister(LORA_REG_MODEM_CONFIG_3, 0x04);

  // Preamble 8 & Sync Word 0x12
  loraWriteRegister(LORA_REG_PREAMBLE_MSB, 0x00);
  loraWriteRegister(LORA_REG_PREAMBLE_LSB, 0x08);
  loraWriteRegister(LORA_REG_SYNC_WORD, 0x12);

  // Masuk Mode RX Continuous (Mendengarkan paket terus menerus)
  loraWriteRegister(LORA_REG_OP_MODE, LORA_MODE_LONG_RANGE | LORA_MODE_RX_CONTINUOUS);

  Serial.printf("[GATEWAY] LoRa Receiver Siap pada %.1f MHz (SF7, BW 125kHz, SyncWord 0x12)\n", (double)(LORA_FREQUENCY / 1E6));
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n[GATEWAY] VITA-Link LoRa Receiver Posko SAR Siap");

  lora_ok = initLoRaReceiver();
  if (!lora_ok) {
    Serial.println("[ERROR] Inisialisasi LoRa gagal! Cek jumper SPI: SCK=18, MISO=19, MOSI=23, NSS=5, RST=2");
  }
}

void loop() {
  if (!lora_ok) {
    delay(1000);
    return;
  }

  // Cek apakah ada IRQ RxDone (Bit 6 RegIrqFlags)
  uint8_t irq = loraReadRegister(LORA_REG_IRQ_FLAGS);
  if (irq & 0x40) { // RxDone
    // Cek CRC error (Bit 5)
    bool crc_error = (irq & 0x20) != 0;

    // Clear IRQ flags
    loraWriteRegister(LORA_REG_IRQ_FLAGS, 0xFF);

    if (!crc_error) {
      uint8_t current_addr = loraReadRegister(LORA_REG_FIFO_RX_CURRENT_ADDR);
      uint8_t nb_bytes = loraReadRegister(LORA_REG_RX_NB_BYTES);

      loraWriteRegister(LORA_REG_FIFO_ADDR_PTR, current_addr);

      String packet = "";
      for (int i = 0; i < nb_bytes; i++) {
        packet += (char)loraReadRegister(LORA_REG_FIFO);
      }

      // Hitung RSSI dan SNR
      int raw_rssi = loraReadRegister(LORA_REG_PKT_RSSI_VALUE);
      int rssi = -157 + raw_rssi; // 915 MHz offset -157
      int raw_snr = (int8_t)loraReadRegister(LORA_REG_PKT_SNR_VALUE);
      float snr = raw_snr * 0.25;

      packets_received++;

      // Jika packet adalah JSON, suntikkan RSSI dan SNR aktual dari gateway
      if (packet.startsWith("{") && packet.endsWith("}")) {
        packet = packet.substring(0, packet.length() - 1); // Buang '}' penutup
        packet += ",\"gateway_rssi\":" + String(rssi) + ",\"gateway_snr\":" + String(snr, 1) + "}";
      }

      // Cetak payload JSON ke Serial Monitor / serial_bridge.py
      Serial.println(packet);
    }
  }
}
