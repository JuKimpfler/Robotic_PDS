#include "PDS.h"
#include "elapsedMillis.h"
#include <stdarg.h>
#include <string.h>

// ── channel_config.h ist OPTIONAL ─────────────────────────────────────────
//  Ohne die Datei laesst sich PDS.h/PDS.cpp unveraendert in ein beliebiges
//  Projekt kopieren: es gibt dann einfach keine vorbelegten Namen und keine
//  Overlays, alles andere (inkl. plot()/track()) funktioniert identisch.
#if defined(__has_include)
#  if __has_include("channel_config.h")
#    include "channel_config.h"
#    define PDS_HAS_CHANNEL_CONFIG 1
#  endif
#endif

#ifndef PDS_HAS_CHANNEL_CONFIG
struct ChannelNameDef { uint8_t index; const char* name; };
struct OverlayDef {
    uint8_t group; const char* type; const char* label;
    int16_t channel = -1; int16_t channel2 = -1;
    float min_val = 0.0f; float max_val = 0.0f;
    float x_pct = -1.0f; float y_pct = -1.0f;
    const char* extra = "";
};
static const ChannelNameDef CHANNEL_NAMES[] = { {0, nullptr} };
static constexpr size_t CHANNEL_NAMES_COUNT = 0;
static const char* const PARAM_SLOW_FLOAT_NAMES[PARAM_SLOW_FLOAT_COUNT] = {};
static const char* const PARAM_SLOW_BOOL_NAMES[PARAM_SLOW_BOOL_COUNT]  = {};
static const char* const PARAM_FAST_FLOAT_NAMES[PARAM_FAST_FLOAT_COUNT] = {};
static const OverlayDef CHANNEL_OVERLAYS[] = { {0, "", ""} };
static constexpr size_t CHANNEL_OVERLAYS_COUNT = 0;
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

static constexpr uint32_t SAMPLE_PERIOD_MS      = 10;   // 10 ms -> 100 Hz
static constexpr uint32_t DESC_CHUNK_PERIOD_MS  = 10;   // ein Deskriptor-Chunk pro 10 ms
static constexpr uint32_t WARN_INTERVAL_MS      = 1000; // Rate-Limit fuer Serial-Warnungen

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

// Reserve fuer die schliessenden Klammern, damit der Deskriptor auch bei
// Ueberlauf gueltiges JSON bleibt (siehe buildDescriptorJson()).
static constexpr size_t DESC_CLOSE_RESERVE = 64;

static elapsedMillis DBGTimer;
static elapsedMillis DescChunkTimer;
static uint32_t      _lastWarnMs = 0;

// Bereichsgeprueft: ein Channel()-Aufruf mit einem Index >= MAX_FLOATS hat
// vorher hinter debugData[] geschrieben und dabei beliebigen anderen Speicher
// zerstoert (uint8_t-Index reicht bis 255, das Array hat 200).
static inline void writeChannel(int chn, float value) {
    if ((unsigned)chn < (unsigned)MAX_FLOATS) debugData[chn] = value;
}

// Serial-Warnungen sind im Roboterbetrieb Nebensache und duerfen den
// 100-Hz-Takt nicht stoeren: hoechstens eine pro Sekunde, und nur wenn ein
// USB-Serial-Terminal ueberhaupt offen ist (sonst blockiert print() nicht,
// verbraucht aber trotzdem Zeit im TX-Puffer).
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

void PowerDebugger::bind(uint8_t c, float* p, const char* n)    { bindRaw(c, p, BoundChannelType::FLOAT_PTR,  n); }
void PowerDebugger::bind(uint8_t c, double* p, const char* n)   { bindRaw(c, p, BoundChannelType::DOUBLE_PTR, n); }
void PowerDebugger::bind(uint8_t c, bool* p, const char* n)     { bindRaw(c, p, BoundChannelType::BOOL_PTR,   n); }
void PowerDebugger::bind(uint8_t c, int8_t* p, const char* n)   { bindRaw(c, p, BoundChannelType::I8_PTR,     n); }
void PowerDebugger::bind(uint8_t c, uint8_t* p, const char* n)  { bindRaw(c, p, BoundChannelType::U8_PTR,     n); }
void PowerDebugger::bind(uint8_t c, int16_t* p, const char* n)  { bindRaw(c, p, BoundChannelType::I16_PTR,    n); }
void PowerDebugger::bind(uint8_t c, uint16_t* p, const char* n) { bindRaw(c, p, BoundChannelType::U16_PTR,    n); }
void PowerDebugger::bind(uint8_t c, int32_t* p, const char* n)  { bindRaw(c, p, BoundChannelType::I32_PTR,    n); }
void PowerDebugger::bind(uint8_t c, uint32_t* p, const char* n) { bindRaw(c, p, BoundChannelType::U32_PTR,    n); }

// Unmittelbar vor buildPacket() aufgerufen: gebundene Kanaele aus ihrem
// Pointer in debugData[] uebernehmen. Iteriert nur ueber die tatsaechlich
// gebundenen Eintraege (frueher: alle 200 Kanaele, 100x/s).
void PowerDebugger::sampleBoundChannels() {
    for (uint8_t i = 0; i < _boundCount; i++) {
        const BoundChannel& b = _bound[i];
        float v;
        switch (b.type) {
            case BoundChannelType::FLOAT_PTR:  v = *(float*)b.ptr;                    break;
            case BoundChannelType::DOUBLE_PTR: v = (float)(*(double*)b.ptr);          break;
            case BoundChannelType::BOOL_PTR:   v = *(bool*)b.ptr ? 1.0f : 0.0f;       break;
            case BoundChannelType::I8_PTR:     v = (float)(*(int8_t*)b.ptr);          break;
            case BoundChannelType::U8_PTR:     v = (float)(*(uint8_t*)b.ptr);         break;
            case BoundChannelType::I16_PTR:    v = (float)(*(int16_t*)b.ptr);         break;
            case BoundChannelType::U16_PTR:    v = (float)(*(uint16_t*)b.ptr);        break;
            case BoundChannelType::I32_PTR:    v = (float)(*(int32_t*)b.ptr);         break;
            case BoundChannelType::U32_PTR:    v = (float)(*(uint32_t*)b.ptr);        break;
            default: continue;
        }
        debugData[b.chn] = v;
    }
}

// ══════════════════════════════════════════════════════════════════════════
//  Namens-/Overlay-Deskriptor: JSON bauen, chunken, ueber UART_DBG senden
// ══════════════════════════════════════════════════════════════════════════
//  Wird beim Boot einmal und danach nur auf Anfrage der GUI gesendet —
//  Effizienz ist hier zweitrangig gegenueber Lesbarkeit und Robustheit.

namespace {

struct JsonBuilder {
    char*  buf;
    size_t cap;      // nutzbare Kapazitaet OHNE die Schluss-Reserve
    size_t pos = 0;
    bool   overflow = false;

    JsonBuilder(char* b, size_t bytes)
        : buf(b), cap(bytes > DESC_CLOSE_RESERVE ? bytes - DESC_CLOSE_RESERVE : 0) {}

    /// Passen `need` weitere Bytes noch in den Nutzbereich?
    bool fits(size_t need) {
        if (pos + need < cap) return true;
        overflow = true;
        return false;
    }

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

    /// Haengt s escaped an (Anfuehrungszeichen/Backslash), OHNE Quotes.
    void putEscaped(const char* s) {
        if (!s) return;
        for (const char* p = s; *p; ++p) {
            if (pos + 2 >= cap) { overflow = true; return; }
            if (*p == '"' || *p == '\\') buf[pos++] = '\\';
            buf[pos++] = *p;
        }
    }

    /// Schluss-Zeichen dürfen die Reserve nutzen und passen daher immer.
    void close(const char* s) {
        while (*s) buf[pos++] = *s++;
    }
};

/// "index":"name" — gibt false zurueck, wenn kein Platz mehr war (Aufrufer
/// bricht die Schleife dann ab, damit das JSON gueltig bleibt).
bool putNameEntry(JsonBuilder& j, bool& first, int index, const char* name) {
    if (!name || !name[0]) return true;                       // Luecke: ueberspringen
    if (!j.fits(strlen(name) * 2 + 16)) return false;
    if (!first) j.put(",");
    first = false;
    j.put("\"%d\":\"", index);
    j.putEscaped(name);
    j.put("\"");
    return true;
}

}  // namespace

void PowerDebugger::buildDescriptorJson() {
    JsonBuilder j(_descBuf, sizeof(_descBuf));

    j.put("{\"channels\":{");
    bool first = true;
    for (int i = 0; i < ACTIVE_CHANNELS; i++) {
        if (!putNameEntry(j, first, i, _names[i])) break;
    }

    j.put("},\"param_slow_floats\":{");
    first = true;
    for (int i = 0; i < PARAM_SLOW_FLOAT_COUNT; i++) {
        if (!putNameEntry(j, first, i, PARAM_SLOW_FLOAT_NAMES[i])) break;
    }

    j.put("},\"param_slow_bools\":{");
    first = true;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
        if (!putNameEntry(j, first, i, PARAM_SLOW_BOOL_NAMES[i])) break;
    }

    j.put("},\"param_fast_floats\":{");
    first = true;
    for (int i = 0; i < PARAM_FAST_FLOAT_COUNT; i++) {
        if (!putNameEntry(j, first, i, PARAM_FAST_FLOAT_NAMES[i])) break;
    }

    j.put("},\"overlays\":[");
    bool firstOverlay = true;
    for (size_t i = 0; i < CHANNEL_OVERLAYS_COUNT; i++) {
        const OverlayDef& ov = CHANNEL_OVERLAYS[i];
        const size_t need = strlen(ov.label ? ov.label : "") * 2
                          + strlen(ov.extra ? ov.extra : "") * 2
                          + strlen(ov.type  ? ov.type  : "") + 160;
        if (!j.fits(need)) break;
        if (!firstOverlay) j.put(",");
        firstOverlay = false;
        j.put("{\"group\":%d,\"type\":\"%s\",\"label\":\"", ov.group, ov.type ? ov.type : "");
        j.putEscaped(ov.label);
        j.put("\"");
        if (ov.channel  >= 0) j.put(",\"channel\":%d",  ov.channel);
        if (ov.channel2 >= 0) j.put(",\"channel2\":%d", ov.channel2);
        if (ov.min_val != 0.0f || ov.max_val != 0.0f)
            j.put(",\"min\":%.3f,\"max\":%.3f", ov.min_val, ov.max_val);
        if (ov.x_pct >= 0.0f)
            j.put(",\"x_pct\":%.2f,\"y_pct\":%.2f", ov.x_pct, ov.y_pct);
        if (ov.extra && ov.extra[0]) {
            j.put(",\"extra\":\"");
            j.putEscaped(ov.extra);
            j.put("\"");
        }
        j.put("}");
    }
    j.close("]}");

    _descJsonLen  = j.pos;
    _descOverflow = j.overflow;
    _descChunkCount = (uint8_t)((j.pos + CHANNEL_DESC_CHUNK_PAYLOAD_MAX - 1)
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
    if (_descNextChunk >= _descChunkCount) { _descNextChunk = 0xFF; return; }

    const size_t offset    = (size_t)_descNextChunk * CHANNEL_DESC_CHUNK_PAYLOAD_MAX;
    const size_t remaining = (offset < _descJsonLen) ? (_descJsonLen - offset) : 0;
    const uint8_t payloadLen = (uint8_t)((remaining < (size_t)CHANNEL_DESC_CHUNK_PAYLOAD_MAX)
                                          ? remaining : (size_t)CHANNEL_DESC_CHUNK_PAYLOAD_MAX);

    uint8_t pkt[CHANNEL_DESC_CHUNK_HEADER_BYTES + CHANNEL_DESC_CHUNK_PAYLOAD_MAX];
    const uint32_t magic = CHANNEL_DESC_MAGIC;
    memcpy(pkt, &magic, 4);
    pkt[4] = _descNextChunk;
    pkt[5] = _descChunkCount;
    pkt[6] = payloadLen;
    memcpy(pkt + CHANNEL_DESC_CHUNK_HEADER_BYTES, _descBuf + offset, payloadLen);

    UART_DBG.write(pkt, CHANNEL_DESC_CHUNK_HEADER_BYTES + payloadLen);

    _descNextChunk++;
    if (_descNextChunk >= _descChunkCount) _descNextChunk = 0xFF;   // fertig
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
                if (_rxExpectedLen == PARAM_SLOW_PACKET_BYTES) {
                    memcpy(_paramFloats, _rxBuf + PARAM_HEADER_BYTES,
                           PARAM_SLOW_FLOAT_COUNT * 4);
                    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
                        _paramBools[i] =
                            _rxBuf[PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + i] != 0;
                    }
                    _lastSlowRxMs = millis();
                    _slowPktCount++;
                } else {
                    memcpy(_fastFloats, _rxBuf + PARAM_HEADER_BYTES,
                           PARAM_FAST_FLOAT_COUNT * 4);
                    _lastFastRxMs = millis();
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

// Namensauflösung ueber die Tabellen aus channel_config.h. Lineare Suche
// ueber hoechstens 50 kurze Strings — bei einem Aufruf je Regelzyklus nicht
// messbar. Wer sie in einer sehr heissen Schleife braucht, holt den Index
// einmal in eine static-Variable (siehe Beispiel-Sketch).
static int lookupParamIndex(const char* const* table, int count, const char* name) {
    if (!name || !name[0]) return -1;
    for (int i = 0; i < count; i++) {
        if (table[i] && strcmp(table[i], name) == 0) return i;
    }
    return -1;
}

float PowerDebugger::param(const char* name) const {
    const int i = lookupParamIndex(PARAM_SLOW_FLOAT_NAMES, PARAM_SLOW_FLOAT_COUNT, name);
    if (i < 0) { pdsWarn("Unbekannter Param-Name \"%s\"", name ? name : "(null)"); return 0.0f; }
    return _paramFloats[i];
}

bool PowerDebugger::paramBool(const char* name) const {
    const int i = lookupParamIndex(PARAM_SLOW_BOOL_NAMES, PARAM_SLOW_BOOL_COUNT, name);
    if (i < 0) { pdsWarn("Unbekannter Bool-Param \"%s\"", name ? name : "(null)"); return false; }
    return _paramBools[i];
}

float PowerDebugger::fastParam(const char* name) const {
    const int i = lookupParamIndex(PARAM_FAST_FLOAT_NAMES, PARAM_FAST_FLOAT_COUNT, name);
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

void PowerDebugger::printStatus(Print& out) const {
    out.printf("[PDS %s] TX=%lu (drop %lu) | Slow=%lu Fast=%lu | Alter=%lu ms | "
               "Sync-Verluste=%lu | Kanaele=%u%s\n",
               PDS_VERSION,
               (unsigned long)_txPktCount, (unsigned long)_txDrops,
               (unsigned long)_slowPktCount, (unsigned long)_fastPktCount,
               (unsigned long)fastParamAgeMs(),
               (unsigned long)_paramSyncLosses,
               (unsigned)_autoNext,
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
    setName(firstChannel + 5, "PDS_Sync_Verluste");
}

// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::begin() {
    // Debug-Array + Namens-Registry initialisieren
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0.0f;
    for (int i = 0; i < ACTIVE_CHANNELS; i++) _names[i][0] = '\0';
    _boundCount = 0;
    _autoNext   = PDS_AUTO_CHANNEL_BASE;

    // Namen aus channel_config.h vorbelegen. bind()/Channel(...,name)/plot()
    // im Sketch ueberschreiben danach gezielt einzelne Eintraege bzw. bekommen
    // die noch freien Kanaele (siehe channelFor()).
    for (size_t i = 0; i < CHANNEL_NAMES_COUNT; i++) {
        setName(CHANNEL_NAMES[i].index, CHANNEL_NAMES[i].name);
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
    _descNextChunk     = 0xFF;
    _bootAnnounceAtMs  = millis() + PDS_BOOT_ANNOUNCE_DELAY_MS;
    if (_bootAnnounceAtMs == 0) _bootAnnounceAtMs = 1;   // 0 ist der "erledigt"-Marker
}

void PowerDebugger::update() {
    // ── Param-Downlink ZUERST: nicht-blockierend, jede update()-Iteration.
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

    // ── Namens-/Overlay-Deskriptor: ein Chunk alle 10 ms, solange ein
    //    Sendevorgang laeuft (Boot oder GUI-Anfrage). Nur senden, wenn im
    //    TX-Puffer genug Platz ist -- sonst wuerde write() blockierend auf
    //    den UART warten und den 100-Hz-Takt des Hauptprogramms verzoegern.
    if (_descNextChunk != 0xFF && DescChunkTimer >= DESC_CHUNK_PERIOD_MS) {
        if (UART_DBG.availableForWrite() >= CHANNEL_DESC_CHUNK_PACKET_BYTES) {
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
