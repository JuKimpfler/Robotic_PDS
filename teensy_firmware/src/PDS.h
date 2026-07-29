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
 *
 *  NEU — Param-Downlink (RPi 5 → Teensy, gleiche UART_DBG-Leitung):
 *    Da UART Vollduplex ist (getrennte TX/RX-Leitungen), läuft der
 *    Telemetrie-Versand (TX, wie oben) UNABHÄNGIG vom Param-Empfang
 *    (RX) — beide Richtungen nutzen dieselbe UART_DBG-Instanz.
 *
 *    Slow-Kanal (0xCAFEFEED): 50 Floats + 50 Bools, 2 Hz
 *    Fast-Kanal (0xFA57DA7A): 5 Floats, 100 Hz (z. B. Joystick)
 *
 *    Werte werden NICHT persistiert (RAM-only) — nach einem Reset
 *    sind alle Werte 0.0f/false, bis das nächste Paket eintrifft.
 *    paramsAreFresh()/fastParamsAreFresh() zeigen an, ob überhaupt
 *    schon (aktuell) Daten empfangen wurden — kein ACK zur GUI.
 * ============================================================
 */

#ifndef ACTIVE_CHANNELS
#define ACTIVE_CHANNELS 200
#endif

// Bindungs-Typ eines per bind() registrierten Kanals (Auto-Sampling, siehe update()).
enum class BoundChannelType : uint8_t { NONE = 0, FLOAT_PTR, BOOL_PTR, INT_PTR };

struct BoundChannel {
    BoundChannelType type = BoundChannelType::NONE;
    void*            ptr  = nullptr;
};

class PowerDebugger{
    private:
        void buildPacket();
        void pollParamUart();          // liest UART_DBG RX, Drei-Magic-Byte-Sync (Slow/Fast/Desc-Request)

        // Param-Downlink: Slow-Kanal (50 Floats + 50 Bools, 2 Hz)
        float    _paramFloats[PARAM_SLOW_FLOAT_COUNT];
        bool     _paramBools[PARAM_SLOW_BOOL_COUNT];
        uint32_t _lastSlowRxMs = 0;

        // Param-Downlink: Fast-Kanal (5 Floats, 100 Hz, z. B. Joystick)
        float    _fastFloats[PARAM_FAST_FLOAT_COUNT];
        uint32_t _lastFastRxMs = 0;

        // ── Kanal-Bindung: per bind() registrierte Pointer, jeden update()-
        //    Zyklus automatisch in debugData[] uebernommen (kein weiterer
        //    Channel()-Aufruf im Sketch noetig) ────────────────────────────
        BoundChannel _bound[ACTIVE_CHANNELS];
        char         _names[ACTIVE_CHANNELS][CHANNEL_NAME_MAXLEN];

        void sampleBoundChannels();
        void setName(uint8_t chn, const char* name);

        // ── Namens-/Overlay-Deskriptor -> GUI (einmalig beim Boot + auf
        //    Anfrage, siehe channel_config.h fuer die Nutzdaten) ──────────
        size_t  _descJsonLen    = 0;
        uint8_t _descChunkCount = 0;
        uint8_t _descNextChunk  = 0xFF;   // 0xFF = kein Sendevorgang aktiv
        bool    _descBuilt      = false;

        void buildDescriptorJson();
        void startDescriptorSend();
        void sendNextDescChunk();

    public:
        void init();
        void update();
        void Channel(u_int8_t chn , float val);
        void Channel(u_int8_t chn , float val, const char* name);   // wie Channel(chn,val), registriert zusaetzlich einen Anzeigenamen

        // ── Kanal-Bindung: Pointer + optionaler Name, Auto-Sampling ──────
        void bind(uint8_t chn, float* ptr, const char* name = nullptr);
        void bind(uint8_t chn, bool*  ptr, const char* name = nullptr);
        void bind(uint8_t chn, int*   ptr, const char* name = nullptr);

        // ── Param-Downlink: öffentliche Zugriffs-API ────────────────────
        float getParam(uint8_t index) const;        // Slow-Float,  Index 0..49
        bool  getParamBool(uint8_t index) const;     // Slow-Bool,   Index 0..49
        float getFastParam(uint8_t index) const;     // Fast-Float,  Index 0..4

        bool  paramsAreFresh() const;                // Slow-Kanal noch aktuell?
        bool  fastParamsAreFresh() const;             // Fast-Kanal noch aktuell? (enger)
};
