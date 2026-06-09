/*
 * ============================================================
 *  Power Debug System — Teensy 4.0 Firmware
 * ============================================================
 *
 *  Rolle   : SPI Slave (RPi Zero W ist Master)
 *  Funktion: Erfasst Telemetriedaten, packt sie als Binärpaket
 *            und signalisiert dem RPi Zero W via DATA_READY,
 *            dass ein neues Paket abholbereit ist.
 *
 *  Paket-Format (Little-Endian):
 *    [0..3]   Header   : uint32_t = 0xDEADBEEF (Magic)
 *    [4..7]   Timestamp: uint32_t = micros()
 *    [8..4007] Data    : float32_t[1000]
 *    Gesamt  : 4008 Bytes
 *
 *  Dummy-Füllung: Nicht verwendete Kanäle werden mit 9898.0f
 *                 gefüllt und vom RPi 5 herausgefiltert.
 *
 *  Pinbelegung SPI0:
 *    SCK  → Pin 13   (Takt, vom RPi Zero getrieben)
 *    MOSI → Pin 11   (RPi → Teensy, für zukünftige Befehle)
 *    MISO → Pin 12   (Teensy → RPi, Nutzdaten)
 *    CS   → Pin 10   (Chip-Select, vom RPi Zero getrieben)
 *    DATA_READY → Pin 9 (Ausgang, HIGH = neues Paket bereit)
 *
 *  Benötigte Bibliothek:
 *    SPISlave_T4 by tonton81
 *    https://github.com/tonton81/SPISlave_T4
 * ============================================================
 */

#include <Arduino.h>
#include "SPISlave_T4.h"

// ── Compile-Time Konfiguration ───────────────────────────────────────────────
#ifndef ACTIVE_CHANNELS
  #define ACTIVE_CHANNELS 500
#endif

static constexpr uint32_t HEADER_MAGIC     = 0xDEADBEEFUL;
static constexpr int      MAX_FLOATS       = 1000;
static constexpr int      PACKET_BYTES     = 8 + MAX_FLOATS * 4;   // 4008
static constexpr uint32_t SAMPLE_PERIOD_US = 10000UL;              // 10 ms = 100 Hz
static constexpr int      DATA_READY_PIN   = 9;

// ── SPI-Slave Instanz (SPI0, 8-Bit-Wörter) ──────────────────────────────────
SPISlave_T4<&SPI, SPI_8_BITS> spiSlave;

// ── Ping-Pong-Puffer ─────────────────────────────────────────────────────────
//    ptr_active : ISR liest hieraus (wird per SPI gesendet)
//    ptr_filling: Loop schreibt hierein (nie gleichzeitig mit ISR)
DMAMEM static uint8_t buf_A[PACKET_BYTES];
DMAMEM static uint8_t buf_B[PACKET_BYTES];

static uint8_t* volatile ptr_active  = buf_A;
static uint8_t* volatile ptr_filling = buf_B;

static volatile uint32_t send_index   = 0;
static volatile bool     transfer_done = true;

// ── Paket befüllen ───────────────────────────────────────────────────────────
static float phase = 0.0f;

void buildPacket(uint8_t* dst) {
    // Header
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(dst,     &magic, 4);
    memcpy(dst + 4, &ts,    4);

    // Nutzdaten
    float* data = reinterpret_cast<float*>(dst + 8);

    for (int i = 0; i < MAX_FLOATS; i++) {
        if (i < ACTIVE_CHANNELS) {
            // ── HIER echte Sensorwerte einsetzen ──────────────────────────────
            // Beispiel: data[i] = sensors.read(i);
            //
            // Testmuster: Sinuswelle pro Kanal + leichtes Rauschen
            data[i] = sinf(phase + i * 0.025f) * 3.3f
                    + cosf(phase * 0.5f + i * 0.01f) * 0.1f;
        } else {
            data[i] = 9898.0f;   // Dummy-Füllung
        }
    }

    phase += 0.05f;
    if (phase > TWO_PI) phase -= TWO_PI;
}

// ── SPI ISR: für jedes Byte, das der Master clocked ─────────────────────────
// FASTRUN: Funktion wird in RAM geladen → minimale Latenz
void FASTRUN onSPIData() {
    while (spiSlave.available()) {
        (void)spiSlave.popr();    // RX-Byte lesen (Dummy vom Master)

        // TX-Byte aus dem aktiven Puffer senden
        const uint8_t tx_byte = (send_index < (uint32_t)PACKET_BYTES)
                                 ? ptr_active[send_index++]
                                 : 0x00;
        spiSlave.pushr(tx_byte);
    }

    // Transfer abgeschlossen?
    if (send_index >= (uint32_t)PACKET_BYTES) {
        send_index    = 0;
        transfer_done = true;
        digitalWriteFast(DATA_READY_PIN, LOW);
    }
}

// ── Setup ────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(400);

    pinMode(DATA_READY_PIN, OUTPUT);
    digitalWriteFast(DATA_READY_PIN, LOW);

    // Ersten Puffer vorausfüllen
    buildPacket(ptr_active);

    spiSlave.begin();
    spiSlave.onReceive(onSPIData);

    Serial.printf("[Teensy] Bereit | Paket: %d Bytes | Kanäle: %d | %.0f Hz\n",
                  PACKET_BYTES, ACTIVE_CHANNELS, 1e6f / SAMPLE_PERIOD_US);
}

// ── Hauptschleife ────────────────────────────────────────────────────────────
static uint32_t pkt_count = 0;

void loop() {
    static uint32_t last_us      = 0;
    static uint32_t last_stat_ms = 0;

    const uint32_t now = micros();

    // ── Alle 10 ms: neues Paket bauen und bereitstellen ─────────────────────
    if (now - last_us >= SAMPLE_PERIOD_US) {
        last_us = now;

        // Neues Paket in den Fill-Puffer schreiben (ISR greift hier NICHT zu)
        buildPacket(ptr_filling);

        // Atomischen Puffertausch nur wenn vorheriger Transfer abgeschlossen
        if (transfer_done) {
            noInterrupts();                 // Minimaler kritischer Abschnitt
            uint8_t* tmp = ptr_active;      // Pointer-Swap (keine Datenkopie!)
            ptr_active   = ptr_filling;
            ptr_filling  = tmp;
            send_index    = 0;
            transfer_done = false;
            interrupts();

            // DATA_READY HIGH → RPi Zero initiiert SPI-Transfer
            digitalWriteFast(DATA_READY_PIN, HIGH);
            pkt_count++;
        }
        // Falls Transfer noch läuft: Paket überspringen (sollte bei 10ms/3.2ms nie passieren)
    }

    // ── Statistik alle 5 Sekunden auf Serial ausgeben ───────────────────────
    const uint32_t now_ms = millis();
    if (now_ms - last_stat_ms >= 5000) {
        last_stat_ms = now_ms;
        Serial.printf("[Teensy] %lu Pakete/5s | %.1f Hz\n",
                      pkt_count, pkt_count / 5.0f);
        pkt_count = 0;
    }
}
