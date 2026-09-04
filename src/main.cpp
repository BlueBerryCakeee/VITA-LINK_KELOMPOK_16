#include <Arduino.h>

// Draf Haar DWT Lifting Scheme (1D) untuk filter sinyal PPG
void haarLiftingScheme(float* signal, int length) {
    for (int i = 0; i < length / 2; i++) {
        float detail = signal[2*i + 1] - signal[2*i]; 
        float approx = signal[2*i] + detail / 2.0;    
        signal[i] = approx;
        signal[length/2 + i] = detail;
    }
}

// Logika Adaptive Sampling berbasis Early Warning Score (EWS)
int getSamplingInterval(int ewsScore) {
    if (ewsScore == 0) return 30000;      // Status Hijau: 30 detik[cite: 1]
    else if (ewsScore <= 4) return 10000; // Status Kuning: 10 detik[cite: 1]
    else return 0;                        // Status Merah: Maksimal/Kontinu[cite: 1]
}

void setup() {
  Serial.begin(115200);
  Serial.println("Sistem VITA-LINK Diinisialisasi");
}

void loop() {
  // Looping utama dikosongkan sementara menunggu driver sensor I2C
}