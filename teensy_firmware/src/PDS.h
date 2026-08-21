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
 *  ── Die drei Wege, einen Wert in die GUI zu bekommen ───────────────────
 *    1) PDS.plot("Ball_X", ballX);        Auto-Kanal, Name geht an die GUI
 *    2) PDS.track("Akku", &akkuVolt);     einmal in setup(), danach nie wieder
 *    3) PDS.Channel(12, wert);            fester Kanal (klassisch, wie bisher)
 *
 *  ── Fernsteuerung / Parameter von der GUI ──────────────────────────────
 *    PDS.fastParam(0)      5 Floats, 100 Hz   (Joystick, PS4-Controller)
 *    PDS.param(3)          50 Floats, 2 Hz    (Tuning-Werte)
 *    PDS.paramBool(7)      50 Bools,  2 Hz    (Schalter)
 *    PDS.param("Kp")       dasselbe per Name (Namen aus channel_config.h)
 *    PDS.linkOk()          true, solange die GUI sendet -> Not-Aus-Kriterium
 *
 *  ── Verkabelung ────────────────────────────────────────────────────────
 *    Teensy Pin 14 (TX3) ──→ RPi Zero Pin 10 (GPIO15, UART RX)
 *    Teensy Pin 15 (RX3) ←── RPi Zero Pin  8 (GPIO14, UART TX)   PFLICHT
 *    GND                 ─── RPi Zero Pin  6 (GND)
 *    Andere UART-Instanz? -> UART_DBG in params.h aendern, sonst nichts.
 *
 *  ── Wire-Format (mit uart_receiver.py + config.py abgestimmt) ───────────
 *    [0..3]   uint32 Magic 0xDEADBEEF
 *    [4..7]   uint32 micros()
 *    [8..807] float32[200]                        = 808 Bytes @ 100 Hz
 *    Baudraten-Budget bei 1 Mbps: Uplink ~81 %, Downlink ~3 %.
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
#define PDS_VERSION "2.0"

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
// dauerhaft ~2.4 kB/s des UART-Budgets zu verbrauchen. Sobald die GUI sendet,
// wird wieder auf PDS_DESC_REPEAT_MS zurueckgesetzt.
#ifndef PDS_DESC_REPEAT_MAX_MS
#define PDS_DESC_REPEAT_MAX_MS 60000
#endif

// Bindungs-Typ eines per bind()/track() registrierten Kanals (Auto-Sampling).
enum class BoundChannelType : uint8_t {
    NONE = 0, FLOAT_PTR, DOUBLE_PTR, BOOL_PTR,
    I8_PTR, U8_PTR, I16_PTR, U16_PTR, I32_PTR, U32_PTR
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
        /// Param-Downlink und sendet alle 10 ms ein Telemetriepaket.
        void update();

        // ══════════════════════════════════════════════════════════════
        //  Kanaele schreiben — Variante 1: automatisch per Name
        // ══════════════════════════════════════════════════════════════

        /// Wert unter einem Namen anzeigen. Der Kanal wird beim ersten
        /// Aufruf automatisch vergeben und der Name an die GUI gemeldet.
        /// Gibt den benutzten Kanal zurueck (meist ignorierbar).
        ///   PDS.plot("Ball_X", ballX);
        /// `name` sollte ein String-Literal sein (dann ist der Aufruf durch
        /// den internen Cache praktisch kostenlos).
        uint8_t plot(const char* name, float value);

        template <class T>
        uint8_t plot(const char* name, T value) {
            return plot(name, static_cast<float>(value));
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

        void bind(uint8_t chn, float*    ptr, const char* name = nullptr);
        void bind(uint8_t chn, double*   ptr, const char* name = nullptr);
        void bind(uint8_t chn, bool*     ptr, const char* name = nullptr);
        void bind(uint8_t chn, int8_t*   ptr, const char* name = nullptr);
        void bind(uint8_t chn, uint8_t*  ptr, const char* name = nullptr);
        void bind(uint8_t chn, int16_t*  ptr, const char* name = nullptr);
        void bind(uint8_t chn, uint16_t* ptr, const char* name = nullptr);
        void bind(uint8_t chn, int32_t*  ptr, const char* name = nullptr);
        void bind(uint8_t chn, uint32_t* ptr, const char* name = nullptr);

        /// bind() mit automatischer Kanalvergabe — die bequemste Variante:
        ///   void setup() { PDS.begin(); PDS.track("Akku", &akkuVolt); }
        template <class T>
        uint8_t track(const char* name, T* ptr) {
            uint8_t chn = channelFor(name);
            bind(chn, ptr, name);
            return chn;
        }

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
        //  Diagnose
        // ══════════════════════════════════════════════════════════════

        uint32_t slowPacketCount()  const { return _slowPktCount; }
        uint32_t fastPacketCount()  const { return _fastPktCount; }
        uint32_t txPacketCount()    const { return _txPktCount; }
        uint32_t txDropCount()      const { return _txDrops; }
        uint32_t paramSyncLosses()  const { return _paramSyncLosses; }
        uint8_t  usedChannels()     const { return _autoNext; }
        bool     descriptorTruncated() const { return _descOverflow; }

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

        float    _fastFloats[PARAM_FAST_FLOAT_COUNT]  = {0};
        uint32_t _lastFastRxMs = 0;

        // Parser-Zustand (frueher function-static — als Member ist die
        // Klasse damit auch in einem Zweit-Objekt sauber initialisiert).
        uint8_t  _rxBuf[PARAM_SLOW_PACKET_BYTES];
        int      _rxFill        = 0;
        int      _rxExpectedLen = 0;

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

        // ── Namens-/Overlay-Deskriptor -> GUI ──────────────────────────
        size_t  _descJsonLen    = 0;
        uint8_t _descChunkCount = 0;
        uint8_t _descNextChunk  = 0xFF;   // 0xFF = kein Sendevorgang aktiv
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
