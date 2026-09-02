#include "PDS.h"
#include "elapsedMillis.h"
#include <stdarg.h>
#include <string.h>
#include <math.h>

// ── channel_config.h ist OPTIONAL ─────────────────────────────────────────
//  Ohne die Datei laesst sich PDS.h/PDS.cpp unveraendert in ein beliebiges
//  Projekt kopieren: es gibt dann einfach keine vorbelegten Namen, keine
//  Param-Konfiguration und keine Overlays, alles andere (inkl. plot()/track()/
//  event()/log()) funktioniert identisch.
//  Die Strukturen selbst stehen in params.h — sie muessen auch dann bekannt
//  sein, wenn channel_config.h fehlt.
#if defined(__has_include)
#  if __has_include("channel_config.h")
#    include "channel_config.h"
#    define PDS_HAS_CHANNEL_CONFIG 1
#  endif
#endif

#ifndef PDS_HAS_CHANNEL_CONFIG
static const ChannelNameDef CHANNEL_NAMES[]         = { {0, nullptr, ""} };
static constexpr size_t     CHANNEL_NAMES_COUNT     = 0;
static const ParamDef       PARAM_SLOW_FLOATS[]     = { {0, nullptr} };
static constexpr size_t     PARAM_SLOW_FLOATS_COUNT = 0;
static const ParamDef       PARAM_SLOW_BOOLS[]      = { {0, nullptr} };
static constexpr size_t     PARAM_SLOW_BOOLS_COUNT  = 0;
static const ParamDef       PARAM_FAST_FLOATS[]     = { {0, nullptr} };
static constexpr size_t     PARAM_FAST_FLOATS_COUNT = 0;
static const JoystickDef    PARAM_JOYSTICKS[]       = { {nullptr, "fast", 0, 1} };
static constexpr size_t     PARAM_JOYSTICKS_COUNT   = 0;
static const OverlayDef     CHANNEL_OVERLAYS[]      = { {0, "", ""} };
static constexpr size_t     CHANNEL_OVERLAYS_COUNT  = 0;
#endif

// GUI_SETTINGS[] ist NEU (PDS 2.2) und bekommt deshalb eine eigene Weiche:
// eine channel_config.h aus einem bestehenden Roboterprojekt kennt die
// Tabelle noch nicht, soll aber unveraendert weiter uebersetzen. Wer sie
// benutzt, setzt in channel_config.h direkt davor
//     #define PDS_HAS_GUI_SETTINGS 1
// (die ausgelieferte Vorlage tut das bereits).
#ifndef PDS_HAS_GUI_SETTINGS
static const SettingDef GUI_SETTINGS[]     = { SettingDef("", 0.0f) };
static constexpr size_t GUI_SETTINGS_COUNT = 0;
#endif

// Die eine, im Sketch benutzte Instanz (siehe PDS.h).
PowerDebugger PDS;

// ══════════════════════════════════════════════════════════════════════════
//  Wire-Format-Konstanten
// ══════════════════════════════════════════════════════════════════════════

static constexpr uint32_t HEADER_MAGIC = 0xDEADBEEF;

// MAX_FLOATS ist Teil des WIRE-FORMATS und muss mit rpi_zero_node/
// uart_receiver.py (MAX_FLOATS) und rpi5_monitor/.../config.py (MAX_FLOATS)
// uebereinstimmen. ACTIVE_CHANNELS (Build-Flag) steuert nur, wie viele davon
// benannt/gebunden werden koennen -- es darf MAX_FLOATS nicht ueberschreiten,
// sonst wuerde sampleBoundChannels() ueber debugData[] hinausschreiben.
static constexpr int MAX_FLOATS   = 200;
static constexpr int PACKET_BYTES = 8 + MAX_FLOATS * 4;   // 808 bei 200 Kanaelen

static_assert(ACTIVE_CHANNELS <= MAX_FLOATS,
              "ACTIVE_CHANNELS darf MAX_FLOATS (Wire-Format) nicht ueberschreiten");
static_assert(ACTIVE_CHANNELS > 0, "ACTIVE_CHANNELS muss > 0 sein");
static_assert((PDS_NAME_CACHE_SIZE & (PDS_NAME_CACHE_SIZE - 1)) == 0,
              "PDS_NAME_CACHE_SIZE muss eine Zweierpotenz sein");
static_assert(PDS_AUTO_CHANNEL_BASE < ACTIVE_CHANNELS,
              "PDS_AUTO_CHANNEL_BASE liegt ausserhalb der aktiven Kanaele");
static_assert(PDS_EVENT_QUEUE_SIZE > 0 && PDS_EVENT_QUEUE_SIZE <= 64,
              "PDS_EVENT_QUEUE_SIZE muss zwischen 1 und 64 liegen");
static_assert(PDS_UNIT_MAXLEN >= 2, "PDS_UNIT_MAXLEN muss mindestens 2 sein");

// Der Telemetrietakt liegt seit PDS 2.2 in _samplePeriodMs (Standard 10 ms
// = 100 Hz) und laesst sich mit setTelemetryRate() zur Laufzeit aendern.
static constexpr uint32_t WARN_INTERVAL_MS = 1000;   // Rate-Limit fuer Serial-Warnungen

// Ein Deskriptor-Chunk (257 B) alle 20 ms = 12.9 kB/s. Zusammen mit den
// 80.8 kB/s Telemetrie bleibt das unter den 100 kB/s, die 1 Mbps 8N1
// hergeben — der Deskriptor verdraengt also keine Telemetrie, sondern
// braucht fuer einen vollen 24-kB-Deskriptor knapp 2 s. Da er nur beim Boot
// und auf Anfrage laeuft, ist das der richtige Kompromiss.
static constexpr uint32_t DESC_CHUNK_PERIOD_MS = 20;

// ── UART-Puffer ───────────────────────────────────────────────────────────
//  TX: 808 B/Paket bei 100 Hz = 80.8 kB/s gegen 100 kB/s Baud-Budget
//      (1 Mbps, 8N1 = 10 Bit/Byte). 4 KB Puffer ueberbrueckt Jitter.
//
//  RX: WICHTIG fuer die Latenz des Fast-/Joystick-Kanals. Der Teensy-Core
//      legt per Default nur 64 Byte RX-Puffer an -- ein einzelnes Slow-Paket
//      (258 B) passt da nicht hinein und laeuft schon waehrend des Empfangs
//      ueber, sobald loop() nicht alle ~0.6 ms pollt. Die dabei verlorenen
//      Bytes bringen den Paket-Parser aus dem Tritt: er wartet dann auf die
//      fehlenden Bytes und frisst dabei die naechsten Fast-Pakete als
//      vermeintliche Nutzlast auf -> ruckartige, hundert Millisekunden lange
//      Aussetzer der Fernsteuerung. 2 KB puffern ~600 ms Downlink-Strom und
//      machen den Empfang unabhaengig von der Zykluszeit des Hauptprogramms.
static uint8_t _uart_dbg_tx_buf[4096];
static uint8_t _uart_dbg_rx_buf[2048];

// Nutzdaten aller Kanaele. Bewusst dateilokal: es gibt genau eine
// PowerDebugger-Instanz (PDS), und so bleibt das Objekt selbst klein.
static float debugData[MAX_FLOATS];

// Der Deskriptor-Puffer wird nur beim Boot / auf Anfrage gebraucht und liegt
// deshalb auf Teensy 4.x im langsameren, dafuer reichlich vorhandenen OCRAM
// statt im knappen, schnellen DTCM.
#if defined(__IMXRT1062__)
#  define PDS_SLOWMEM DMAMEM
#else
#  define PDS_SLOWMEM
#endif
#ifndef PDS_DESC_BUF_BYTES
#define PDS_DESC_BUF_BYTES CHANNEL_DESC_JSON_BUF_BYTES   // Default aus params.h
#endif
PDS_SLOWMEM static char _descBuf[PDS_DESC_BUF_BYTES];

// chunk_idx/chunk_count sind je ein Byte im Wire-Format -> mehr als 255
// Chunks liessen sich gar nicht adressieren.
static_assert(PDS_DESC_BUF_BYTES / CHANNEL_DESC_CHUNK_PAYLOAD_MAX < 255,
              "PDS_DESC_BUF_BYTES zu gross fuer die 8-Bit-Chunknummer");

// Reserve fuer die STRUKTURZEICHEN des JSON (Abschnittstrenner + schliessende
// Klammern), damit der Deskriptor auch bei vollem Puffer gueltiges JSON
// bleibt: die variablen Inhalte (Namen, Param-Konfiguration, Overlays) duerfen
// nur bis Puffergroesse minus dieser Reserve wachsen, die Struktur passt
// danach garantiert noch hinein. Siehe JsonBuilder::raw() vs. put().
//
// 256 statt der frueheren 192: die Abschnittstrenner summieren sich vom
// ersten Ueberlauf an gerechnet auf 191 Zeichen, mit dem neuen Abschnitt
// "settings" auf 205. Die alte Reserve war damit auf ein Zeichen genau
// ausgereizt — ein weiterer Abschnitt haette den Deskriptor bei vollem
// Puffer ungueltig gemacht.
static constexpr size_t DESC_STRUCT_RESERVE = 256;

static elapsedMillis DBGTimer;
static elapsedMillis DescChunkTimer;
static elapsedMillis ParamAckTimer;
static uint32_t      _lastWarnMs = 0;

// ── Watchdog: i.MX RT1062 WDOG1 (Referenzhandbuch Kap. 62) ────────────────
//  Bewusst mit eigenen Zeigern statt der Core-Makros: so haengt die
//  Bibliothek an keiner bestimmten Teensyduino-Version und laesst sich
//  unveraendert in fremde Projekte kopieren.
#if defined(__IMXRT1062__)
static volatile uint16_t* const PDS_WDOG1_WCR  = (volatile uint16_t*)0x400B8000;
static volatile uint16_t* const PDS_WDOG1_WSR  = (volatile uint16_t*)0x400B8002;
static volatile uint16_t* const PDS_WDOG1_WRSR = (volatile uint16_t*)0x400B8004;
static constexpr uint16_t PDS_WCR_WDE   = 0x0004;   // Watchdog Enable (nur einmal setzbar)
static constexpr uint16_t PDS_WCR_SRS   = 0x0010;   // 1 = keinen Software-Reset ausloesen
static constexpr uint16_t PDS_WCR_WDA   = 0x0020;   // 1 = WDOG_B-Pin nicht ziehen
static constexpr uint16_t PDS_WRSR_TOUT = 0x0002;   // letzter Reset kam vom Timeout
#endif

// Bereichsgeprueft: ein Channel()-Aufruf mit einem Index >= MAX_FLOATS hat
// vorher hinter debugData[] geschrieben und dabei beliebigen anderen Speicher
// zerstoert (uint8_t-Index reicht bis 255, das Array hat 200).
static inline void writeChannel(int chn, float value) {
    if ((unsigned)chn < (unsigned)MAX_FLOATS) debugData[chn] = value;
}

// Bevor irgendetwas ausser Telemetrie geschrieben wird, muss im TX-Puffer
// noch ein KOMPLETTES Telemetriepaket zusaetzlich Platz haben. Damit kann
// kein Deskriptor-/Ereignis-/Ack-Paket den 100-Hz-Takt verdraengen.
static inline bool txRoomFor(int extraBytes) {
    return UART_DBG.availableForWrite() >= (PACKET_BYTES + extraBytes);
}

// Klartextmeldungen der Bibliothek. Abschaltbar ueber
// PDS.setSerialDiagnostics(false); dateilokal, weil pdsWarn() eine freie
// Funktion ist und auch aus const-Methoden heraus benutzt wird.
static bool g_serialDiag = true;

// Ist im USB-Serial-Puffer Platz fuer `len` Zeichen?
//
// DAS IST DER ENTSCHEIDENDE PUNKT und nicht bloss Feinschliff: Serial.print()
// auf dem Teensy 4 WARTET, wenn der Host die Schnittstelle geoeffnet hat, sie
// aber gerade nicht leerliest (ein offenes, weggescrolltes Terminalfenster
// genuegt) — bis zu 120 ms je Aufruf. Genau so lange steht dann auch die
// Regelschleife des Roboters. Mit dieser Abfrage faellt die Meldung lieber
// aus, statt zu warten.
static inline bool serialRoomFor(int len) {
    if (!g_serialDiag) return false;
    if (!Serial) return false;                 // kein Terminal offen
    return Serial.availableForWrite() >= len;
}

// Serial-Warnungen sind im Roboterbetrieb Nebensache und duerfen den
// 100-Hz-Takt nicht stoeren: hoechstens eine pro Sekunde, nur wenn ein
// USB-Serial-Terminal offen ist UND dessen Puffer die Zeile auch aufnimmt.
static void pdsWarn(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void pdsWarn(const char* fmt, ...) {
    uint32_t now = millis();
    if (now - _lastWarnMs < WARN_INTERVAL_MS) return;
    if (!g_serialDiag || !Serial) return;
    _lastWarnMs = now;
    char line[128];
    va_list args;
    va_start(args, fmt);
    const int n = vsnprintf(line, sizeof(line), fmt, args);
    va_end(args);
    // +8 fuer "[PDS] " und den Zeilenumbruch.
    if (!serialRoomFor((n > 0 ? n : 0) + 8)) return;
    Serial.print("[PDS] ");
    Serial.println(line);
}

void PowerDebugger::setSerialDiagnostics(bool on) {
    _serialDiagOn = on;    // Member  — fuer printStatus()/Diagnose
    g_serialDiag  = on;    // dateilokal — fuer pdsWarn(), das keine Instanz kennt
}

// ══════════════════════════════════════════════════════════════════════════
//  Kanaele schreiben
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::Channel(uint8_t chn, float val) {
    writeChannel(chn, val);
}

void PowerDebugger::Channel(uint8_t chn, float val, const char* name) {
    writeChannel(chn, val);
    if (name) setName(chn, name);
}

void PowerDebugger::setName(uint8_t chn, const char* name) {
    if (chn >= ACTIVE_CHANNELS || !name || !name[0]) return;

    // Unveraendert? Dann NICHTS anfassen — insbesondere nicht _descBuilt.
    //
    // Das ist kein Feinschliff: PDS.Channel(12, wert, "Name") ist ein voellig
    // ueblicher Aufruf mitten in der Regelschleife und landete hier 100x pro
    // Sekunde. Jeder dieser Aufrufe erklaerte den Deskriptor fuer ungueltig,
    // und die naechste Namensmeldung baute die kompletten 24 kB JSON neu auf.
    if (strncmp(_names[chn], name, CHANNEL_NAME_MAXLEN - 1) == 0) return;

    strncpy(_names[chn], name, CHANNEL_NAME_MAXLEN - 1);
    _names[chn][CHANNEL_NAME_MAXLEN - 1] = '\0';
    // Namen sind Teil des Deskriptors -> beim naechsten Sendevorgang neu bauen.
    _descBuilt = false;
}

// ── Auto-Kanalvergabe ─────────────────────────────────────────────────────
//  channelFor() ist der Kern der "keine Kanalnummern mehr"-Bedienung:
//    1. Pointer-Cache (String-Literale haben eine stabile Adresse) -> O(1)
//    2. Namensvergleich ueber die Registry (nur beim allerersten Aufruf
//       eines Namens bzw. nach einer Cache-Kollision)
//    3. sonst: naechsten noch unbenannten Kanal reservieren
uint8_t PowerDebugger::channelFor(const char* name) {
    if (!name || !name[0]) return 0xFF;

    const size_t slot = ((uintptr_t)name >> 2) & (PDS_NAME_CACHE_SIZE - 1);
    if (_nameCache[slot].key == name) return _nameCache[slot].chn;

    // Bereits vergeben?
    for (int i = 0; i < ACTIVE_CHANNELS; i++) {
        if (_names[i][0] && strncmp(_names[i], name, CHANNEL_NAME_MAXLEN - 1) == 0) {
            _nameCache[slot].key = name;
            _nameCache[slot].chn = (uint8_t)i;
            return (uint8_t)i;
        }
    }

    // Neu vergeben: naechster freier (unbenannter) Kanal.
    while (_autoNext < ACTIVE_CHANNELS && _names[_autoNext][0] != '\0') _autoNext++;
    if (_autoNext >= ACTIVE_CHANNELS) {
        pdsWarn("Kein freier Kanal mehr fuer \"%s\" (ACTIVE_CHANNELS=%d)",
                name, ACTIVE_CHANNELS);
        return 0xFF;   // Channel(0xFF, ...) wird von writeChannel() verworfen
    }

    const uint8_t chn = _autoNext++;
    setName(chn, name);
    _nameCache[slot].key = name;
    _nameCache[slot].chn = chn;
    return chn;
}

uint8_t PowerDebugger::plot(const char* name, float value) {
    const uint8_t chn = channelFor(name);
    writeChannel(chn, value);
    return chn;
}

uint8_t PowerDebugger::plot(const char* name, float value, const char* unit) {
    const uint8_t chn = channelFor(name);
    writeChannel(chn, value);
    if (unit && chn != 0xFF) setUnit(chn, unit);
    return chn;
}

// ══════════════════════════════════════════════════════════════════════════
//  Einheiten
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::setUnit(uint8_t chn, const char* unit) {
    if (chn >= ACTIVE_CHANNELS || !unit || !unit[0]) return;

    for (uint8_t i = 0; i < _unitCount; i++) {
        if (_units[i].chn == chn) {
            if (strncmp(_units[i].unit, unit, PDS_UNIT_MAXLEN - 1) == 0) return;
            strncpy(_units[i].unit, unit, PDS_UNIT_MAXLEN - 1);
            _units[i].unit[PDS_UNIT_MAXLEN - 1] = '\0';
            _descBuilt = false;
            return;
        }
    }
    if (_unitCount >= PDS_MAX_UNITS) {
        pdsWarn("Keine Einheit mehr frei (PDS_MAX_UNITS=%d)", PDS_MAX_UNITS);
        return;
    }
    _units[_unitCount].chn = chn;
    strncpy(_units[_unitCount].unit, unit, PDS_UNIT_MAXLEN - 1);
    _units[_unitCount].unit[PDS_UNIT_MAXLEN - 1] = '\0';
    _unitCount++;
    _descBuilt = false;
}

const char* PowerDebugger::unitOf(uint8_t chn) const {
    for (uint8_t i = 0; i < _unitCount; i++) {
        if (_units[i].chn == chn) return _units[i].unit;
    }
    return "";
}

// ══════════════════════════════════════════════════════════════════════════
//  Ereignisse und Logzeilen
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::pushEvent(uint8_t kind, uint8_t level, const char* text, float value) {
    if (!text) text = "";
    // Bei vollem Puffer gewinnt der AELTERE Eintrag: eine Fehlermeldung soll
    // nicht von nachfolgendem Rauschen verdraengt werden.
    if (_evCount >= PDS_EVENT_QUEUE_SIZE) { _evDrops++; return; }

    const uint8_t slot = (uint8_t)((_evHead + _evCount) % PDS_EVENT_QUEUE_SIZE);
    EventEntry& e = _evQueue[slot];
    e.ts_us = micros();
    e.value = value;
    e.kind  = kind;
    e.level = level;
    size_t n = strlen(text);
    if (n > (size_t)PDS_EVENT_TEXT_MAX) n = (size_t)PDS_EVENT_TEXT_MAX;
    memcpy(e.text, text, n);
    e.len = (uint8_t)n;
    _evCount++;
}

void PowerDebugger::pushEventV(uint8_t kind, uint8_t level, float value,
                                const char* fmt, va_list args) {
    char line[PDS_EVENT_TEXT_MAX + 1];
    vsnprintf(line, sizeof(line), fmt ? fmt : "", args);
    pushEvent(kind, level, line, value);
}

void PowerDebugger::logf(const char* fmt, ...) {
    va_list args; va_start(args, fmt);
    pushEventV(PDS_EVENT_KIND_LOG, PDS_LEVEL_INFO, 0.0f, fmt, args);
    va_end(args);
}

void PowerDebugger::warn(const char* fmt, ...) {
    va_list args; va_start(args, fmt);
    pushEventV(PDS_EVENT_KIND_LOG, PDS_LEVEL_WARN, 0.0f, fmt, args);
    va_end(args);
}

void PowerDebugger::error(const char* fmt, ...) {
    va_list args; va_start(args, fmt);
    pushEventV(PDS_EVENT_KIND_LOG, PDS_LEVEL_ERROR, 0.0f, fmt, args);
    va_end(args);
}

bool PowerDebugger::sendNextEvent() {
    if (_evCount == 0 || !_eventsOn) return false;

    // Rate-Limit: eine Endlosschleife mit log() im Roboter-Code darf den
    // Uplink nicht fluten (Standard PDS_EVENT_MAX_PER_SEC aus params.h,
    // zur Laufzeit ueber setEventRateLimit()).
    const uint32_t now = millis();
    if (now - _evWindowStartMs >= 1000) {
        _evWindowStartMs = now;
        _evInWindow = 0;
    }
    if (_evInWindow >= _eventMaxPerSec) return false;

    const EventEntry& e = _evQueue[_evHead];
    const int total = PDS_EVENT_HEADER_BYTES + (int)e.len;
    if (!txRoomFor(total)) return false;

    uint8_t pkt[PDS_EVENT_PACKET_MAX];
    const uint32_t magic = PDS_EVENT_MAGIC;
    memcpy(pkt,      &magic,   4);
    memcpy(pkt + 4,  &e.ts_us, 4);
    memcpy(pkt + 8,  &e.value, 4);
    pkt[12] = e.kind;
    pkt[13] = e.level;
    pkt[14] = e.len;
    pkt[15] = 0;                       // reserved -- Plausibilitaetspruefung im Node
    memcpy(pkt + PDS_EVENT_HEADER_BYTES, e.text, e.len);
    UART_DBG.write(pkt, total);

    _evHead = (uint8_t)((_evHead + 1) % PDS_EVENT_QUEUE_SIZE);
    _evCount--;
    _evSent++;
    _evInWindow++;
    return true;
}

// ══════════════════════════════════════════════════════════════════════════
//  Parameter-Rueckmeldung (2 Hz) — "was habe ich wirklich?"
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::sendParamAck() {
    if (!txRoomFor(PARAM_ACK_PACKET_BYTES)) return;

    uint8_t pkt[PARAM_ACK_PACKET_BYTES];
    const uint32_t magic   = PARAM_ACK_MAGIC;
    const uint32_t slowAge = (_lastSlowRxMs == 0) ? 0xFFFFFFFFUL : (millis() - _lastSlowRxMs);
    const uint32_t fastAge = (_lastFastRxMs == 0) ? 0xFFFFFFFFUL : (millis() - _lastFastRxMs);

    memcpy(pkt,      &magic,        4);
    memcpy(pkt + 4,  &_lastSlowSeq, 4);
    memcpy(pkt + 8,  &_lastFastSeq, 4);
    memcpy(pkt + 12, &slowAge,      4);
    memcpy(pkt + 16, &fastAge,      4);

    int off = PARAM_ACK_HEADER_BYTES;
    memcpy(pkt + off, _paramFloats, PARAM_SLOW_FLOAT_COUNT * 4);
    off += PARAM_SLOW_FLOAT_COUNT * 4;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) pkt[off + i] = _paramBools[i] ? 1 : 0;
    off += PARAM_SLOW_BOOL_COUNT;
    memcpy(pkt + off, _fastFloats, PARAM_FAST_FLOAT_COUNT * 4);

    UART_DBG.write(pkt, PARAM_ACK_PACKET_BYTES);
}

// ══════════════════════════════════════════════════════════════════════════
//  Kanal-Bindungen (Auto-Sampling)
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::bindRaw(uint8_t chn, void* ptr, BoundChannelType type,
                             const char* name) {
    if (chn >= ACTIVE_CHANNELS || !ptr) return;

    // Schon gebunden? Dann ersetzen statt einen zweiten Eintrag anzulegen —
    // sonst wuerde die Liste bei wiederholtem bind() ueberlaufen.
    for (uint8_t i = 0; i < _boundCount; i++) {
        if (_bound[i].chn == chn) {
            _bound[i].ptr  = ptr;
            _bound[i].type = type;
            if (name) setName(chn, name);
            return;
        }
    }
    if (_boundCount >= ACTIVE_CHANNELS) return;

    _bound[_boundCount].chn  = chn;
    _bound[_boundCount].ptr  = ptr;
    _bound[_boundCount].type = type;
    _boundCount++;
    if (name) setName(chn, name);
}

void PowerDebugger::bind(uint8_t c, float* p, const char* n)              { bindRaw(c, p, BoundChannelType::FLOAT_PTR,  n); }
void PowerDebugger::bind(uint8_t c, double* p, const char* n)             { bindRaw(c, p, BoundChannelType::DOUBLE_PTR, n); }
void PowerDebugger::bind(uint8_t c, bool* p, const char* n)               { bindRaw(c, p, BoundChannelType::BOOL_PTR,   n); }
void PowerDebugger::bind(uint8_t c, signed char* p, const char* n)        { bindRaw(c, p, BoundChannelType::SCHAR_PTR,  n); }
void PowerDebugger::bind(uint8_t c, unsigned char* p, const char* n)      { bindRaw(c, p, BoundChannelType::UCHAR_PTR,  n); }
void PowerDebugger::bind(uint8_t c, short* p, const char* n)              { bindRaw(c, p, BoundChannelType::SHORT_PTR,  n); }
void PowerDebugger::bind(uint8_t c, unsigned short* p, const char* n)     { bindRaw(c, p, BoundChannelType::USHORT_PTR, n); }
void PowerDebugger::bind(uint8_t c, int* p, const char* n)                { bindRaw(c, p, BoundChannelType::INT_PTR,    n); }
void PowerDebugger::bind(uint8_t c, unsigned int* p, const char* n)       { bindRaw(c, p, BoundChannelType::UINT_PTR,   n); }
void PowerDebugger::bind(uint8_t c, long* p, const char* n)               { bindRaw(c, p, BoundChannelType::LONG_PTR,   n); }
void PowerDebugger::bind(uint8_t c, unsigned long* p, const char* n)      { bindRaw(c, p, BoundChannelType::ULONG_PTR,  n); }
void PowerDebugger::bind(uint8_t c, long long* p, const char* n)          { bindRaw(c, p, BoundChannelType::LLONG_PTR,  n); }
void PowerDebugger::bind(uint8_t c, unsigned long long* p, const char* n) { bindRaw(c, p, BoundChannelType::ULLONG_PTR, n); }

// Unmittelbar vor dem Senden aufgerufen: gebundene Kanaele aus ihrem
// Pointer in debugData[] uebernehmen. Iteriert nur ueber die tatsaechlich
// gebundenen Eintraege (frueher: alle 200 Kanaele, 100x/s).
void PowerDebugger::sampleBoundChannels() {
    for (uint8_t i = 0; i < _boundCount; i++) {
        const BoundChannel& b = _bound[i];
        float v;
        switch (b.type) {
            case BoundChannelType::FLOAT_PTR:  v = *(float*)b.ptr;                       break;
            case BoundChannelType::DOUBLE_PTR: v = (float)(*(double*)b.ptr);             break;
            case BoundChannelType::BOOL_PTR:   v = *(bool*)b.ptr ? 1.0f : 0.0f;          break;
            case BoundChannelType::SCHAR_PTR:  v = (float)(*(signed char*)b.ptr);        break;
            case BoundChannelType::UCHAR_PTR:  v = (float)(*(unsigned char*)b.ptr);      break;
            case BoundChannelType::SHORT_PTR:  v = (float)(*(short*)b.ptr);              break;
            case BoundChannelType::USHORT_PTR: v = (float)(*(unsigned short*)b.ptr);     break;
            case BoundChannelType::INT_PTR:    v = (float)(*(int*)b.ptr);                break;
            case BoundChannelType::UINT_PTR:   v = (float)(*(unsigned int*)b.ptr);       break;
            case BoundChannelType::LONG_PTR:   v = (float)(*(long*)b.ptr);               break;
            case BoundChannelType::ULONG_PTR:  v = (float)(*(unsigned long*)b.ptr);      break;
            case BoundChannelType::LLONG_PTR:  v = (float)(*(long long*)b.ptr);          break;
            case BoundChannelType::ULLONG_PTR: v = (float)(*(unsigned long long*)b.ptr); break;
            default: continue;
        }
        debugData[b.chn] = v;
    }
}

// ══════════════════════════════════════════════════════════════════════════
//  Deskriptor: JSON bauen, chunken, ueber UART_DBG senden
// ══════════════════════════════════════════════════════════════════════════
//  Wird beim Boot einmal und danach nur auf Anfrage bzw. beim
//  Wiederverbinden gesendet — Effizienz ist hier zweitrangig gegenueber
//  Lesbarkeit und Robustheit.

namespace {

struct JsonBuilder {
    char*  buf;
    size_t total;    // komplette Puffergroesse
    size_t cap;      // nutzbare Kapazitaet fuer VARIABLE Inhalte
    size_t pos = 0;
    bool   overflow = false;

    JsonBuilder(char* b, size_t bytes)
        : buf(b), total(bytes),
          cap(bytes > DESC_STRUCT_RESERVE ? bytes - DESC_STRUCT_RESERVE : 0) {}

    /// Passen `need` weitere Bytes noch in den Nutzbereich?
    bool fits(size_t need) {
        if (pos + need < cap) return true;
        overflow = true;
        return false;
    }

    __attribute__((format(printf, 2, 3)))
    void put(const char* fmt, ...) {
        if (pos + 1 >= cap) { overflow = true; return; }
        va_list args;
        va_start(args, fmt);
        const int n = vsnprintf(buf + pos, cap - pos, fmt, args);
        va_end(args);
        if (n <= 0) return;
        // vsnprintf liefert die Laenge, die OHNE Abschneiden noetig gewesen
        // waere. Ungeprueft uebernommen wandert pos hinter das Pufferende --
        // _descJsonLen waere dann groesser als _descBuf und sendNextDescChunk()
        // haette Fremdspeicher verschickt.
        const size_t written = (size_t)n;
        const size_t room    = cap - pos - 1;
        if (written >= room) overflow = true;
        pos += (written < room) ? written : room;
    }

    /// Zahl JSON-konform anhaengen. %g ist kompakt ("2.5" statt "2.500"),
    /// liefert fuer NaN/Inf aber "nan"/"inf" — beides ist KEIN gueltiges
    /// JSON und wuerde den Parser der GUI ueber den kompletten Deskriptor
    /// stolpern lassen. Deshalb hier abgefangen.
    void putNum(float v) {
        if (!isfinite(v)) v = 0.0f;
        put("%g", (double)v);
    }

    /// Haengt s escaped an (Anfuehrungszeichen/Backslash/Steuerzeichen),
    /// OHNE die umgebenden Quotes.
    void putEscaped(const char* s) {
        if (!s) return;
        for (const char* p = s; *p; ++p) {
            const unsigned char c = (unsigned char)*p;
            if (c == '"' || c == '\\') {
                if (pos + 3 >= cap) { overflow = true; return; }
                buf[pos++] = '\\';
                buf[pos++] = (char)c;
            } else if (c < 0x20) {
                // Steuerzeichen sind in JSON-Strings nicht erlaubt.
                if (!fits(8)) return;
                put("\\u%04x", (unsigned)c);
            } else {
                if (pos + 2 >= cap) { overflow = true; return; }
                buf[pos++] = (char)c;
            }
        }
    }

    /// Strukturzeichen (Abschnittstrenner, schliessende Klammern). Sie
    /// duerfen die Reserve nutzen und passen deshalb IMMER — auch wenn die
    /// variablen Inhalte den Puffer bereits ausgeschoepft haben. Genau das
    /// haelt das JSON bei Ueberlauf gueltig: dann fehlen zwar Eintraege,
    /// aber die Klammerstruktur bleibt vollstaendig.
    void raw(const char* s) {
        while (*s && pos + 1 < total) buf[pos++] = *s++;
    }
};

/// "index":"name" — gibt false zurueck, wenn kein Platz mehr war (Aufrufer
/// bricht die Schleife dann ab, damit das JSON gueltig bleibt).
bool putNameEntry(JsonBuilder& j, bool& first, int index, const char* name) {
    if (!name || !name[0]) return true;                       // Luecke: ueberspringen
    if (!j.fits(strlen(name) * 6 + 16)) return false;         // *6: \u00xx im Extremfall
    if (!first) j.put(",");
    first = false;
    j.put("\"%d\":\"", index);
    j.putEscaped(name);
    j.put("\"");
    return true;
}

/// Ein Parameter-Eintrag der Widget-Konfiguration.
bool putParamDef(JsonBuilder& j, bool& first, const ParamDef& d) {
    if (!d.name || !d.name[0]) return true;
    const size_t need = strlen(d.name) * 6
                      + strlen(d.widget ? d.widget : "")
                      + strlen(d.group  ? d.group  : "") * 6 + 140;
    if (!j.fits(need)) return false;
    if (!first) j.put(",");
    first = false;
    j.put("{\"i\":%d,\"n\":\"", (int)d.index);
    j.putEscaped(d.name);
    j.put("\",\"w\":\"%s\",\"min\":", d.widget ? d.widget : "slider");
    j.putNum(d.min_val);
    j.put(",\"max\":");
    j.putNum(d.max_val);
    j.put(",\"step\":");
    j.putNum(d.step);
    j.put(",\"def\":");
    j.putNum(d.def_val);
    if (d.group && d.group[0]) {
        j.put(",\"g\":\"");
        j.putEscaped(d.group);
        j.put("\"");
    }
    if (d.momentary) j.put(",\"m\":true");
    j.put("}");
    return true;
}

}  // namespace

// ══════════════════════════════════════════════════════════════════════════
//  Deskriptor: JSON in SCHEIBEN bauen
// ══════════════════════════════════════════════════════════════════════════
//  Frueher entstand der komplette JSON-Text (bis 24 kB, ueber 1500
//  vsnprintf-Aufrufe) in EINEM Aufruf mitten im update(). Das waren je nach
//  Konfiguration mehrere Millisekunden am Stueck — und zwar genau dann, wenn
//  keine GUI da ist und der Deskriptor deshalb regelmaessig wiederholt wird.
//  Fuer eine Regelschleife, die alle 10 ms fertig sein soll, ist das ein
//  Aussetzer, kein Rundungsfehler.
//
//  Jetzt merken sich _descStage/_descIdx, wo der letzte Aufruf aufgehoert
//  hat: je update() wandern hoechstens PDS_DESC_BUILD_STEP Eintraege in den
//  Puffer, und nur solange vom Zeitbudget noch etwas uebrig ist. Der
//  Deskriptor braucht dadurch ein paar Zyklen laenger — er wird ohnehin
//  chunkweise mit 20 ms Abstand verschickt, das faellt also nicht auf.
namespace {

// Abschnitte des Deskriptors, in genau der Reihenfolge, in der sie im JSON
// stehen. Die Zwischenzeichen schreibt jeweils der UEBERGANG zum naechsten
// Abschnitt, die Reserve DESC_STRUCT_RESERVE haelt dafuer Platz frei.
enum : uint8_t {
    DS_META = 0, DS_CHANNELS, DS_UNITS,
    DS_PSF, DS_PSB, DS_PFF,
    DS_CFG_SF, DS_CFG_SB, DS_CFG_FF, DS_CFG_JS,
    DS_OVERLAYS, DS_SETTINGS,
    DS_DONE = 0xFF
};

}  // namespace

void PowerDebugger::beginDescriptorBuild() {
    _descStage    = DS_META;
    _descIdx      = 0;
    _descPos      = 0;
    _descFirst    = true;
    _descOverflow = false;
    _descBuilt    = false;
}

bool PowerDebugger::buildDescriptorStep() {
    if (_descStage == DS_DONE) return true;

    // JsonBuilder ist zustandslos ausser pos/overflow — die beiden liegen als
    // Member vor und werden hier nur ein- und wieder ausgehaengt.
    JsonBuilder j(_descBuf, sizeof(_descBuf));
    j.pos      = _descPos;
    j.overflow = _descOverflow;

    int budget = PDS_DESC_BUILD_STEP;

    switch (_descStage) {

    // ── meta: Firmware-Version und Eckdaten ───────────────────────────────
    case DS_META:
        j.raw("{\"meta\":{");
        j.put("\"pds\":\"%s\",\"wire\":%d,\"channels\":%d,\"used\":%d",
              PDS_VERSION, (int)PDS_WIRE_VERSION, (int)ACTIVE_CHANNELS, (int)_autoNext);
        j.put(",\"build\":\"%s %s\"", __DATE__, __TIME__);
        j.put(",\"rate\":%u", (unsigned)telemetryRate());
        if (_fwVersion[0]) {
            j.put(",\"fw\":\"");
            j.putEscaped(_fwVersion);
            j.put("\"");
        }
        if (_wdtWasReset) j.put(",\"wdt_reset\":true");
        j.raw("},\"channels\":{");
        _descStage = DS_CHANNELS; _descIdx = 0; _descFirst = true;
        break;

    case DS_CHANNELS:
        while (budget-- > 0 && _descIdx < (uint16_t)ACTIVE_CHANNELS) {
            if (!putNameEntry(j, _descFirst, _descIdx, _names[_descIdx])) {
                _descIdx = (uint16_t)ACTIVE_CHANNELS;   // Puffer voll -> Rest weglassen
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)ACTIVE_CHANNELS) {
            j.raw("},\"units\":{");
            _descStage = DS_UNITS; _descIdx = 0; _descFirst = true;
        }
        break;

    case DS_UNITS:
        while (budget-- > 0 && _descIdx < _unitCount) {
            if (!putNameEntry(j, _descFirst, _units[_descIdx].chn, _units[_descIdx].unit)) {
                _descIdx = _unitCount;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= _unitCount) {
            j.raw("},\"param_slow_floats\":{");
            _descStage = DS_PSF; _descIdx = 0; _descFirst = true;
        }
        break;

    // ── Param-Namen (schlanker Pfad, den die GUI seit jeher liest) ────────
    case DS_PSF:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_SLOW_FLOATS_COUNT) {
            if (!putNameEntry(j, _descFirst, PARAM_SLOW_FLOATS[_descIdx].index,
                               PARAM_SLOW_FLOATS[_descIdx].name)) {
                _descIdx = (uint16_t)PARAM_SLOW_FLOATS_COUNT;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_SLOW_FLOATS_COUNT) {
            j.raw("},\"param_slow_bools\":{");
            _descStage = DS_PSB; _descIdx = 0; _descFirst = true;
        }
        break;

    case DS_PSB:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_SLOW_BOOLS_COUNT) {
            if (!putNameEntry(j, _descFirst, PARAM_SLOW_BOOLS[_descIdx].index,
                               PARAM_SLOW_BOOLS[_descIdx].name)) {
                _descIdx = (uint16_t)PARAM_SLOW_BOOLS_COUNT;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_SLOW_BOOLS_COUNT) {
            j.raw("},\"param_fast_floats\":{");
            _descStage = DS_PFF; _descIdx = 0; _descFirst = true;
        }
        break;

    case DS_PFF:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_FAST_FLOATS_COUNT) {
            if (!putNameEntry(j, _descFirst, PARAM_FAST_FLOATS[_descIdx].index,
                               PARAM_FAST_FLOATS[_descIdx].name)) {
                _descIdx = (uint16_t)PARAM_FAST_FLOATS_COUNT;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_FAST_FLOATS_COUNT) {
            j.raw("},\"param_cfg\":{\"slow_floats\":[");
            _descStage = DS_CFG_SF; _descIdx = 0; _descFirst = true;
        }
        break;

    // ── Vollstaendige Widget-Konfiguration des Parameter-Tabs ─────────────
    case DS_CFG_SF:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_SLOW_FLOATS_COUNT) {
            if (!putParamDef(j, _descFirst, PARAM_SLOW_FLOATS[_descIdx])) {
                _descIdx = (uint16_t)PARAM_SLOW_FLOATS_COUNT;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_SLOW_FLOATS_COUNT) {
            j.raw("],\"slow_bools\":[");
            _descStage = DS_CFG_SB; _descIdx = 0; _descFirst = true;
        }
        break;

    case DS_CFG_SB:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_SLOW_BOOLS_COUNT) {
            if (!putParamDef(j, _descFirst, PARAM_SLOW_BOOLS[_descIdx])) {
                _descIdx = (uint16_t)PARAM_SLOW_BOOLS_COUNT;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_SLOW_BOOLS_COUNT) {
            j.raw("],\"fast_floats\":[");
            _descStage = DS_CFG_FF; _descIdx = 0; _descFirst = true;
        }
        break;

    case DS_CFG_FF:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_FAST_FLOATS_COUNT) {
            if (!putParamDef(j, _descFirst, PARAM_FAST_FLOATS[_descIdx])) {
                _descIdx = (uint16_t)PARAM_FAST_FLOATS_COUNT;
                break;
            }
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_FAST_FLOATS_COUNT) {
            j.raw("],\"joysticks\":[");
            _descStage = DS_CFG_JS; _descIdx = 0; _descFirst = true;
        }
        break;

    case DS_CFG_JS:
        while (budget-- > 0 && _descIdx < (uint16_t)PARAM_JOYSTICKS_COUNT) {
            const JoystickDef& js = PARAM_JOYSTICKS[_descIdx];
            if (!js.name || !js.name[0]) { _descIdx++; continue; }
            if (!j.fits(strlen(js.name) * 6 + 160)) {
                _descIdx = (uint16_t)PARAM_JOYSTICKS_COUNT;
                break;
            }
            if (!_descFirst) j.put(",");
            _descFirst = false;
            j.put("{\"n\":\"");
            j.putEscaped(js.name);
            j.put("\",\"s\":\"%s\",\"x\":%d,\"y\":%d,\"xr\":[",
                  js.source ? js.source : "fast", (int)js.x_index, (int)js.y_index);
            j.putNum(js.x_min); j.put(",");
            j.putNum(js.x_max); j.put("],\"yr\":[");
            j.putNum(js.y_min); j.put(",");
            j.putNum(js.y_max);
            j.put("],\"c\":%s}", js.return_to_center ? "true" : "false");
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)PARAM_JOYSTICKS_COUNT) {
            j.raw("]},\"overlays\":[");
            _descStage = DS_OVERLAYS; _descIdx = 0; _descFirst = true;
        }
        break;

    // ── Overlays der Systemansicht ────────────────────────────────────────
    case DS_OVERLAYS:
        while (budget-- > 0 && _descIdx < (uint16_t)CHANNEL_OVERLAYS_COUNT) {
            const OverlayDef& ov = CHANNEL_OVERLAYS[_descIdx];
            if (!ov.type || !ov.type[0]) { _descIdx++; continue; }
            const size_t need = strlen(ov.label ? ov.label : "") * 6
                              + strlen(ov.extra ? ov.extra : "") * 6
                              + strlen(ov.type) + 220;
            if (!j.fits(need)) {
                _descIdx = (uint16_t)CHANNEL_OVERLAYS_COUNT;
                break;
            }
            if (!_descFirst) j.put(",");
            _descFirst = false;
            j.put("{\"group\":%d,\"type\":\"%s\",\"label\":\"", ov.group, ov.type);
            j.putEscaped(ov.label);
            j.put("\"");
            if (ov.channel  >= 0) j.put(",\"channel\":%d",  ov.channel);
            if (ov.channel2 >= 0) j.put(",\"channel2\":%d", ov.channel2);
            if (ov.min_val != 0.0f || ov.max_val != 0.0f) {
                j.put(",\"min\":"); j.putNum(ov.min_val);
                j.put(",\"max\":"); j.putNum(ov.max_val);
            }
            if (ov.x_pct >= 0.0f) {
                j.put(",\"x_pct\":"); j.putNum(ov.x_pct);
                j.put(",\"y_pct\":"); j.putNum(ov.y_pct);
            }
            if (ov.extra && ov.extra[0]) {
                j.put(",\"extra\":\"");
                j.putEscaped(ov.extra);
                j.put("\"");
            }
            j.put("}");
            _descIdx++;
        }
        if (_descIdx >= (uint16_t)CHANNEL_OVERLAYS_COUNT) {
            j.raw("],\"settings\":{");
            _descStage = DS_SETTINGS; _descIdx = 0; _descFirst = true;
        }
        break;

    // ── Einstellungen der Oberflaeche (siehe PDS.setting()) ───────────────
    //  Punktpfad -> Wert, typrichtig: Wahrheitswerte als true/false, Zahlen
    //  als Zahl, Text in Anfuehrungszeichen. Die GUI prueft jeden Wert gegen
    //  ihren eigenen Standardwert (app_settings.py) und behaelt bei einem
    //  Typfehler den eigenen.
    case DS_SETTINGS:
        while (budget-- > 0 && _descIdx < _settingCount) {
            const SettingEntry& s = _settings[_descIdx];
            if (!j.fits(strlen(s.key) * 6 + PDS_SETTING_TEXT_MAXLEN * 6 + 48)) {
                _descIdx = _settingCount;
                break;
            }
            if (!_descFirst) j.put(",");
            _descFirst = false;
            j.put("\"");
            j.putEscaped(s.key);
            j.put("\":");
            if (s.kind == PDS_SETTING_BOOL) {
                j.put(s.num != 0.0f ? "true" : "false");
            } else if (s.kind == PDS_SETTING_TEXT) {
                j.put("\"");
                j.putEscaped(s.text);
                j.put("\"");
            } else {
                j.putNum(s.num);
            }
            _descIdx++;
        }
        if (_descIdx >= _settingCount) {
            j.raw("}}");
            _descStage = DS_DONE;
        }
        break;

    default:
        // Unmoegliche Stufe (verirrter Speicher): sauber abschliessen, statt
        // endlos weiterzulaufen.
        j.raw("}}");
        _descStage = DS_DONE;
        break;
    }

    _descPos      = j.pos;
    _descOverflow = j.overflow;

    if (_descStage != DS_DONE) return false;

    _descJsonLen    = _descPos;
    _descChunkCount = (uint16_t)((_descPos + CHANNEL_DESC_CHUNK_PAYLOAD_MAX - 1)
                                  / CHANNEL_DESC_CHUNK_PAYLOAD_MAX);
    if (_descChunkCount == 0) _descChunkCount = 1;   // leerer Deskriptor -> 1 leerer Chunk
    _descBuilt = true;

    if (_descOverflow) {
        pdsWarn("Deskriptor gekuerzt (%u B Puffer voll) - PDS_DESC_BUF_BYTES erhoehen",
                (unsigned)sizeof(_descBuf));
    }
    return true;
}

// Sendewunsch anmelden. Der eigentliche Versand beginnt erst, wenn der
// Deskriptor fertig gebaut ist (siehe update()) — announceChannelNames()
// bleibt damit ein Aufruf, der nichts kostet und nichts blockiert.
void PowerDebugger::requestDescriptorSend(bool force) {
    if (!_descOn) return;
    if (_descNextChunk != 0xFFFF) return;    // laeuft schon
    if (_descWanted) return;                 // steht schon an

    // Mindestabstand: eine zappelnde Verbindung (GUI kommt und geht im
    // 100-ms-Takt) loeste frueher an JEDER steigenden Flanke einen neuen
    // Versand aus. Bei einem 6-kB-Deskriptor sind das 24 Chunks und ein
    // kompletter Neubau, mehrmals pro Sekunde — genau daran erstickte der
    // Teensy, wenn die Gegenstelle unregelmaessig sendete.
    //
    // `force` uebergeht den Abstand: eine ausdrueckliche Anfrage der GUI
    // ("Kanalnamen anfordern") soll sofort beantwortet werden, sie kommt ja
    // nicht von allein alle 100 ms.
    const uint32_t now = millis();
    if (!force && _descLastStartMs != 0
            && (now - _descLastStartMs) < PDS_DESC_MIN_GAP_MS) return;
    _descLastStartMs = now;

    _descWanted = true;
    if (!_descBuilt) beginDescriptorBuild();
}

void PowerDebugger::startDescriptorSend() {
    _descNextChunk = 0;
    _descWanted    = false;
    DescChunkTimer = 0;
}

void PowerDebugger::sendNextDescChunk() {
    if (_descNextChunk >= _descChunkCount) { _descNextChunk = 0xFFFF; return; }

    const size_t offset    = (size_t)_descNextChunk * CHANNEL_DESC_CHUNK_PAYLOAD_MAX;
    const size_t remaining = (offset < _descJsonLen) ? (_descJsonLen - offset) : 0;
    const uint8_t payloadLen = (uint8_t)((remaining < (size_t)CHANNEL_DESC_CHUNK_PAYLOAD_MAX)
                                          ? remaining : (size_t)CHANNEL_DESC_CHUNK_PAYLOAD_MAX);

    uint8_t pkt[CHANNEL_DESC_CHUNK_HEADER_BYTES + CHANNEL_DESC_CHUNK_PAYLOAD_MAX];
    const uint32_t magic = CHANNEL_DESC_MAGIC;
    memcpy(pkt, &magic, 4);
    pkt[4] = (uint8_t)_descNextChunk;
    pkt[5] = (uint8_t)_descChunkCount;
    pkt[6] = payloadLen;
    memcpy(pkt + CHANNEL_DESC_CHUNK_HEADER_BYTES, _descBuf + offset, payloadLen);

    UART_DBG.write(pkt, CHANNEL_DESC_CHUNK_HEADER_BYTES + payloadLen);

    _descNextChunk++;
    if (_descNextChunk >= _descChunkCount) _descNextChunk = 0xFFFF;   // fertig
}

// ══════════════════════════════════════════════════════════════════════════
//  Telemetrie-Versand
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::sendTelemetryPacket() {
    // Nie blockierend schreiben: ist der TX-Puffer wider Erwarten voll
    // (z. B. weil update() laenger als eine Sendeperiode nicht drankam),
    // wuerde write() auf den UART warten und dabei die Regelschleife des
    // Roboters anhalten. Lieber ein Paket verwerfen und zaehlen.
    if (UART_DBG.availableForWrite() < PACKET_BYTES) {
        _txDrops++;
        return;
    }

    sampleBoundChannels();

    uint8_t header[8];
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(header,     &magic, 4);
    memcpy(header + 4, &ts,    4);

    // Direkt aus debugData[] in den TX-Ringpuffer: spart den frueheren
    // Zwischenpuffer (_pkt_buf, 808 B RAM) und eine 800-Byte-memcpy pro Paket.
    UART_DBG.write(header, sizeof(header));
    UART_DBG.write((const uint8_t*)debugData, MAX_FLOATS * sizeof(float));
    _txPktCount++;
}

// ══════════════════════════════════════════════════════════════════════════
//  Param-Downlink: Magic-Sync-Parser (RPi Zero -> Teensy, RX)
// ══════════════════════════════════════════════════════════════════════════
//
//  UART_DBG.available()/read() wird jede update()-Iteration abgefragt,
//  nicht-blockierend. Ein 4-Byte-Schiebefenster sucht nach einem der drei
//  bekannten Magic-Werte; sobald einer erkannt ist, steht die erwartete
//  Gesamtlaenge fest (Slow = 258 B, Fast = 28 B) und die restlichen Bytes
//  werden angehaengt, bis das Paket vollstaendig ist. Da loop()/update()
//  einstraengig laufen (keine ISR greift auf dieselben Arrays zu), ist kein
//  noInterrupts()/interrupts() noetig.
//
//  BUGFIX (Latenz Fernsteuerung): Eine aeltere Fassung hat das Schiebefenster
//  bei JEDEM Byte weitergeschoben, den Magic-Vergleich aber erst ab dem
//  FUENFTEN Byte nach einem Zustands-Reset ausgefuehrt. Nach jedem fertig
//  geparsten Paket wurde der Magic des unmittelbar folgenden Pakets deshalb
//  systematisch uebersehen -- der Fast-Kanal kam nur mit 50 statt 100 Hz an.
//  Jetzt wird das Fenster erst gefuellt und danach bei jedem Byte geprueft.
void PowerDebugger::pollParamUart() {
    const uint32_t nowMs = millis();

    // ── Abgebrochenes Paket: nach einer Ruhezeit von vorn anfangen ────────
    //  Bricht die Gegenstelle mitten in einem Paket ab (GUI stuerzt ab, Kabel
    //  wackelt, Node startet neu), wartete der Parser bisher UNBEGRENZT auf
    //  die fehlenden Bytes. Traf spaeter wieder etwas ein, verfuetterte er
    //  dessen Anfang als vermeintliche Nutzlast an das abgebrochene Paket —
    //  und legte einen aus der Mitte eines fremden Pakets zusammengesetzten
    //  ZUFALLSWERT in _fastFloats, samt frischem _lastFastRxMs. linkOk()
    //  meldete dabei "alles in Ordnung". Bei einem Joystick- oder Gas-Kanal
    //  faehrt der Roboter damit davon. Der Parser fing sich erst nach dem
    //  naechsten vollstaendigen Paket wieder, im Slow-Fall nach ueber 200
    //  Bytes; genau diese Luecke schliesst der Timeout.
    if (_rxExpectedLen != 0 && PDS_RX_PACKET_TIMEOUT_MS > 0
            && (nowMs - _rxLastByteMs) >= (uint32_t)PDS_RX_PACKET_TIMEOUT_MS) {
        _rxExpectedLen = 0;
        _rxFill        = 0;
        _rxResyncCount++;
    }

    // Byte-Budget: ein Dauerstrom auf der Leitung (defekte Gegenstelle,
    // verstellte Baudrate, Stoerung) darf diese Schleife nicht festhalten.
    // Was nicht mehr hineinpasst, liegt im 2-kB-RX-Puffer und ist im
    // naechsten update() dran.
    int budget = _rxByteBudget;
    bool gotAnything = false;

    while (budget-- > 0 && UART_DBG.available()) {
        const uint8_t b = (uint8_t)UART_DBG.read();
        gotAnything = true;

        if (_rxExpectedLen == 0) {
            if (_rxFill < 4) {
                _rxBuf[_rxFill++] = b;
                if (_rxFill < 4) continue;    // noch keine 4 Bytes -> kein Magic moeglich
            } else {
                _rxBuf[0] = _rxBuf[1]; _rxBuf[1] = _rxBuf[2];
                _rxBuf[2] = _rxBuf[3]; _rxBuf[3] = b;
                _paramSyncLosses++;           // das herausgeschobene Byte war Muell
            }

            uint32_t magic;
            memcpy(&magic, _rxBuf, 4);

            if (magic == PARAM_SLOW_MAGIC) {
                _rxExpectedLen = PARAM_SLOW_PACKET_BYTES;
            } else if (magic == PARAM_FAST_MAGIC) {
                _rxExpectedLen = PARAM_FAST_PACKET_BYTES;
            } else if (magic == CHANNEL_DESC_REQUEST_MAGIC) {
                // Kein Payload -- das Paket ist mit dem Magic schon komplett.
                // Nur ANMELDEN: gebaut und gesendet wird in update(), damit
                // eine Anfrage der GUI hier nichts kostet.
                requestDescriptorSend(true);
                _rxFill = 0;
            }
            // sonst: unbekannter Magic -- Fenster bleibt, naechstes Byte pruefen
        } else {
            _rxBuf[_rxFill++] = b;

            if (_rxFill >= _rxExpectedLen) {
                uint32_t seq;
                memcpy(&seq, _rxBuf + 4, 4);
                if (_rxExpectedLen == PARAM_SLOW_PACKET_BYTES) {
                    memcpy(_paramFloats, _rxBuf + PARAM_HEADER_BYTES,
                           PARAM_SLOW_FLOAT_COUNT * 4);
                    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
                        _paramBools[i] =
                            _rxBuf[PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + i] != 0;
                    }
                    _lastSlowRxMs = millis();
                    _lastSlowSeq  = seq;
                    _slowPktCount++;
                } else {
                    memcpy(_fastFloats, _rxBuf + PARAM_HEADER_BYTES,
                           PARAM_FAST_FLOAT_COUNT * 4);
                    _lastFastRxMs = millis();
                    _lastFastSeq  = seq;
                    _fastPktCount++;
                }
                _rxExpectedLen = 0;
                _rxFill = 0;   // bereit fuer das naechste Paket
            }
        }
    }

    // Einmal je Aufruf statt einmal je Byte: die Aufloesung des Timeouts
    // sind 50 ms, ein paar hundert Mikrosekunden Ungenauigkeit sind dabei
    // bedeutungslos — 1024 millis()-Aufrufe je update() waeren es nicht.
    if (gotAnything) _rxLastByteMs = nowMs;
}

// ══════════════════════════════════════════════════════════════════════════
//  Oeffentliche Zugriffs-API
// ══════════════════════════════════════════════════════════════════════════

float PowerDebugger::param(int index) const {
    return ((unsigned)index < (unsigned)PARAM_SLOW_FLOAT_COUNT) ? _paramFloats[index] : 0.0f;
}

bool PowerDebugger::paramBool(int index) const {
    return ((unsigned)index < (unsigned)PARAM_SLOW_BOOL_COUNT) ? _paramBools[index] : false;
}

float PowerDebugger::fastParam(int index) const {
    return ((unsigned)index < (unsigned)PARAM_FAST_FLOAT_COUNT) ? _fastFloats[index] : 0.0f;
}

// Namensaufloesung ueber die Tabellen aus channel_config.h. Lineare Suche
// ueber hoechstens 50 kurze Strings — bei einem Aufruf je Regelzyklus nicht
// messbar. Wer sie in einer sehr heissen Schleife braucht, holt den Index
// einmal in eine static-Variable (siehe Beispiel-Sketch).
static int lookupParamIndex(const ParamDef* table, size_t count, int limit, const char* name) {
    if (!name || !name[0]) return -1;
    for (size_t i = 0; i < count; i++) {
        if (table[i].name && strcmp(table[i].name, name) == 0) {
            return (table[i].index < (uint8_t)limit) ? (int)table[i].index : -1;
        }
    }
    return -1;
}

float PowerDebugger::param(const char* name) const {
    const int i = lookupParamIndex(PARAM_SLOW_FLOATS, PARAM_SLOW_FLOATS_COUNT,
                                    PARAM_SLOW_FLOAT_COUNT, name);
    if (i < 0) { pdsWarn("Unbekannter Param-Name \"%s\"", name ? name : "(null)"); return 0.0f; }
    return _paramFloats[i];
}

bool PowerDebugger::paramBool(const char* name) const {
    const int i = lookupParamIndex(PARAM_SLOW_BOOLS, PARAM_SLOW_BOOLS_COUNT,
                                    PARAM_SLOW_BOOL_COUNT, name);
    if (i < 0) { pdsWarn("Unbekannter Bool-Param \"%s\"", name ? name : "(null)"); return false; }
    return _paramBools[i];
}

float PowerDebugger::fastParam(const char* name) const {
    const int i = lookupParamIndex(PARAM_FAST_FLOATS, PARAM_FAST_FLOATS_COUNT,
                                    PARAM_FAST_FLOAT_COUNT, name);
    if (i < 0) { pdsWarn("Unbekannter Fast-Param \"%s\"", name ? name : "(null)"); return 0.0f; }
    return _fastFloats[i];
}

bool PowerDebugger::paramsAreFresh() const {
    return (_lastSlowRxMs != 0) && (millis() - _lastSlowRxMs < _slowTimeoutMs);
}

bool PowerDebugger::fastParamsAreFresh() const {
    return (_lastFastRxMs != 0) && (millis() - _lastFastRxMs < _fastTimeoutMs);
}

uint32_t PowerDebugger::fastParamAgeMs() const {
    if (_lastFastRxMs == 0) return 0xFFFFFFFFUL;   // noch nie etwas empfangen
    return millis() - _lastFastRxMs;
}

// ══════════════════════════════════════════════════════════════════════════
//  Watchdog
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::enableWatchdog(uint32_t timeoutMs) {
#if defined(__IMXRT1062__)
    if (_wdtOn) { feedWatchdog(); return; }

    if (timeoutMs < 500)    timeoutMs = 500;
    if (timeoutMs > 128000) timeoutMs = 128000;
    uint32_t halfSeconds = (timeoutMs + 499) / 500;    // aufrunden
    if (halfSeconds < 1)   halfSeconds = 1;
    if (halfSeconds > 128) halfSeconds = 128;

    // WDE ist per Hardware nur EINMAL setzbar und laesst sich ohne Reset
    // nicht mehr loeschen — genau das macht einen Watchdog verlaesslich.
    // SRS/WDA bleiben gesetzt: beide sind aktiv-LOW, ein versehentliches
    // Loeschen wuerde sofort einen Reset ausloesen.
    *PDS_WDOG1_WCR = (uint16_t)(((halfSeconds - 1) << 8)
                                 | PDS_WCR_WDA | PDS_WCR_SRS | PDS_WCR_WDE);
    _wdtOn = true;
    feedWatchdog();
    logf("Watchdog aktiv: %lu ms", (unsigned long)(halfSeconds * 500));
#else
    (void)timeoutMs;
    pdsWarn("Watchdog wird nur auf Teensy 4.x unterstuetzt");
#endif
}

void PowerDebugger::feedWatchdog() {
#if defined(__IMXRT1062__)
    if (!_wdtOn) return;
    *PDS_WDOG1_WSR = 0x5555;
    *PDS_WDOG1_WSR = 0xAAAA;
#endif
}

// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::setFirmwareVersion(const char* v) {
    if (!v) v = "";
    strncpy(_fwVersion, v, sizeof(_fwVersion) - 1);
    _fwVersion[sizeof(_fwVersion) - 1] = '\0';
    _descBuilt = false;
}

void PowerDebugger::printStatus(Print& out) const {
    out.printf("[PDS %s%s%s] TX=%lu (drop %lu) | Slow=%lu Fast=%lu | Alter=%lu ms | "
               "Sync-Verluste=%lu | Kanaele=%u | Ereignisse=%lu (verworfen %lu)%s%s\n",
               PDS_VERSION,
               _fwVersion[0] ? " fw " : "", _fwVersion,
               (unsigned long)_txPktCount, (unsigned long)_txDrops,
               (unsigned long)_slowPktCount, (unsigned long)_fastPktCount,
               (unsigned long)fastParamAgeMs(),
               (unsigned long)_paramSyncLosses, (unsigned long)_rxResyncCount,
               (unsigned)_autoNext,
               (unsigned long)_evSent, (unsigned long)_evDrops,
               (unsigned long)_lastUpdateUs, (unsigned long)_maxUpdateUs,
               _wdtOn ? " | WDT" : "",
               _descOverflow ? " | DESKRIPTOR GEKUERZT" : "",
               _degraded ? " | NOTBREMSE" : "",
               _enabled ? "" : " | PDS AUS");
}

void PowerDebugger::enableSelfDiagnostics(int firstChannel) {
    if (firstChannel < 0) firstChannel = ACTIVE_CHANNELS - 6;
    if (firstChannel < 0 || firstChannel + 6 > ACTIVE_CHANNELS) return;
    _diagFirstChannel = (int16_t)firstChannel;
    setName(firstChannel + 0, "PDS_TX_Pakete");
    setName(firstChannel + 1, "PDS_TX_Drops");
    setName(firstChannel + 2, "PDS_Slow_Pakete");
    setName(firstChannel + 3, "PDS_Fast_Pakete");
    setName(firstChannel + 4, "PDS_Fast_Alter_ms");
    setUnit(firstChannel + 4, "ms");
    setName(firstChannel + 5, "PDS_Sync_Verluste");
}

// ══════════════════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════════════════
//  Einstellungen der BIBLIOTHEK
// ══════════════════════════════════════════════════════════════════════════
//  Alle Setter begrenzen ihren Wert, statt ihn zu verwerfen oder zu
//  uebernehmen: ein Tippfehler (setTelemetryRate(10000)) soll weder den
//  Uplink sprengen noch stillschweigend folgenlos bleiben.

namespace {
template <class T>
inline T pdsClamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }
}  // namespace

void PowerDebugger::setTelemetryRate(uint16_t hz) {
    hz = pdsClamp<uint16_t>(hz, 1, 1000);
    // Auf ganze Millisekunden gerundet — der Takt haengt an elapsedMillis.
    uint32_t ms = 1000UL / hz;
    if (ms == 0) ms = 1;
    _samplePeriodMs = ms;
}

uint16_t PowerDebugger::telemetryRate() const {
    return (uint16_t)(_samplePeriodMs ? (1000UL / _samplePeriodMs) : 0);
}

void PowerDebugger::setParamAckInterval(uint32_t ms) {
    _ackIntervalMs = pdsClamp<uint32_t>(ms, 100, 10000);
}

void PowerDebugger::setEventRateLimit(uint16_t perSecond) {
    _eventMaxPerSec = pdsClamp<uint16_t>(perSecond, 1, 200);
}

void PowerDebugger::setDescriptorRepeat(uint32_t startMs, uint32_t maxMs) {
    if (startMs != 0) startMs = pdsClamp<uint32_t>(startMs, 500, 3600000UL);
    if (maxMs == 0)   maxMs   = startMs > _descRepeatMaxMs ? startMs : _descRepeatMaxMs;
    if (maxMs < startMs) maxMs = startMs;
    _descRepeatBaseMs = startMs;
    _descRepeatMaxMs  = maxMs;
    _descRepeatMs     = startMs;
}

void PowerDebugger::setFastTimeout(uint32_t ms) {
    _fastTimeoutMs = pdsClamp<uint32_t>(ms, 20, 60000);
}

void PowerDebugger::setSlowTimeout(uint32_t ms) {
    _slowTimeoutMs = pdsClamp<uint32_t>(ms, 100, 60000);
}

void PowerDebugger::setAutoChannelBase(uint8_t chn) {
    if (chn >= ACTIVE_CHANNELS) {
        pdsWarn("setAutoChannelBase(%u) liegt ausserhalb ACTIVE_CHANNELS=%d",
                (unsigned)chn, ACTIVE_CHANNELS);
        return;
    }
    if (chn > _autoNext) _autoNext = chn;   // schon vergebene Kanaele bleiben
}

void PowerDebugger::setRxByteBudget(uint16_t bytes) {
    _rxByteBudget = pdsClamp<uint16_t>(bytes, 64, 8192);
}

void PowerDebugger::setPanicLimit(uint32_t us, uint8_t strikes) {
    _panicUs      = (us == 0) ? 0 : pdsClamp<uint32_t>(us, 200, 1000000UL);
    _panicStrikes = strikes;
    _panicSeen    = 0;
}

void PowerDebugger::enable(bool on) {
    if (on) {
        // enable(true) hebt auch eine ausgeloeste Notbremse wieder auf —
        // sonst gaebe es aus dem Sparbetrieb keinen Rueckweg ausser einem
        // Neustart des Roboters.
        _degraded  = false;
        _panicSeen = 0;
    }
    _enabled = on;
}

// ══════════════════════════════════════════════════════════════════════════
//  Einstellungen der OBERFLAECHE (Punktpfade aus settings.json der GUI)
// ══════════════════════════════════════════════════════════════════════════

PowerDebugger::SettingEntry* PowerDebugger::findOrAddSetting(const char* key) {
    if (!key || !key[0]) return nullptr;

    for (uint8_t i = 0; i < _settingCount; i++) {
        if (strncmp(_settings[i].key, key, PDS_SETTING_KEY_MAXLEN - 1) == 0)
            return &_settings[i];
    }
    if (_settingCount >= PDS_MAX_SETTINGS) {
        pdsWarn("Keine Einstellung mehr frei fuer \"%s\" (PDS_MAX_SETTINGS=%d)",
                key, PDS_MAX_SETTINGS);
        return nullptr;
    }
    if (strlen(key) >= PDS_SETTING_KEY_MAXLEN) {
        // Abgeschnitten waere der Punktpfad ein ANDERER Schluessel, und die
        // GUI legte still einen unbenutzten Eintrag an. Lieber ablehnen.
        pdsWarn("Einstellungsname zu lang: \"%s\" (max %d Zeichen)",
                key, PDS_SETTING_KEY_MAXLEN - 1);
        return nullptr;
    }

    SettingEntry& e = _settings[_settingCount++];
    strncpy(e.key, key, PDS_SETTING_KEY_MAXLEN - 1);
    e.key[PDS_SETTING_KEY_MAXLEN - 1] = '\0';
    e.text[0] = '\0';
    e.num     = 0.0f;
    e.kind    = PDS_SETTING_NUM;
    return &e;
}

bool PowerDebugger::setting(const char* key, float value) {
    SettingEntry* e = findOrAddSetting(key);
    if (!e) return false;
    if (!isfinite(value)) value = 0.0f;     // NaN/Inf waeren kein gueltiges JSON
    if (e->kind == PDS_SETTING_NUM && e->num == value) return true;
    e->kind = PDS_SETTING_NUM;
    e->num  = value;
    _descBuilt = false;                     // Deskriptor neu bauen lassen
    return true;
}

bool PowerDebugger::setting(const char* key, bool value) {
    SettingEntry* e = findOrAddSetting(key);
    if (!e) return false;
    const float v = value ? 1.0f : 0.0f;
    if (e->kind == PDS_SETTING_BOOL && e->num == v) return true;
    e->kind = PDS_SETTING_BOOL;
    e->num  = v;
    _descBuilt = false;
    return true;
}

bool PowerDebugger::setting(const char* key, const char* value) {
    if (!value) value = "";
    SettingEntry* e = findOrAddSetting(key);
    if (!e) return false;
    if (e->kind == PDS_SETTING_TEXT
            && strncmp(e->text, value, PDS_SETTING_TEXT_MAXLEN - 1) == 0) return true;
    if (strlen(value) >= PDS_SETTING_TEXT_MAXLEN) {
        pdsWarn("Wert von \"%s\" zu lang (max %d Zeichen)",
                key, PDS_SETTING_TEXT_MAXLEN - 1);
        return false;
    }
    e->kind = PDS_SETTING_TEXT;
    strncpy(e->text, value, PDS_SETTING_TEXT_MAXLEN - 1);
    e->text[PDS_SETTING_TEXT_MAXLEN - 1] = '\0';
    _descBuilt = false;
    return true;
}

bool PowerDebugger::removeSetting(const char* key) {
    if (!key || !key[0]) return false;
    for (uint8_t i = 0; i < _settingCount; i++) {
        if (strncmp(_settings[i].key, key, PDS_SETTING_KEY_MAXLEN - 1) != 0) continue;
        // Luecke schliessen: die Reihenfolge im Deskriptor ist bedeutungslos,
        // der letzte Eintrag darf also nach vorn ruecken.
        _settings[i] = _settings[_settingCount - 1];
        _settingCount--;
        _descBuilt = false;
        return true;
    }
    return false;
}

void PowerDebugger::clearSettings() {
    if (_settingCount == 0) return;
    _settingCount = 0;
    _descBuilt = false;
}

// ── Bequeme Namen fuer die haeufigsten Faelle ─────────────────────────────

void PowerDebugger::guiBatteryWarning(int channel, float warnBelow,
                                       float criticalBelow, float holdSeconds) {
    setting("battery.enabled", channel >= 0);
    setting("battery.channel", channel);
    setting("battery.warn_below", warnBelow);
    setting("battery.critical_below", criticalBelow);
    setting("battery.hold_seconds", holdSeconds);
}

void PowerDebugger::guiPlotter(int historySeconds, int points, int maxCurves) {
    if (historySeconds > 0) setting("plotter.historySeconds", historySeconds);
    if (points > 0)         setting("plotter.defaultPoints", points);
    if (maxCurves > 0)      setting("plotter.maxCurves", maxCurves);
}

void PowerDebugger::guiCurveColor(int index, const char* color) {
    if (index < 0 || index > 7 || !color) return;
    // Punktpfad mit Listenindex — die GUI loest "plotter.curveColors.3"
    // auf das vierte Element der Farbliste auf.
    char key[PDS_SETTING_KEY_MAXLEN];
    snprintf(key, sizeof(key), "plotter.curveColors.%d", index);
    setting(key, color);
}

void PowerDebugger::guiColor(const char* name, const char* color, bool dark) {
    if (!name || !name[0] || !color) return;
    char key[PDS_SETTING_KEY_MAXLEN];
    snprintf(key, sizeof(key), "theme.colors.%s.%s", dark ? "dark" : "light", name);
    setting(key, color);
}


void PowerDebugger::begin() {
    // Debug-Array + Namens-Registry initialisieren
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0.0f;
    for (int i = 0; i < ACTIVE_CHANNELS; i++) _names[i][0] = '\0';
    _boundCount = 0;
    _unitCount  = 0;
    _autoNext   = PDS_AUTO_CHANNEL_BASE;
    _evHead = _evCount = _evInWindow = 0;
    _evWindowStartMs = millis();

    // Selbstschutz zuruecksetzen: nach einem Neustart der Bibliothek soll
    // eine frueher ausgeloeste Notbremse nicht weiterwirken.
    _enabled  = true;
    _degraded = false;
    _panicSeen = 0;
    _lastUpdateUs = _maxUpdateUs = 0;
    _budgetOverruns = _panicCount = 0;
    g_serialDiag = _serialDiagOn;

    // Deskriptor-Bau: noch nichts angefangen.
    _descStage    = 0;
    _descIdx      = 0;
    _descPos      = 0;
    _descFirst    = true;
    _descBuilt    = false;
    _descOverflow = false;
    _descWanted   = false;
    _descLastStartMs = 0;
    _descRepeatMs = _descRepeatBaseMs;

    if (PDS_FW_VERSION[0]) setFirmwareVersion(PDS_FW_VERSION);

    // Kam der letzte Reset vom Watchdog? Muss VOR dem ersten feedWatchdog()
    // gelesen werden — WRSR haelt den Grund bis zum naechsten Power-On.
#if defined(__IMXRT1062__)
    _wdtWasReset = (*PDS_WDOG1_WRSR & PDS_WRSR_TOUT) != 0;
#endif

    // Namen/Einheiten aus channel_config.h vorbelegen. bind()/Channel(...,name)/
    // plot() im Sketch ueberschreiben danach gezielt einzelne Eintraege bzw.
    // bekommen die noch freien Kanaele (siehe channelFor()).
    for (size_t i = 0; i < CHANNEL_NAMES_COUNT; i++) {
        setName(CHANNEL_NAMES[i].index, CHANNEL_NAMES[i].name);
        if (CHANNEL_NAMES[i].unit) setUnit(CHANNEL_NAMES[i].index, CHANNEL_NAMES[i].unit);
    }

    // TX- UND RX-Puffer erweitern, danach erst UART starten. Der RX-Puffer ist
    // der entscheidende Teil fuer die Reaktionszeit der Fernsteuerung -- siehe
    // Kommentar bei _uart_dbg_rx_buf oben.
    UART_DBG.addMemoryForWrite(_uart_dbg_tx_buf, sizeof(_uart_dbg_tx_buf));
    UART_DBG.addMemoryForRead(_uart_dbg_rx_buf, sizeof(_uart_dbg_rx_buf));
    UART_DBG.begin(UART_DBG_BAUD, SERIAL_8N1);

    // Param-Downlink: RAM-only, alle Werte starten bei 0.0f / false, bis das
    // erste Paket von der GUI eintrifft (siehe paramsAreFresh()).
    for (int i = 0; i < PARAM_SLOW_FLOAT_COUNT; i++) _paramFloats[i] = 0.0f;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT;  i++) _paramBools[i]  = false;
    for (int i = 0; i < PARAM_FAST_FLOAT_COUNT; i++) _fastFloats[i]  = 0.0f;
    _rxFill = 0;
    _rxExpectedLen = 0;
    _rxLastByteMs  = millis();
    _rxResyncCount = 0;

    // Einstellungen aus channel_config.h uebernehmen. Im Sketch gesetzte
    // Werte (PDS.setting(...) in setup()) ueberschreiben sie danach, weil
    // setup() nach begin() weiterlaeuft.
    for (size_t i = 0; i < GUI_SETTINGS_COUNT; i++) {
        const SettingDef& d = GUI_SETTINGS[i];
        if (!d.key || !d.key[0]) continue;
        if (d.kind == PDS_SETTING_BOOL)      setting(d.key, d.num != 0.0f);
        else if (d.kind == PDS_SETTING_TEXT) setting(d.key, d.text);
        else                                 setting(d.key, d.num);
    }

    // Namens-/Overlay-Deskriptor beim Boot melden — aber nicht sofort:
    // plot()/track() registrieren ihre Namen erst in setup()/dem ersten
    // loop()-Durchlauf, ein hier gebauter Deskriptor waere noch leer.
    // (Die GUI kann per CHANNEL_DESC_REQUEST_MAGIC jederzeit eine
    //  Neuuebertragung anfordern.)
    _descNextChunk    = 0xFFFF;
    _bootAnnounceAtMs = millis() + PDS_BOOT_ANNOUNCE_DELAY_MS;
    if (_bootAnnounceAtMs == 0) _bootAnnounceAtMs = 1;   // 0 ist der "erledigt"-Marker

    if (_wdtWasReset) {
        // Als Ereignis in die GUI: ein Watchdog-Reset ist die wichtigste
        // Einzelinformation nach einem unerklaerlichen Neustart im Spiel.
        pushEvent(PDS_EVENT_KIND_LOG, PDS_LEVEL_ERROR, "Neustart durch Watchdog", 0.0f);
    }
}

// ══════════════════════════════════════════════════════════════════════════
//  update() — der einzige Aufruf im loop(), und er wartet auf NICHTS
// ══════════════════════════════════════════════════════════════════════════
//  Die Reihenfolge ist Absicht:
//
//    1. Watchdog fuettern      — passiert IMMER, auch wenn PDS abgeschaltet
//                                oder in der Notbremse ist. Wer den Watchdog
//                                eingeschaltet hat, verlaesst sich darauf.
//    2. Param-Downlink lesen   — mit Byte-Budget; muss vor dem Senden laufen,
//                                damit fastParam() direkt nach update() den
//                                frischesten Stand liefert.
//    3. Telemetrie senden      — der 100-Hz-Takt, hat Vorrang vor allem
//                                anderen und schreibt nie blockierend.
//    4. Alles Uebrige          — Ereignisse, Parameter-Rueckmeldung,
//                                Deskriptor: NUR solange vom Zeitbudget noch
//                                etwas uebrig ist. Was nicht drankommt,
//                                kommt im naechsten Aufruf dran.
//    5. Selbstmessung          — dauert ein Aufruf trotzdem laenger als das
//                                Panik-Limit, schaltet PDS erst die
//                                Nebenwege und dann sich selbst ab.
void PowerDebugger::update() {
    // ── Watchdog zuerst: solange update() laeuft, laeuft auch der Roboter.
    feedWatchdog();

    if (!_enabled) return;      // Not-Aus fuer PDS selbst (siehe enable())

    const uint32_t t0 = micros();

    // ── Param-Downlink: nicht-blockierend, jede update()-Iteration.
    //    Bewusst vor dem Telemetrie-Versand, damit fastParam() direkt nach
    //    update() den zuletzt eingetroffenen Stand liefert und nicht einen
    //    um einen Zyklus alten.
    pollParamUart();

    // ── Alle _samplePeriodMs: Telemetriepaket senden (Standard 100 Hz) ───
    if (_telemetryOn && DBGTimer >= _samplePeriodMs) {
        // Nachlauf statt Reset auf 0: verhindert, dass sich die Sendefrequenz
        // bei einer laengeren loop()-Iteration dauerhaft nach unten verschiebt.
        // Nur wenn wir mehr als eine ganze Periode hinterherhinken, wird hart
        // resynchronisiert (sonst wuerden Pakete nachgeholt/gebuendelt).
        if (DBGTimer >= 2 * _samplePeriodMs) DBGTimer = 0;
        else                                 DBGTimer -= _samplePeriodMs;

        if (_diagFirstChannel >= 0) {
            const int c = _diagFirstChannel;
            writeChannel(c + 0, (float)_txPktCount);
            writeChannel(c + 1, (float)_txDrops);
            writeChannel(c + 2, (float)_slowPktCount);
            writeChannel(c + 3, (float)_fastPktCount);
            writeChannel(c + 4, (float)fastParamAgeMs());
            writeChannel(c + 5, (float)_paramSyncLosses);
        }

        sendTelemetryPacket();
    }

    // ── Ab hier ist alles OPTIONAL und laeuft nur mit Restbudget ────────
    //  Ereignisse/Logzeilen: hoechstens eines pro update(), und nur wenn im
    //  TX-Puffer noch ein komplettes Telemetriepaket zusaetzlich Platz hat
    //  (txRoomFor). Marken sollen zeitnah ankommen, duerfen den 100-Hz-Takt
    //  aber unter keinen Umstaenden verdraengen.
    if (budgetLeft(t0)) sendNextEvent();

    // ── Parameter-Rueckmeldung an die GUI (2 Hz) ─────────────────────────
    if (_paramAckOn && ParamAckTimer >= _ackIntervalMs && budgetLeft(t0)) {
        ParamAckTimer = 0;
        sendParamAck();
    }

    // ── Deskriptor: bauen und senden, beides nur mit Restbudget ──────────
    //  Als einziger Weg faellt er in der Notbremse (_degraded) ganz aus: er
    //  ist der einzige, der ueberhaupt nennenswert Zeit brauchen KANN.
    //  Ereignisse und Rueckmeldung sind ein memcpy fester Groesse und
    //  bleiben deshalb an — die Notbremse selbst meldet sich darueber.
    if (!_degraded && budgetLeft(t0)) updateDescriptor(t0);

    noteUpdateDuration((uint32_t)(micros() - t0));
}

// Alles rund um den Namens-/Overlay-Deskriptor. Ausgelagert, damit update()
// selbst kurz und lesbar bleibt — der Ablauf ist verzwickter als er aussieht:
// bauen, senden, wiederholen und die Flanke "GUI ist wieder da" haengen alle
// am selben Zustand.
void PowerDebugger::updateDescriptor(uint32_t startUs) {
    if (!_descOn) return;

    // ── 1) Ein angemeldeter Deskriptor wird zuerst fertig GEBAUT ─────────
    //  Scheibchenweise, solange Budget da ist. Erst danach beginnt der
    //  Versand — ein halb gebauter Deskriptor darf die Leitung nicht sehen.
    if (_descWanted) {
        while (!_descBuilt && budgetLeft(startUs)) {
            if (buildDescriptorStep()) break;
        }
        if (_descBuilt) startDescriptorSend();
        return;
    }

    // ── 2) Laufender Versand: ein Chunk alle DESC_CHUNK_PERIOD_MS ────────
    if (_descNextChunk != 0xFFFF) {
        if (DescChunkTimer >= DESC_CHUNK_PERIOD_MS
                && txRoomFor(CHANNEL_DESC_CHUNK_PACKET_BYTES)) {
            DescChunkTimer = 0;
            sendNextDescChunk();
        }
        return;
    }

    // ── 3) Erste Namensmeldung nach dem Boot ─────────────────────────────
    if (_bootAnnounceAtMs != 0 && (int32_t)(millis() - _bootAnnounceAtMs) >= 0) {
        _bootAnnounceAtMs = 0;
        requestDescriptorSend(true);
        return;
    }

    // ── 4) Robustheit gegen Neustarts (auf BEIDEN Seiten) ────────────────
    //  Der Deskriptor wurde frueher ausschliesslich beim Boot des Teensy
    //  gesendet. Startete die GUI (oder der Pi-Zero-Node) danach neu, waren
    //  die Kanalnamen weg, bis jemand von Hand "Kanalnamen anfordern"
    //  gedrueckt hat. Zwei Automatismen decken jetzt beide Richtungen ab:
    //
    //    a) Flanke "Verbindung zur GUI kommt (wieder) zustande" -> senden.
    //       Deckt: GUI/Node startet neu, waehrend der Teensy durchlaeuft.
    //       requestDescriptorSend() haelt dabei den Mindestabstand ein —
    //       eine zappelnde Verbindung loest damit KEINEN Dauerversand aus.
    //    b) In Ruhe (keine GUI) wiederholen, beginnend bei
    //       _descRepeatBaseMs und mit jedem unbeantworteten Versuch
    //       verdoppelt bis _descRepeatMaxMs.
    //       Deckt: Teensy startet neu, bevor GUI/Node ueberhaupt da sind —
    //       ohne im reinen Wettkampfbetrieb (nie eine GUI) dauerhaft
    //       Bandbreite zu verbrauchen.
    const bool linkUp = linkOk();
    if (linkUp != _linkWasUp) {
        _linkWasUp = linkUp;
        if (linkUp) {
            _descRepeatMs = _descRepeatBaseMs;   // GUI da -> wieder schnell reagieren
            requestDescriptorSend();
        }
    } else if (!linkUp && _descRepeatBaseMs > 0 && DescChunkTimer >= _descRepeatMs) {
        DescChunkTimer = 0;          // auch dann weiterzaehlen, wenn der
        requestDescriptorSend();     // Mindestabstand den Versand verwirft
        if (_descRepeatMs < _descRepeatMaxMs) {
            _descRepeatMs *= 2;
            if (_descRepeatMs > _descRepeatMaxMs) _descRepeatMs = _descRepeatMaxMs;
        }
    }
}

// ══════════════════════════════════════════════════════════════════════════
//  Notbremse
// ══════════════════════════════════════════════════════════════════════════
//  Die letzte Sicherung: Wenn update() trotz Budget und Scheibenbau laenger
//  braucht als das Panik-Limit, ist in dieser Bibliothek etwas kaputt —
//  ein Zeiger, eine Endlosschleife, ein UART-Treiber, der doch wartet. Der
//  Roboter darf daran nicht sterben. Also schaltet PDS erst seine Nebenwege
//  ab (Telemetrie und Fernsteuerung bleiben) und im Wiederholungsfall sich
//  selbst. Beides meldet es, solange es das noch kann.
void PowerDebugger::noteUpdateDuration(uint32_t us) {
    _lastUpdateUs = us;
    if (us > _maxUpdateUs) _maxUpdateUs = us;
    if (_budgetUs != 0 && us > _budgetUs) _budgetOverruns++;

    if (_panicStrikes == 0 || _panicUs == 0 || us <= _panicUs) {
        _panicSeen = 0;                  // ein einzelner Ausreisser zaehlt nicht
        return;
    }

    _panicCount++;
    if (_panicSeen < 0xFF) _panicSeen++;
    if (_panicSeen < _panicStrikes) return;

    _panicSeen = 0;
    if (!_degraded) {
        _degraded = true;
        // Die Meldung geht ueber die normale Warteschlange raus, solange die
        // Leitung noch steht — sie ist der einzige Hinweis, den die GUI auf
        // dieses Ereignis je bekommt. (Wer enableEvents(false) gesetzt hat,
        // bekommt sie nicht; das ist dann eine bewusste Entscheidung.)
        pushEvent(PDS_EVENT_KIND_LOG, PDS_LEVEL_ERROR,
                   "PDS-Notbremse: Nebenwege abgeschaltet", (float)us);
        pdsWarn("Notbremse: update() brauchte %lu us (Limit %lu) - "
                "Deskriptor/Ereignisse/Rueckmeldung sind aus",
                (unsigned long)us, (unsigned long)_panicUs);
    } else {
        _enabled = false;
        pdsWarn("Notbremse: update() brauchte trotz Sparbetrieb %lu us - "
                "PDS ist jetzt aus (PDS.enable(true) hebt das auf)",
                (unsigned long)us);
    }
}
