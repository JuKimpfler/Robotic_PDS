#include "Arduino.h"
#include "params.h"

// enum.h stammt aus dem Roboter-Projekt, in das diese Bibliothek eingebunden
// wird, und liegt bewusst nicht in diesem Repository. PDS.h/PDS.cpp selbst
// brauchen nichts daraus — der Include stand hier nur, damit main.cpp ihn
// nicht separat einbinden muss. Ohne die Bedingung liess sich teensy_firmware/
// gar nicht eigenstaendig uebersetzen (fataler Fehler "enum.h: No such file").
#if defined(__has_include)
#  if __has_include("enum.h")
#    include "enum.h"
#  endif
#endif

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
 *    [0..3]   Header   : uint32_t = 0xDEADBEEF  (Magic)
 *    [4..7]   Timestamp: uint32_t = micros()
 *    [8..807] Data     : float32[200]     (MAX_FLOATS in PDS.cpp)
 *    Gesamt  : 808 Bytes
 *
 *    MAX_FLOATS ist Wire-Format und muss mit rpi_zero_node/spi_receiver.py
 *    und rpi5_monitor/64Bit_Version/config.py uebereinstimmen.
 *
 *  Dummy-Füllung: Inaktive Kanäle = 9898.0f
 *                 (wird vom RPi 5 herausgefiltert)
 *
 *  Verwendete UART-Instanz: UART_DBG (Default Serial3, siehe params.h).
 *    Teensy Pin 14 (TX3) ──→ RPi Zero Pin 10 (GPIO15, UART RX)
 *    Teensy Pin 15 (RX3) ←── RPi Zero Pin  8 (GPIO14, UART TX)
 *    GND                ───  RPi Zero Pin  6 (GND)
 *    Die RX-Leitung ist fuer den Param-Downlink (Joystick/Controller)
 *    zwingend erforderlich, nicht optional.
 *
 *  Baudraten-Budget (UART_DBG_BAUD = 1 Mbps, 8N1 = 10 Bit/Byte):
 *    Uplink   : 808 B × 100 Hz = 80.8 kB/s von 100 kB/s  → ~81 % Auslastung
 *    Downlink : 28 B × 100 Hz + 258 B × 2 Hz ≈ 3.3 kB/s  → ~3 % Auslastung
 *
 *  Debug-Array:
 *    Werte per Channel(Kanal, Wert) bzw. bind(Kanal, &var) eintragen —
 *    siehe channel_config.h für die Namens-/Overlay-Zuordnung.
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

        // ── Diagnose-Zaehler ────────────────────────────────────────────
        //    Nuetzlich, um Latenz-/Aussetzer-Probleme der Fernsteuerung
        //    direkt auf dem Roboter sichtbar zu machen: einfach per
        //    Channel(n, pds.fastPacketCount()) o. ae. auf einen freien
        //    Debug-Kanal legen.
        uint32_t _slowPktCount    = 0;
        uint32_t _fastPktCount    = 0;
        uint32_t _txPktCount      = 0;
        uint32_t _paramSyncLosses = 0;

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
        void Channel(uint8_t chn , float val);
        void Channel(uint8_t chn , float val, const char* name);   // wie Channel(chn,val), registriert zusaetzlich einen Anzeigenamen

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

        // Alter des zuletzt empfangenen Fast-Pakets in ms. Direkt als
        // Latenz-Anzeige verwendbar (im Normalbetrieb 0..10 ms); gibt
        // 0xFFFFFFFF zurueck, solange ueberhaupt noch nichts empfangen wurde.
        uint32_t fastParamAgeMs() const;

        // ── Diagnose ────────────────────────────────────────────────────
        uint32_t slowPacketCount()  const { return _slowPktCount; }
        uint32_t fastPacketCount()  const { return _fastPktCount; }
        uint32_t txPacketCount()    const { return _txPktCount; }
        uint32_t paramSyncLosses()  const { return _paramSyncLosses; }
};
