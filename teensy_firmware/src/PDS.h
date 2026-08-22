#pragma once
/*
 * ============================================================
 *  Power Debug System (PDS) — Teensy-Bibliothek
 * ============================================================
 *
 *  ┌──────────────────────────────────────────────────────────┐
 *  │  MINIMAL-SKETCH — mehr braucht es nicht:                 │
 *  │                                                          │
 *  │    #include "PDS.h"                                      │
 *  │                                                          │
 *  │    float speed = 0;                                      │
 *  │                                                          │
 *  │    void setup() {                                        │
 *  │        PDS.begin();                                      │
 *  │    }                                                     │
 *  │                                                          │
 *  │    void loop() {                                         │
 *  │        speed = PDS.fastParam(0);   // Joystick/Controller│
 *  │        PDS.plot("Speed", speed);   // Kanal automatisch  │
 *  │        PDS.update();               // 1x pro loop()      │
 *  │    }                                                     │
 *  └──────────────────────────────────────────────────────────┘
 *
 *  `PDS` ist eine fertige globale Instanz — kein eigenes Objekt anlegen.
 *  Kanalnummern muss man nur noch vergeben, wenn man WILL: plot()/track()
 *  vergeben sie automatisch und melden die Namen an die GUI.
 *
 *  ── Die vier Wege, einen Wert in die GUI zu bekommen ───────────────────
 *    1) PDS.plot("Ball_X", ballX);          Auto-Kanal, Name geht an die GUI
 *    2) PDS.track("Akku", &akkuVolt);       Auto-Kanal, einmal in setup()
 *    3) PDS.bind("Akku", &akkuVolt, 12);    FESTER Kanal 12, einmal in setup()
 *    4) PDS.Channel(12, wert);              fester Kanal, klassisch
 *
 *  ── Einheiten, Ereignisse, Logzeilen ───────────────────────────────────
 *    PDS.plot("Akku", v, "V");        Einheit erscheint in Tabelle/Plotter
 *    PDS.event("Ball verloren");      senkrechte Marke im Plotter
 *    PDS.log("Kalibrierung fertig");  Zeile im Logbuch der GUI
 *    PDS.warn("Akku schwach: %.1f V", v);
 *
 *  ── Fernsteuerung / Parameter von der GUI ──────────────────────────────
 *    PDS.fastParam(0)      5 Floats, 100 Hz   (Joystick, PS4-Controller)
 *    PDS.param(3)          50 Floats, 2 Hz    (Tuning-Werte)
 *    PDS.paramBool(7)      50 Bools,  2 Hz    (Schalter)
 *    PDS.param("Kp")       dasselbe per Name (Namen aus channel_config.h)
 *    PDS.linkOk()          true, solange die GUI sendet -> Not-Aus-Kriterium
 *
 *  ── Watchdog (optional, Teensy 4.x) ────────────────────────────────────
 *    PDS.enableWatchdog(2000);        in setup(): Reset, wenn update() 2 s
 *                                     lang nicht mehr aufgerufen wird.
 *
 *  ── Verkabelung ────────────────────────────────────────────────────────
 *    Teensy Pin 14 (TX3) ──→ RPi Zero Pin 10 (GPIO15, UART RX)
 *    Teensy Pin 15 (RX3) ←── RPi Zero Pin  8 (GPIO14, UART TX)   PFLICHT
 *    GND                 ─── RPi Zero Pin  6 (GND)
 *    Andere UART-Instanz? -> UART_DBG in params.h aendern, sonst nichts.
 *
 *  ── Wire-Format (mit uart_receiver.py + config.py abgestimmt) ───────────
 *    Uplink   Telemetrie  0xDEADBEEF  808 B @ 100 Hz   ~81 % der Leitung
 *             Deskriptor  0xDE5C0001  257 B, nur auf Anfrage/beim Boot
 *             Ereignis    0xE7E5C0DE  <=64 B, max. 20/s
 *             Param-Ack   0xACC0FEED  290 B @ 2 Hz
 *    Downlink Slow/Fast/Request/Discovery — siehe params.h
 *
 *  Keine externen Bibliotheken noetig.
 * ============================================================
 */

#include "Arduino.h"
#include "params.h"

// enum.h stammt aus dem Roboter-Projekt, in das diese Bibliothek eingebunden
// wird, und liegt bewusst nicht in diesem Repository. PDS.h/PDS.cpp selbst
// brauchen nichts daraus — der Include steht hier nur, damit main.cpp ihn
// nicht separat einbinden muss. Ohne die Bedingung liesse sich teensy_firmware/
// gar nicht eigenstaendig uebersetzen (fataler Fehler "enum.h: No such file").
#if defined(__has_include)
#  if __has_include("enum.h")
#    include "enum.h"
#  endif
#endif

// Versionsnummer der Bibliothek (fuer Doku/Diagnose, siehe printStatus()).
#define PDS_VERSION "2.1"

// Version der ROBOTER-Firmware. Wird im Deskriptor an die GUI gemeldet, damit
// dort sichtbar ist, welcher Stand auf welchem Roboter laeuft. Per Build-Flag
// setzen (-DPDS_FW_VERSION='"1.4.2"') oder zur Laufzeit ueber
// PDS.setFirmwareVersion("..."). Ohne Angabe meldet der Teensy den
// Compilier-Zeitpunkt, der dafuer auch schon reicht.
#ifndef PDS_FW_VERSION
#define PDS_FW_VERSION ""
#endif

// Wie viele der MAX_FLOATS Kanaele Namen/Bindungen tragen koennen. Nur ein
// RAM-Limit — das Wire-Format bleibt immer 200 Kanaele breit.
#ifndef ACTIVE_CHANNELS
#define ACTIVE_CHANNELS 200
#endif

// Ab diesem Kanal vergibt plot()/track() automatisch (aufsteigend, erster
// freier Kanal). Wer die unteren Kanaele fest fuer sich reservieren will,
// setzt das Build-Flag -DPDS_AUTO_CHANNEL_BASE=50.
#ifndef PDS_AUTO_CHANNEL_BASE
#define PDS_AUTO_CHANNEL_BASE 0
#endif

// Direkt abbildender Cache Name-Pointer -> Kanal, damit plot("X", v) in einer
// schnellen Regelschleife nicht jedes Mal alle Namen vergleichen muss.
// Muss eine Zweierpotenz sein.
#ifndef PDS_NAME_CACHE_SIZE
#define PDS_NAME_CACHE_SIZE 128
#endif

// Wie viele Kanaele eine Einheit tragen koennen ("V", "cm", "°/s", ...).
// Bewusst eine kleine Seitentabelle statt eines Feldes ueber alle 200 Kanaele:
// Einheiten hat man typischerweise nur an einer Handvoll Werten.
#ifndef PDS_MAX_UNITS
#define PDS_MAX_UNITS 32
#endif
#ifndef PDS_UNIT_MAXLEN
#define PDS_UNIT_MAXLEN 8      // inkl. Nullterminator
#endif

// Wie viele Ereignisse/Logzeilen zwischengepuffert werden, bis update() sie
// nacheinander abschickt. Laeuft der Puffer ueber, gewinnt der AELTERE
// Eintrag (eine Fehlermeldung soll nicht von nachfolgendem Rauschen
// verdraengt werden) — siehe eventDropCount().
#ifndef PDS_EVENT_QUEUE_SIZE
#define PDS_EVENT_QUEUE_SIZE 8
#endif

// Solange die GUI noch nie (bzw. gerade nicht) sendet, wiederholt der Teensy
// den Namens-/Overlay-Deskriptor in diesem Abstand. Damit findet eine erst
// spaeter gestartete GUI die Kanalnamen von allein, ohne dass jemand
// "Kanalnamen anfordern" druecken muss. 0 = aus.
#ifndef PDS_DESC_REPEAT_MS
#define PDS_DESC_REPEAT_MS 5000
#endif

// Die erste Namensmeldung wartet so lange nach begin(). Grund: plot() und
// track() registrieren ihre Namen erst waehrend setup()/dem ersten loop()-
// Durchlauf — wuerde der Deskriptor direkt in begin() gebaut, ginge er
// (fast) leer raus und muesste sofort wiederholt werden.
#ifndef PDS_BOOT_ANNOUNCE_DELAY_MS
#define PDS_BOOT_ANNOUNCE_DELAY_MS 250
#endif

// Der Abstand verdoppelt sich nach jeder unbeantworteten Wiederholung bis zu
// diesem Wert. Im Wettkampfbetrieb (Roboter laeuft ohne GUI) faellt die
// Namensmeldung dadurch nach kurzer Zeit auf ein Minimum zurueck, statt
// dauerhaft Bandbreite zu verbrauchen. Sobald die GUI sendet, wird wieder auf
// PDS_DESC_REPEAT_MS zurueckgesetzt.
#ifndef PDS_DESC_REPEAT_MAX_MS
#define PDS_DESC_REPEAT_MAX_MS 60000
#endif

// Bindungs-Typ eines per bind()/track() registrierten Kanals (Auto-Sampling).
//
// Bewusst nach den FUNDAMENTALEN C++-Typen benannt, nicht nach int8_t/int32_t:
// die Festbreiten-Typen sind nur Aliase, und welcher fundamentale Typ dahinter
// steckt, haengt vom Compiler ab. Auf dem Teensy ist int32_t z. B. "long" --
// eine Ueberladung fuer int32_t* hat deshalb ein ganz gewoehnliches
//     int heading;  PDS.track("Heading", &heading);
// NICHT angenommen, sondern eine seitenlange Fehlermeldung erzeugt. Mit den
// fundamentalen Typen ist jeder Ganzzahltyp genau einmal abgedeckt.
enum class BoundChannelType : uint8_t {
    NONE = 0, FLOAT_PTR, DOUBLE_PTR, BOOL_PTR,
    SCHAR_PTR, UCHAR_PTR,     // signed char / unsigned char   (= int8_t/uint8_t)
    SHORT_PTR, USHORT_PTR,    // short       / unsigned short  (= int16_t/uint16_t)
    INT_PTR,   UINT_PTR,      // int         / unsigned int
    LONG_PTR,  ULONG_PTR,     // long        / unsigned long
    LLONG_PTR, ULLONG_PTR     // long long   / unsigned long long
};

class PowerDebugger {
    public:
        // ══════════════════════════════════════════════════════════════
        //  Lebenszyklus
        // ══════════════════════════════════════════════════════════════

        /// Einmal in setup() aufrufen: UART starten, Puffer setzen,
        /// Namens-Deskriptor an die GUI schicken.
        void begin();

        /// Alias fuer begin() (Kompatibilitaet mit aelteren Sketches).
        void init() { begin(); }

        /// Einmal pro loop() aufrufen. Nicht blockierend: liest den
        /// Param-Downlink, sendet alle 10 ms ein Telemetriepaket und
        /// fuettert (falls aktiviert) den Hardware-Watchdog.
        void update();

        // ══════════════════════════════════════════════════════════════
        //  Kanaele schreiben — Variante 1: automatisch per Name
        // ══════════════════════════════════════════════════════════════

        /// Wert unter einem Namen anzeigen. Der Kanal wird beim ersten
        /// Aufruf automatisch vergeben und der Name an die GUI gemeldet.
        /// Gibt den benutzten Kanal zurueck (meist ignorierbar).
        ///   PDS.plot("Ball_X", ballX);
        ///   PDS.plot("Akku", volt, "V");    // mit Einheit
        /// `name` sollte ein String-Literal sein (dann ist der Aufruf durch
        /// den internen Cache praktisch kostenlos).
        uint8_t plot(const char* name, float value);
        uint8_t plot(const char* name, float value, const char* unit);

        template <class T>
        uint8_t plot(const char* name, T value) {
            return plot(name, static_cast<float>(value));
        }
        template <class T>
        uint8_t plot(const char* name, T value, const char* unit) {
            return plot(name, static_cast<float>(value), unit);
        }

        /// Kanalnummer zu einem Namen (vergibt beim ersten Aufruf eine neue).
        /// Nuetzlich, wenn man den Kanal einmal holen und danach direkt
        /// Channel() benutzen will.
        uint8_t channelFor(const char* name);

        // ══════════════════════════════════════════════════════════════
        //  Kanaele schreiben — Variante 2: fester Kanal (klassisch)
        // ══════════════════════════════════════════════════════════════

        void Channel(uint8_t chn, float val);
        /// wie Channel(chn, val), registriert zusaetzlich einen Anzeigenamen
        void Channel(uint8_t chn, float val, const char* name);

        /// Kleinschreibung + beliebiger Zahlentyp (int, bool, double, ...).
        template <class T>
        void channel(uint8_t chn, T val) { Channel(chn, static_cast<float>(val)); }
        template <class T>
        void channel(uint8_t chn, T val, const char* name) {
            Channel(chn, static_cast<float>(val), name);
        }

        // ══════════════════════════════════════════════════════════════
        //  Kanaele binden — Variante 3: einmal registrieren, nie wieder anfassen
        // ══════════════════════════════════════════════════════════════
        //  Der gebundene Zeiger wird unmittelbar vor jedem Sendevorgang
        //  ausgelesen (100 Hz) — im loop() ist danach kein Aufruf mehr noetig.
        //
        //    PDS.bind(12, &akkuVolt, "Akku");     // Kanal zuerst
        //    PDS.bind("Akku", &akkuVolt, 12);     // Name zuerst — identisch
        //    PDS.track("Akku", &akkuVolt);        // Kanal automatisch

        void bind(uint8_t chn, float*              ptr, const char* name = nullptr);
        void bind(uint8_t chn, double*             ptr, const char* name = nullptr);
        void bind(uint8_t chn, bool*               ptr, const char* name = nullptr);
        void bind(uint8_t chn, signed char*        ptr, const char* name = nullptr);
        void bind(uint8_t chn, unsigned char*      ptr, const char* name = nullptr);
        void bind(uint8_t chn, short*              ptr, const char* name = nullptr);
        void bind(uint8_t chn, unsigned short*     ptr, const char* name = nullptr);
        void bind(uint8_t chn, int*                ptr, const char* name = nullptr);
        void bind(uint8_t chn, unsigned int*       ptr, const char* name = nullptr);
        void bind(uint8_t chn, long*               ptr, const char* name = nullptr);
        void bind(uint8_t chn, unsigned long*      ptr, const char* name = nullptr);
        void bind(uint8_t chn, long long*          ptr, const char* name = nullptr);
        void bind(uint8_t chn, unsigned long long* ptr, const char* name = nullptr);

        /// Auffangnetz fuer alles andere. Ohne diese Ueberladung liefert ein
        /// nicht unterstuetzter Typ eine seitenlange Kandidatenliste; so steht
        /// stattdessen ein einziger, lesbarer Satz im Compilerfehler.
        template <class T>
        void bind(uint8_t, T*, const char* = nullptr) {
            static_assert(sizeof(T) == 0,
                "PDS.bind()/PDS.track(): dieser Typ wird nicht unterstuetzt. "
                "Erlaubt sind float, double, bool und alle Ganzzahltypen.");
        }

        /// bind() mit dem Namen zuerst und der Kanalnummer als drittem
        /// Argument — dieselbe Wirkung wie bind(chn, ptr, name), liest sich
        /// aber wie track() und macht die feste Kanalnummer explizit:
        ///   PDS.bind("Akku", &akkuVolt, 12);
        ///   PDS.bind("Akku", &akkuVolt, 12, "V");   // mit Einheit
        template <class T>
        uint8_t bind(const char* name, T* ptr, int chn, const char* unit = nullptr) {
            if (chn < 0 || chn >= ACTIVE_CHANNELS) return 0xFF;
            bind((uint8_t)chn, ptr, name);
            if (unit) setUnit((uint8_t)chn, unit);
            return (uint8_t)chn;
        }

        /// bind() mit automatischer Kanalvergabe — die bequemste Variante:
        ///   void setup() { PDS.begin(); PDS.track("Akku", &akkuVolt, "V"); }
        template <class T>
        uint8_t track(const char* name, T* ptr, const char* unit = nullptr) {
            uint8_t chn = channelFor(name);
            if (chn == 0xFF) return 0xFF;
            bind(chn, ptr, name);
            if (unit) setUnit(chn, unit);
            return chn;
        }

        // ══════════════════════════════════════════════════════════════
        //  Einheiten
        // ══════════════════════════════════════════════════════════════
        //  Rein kosmetisch, aber in der GUI sehr hilfreich: "12.4 V" statt
        //  "12.4". Die Einheit wird im Deskriptor mitgeschickt.

        void setUnit(uint8_t chn, const char* unit);
        void setUnit(const char* name, const char* unit) { setUnit(channelFor(name), unit); }
        const char* unitOf(uint8_t chn) const;

        // ══════════════════════════════════════════════════════════════
        //  Ereignisse und Logzeilen -> GUI
        // ══════════════════════════════════════════════════════════════
        //  event() setzt eine senkrechte Marke in den Plotter (mit Zeitstempel
        //  aus derselben micros()-Basis wie die Telemetrie), log()/warn()/
        //  error() schreiben eine Zeile ins Logbuch der GUI.
        //
        //  Beide sind nicht-blockierend: die Meldung wandert in eine kleine
        //  Warteschlange und geht im naechsten update() raus, sobald die
        //  Leitung Platz hat. Der 100-Hz-Telemetrietakt hat immer Vorrang.

        void event(const char* name)               { pushEvent(PDS_EVENT_KIND_EVENT, PDS_LEVEL_INFO, name, 0.0f); }
        void event(const char* name, float value)  { pushEvent(PDS_EVENT_KIND_EVENT, PDS_LEVEL_INFO, name, value); }
        void log(const char* text)                 { pushEvent(PDS_EVENT_KIND_LOG,   PDS_LEVEL_INFO, text, 0.0f); }

        /// printf-Formatierung fuer das Logbuch (max. PDS_EVENT_TEXT_MAX Zeichen).
        void logf(const char* fmt, ...)   __attribute__((format(printf, 2, 3)));
        void warn(const char* fmt, ...)   __attribute__((format(printf, 2, 3)));
        void error(const char* fmt, ...)  __attribute__((format(printf, 2, 3)));

        uint32_t eventSentCount() const { return _evSent; }
        uint32_t eventDropCount() const { return _evDrops; }

        // ══════════════════════════════════════════════════════════════
        //  Parameter von der GUI lesen
        // ══════════════════════════════════════════════════════════════
        //  Slow-Kanal: 50 Floats + 50 Bools @ 2 Hz  (Tuning)
        //  Fast-Kanal: 5 Floats @ 100 Hz            (Joystick/Controller)
        //  Alles RAM-only: nach einem Reset 0.0f/false, bis das erste Paket
        //  eintrifft (siehe paramsAreFresh()).

        float param(int index)     const;      ///< Slow-Float 0..49
        bool  paramBool(int index) const;      ///< Slow-Bool  0..49
        float fastParam(int index) const;      ///< Fast-Float 0..4

        /// Zugriff ueber den in channel_config.h vergebenen Namen.
        /// Unbekannter Name -> 0.0f / false (und einmalig eine Warnung
        /// ueber Serial, damit Tippfehler nicht still verschwinden).
        float param(const char* name)     const;
        bool  paramBool(const char* name) const;
        float fastParam(const char* name) const;

        // Alte Namen, unveraendert erhalten:
        float getParam(uint8_t index)     const { return param((int)index); }
        bool  getParamBool(uint8_t index) const { return paramBool((int)index); }
        float getFastParam(uint8_t index) const { return fastParam((int)index); }

        /// Rueckmeldung an die GUI: welche Parameter haelt der Teensy gerade
        /// wirklich? Laeuft automatisch mit 2 Hz. Nur abschalten, wenn jedes
        /// Byte Uplink zaehlt.
        void enableParamAck(bool on) { _paramAckOn = on; }

        // ══════════════════════════════════════════════════════════════
        //  Verbindungszustand
        // ══════════════════════════════════════════════════════════════

        bool paramsAreFresh()     const;   ///< Slow-Kanal aktuell? (< 1000 ms)
        bool fastParamsAreFresh() const;   ///< Fast-Kanal aktuell? (< 150 ms)

        /// true, solange ueberhaupt etwas von der GUI kommt. Das richtige
        /// Kriterium fuer einen Not-Aus im Roboter-Code:
        ///   if (!PDS.linkOk()) { motorenStopp(); }
        bool linkOk() const { return fastParamsAreFresh() || paramsAreFresh(); }

        /// Alter des zuletzt empfangenen Fast-Pakets in ms — direkt als
        /// Latenzanzeige verwendbar (normal 0..10 ms). 0xFFFFFFFF, solange
        /// noch nie etwas empfangen wurde.
        uint32_t fastParamAgeMs() const;

        // ══════════════════════════════════════════════════════════════
        //  Watchdog (Teensy 4.x: Hardware-WDOG1)
        // ══════════════════════════════════════════════════════════════
        //  Bleibt loop() haengen (blockierende I2C-Lesung, Endlosschleife),
        //  startet der Teensy nach `timeoutMs` neu, statt bewegungslos mit
        //  laufenden Motoren stehenzubleiben.
        //
        //  update() fuettert den Watchdog automatisch — es reicht also, ihn
        //  einmal in setup() einzuschalten. feedWatchdog() ist nur noetig,
        //  wenn im Roboter-Code absichtlich laenger nicht update() laeuft
        //  (z. B. waehrend einer Kalibrierfahrt).
        //
        //  ACHTUNG: Der Watchdog laesst sich per Hardware nicht wieder
        //  abschalten. Aufloesung 0.5 s, Bereich 500..128000 ms.

        void enableWatchdog(uint32_t timeoutMs = 2000);
        void feedWatchdog();
        bool watchdogEnabled() const { return _wdtOn; }

        /// true, wenn der LETZTE Reset vom Watchdog ausgeloest wurde. Wird in
        /// begin() einmal aus der Hardware gelesen und dann als Ereignis an
        /// die GUI gemeldet.
        bool watchdogResetOccurred() const { return _wdtWasReset; }

        // ══════════════════════════════════════════════════════════════
        //  Firmware-Version
        // ══════════════════════════════════════════════════════════════

        /// Version der ROBOTER-Firmware fuer die Anzeige in der GUI.
        /// Alternativ das Build-Flag -DPDS_FW_VERSION='"1.4.2"' benutzen.
        void setFirmwareVersion(const char* v);
        const char* firmwareVersion() const { return _fwVersion; }

        // ══════════════════════════════════════════════════════════════
        //  Diagnose
        // ══════════════════════════════════════════════════════════════

        uint32_t slowPacketCount()  const { return _slowPktCount; }
        uint32_t fastPacketCount()  const { return _fastPktCount; }
        uint32_t txPacketCount()    const { return _txPktCount; }
        uint32_t txDropCount()      const { return _txDrops; }
        uint32_t paramSyncLosses()  const { return _paramSyncLosses; }
        uint8_t  usedChannels()     const { return _autoNext; }
        bool     descriptorTruncated() const { return _descOverflow; }
        size_t   descriptorBytes()  const { return _descJsonLen; }

        /// Eine Zeile Klartext-Diagnose, z. B. 1x/s im Sketch:
        ///   PDS.printStatus();          // -> USB-Serial
        void printStatus(Print& out = Serial) const;

        /// Legt die wichtigsten Diagnosezaehler auf sechs aufeinander
        /// folgende Debug-Kanaele (Default: die letzten sechs), damit man
        /// Aussetzer direkt in der GUI sieht — einmal in setup() aufrufen.
        void enableSelfDiagnostics(int firstChannel = -1);

        /// Sendet den Namens-/Overlay-Deskriptor (erneut) an die GUI.
        /// Passiert automatisch beim Boot, in Ruhe alle PDS_DESC_REPEAT_MS
        /// und sobald die Verbindung zur GUI (wieder) zustande kommt —
        /// von Hand also nur noetig, wenn man Namen zur Laufzeit aendert.
        void announceChannelNames() { startDescriptorSend(); }

    private:
        // ── Telemetrie-Versand ─────────────────────────────────────────
        void sendTelemetryPacket();

        // ── Param-Downlink (RX): Magic-Sync-Parser ─────────────────────
        void pollParamUart();

        float    _paramFloats[PARAM_SLOW_FLOAT_COUNT] = {0};
        bool     _paramBools[PARAM_SLOW_BOOL_COUNT]   = {false};
        uint32_t _lastSlowRxMs = 0;
        uint32_t _lastSlowSeq  = 0;

        float    _fastFloats[PARAM_FAST_FLOAT_COUNT]  = {0};
        uint32_t _lastFastRxMs = 0;
        uint32_t _lastFastSeq  = 0;

        // Parser-Zustand (frueher function-static — als Member ist die
        // Klasse damit auch in einem Zweit-Objekt sauber initialisiert).
        uint8_t  _rxBuf[PARAM_SLOW_PACKET_BYTES];
        int      _rxFill        = 0;
        int      _rxExpectedLen = 0;

        // ── Parameter-Rueckmeldung ─────────────────────────────────────
        bool     _paramAckOn = true;
        void     sendParamAck();

        // ── Diagnose-Zaehler ───────────────────────────────────────────
        uint32_t _slowPktCount    = 0;
        uint32_t _fastPktCount    = 0;
        uint32_t _txPktCount      = 0;
        uint32_t _txDrops         = 0;
        uint32_t _paramSyncLosses = 0;
        int16_t  _diagFirstChannel = -1;

        // ── Kanal-Bindungen: kompakte Liste statt Array ueber alle 200
        //    Kanaele (sampleBoundChannels() laeuft 100x/s, iteriert jetzt
        //    nur ueber die tatsaechlich gebundenen Eintraege) ────────────
        struct BoundChannel {
            void*            ptr  = nullptr;
            uint8_t          chn  = 0;
            BoundChannelType type = BoundChannelType::NONE;
        };
        BoundChannel _bound[ACTIVE_CHANNELS];
        uint8_t      _boundCount = 0;

        void bindRaw(uint8_t chn, void* ptr, BoundChannelType type, const char* name);
        void sampleBoundChannels();

        // ── Namens-Registry ────────────────────────────────────────────
        char    _names[ACTIVE_CHANNELS][CHANNEL_NAME_MAXLEN];
        uint8_t _autoNext = PDS_AUTO_CHANNEL_BASE;   // naechster Kandidat fuer plot()/track()

        void setName(uint8_t chn, const char* name);

        // Name-Pointer -> Kanal (direkt abbildender Cache, siehe channelFor()).
        struct NameCacheEntry { const char* key = nullptr; uint8_t chn = 0; };
        NameCacheEntry _nameCache[PDS_NAME_CACHE_SIZE];

        // ── Einheiten (kleine Seitentabelle, siehe PDS_MAX_UNITS) ──────
        struct UnitEntry { uint8_t chn; char unit[PDS_UNIT_MAXLEN]; };
        UnitEntry _units[PDS_MAX_UNITS];
        uint8_t   _unitCount = 0;

        // ── Ereignis-/Log-Warteschlange ────────────────────────────────
        struct EventEntry {
            uint32_t ts_us;
            float    value;
            uint8_t  kind;
            uint8_t  level;
            uint8_t  len;
            char     text[PDS_EVENT_TEXT_MAX];
        };
        EventEntry _evQueue[PDS_EVENT_QUEUE_SIZE];
        uint8_t    _evHead = 0;      // naechster zu sendender Eintrag
        uint8_t    _evCount = 0;
        uint32_t   _evSent = 0;
        uint32_t   _evDrops = 0;
        uint32_t   _evWindowStartMs = 0;
        uint8_t    _evInWindow = 0;  // in dieser Sekunde bereits gesendet

        void pushEvent(uint8_t kind, uint8_t level, const char* text, float value);
        void pushEventV(uint8_t kind, uint8_t level, float value, const char* fmt, va_list args);
        bool sendNextEvent();

        // ── Watchdog ───────────────────────────────────────────────────
        bool _wdtOn       = false;
        bool _wdtWasReset = false;

        // ── Firmware-Version ───────────────────────────────────────────
        // 48 Byte, nicht 24: ein zusammengesetzter Text wie
        // "v0.0.1 (Build 22.08.2026 14:23:05)" ist knapp 40 Zeichen lang
        // und wurde vorher stillschweigend nach "…Aug 22" abgeschnitten.
        // Der Deskriptor hat mit 24 kB reichlich Platz dafuer.
        char _fwVersion[48] = {0};

        // ── Namens-/Overlay-Deskriptor -> GUI ──────────────────────────
        size_t  _descJsonLen    = 0;
        uint16_t _descChunkCount = 0;
        uint16_t _descNextChunk  = 0xFFFF;   // 0xFFFF = kein Sendevorgang aktiv
        bool     _descBuilt     = false;
        bool     _descOverflow  = false;
        bool     _linkWasUp     = false;   // fuer die Flanke "GUI wieder da"
        uint32_t _descRepeatMs  = PDS_DESC_REPEAT_MS;   // waechst bis PDS_DESC_REPEAT_MAX_MS
        uint32_t _bootAnnounceAtMs = 0;    // 0 = erste Meldung schon raus

        void buildDescriptorJson();
        void startDescriptorSend();
        void sendNextDescChunk();
};

// Fertige globale Instanz — im Sketch einfach `PDS.` benutzen.
extern PowerDebugger PDS;

/*
 * PDS_PLOT(name, wert) — nulloverhead-Variante von PDS.plot().
 * Die Kanalnummer wird beim ersten Durchlauf einmalig ermittelt und danach
 * in einer static-Variable gehalten; es bleibt ein reiner Array-Schreibzugriff.
 * Fuer sehr heisse Schleifen (mehrere kHz) gedacht — PDS.plot() selbst ist
 * durch den Namens-Cache aber ebenfalls O(1) und fuer den Normalfall genug.
 */
#define PDS_PLOT(name, value)                                                  \
    do {                                                                       \
        static const uint8_t _pds_chn = PDS.channelFor(name);                  \
        PDS.Channel(_pds_chn, static_cast<float>(value));                      \
    } while (0)
