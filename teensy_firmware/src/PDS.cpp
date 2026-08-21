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

static constexpr uint32_t SAMPLE_PERIOD_MS = 10;     // 10 ms -> 100 Hz
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
static constexpr size_t DESC_STRUCT_RESERVE = 192;

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

// Serial-Warnungen sind im Roboterbetrieb Nebensache und duerfen den
// 100-Hz-Takt nicht stoeren: hoechstens eine pro Sekunde, und nur wenn ein
// USB-Serial-Terminal ueberhaupt offen ist (sonst blockiert print() nicht,
// verbraucht aber trotzdem Zeit im TX-Puffer).
static void pdsWarn(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void pdsWarn(const char* fmt, ...) {
    uint32_t now = millis();
    if (now - _lastWarnMs < WARN_INTERVAL_MS) return;
    _lastWarnMs = now;
    if (!Serial) return;
    char line[128];
    va_list args;
    va_start(args, fmt);
    vsnprintf(line, sizeof(line), fmt, args);
    va_end(args);
    Serial.print("[PDS] ");
    Serial.println(line);
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
    if (_evCount == 0) return false;

    // Rate-Limit: eine Endlosschleife mit log() im Roboter-Code darf den
    // Uplink nicht fluten (siehe PDS_EVENT_MAX_PER_SEC in params.h).
    const uint32_t now = millis();
    if (now - _evWindowStartMs >= 1000) {
        _evWindowStartMs = now;
        _evInWindow = 0;
    }
    if (_evInWindow >= PDS_EVENT_MAX_PER_SEC) return false;

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

void PowerDebugger::buildDescriptorJson() {
    JsonBuilder j(_descBuf, sizeof(_descBuf));

    // ── meta: Firmware-Version und Eckdaten ───────────────────────────────
    j.raw("{\"meta\":{");
    j.put("\"pds\":\"%s\",\"wire\":%d,\"channels\":%d,\"used\":%d",
          PDS_VERSION, (int)PDS_WIRE_VERSION, (int)ACTIVE_CHANNELS, (int)_autoNext);
    j.put(",\"build\":\"%s %s\"", __DATE__, __TIME__);
    if (_fwVersion[0]) {
        j.put(",\"fw\":\"");
        j.putEscaped(_fwVersion);
        j.put("\"");
    }
    if (_wdtWasReset) j.put(",\"wdt_reset\":true");

    j.raw("},\"channels\":{");
    bool first = true;
    for (int i = 0; i < ACTIVE_CHANNELS; i++) {
        if (!putNameEntry(j, first, i, _names[i])) break;
    }

    j.raw("},\"units\":{");
    first = true;
    for (uint8_t i = 0; i < _unitCount; i++) {
        if (!putNameEntry(j, first, _units[i].chn, _units[i].unit)) break;
    }

    // ── Param-Namen (schlanker Pfad, den die GUI seit jeher liest) ────────
    j.raw("},\"param_slow_floats\":{");
    first = true;
    for (size_t i = 0; i < PARAM_SLOW_FLOATS_COUNT; i++) {
        if (!putNameEntry(j, first, PARAM_SLOW_FLOATS[i].index, PARAM_SLOW_FLOATS[i].name)) break;
    }

    j.raw("},\"param_slow_bools\":{");
    first = true;
    for (size_t i = 0; i < PARAM_SLOW_BOOLS_COUNT; i++) {
        if (!putNameEntry(j, first, PARAM_SLOW_BOOLS[i].index, PARAM_SLOW_BOOLS[i].name)) break;
    }

    j.raw("},\"param_fast_floats\":{");
    first = true;
    for (size_t i = 0; i < PARAM_FAST_FLOATS_COUNT; i++) {
        if (!putNameEntry(j, first, PARAM_FAST_FLOATS[i].index, PARAM_FAST_FLOATS[i].name)) break;
    }

    // ── Vollstaendige Widget-Konfiguration des Parameter-Tabs ─────────────
    j.raw("},\"param_cfg\":{\"slow_floats\":[");
    first = true;
    for (size_t i = 0; i < PARAM_SLOW_FLOATS_COUNT; i++) {
        if (!putParamDef(j, first, PARAM_SLOW_FLOATS[i])) break;
    }
    j.raw("],\"slow_bools\":[");
    first = true;
    for (size_t i = 0; i < PARAM_SLOW_BOOLS_COUNT; i++) {
        if (!putParamDef(j, first, PARAM_SLOW_BOOLS[i])) break;
    }
    j.raw("],\"fast_floats\":[");
    first = true;
    for (size_t i = 0; i < PARAM_FAST_FLOATS_COUNT; i++) {
        if (!putParamDef(j, first, PARAM_FAST_FLOATS[i])) break;
    }
    j.raw("],\"joysticks\":[");
    first = true;
    for (size_t i = 0; i < PARAM_JOYSTICKS_COUNT; i++) {
        const JoystickDef& js = PARAM_JOYSTICKS[i];
        if (!js.name || !js.name[0]) continue;
        if (!j.fits(strlen(js.name) * 6 + 160)) break;
        if (!first) j.put(",");
        first = false;
        j.put("{\"n\":\"");
        j.putEscaped(js.name);
        j.put("\",\"s\":\"%s\",\"x\":%d,\"y\":%d,\"xr\":[",
              js.source ? js.source : "fast", (int)js.x_index, (int)js.y_index);
        j.putNum(js.x_min); j.put(",");
        j.putNum(js.x_max); j.put("],\"yr\":[");
        j.putNum(js.y_min); j.put(",");
        j.putNum(js.y_max);
        j.put("],\"c\":%s}", js.return_to_center ? "true" : "false");
    }

    // ── Overlays der Systemansicht ────────────────────────────────────────
    j.raw("]},\"overlays\":[");
    bool firstOverlay = true;
    for (size_t i = 0; i < CHANNEL_OVERLAYS_COUNT; i++) {
        const OverlayDef& ov = CHANNEL_OVERLAYS[i];
        if (!ov.type || !ov.type[0]) continue;
        const size_t need = strlen(ov.label ? ov.label : "") * 6
                          + strlen(ov.extra ? ov.extra : "") * 6
                          + strlen(ov.type) + 220;
        if (!j.fits(need)) break;
        if (!firstOverlay) j.put(",");
        firstOverlay = false;
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
    }
    j.raw("]}");

    _descJsonLen    = j.pos;
    _descOverflow   = j.overflow;
    _descChunkCount = (uint16_t)((j.pos + CHANNEL_DESC_CHUNK_PAYLOAD_MAX - 1)
                                  / CHANNEL_DESC_CHUNK_PAYLOAD_MAX);
    if (_descChunkCount == 0) _descChunkCount = 1;   // leerer Deskriptor -> 1 leerer Chunk
    _descBuilt = true;

    if (_descOverflow) {
        pdsWarn("Deskriptor gekuerzt (%u B Puffer voll) - PDS_DESC_BUF_BYTES erhoehen",
                (unsigned)sizeof(_descBuf));
    }
}

void PowerDebugger::startDescriptorSend() {
    if (!_descBuilt) buildDescriptorJson();
    _descNextChunk = 0;
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
    while (UART_DBG.available()) {
        const uint8_t b = (uint8_t)UART_DBG.read();

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
                startDescriptorSend();
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
    return (_lastSlowRxMs != 0) && (millis() - _lastSlowRxMs < PARAM_SLOW_TIMEOUT_MS);
}

bool PowerDebugger::fastParamsAreFresh() const {
    return (_lastFastRxMs != 0) && (millis() - _lastFastRxMs < PARAM_FAST_TIMEOUT_MS);
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
               (unsigned long)_paramSyncLosses,
               (unsigned)_autoNext,
               (unsigned long)_evSent, (unsigned long)_evDrops,
               _wdtOn ? " | WDT" : "",
               _descOverflow ? " | DESKRIPTOR GEKUERZT" : "");
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

void PowerDebugger::begin() {
    // Debug-Array + Namens-Registry initialisieren
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0.0f;
    for (int i = 0; i < ACTIVE_CHANNELS; i++) _names[i][0] = '\0';
    _boundCount = 0;
    _unitCount  = 0;
    _autoNext   = PDS_AUTO_CHANNEL_BASE;
    _evHead = _evCount = _evInWindow = 0;
    _evWindowStartMs = millis();

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

void PowerDebugger::update() {
    // ── Watchdog zuerst: solange update() laeuft, laeuft auch der Roboter.
    feedWatchdog();

    // ── Param-Downlink: nicht-blockierend, jede update()-Iteration.
    //    Bewusst vor dem Telemetrie-Versand, damit fastParam() direkt nach
    //    update() den zuletzt eingetroffenen Stand liefert und nicht einen
    //    um einen Zyklus alten.
    pollParamUart();

    // ── Alle 10 ms: Telemetriepaket senden (100 Hz) ─────────────────────
    if (DBGTimer >= SAMPLE_PERIOD_MS) {
        // Nachlauf statt Reset auf 0: verhindert, dass sich die Sendefrequenz
        // bei einer laengeren loop()-Iteration dauerhaft nach unten verschiebt.
        // Nur wenn wir mehr als eine ganze Periode hinterherhinken, wird hart
        // resynchronisiert (sonst wuerden Pakete nachgeholt/gebuendelt).
        if (DBGTimer >= 2 * SAMPLE_PERIOD_MS) DBGTimer = 0;
        else                                  DBGTimer -= SAMPLE_PERIOD_MS;

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

    // ── Ereignisse/Logzeilen: hoechstens eines pro update(), und nur wenn
    //    im TX-Puffer noch ein komplettes Telemetriepaket zusaetzlich Platz
    //    hat (txRoomFor). Marken sollen zeitnah ankommen, duerfen den
    //    100-Hz-Takt aber unter keinen Umstaenden verdraengen.
    sendNextEvent();

    // ── Parameter-Rueckmeldung an die GUI (2 Hz) ─────────────────────────
    if (_paramAckOn && ParamAckTimer >= PARAM_ACK_INTERVAL_MS) {
        ParamAckTimer = 0;
        sendParamAck();
    }

    // ── Deskriptor: ein Chunk alle DESC_CHUNK_PERIOD_MS, solange ein
    //    Sendevorgang laeuft (Boot, GUI-Anfrage oder Wiederverbindung).
    if (_descNextChunk != 0xFFFF && DescChunkTimer >= DESC_CHUNK_PERIOD_MS) {
        if (txRoomFor(CHANNEL_DESC_CHUNK_PACKET_BYTES)) {
            DescChunkTimer = 0;
            sendNextDescChunk();
        }
        return;
    }

    // ── Erste Namensmeldung nach dem Boot ───────────────────────────────
    if (_bootAnnounceAtMs != 0 && (int32_t)(millis() - _bootAnnounceAtMs) >= 0) {
        _bootAnnounceAtMs = 0;
        startDescriptorSend();
        return;
    }

    // ── Robustheit gegen Neustarts (auf BEIDEN Seiten) ──────────────────
    //  Der Deskriptor wurde frueher ausschliesslich beim Boot des Teensy
    //  gesendet. Startete die GUI (oder der Pi-Zero-Node) danach neu, waren
    //  die Kanalnamen weg, bis jemand von Hand "Kanalnamen anfordern"
    //  gedrueckt hat. Zwei Automatismen decken jetzt beide Richtungen ab:
    //
    //    a) Flanke "Verbindung zur GUI kommt (wieder) zustande" -> senden.
    //       Deckt: GUI/Node startet neu, waehrend der Teensy durchlaeuft.
    //    b) In Ruhe (keine GUI) wiederholen, beginnend bei
    //       PDS_DESC_REPEAT_MS und mit jedem unbeantworteten Versuch
    //       verdoppelt bis PDS_DESC_REPEAT_MAX_MS.
    //       Deckt: Teensy startet neu, bevor GUI/Node ueberhaupt da sind —
    //       ohne im reinen Wettkampfbetrieb (nie eine GUI) dauerhaft
    //       Bandbreite zu verbrauchen.
    const bool linkUp = linkOk();
    if (linkUp != _linkWasUp) {
        _linkWasUp = linkUp;
        if (linkUp) {
            _descRepeatMs = PDS_DESC_REPEAT_MS;   // GUI da -> wieder schnell reagieren
            startDescriptorSend();
        }
    } else if (!linkUp && PDS_DESC_REPEAT_MS > 0 && DescChunkTimer >= _descRepeatMs) {
        startDescriptorSend();
        if (_descRepeatMs < (uint32_t)PDS_DESC_REPEAT_MAX_MS) {
            _descRepeatMs *= 2;
            if (_descRepeatMs > (uint32_t)PDS_DESC_REPEAT_MAX_MS)
                _descRepeatMs = PDS_DESC_REPEAT_MAX_MS;
        }
    }
}
