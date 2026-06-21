/*
 * ============================================================
 *  Power Debug System — Teensy 4.0 Firmware  (UART Version)
 * ============================================================
 *
 *  Rolle   : UART Sender (RPi Zero W empfängt)
 *  Funktion: Erfasst Telemetriedaten, packt sie als Binärpaket
 *            und sendet es mit 100 Hz per UART an den RPi Zero W.
 *            Kein SPI, kein DATA_READY-Signal nötig.
 *
 *  Paket-Format (Little-Endian):
 *    [0..3]    Header   : uint32_t = 0xDEADBEEF  (Magic)
 *    [4..7]    Timestamp: uint32_t = micros()
 *    [8..1607] Data     : float32_t[400]
 *    Gesamt   : 1608 Bytes
 *
 *  Dummy-Füllung: Inaktive Kanäle = 9898.0f
 *                 (wird vom RPi 5 herausgefiltert)
 *
 *  Pinbelegung UART (Serial1):
 *    TX → Pin 1   (Teensy sendet → RPi GPIO15 / Pin 10)
 *    RX → Pin 0   (Teensy empfängt ← RPi GPIO14 / Pin 8, optional)
 *    GND → GND
 *
 *  Verdrahtung:
 *    Teensy Pin 1 (TX1) ──→ RPi Zero Pin 10 (GPIO15, UART RX)
 *    Teensy Pin 0 (RX1) ←── RPi Zero Pin  8 (GPIO14, UART TX)  ← optional
 *    GND               ───  RPi Zero Pin  6 (GND)
 *
 *  Baudraten-Wahl:
 *    4 000 000 Baud  →  ~4 ms Übertragungszeit / Paket
 *    Paket-Intervall:   10 ms  →  ~40 % UART-Auslastung
 *
 *  Debug-Array:
 *    Werte per DBG(Kanal, Wert) eintragen — siehe debug_channels.h
 *
 *  Keine externen Bibliotheken nötig (kein SPISlave_T4 mehr).
 * ============================================================
 */

#include <Arduino.h>
#include <elapsedMillis.h>

elapsedMicros timer_cycle;

// ── Compile-Time Konfiguration ───────────────────────────────────────────────
#ifndef ACTIVE_CHANNELS
  #define ACTIVE_CHANNELS 200
#endif

static constexpr uint32_t UART_BAUD        = 1'000'000UL; // 4 Mbps
static constexpr uint32_t HEADER_MAGIC     = 0xDEADBEEF;
static constexpr int      MAX_FLOATS       = 200;
static constexpr int      PACKET_BYTES     = 8 + MAX_FLOATS * 4;  // 1608
static constexpr uint32_t SAMPLE_PERIOD_US = 10;            // 50 Hz

// ── Serial1 TX-Buffer ─────────────────────────────────────────────────────────
//    Default: 64 Bytes — zu klein für 1608 Bytes.
//    addMemoryForWrite() erweitert den internen TX-Ringbuffer.
//    Mit 4096 Bytes: ~2,5 Pakete Puffer → Serial1.write() blockiert nie.
static uint8_t _serial1_tx_buf[4096];

// ── Paket-Buffer ─────────────────────────────────────────────────────────────
//    buildPacket() schreibt hierhin.
//    Serial1.write() kopiert sofort in den TX-Buffer (non-blocking).
//    Kein Ping-Pong nötig: TX-Buffer ist eigenständig.
static uint8_t _pkt_buf[PACKET_BYTES];

// ── Debug-Datenarray & Makro ──────────────────────────────────────────────────
//    Alle Kanäle mit Dummy-Wert vorbelegen.
//    DBG(Kanal, Wert) — kostet nur eine float-Zuweisung (~1–2 ns).
static float debugData[MAX_FLOATS];
#define DBG(channel, value)  debugData[(channel)] = static_cast<float>(value)

// ── Kanal-Definitionen ────────────────────────────────────────────────────────
//    Empfehlung: in eigene Datei debug_channels.h auslagern (→ USER.md Abschn. 4)
//    Beispiele:
 #define CH_Start    0
// #define CH_MOTOR_R_SPEED    1
// #define CH_COMPASS_HEADING 10
// #define CH_BALL_ANGLE      20
// #define CH_STATE           80
// #define CH_LOOP_TIME       81


void buildPacket() {
    // ── Header: Magic + Timestamp ─────────────────────────────────────────────
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(_pkt_buf,     &magic, 4);
    memcpy(_pkt_buf + 4, &ts,    4);

    // ── Nutzdaten: debugData[] direkt kopieren ────────────────────────────────
    memcpy(_pkt_buf + 8, debugData, MAX_FLOATS * sizeof(float));
}

// ══════════════════════════════════════════════════════════════════════════════
//  Setup
// ══════════════════════════════════════════════════════════════════════════════

void setup() {
    // USB-Seriell (Debugging/Statistik auf PC)
    Serial.begin(115200);
    delay(200);

    // Debug-Array initialisieren (alle Kanäle = inaktiv / Dummy)
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0;  // 9898.0f Dummy wert

    // Serial1 TX-Buffer erweitern und UART starten
    Serial3.addMemoryForWrite(_serial1_tx_buf, sizeof(_serial1_tx_buf));
    Serial3.begin(UART_BAUD, SERIAL_8N1);

    pinMode(10,INPUT);

    Serial.printf(
        "[Teensy] UART bereit\n"
        "  Baud   : %lu (%.1f Mbps)\n"
        "  Paket  : %d Bytes  (%d Floats + 8 Header)\n"
        "  Rate   : %.0f Hz\n"
        "  TX-Pin : 1  →  RPi GPIO15 (Pin 10)\n"
        "  RX-Pin : 0  ←  RPi GPIO14 (Pin 8)  [optional]\n",
        UART_BAUD,
        UART_BAUD / 1e6f,
        PACKET_BYTES,
        MAX_FLOATS,
        1e6f / SAMPLE_PERIOD_US
    );
}
int time_counter =0;
int time_cycle = 0;
// ══════════════════════════════════════════════════════════════════════════════
//  Hauptschleife
// ══════════════════════════════════════════════════════════════════════════════
static uint32_t pkt_count      = 0;
void loop() {
    timer_cycle = 0;
    static uint32_t last_sample_us = 0;
    static uint32_t last_stat_ms   = 0;
    static uint32_t loop_start_us  = 0;

    loop_start_us = millis();

    // ══════════════════════════════════════════════════════════════════════════
    //  HIER: eigenen Roboter-Code und DBG()-Aufrufe einsetzen
    //
    //  Beispiel:
    //    compass.update();
    //    DBG(CH_COMPASS_HEADING, compass.getHeading());
    //    DBG(CH_BALL_ANGLE,      ball.getAngle());
    //    DBG(CH_MOTOR_L_SPEED,   motors.getLeftSpeed());
    //    DBG(CH_STATE,           (int)robotState);
    //    DBG(CH_LOOP_TIME,       micros() - loop_start_us);
    // ══════════════════════════════════════════════════════════════════════════

    DBG(CH_Start, digitalRead(10));
    DBG(1, 200);
    DBG(2, time_cycle);
    DBG(3, timer_cycle);
    DBG(4, 200);
    DBG(5, 400);

    DBG(50, 0);
    DBG(51, 20);
    DBG(52, 0);
    DBG(53, 30);
    DBG(54, 0);
    DBG(55, 0);
    DBG(56, 3500);
    DBG(57, 0);
    DBG(58, 0);
    DBG(59, 0);
    DBG(60, 0);
    DBG(61, 1);
    DBG(62, 0);
    DBG(63, 0);
    DBG(64, 1);
    DBG(65, 0);
    DBG(66, 0);
    DBG(67, 3000);
    DBG(68, 3000);
    DBG(69, 0);
    DBG(70, 1);
    DBG(71, 0);
    DBG(72, 0);
    DBG(73, 0);
    DBG(74, 0);
    DBG(75, 0);
    DBG(76, 0);
    DBG(77, 0);
    DBG(78, 0);
    DBG(79, 0);
    DBG(80, 0);
    DBG(81, 0);
    DBG(82, 0);
    DBG(83, 0);
    DBG(84, 0);
    DBG(85, 0);
    DBG(86, 0);
    DBG(87, 0);
    DBG(88, 0);
    DBG(89, 0);
    if(digitalRead(10)){
        DBG(90, 1300);
    }
    else{
        DBG(90, 5000);
    }
    




    // ── Alle 10 ms: Paket senden (100 Hz) ────────────────────────────────────
    const uint32_t now = millis();
    if (now - last_sample_us >= SAMPLE_PERIOD_US) {
        last_sample_us = now;

        buildPacket();

        // Serial1.write() kopiert 1608 Bytes in den TX-Buffer und kehrt
        // sofort zurück. Der UART-DMA überträgt asynchron (~4 ms bei 4 Mbps).
        // Bei 10 ms Paket-Intervall ist der Buffer stets leer wenn wir schreiben.
        //last_buffer = _pkt_buf;
        //last_bytes = PACKET_BYTES;
        Serial3.write(_pkt_buf, PACKET_BYTES);
        pkt_count++;
    }

    // ── Statistik alle 5 Sekunden auf USB-Serial ausgeben ────────────────────
    const uint32_t now_ms = millis();
    if (now_ms - last_stat_ms >= 5000UL) {
        last_stat_ms = now_ms;
        const float hz    = pkt_count / 5.0f;
        const float kbps  = (float)pkt_count * PACKET_BYTES / 5.0f / 1024.0f;
        Serial.printf("[Teensy] %.1f Hz | %.1f KB/s | TX-frei: %d B | count: %d\n",
                      hz, kbps, Serial3.availableForWrite(),pkt_count);
        pkt_count = 0;
    }

    time_counter++;
    time_cycle = timer_cycle ;
    Serial.println(time_counter);
}
