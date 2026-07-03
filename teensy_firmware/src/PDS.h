#include "Arduino.h"
#include "params.h"
#include "enum.h"

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

#ifndef ACTIVE_CHANNELS
#define ACTIVE_CHANNELS 200
#endif


class PowerDebugger{
    private:
        void buildPacket();

    public:
        void init();
        void update();
        void Channel(u_int8_t chn , float val);
};
