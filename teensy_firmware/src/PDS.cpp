#include "PDS.h"
#include "elapsedMillis.h"
#include "channel_config.h"
#include <stdarg.h>

elapsedMillis DBGTimer;
elapsedMillis DescChunkTimer;

static constexpr uint32_t HEADER_MAGIC     = 0xDEADBEEF;
static constexpr int      MAX_FLOATS       = 200;
static constexpr int      PACKET_BYTES     = 8 + MAX_FLOATS * 4;  // 1608
static constexpr uint32_t SAMPLE_PERIOD_US = 10;            // 50 Hz
static constexpr uint32_t DESC_CHUNK_PERIOD_MS = 10;        // ein Deskriptor-Chunk pro 10 ms
static uint8_t _serial1_tx_buf[4096];
static uint8_t _pkt_buf[PACKET_BYTES];
uint32_t pkt_count = 0;

static float debugData[MAX_FLOATS];
#define DBG(channel, value)  debugData[(channel)] = static_cast<float>(value);

static char _descBuf[CHANNEL_DESC_JSON_BUF_BYTES];

// ── Kleine JSON-Bau-Helfer (Deskriptor wird nur einmal beim Boot bzw. auf
//    Anfrage gebaut -- Effizienz ist hier zweitrangig gegenueber Klarheit) ──
static void jsonPut(char* buf, size_t bufSize, size_t& pos, const char* fmt, ...) {
    if (pos >= bufSize) return;
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf + pos, bufSize - pos, fmt, args);
    va_end(args);
    if (n > 0) pos += (size_t)n;
}

// Haengt s escaped an (Anfuehrungszeichen/Backslash), OHNE umschliessende Quotes.
static void jsonPutEscaped(char* buf, size_t bufSize, size_t& pos, const char* s) {
    if (!s) return;
    for (const char* p = s; *p; ++p) {
        if (pos + 2 >= bufSize) break;   // Platz fuer Escape-Zeichen + Nullterminator reservieren
        if (*p == '"' || *p == '\\') buf[pos++] = '\\';
        buf[pos++] = *p;
    }
}

void PowerDebugger::Channel(u_int8_t chn , float val){
    DBG(chn,val);
}

void PowerDebugger::Channel(u_int8_t chn, float val, const char* name){
    DBG(chn,val);
    if (name) setName(chn, name);
}

void PowerDebugger::setName(uint8_t chn, const char* name){
    if (chn >= ACTIVE_CHANNELS || !name) return;
    strncpy(_names[chn], name, CHANNEL_NAME_MAXLEN - 1);
    _names[chn][CHANNEL_NAME_MAXLEN - 1] = '\0';
}

void PowerDebugger::bind(uint8_t chn, float* ptr, const char* name){
    if (chn >= ACTIVE_CHANNELS || !ptr) return;
    _bound[chn].type = BoundChannelType::FLOAT_PTR;
    _bound[chn].ptr  = ptr;
    if (name) setName(chn, name);
}

void PowerDebugger::bind(uint8_t chn, bool* ptr, const char* name){
    if (chn >= ACTIVE_CHANNELS || !ptr) return;
    _bound[chn].type = BoundChannelType::BOOL_PTR;
    _bound[chn].ptr  = ptr;
    if (name) setName(chn, name);
}

void PowerDebugger::bind(uint8_t chn, int* ptr, const char* name){
    if (chn >= ACTIVE_CHANNELS || !ptr) return;
    _bound[chn].type = BoundChannelType::INT_PTR;
    _bound[chn].ptr  = ptr;
    if (name) setName(chn, name);
}

// Vor buildPacket() aufgerufen: gebundene Kanaele automatisch aus ihrem
// Pointer in debugData[] uebernehmen -- Channel()-Aufrufe fuer diese
// Kanaele sind danach nicht mehr noetig (koennten sie aber weiterhin
// ueberschreiben, letzter Schreibzugriff im Zyklus gewinnt).
void PowerDebugger::sampleBoundChannels(){
    for (int i = 0; i < ACTIVE_CHANNELS; i++) {
        switch (_bound[i].type) {
            case BoundChannelType::FLOAT_PTR:
                debugData[i] = *reinterpret_cast<float*>(_bound[i].ptr);
                break;
            case BoundChannelType::BOOL_PTR:
                debugData[i] = *reinterpret_cast<bool*>(_bound[i].ptr) ? 1.0f : 0.0f;
                break;
            case BoundChannelType::INT_PTR:
                debugData[i] = static_cast<float>(*reinterpret_cast<int*>(_bound[i].ptr));
                break;
            default:
                break;
        }
    }
}

// ══════════════════════════════════════════════════════════════════════════
//  Namens-/Overlay-Deskriptor: JSON aus channel_config.h + Namens-Registry
//  bauen, in Chunks aufteilen und ueber UART_DBG senden (siehe params.h fuer
//  das Chunk-Paket-Format).
// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::buildDescriptorJson(){
    size_t pos = 0;
    char* buf = _descBuf;
    const size_t bufSize = CHANNEL_DESC_JSON_BUF_BYTES;

    jsonPut(buf, bufSize, pos, "{\"channels\":{");
    bool first = true;
    for (int i = 0; i < ACTIVE_CHANNELS; i++) {
        if (_names[i][0] == '\0') continue;
        if (!first) jsonPut(buf, bufSize, pos, ",");
        first = false;
        jsonPut(buf, bufSize, pos, "\"%d\":\"", i);
        jsonPutEscaped(buf, bufSize, pos, _names[i]);
        jsonPut(buf, bufSize, pos, "\"");
    }

    jsonPut(buf, bufSize, pos, "},\"param_slow_floats\":{");
    first = true;
    for (int i = 0; i < PARAM_SLOW_FLOAT_COUNT; i++) {
        const char* n = PARAM_SLOW_FLOAT_NAMES[i];
        if (!n || !n[0]) continue;
        if (!first) jsonPut(buf, bufSize, pos, ",");
        first = false;
        jsonPut(buf, bufSize, pos, "\"%d\":\"", i);
        jsonPutEscaped(buf, bufSize, pos, n);
        jsonPut(buf, bufSize, pos, "\"");
    }

    jsonPut(buf, bufSize, pos, "},\"param_slow_bools\":{");
    first = true;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
        const char* n = PARAM_SLOW_BOOL_NAMES[i];
        if (!n || !n[0]) continue;
        if (!first) jsonPut(buf, bufSize, pos, ",");
        first = false;
        jsonPut(buf, bufSize, pos, "\"%d\":\"", i);
        jsonPutEscaped(buf, bufSize, pos, n);
        jsonPut(buf, bufSize, pos, "\"");
    }

    jsonPut(buf, bufSize, pos, "},\"param_fast_floats\":{");
    first = true;
    for (int i = 0; i < PARAM_FAST_FLOAT_COUNT; i++) {
        const char* n = PARAM_FAST_FLOAT_NAMES[i];
        if (!n || !n[0]) continue;
        if (!first) jsonPut(buf, bufSize, pos, ",");
        first = false;
        jsonPut(buf, bufSize, pos, "\"%d\":\"", i);
        jsonPutEscaped(buf, bufSize, pos, n);
        jsonPut(buf, bufSize, pos, "\"");
    }

    jsonPut(buf, bufSize, pos, "},\"overlays\":[");
    for (size_t i = 0; i < CHANNEL_OVERLAYS_COUNT; i++) {
        const OverlayDef& ov = CHANNEL_OVERLAYS[i];
        if (i > 0) jsonPut(buf, bufSize, pos, ",");
        jsonPut(buf, bufSize, pos, "{\"group\":%d,\"type\":\"%s\",\"label\":\"", ov.group, ov.type);
        jsonPutEscaped(buf, bufSize, pos, ov.label);
        jsonPut(buf, bufSize, pos, "\"");
        if (ov.channel  >= 0) jsonPut(buf, bufSize, pos, ",\"channel\":%d", ov.channel);
        if (ov.channel2 >= 0) jsonPut(buf, bufSize, pos, ",\"channel2\":%d", ov.channel2);
        if (ov.min_val != 0.0f || ov.max_val != 0.0f)
            jsonPut(buf, bufSize, pos, ",\"min\":%.3f,\"max\":%.3f", ov.min_val, ov.max_val);
        if (ov.x_pct >= 0.0f)
            jsonPut(buf, bufSize, pos, ",\"x_pct\":%.2f,\"y_pct\":%.2f", ov.x_pct, ov.y_pct);
        if (ov.extra && ov.extra[0]) {
            jsonPut(buf, bufSize, pos, ",\"extra\":\"");
            jsonPutEscaped(buf, bufSize, pos, ov.extra);
            jsonPut(buf, bufSize, pos, "\"");
        }
        jsonPut(buf, bufSize, pos, "}");
    }
    jsonPut(buf, bufSize, pos, "]}");

    _descJsonLen = pos;
    _descChunkCount = (uint8_t)((pos + CHANNEL_DESC_CHUNK_PAYLOAD_MAX - 1) / CHANNEL_DESC_CHUNK_PAYLOAD_MAX);
    if (_descChunkCount == 0) _descChunkCount = 1;   // leerer Deskriptor -> trotzdem 1 (leerer) Chunk
    _descBuilt = true;
}

void PowerDebugger::startDescriptorSend(){
    if (!_descBuilt) buildDescriptorJson();
    _descNextChunk = 0;
    DescChunkTimer = 0;
}

void PowerDebugger::sendNextDescChunk(){
    if (_descNextChunk >= _descChunkCount) { _descNextChunk = 0xFF; return; }

    size_t offset    = (size_t)_descNextChunk * CHANNEL_DESC_CHUNK_PAYLOAD_MAX;
    size_t remaining = _descJsonLen - offset;
    uint8_t payloadLen = (uint8_t)((remaining < (size_t)CHANNEL_DESC_CHUNK_PAYLOAD_MAX)
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
    if (_descNextChunk >= _descChunkCount) _descNextChunk = 0xFF;   // Sendevorgang fertig
}

void PowerDebugger::buildPacket() {
    // ── Header: Magic + Timestamp ─────────────────────────────────────────────
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(_pkt_buf,     &magic, 4);
    memcpy(_pkt_buf + 4, &ts,    4);

    // ── Nutzdaten: debugData[] direkt kopieren ────────────────────────────────
    memcpy(_pkt_buf + 8, debugData, MAX_FLOATS * sizeof(float));
}

// ══════════════════════════════════════════════════════════════════════════
//  Param-Downlink: Zwei-Magic-Byte-Sync-Parser (RPi Zero → Teensy, RX)
// ══════════════════════════════════════════════════════════════════════════
//
//  UART_DBG.available()/read() wird jede update()-Iteration abgefragt,
//  nicht-blockierend. Ein 4-Byte-Schiebefenster sucht nach einem der
//  beiden bekannten Magic-Werte; sobald einer erkannt ist, steht die
//  erwartete Gesamtlänge fest (Slow = 258 Byte, Fast = 28 Byte) und die
//  restlichen Bytes werden einfach angehängt, bis das Paket vollständig
//  ist. Da loop()/update() einzelsträngig laufen (keine ISR greift auf
//  dieselben Arrays zu), ist kein noInterrupts()/interrupts() nötig.
//
void PowerDebugger::pollParamUart() {
    static uint8_t buf[PARAM_SLOW_PACKET_BYTES];   // größerer der beiden Pakettypen, wiederverwendet
    static int     fill = 0;
    static int     expectedLen = 0;                // 0 = suche noch nach gültigem Magic

    while (UART_DBG.available()) {
        uint8_t b = UART_DBG.read();

        if (expectedLen == 0) {
            // Schiebefenster über die letzten 4 Bytes fuer die Magic-Suche
            buf[0] = buf[1]; buf[1] = buf[2]; buf[2] = buf[3]; buf[3] = b;
            if (fill < 4) { fill++; continue; }

            uint32_t magic;
            memcpy(&magic, buf, 4);

            if (magic == PARAM_SLOW_MAGIC) {
                expectedLen = PARAM_SLOW_PACKET_BYTES;
                fill = 4;
            } else if (magic == PARAM_FAST_MAGIC) {
                expectedLen = PARAM_FAST_PACKET_BYTES;
                fill = 4;
            } else if (magic == CHANNEL_DESC_REQUEST_MAGIC) {
                // Kein Payload -- Paket ist mit dem Magic selbst schon komplett,
                // bleibt daher in diesem Zweig (nicht ueber expectedLen/fill,
                // die Laenge waere identisch zur Magic-Fenstergroesse).
                startDescriptorSend();
                fill = 0;
            }
            // Sonst: kein bekannter Magic -- Fenster bleibt, naechstes Byte pruefen
        } else {
            buf[fill++] = b;

            if (fill == expectedLen) {
                if (expectedLen == PARAM_SLOW_PACKET_BYTES) {
                    memcpy(_paramFloats, buf + PARAM_HEADER_BYTES,
                           PARAM_SLOW_FLOAT_COUNT * 4);
                    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
                        _paramBools[i] =
                            buf[PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + i] != 0;
                    }
                    _lastSlowRxMs = millis();
                } else {
                    memcpy(_fastFloats, buf + PARAM_HEADER_BYTES,
                           PARAM_FAST_FLOAT_COUNT * 4);
                    _lastFastRxMs = millis();
                }
                expectedLen = 0;
                fill = 0;   // bereit fuer das naechste Paket
            }
        }
    }
}

// ── Öffentliche Zugriffs-API ────────────────────────────────────────────────

float PowerDebugger::getParam(uint8_t index) const {
    return (index < PARAM_SLOW_FLOAT_COUNT) ? _paramFloats[index] : 0.0f;
}

bool PowerDebugger::getParamBool(uint8_t index) const {
    return (index < PARAM_SLOW_BOOL_COUNT) ? _paramBools[index] : false;
}

float PowerDebugger::getFastParam(uint8_t index) const {
    return (index < PARAM_FAST_FLOAT_COUNT) ? _fastFloats[index] : 0.0f;
}

bool PowerDebugger::paramsAreFresh() const {
    return (_lastSlowRxMs != 0) && (millis() - _lastSlowRxMs < PARAM_SLOW_TIMEOUT_MS);
}

bool PowerDebugger::fastParamsAreFresh() const {
    return (_lastFastRxMs != 0) && (millis() - _lastFastRxMs < PARAM_FAST_TIMEOUT_MS);
}

// ══════════════════════════════════════════════════════════════════════════

void PowerDebugger::init(){
    // Debug-Array initialisieren (alle Kanäle = inaktiv / Dummy)
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0;  // 9898.0f Dummy wert

    // Namens-Registry + Kanal-Bindungen: erst aus channel_config.h vorbelegen,
    // bind()/Channel(...,name) im Sketch ueberschreiben danach gezielt einzelne
    // Eintraege (siehe setName()).
    for (int i = 0; i < ACTIVE_CHANNELS; i++) {
        _names[i][0]    = '\0';
        _bound[i].type   = BoundChannelType::NONE;
        _bound[i].ptr    = nullptr;
    }
    for (size_t i = 0; i < CHANNEL_NAMES_COUNT; i++) {
        setName(CHANNEL_NAMES[i].index, CHANNEL_NAMES[i].name);
    }

    // Serial1 TX-Buffer erweitern und UART starten
    UART_DBG.addMemoryForWrite(_serial1_tx_buf, sizeof(_serial1_tx_buf));
    UART_DBG.begin(UART_DBG_BAUD, SERIAL_8N1);

    pinMode(10,INPUT);

    // Param-Downlink: RAM-only, alle Werte starten bei 0.0f / false,
    // bis das erste Paket von der GUI eintrifft (siehe paramsAreFresh()).
    for (int i = 0; i < PARAM_SLOW_FLOAT_COUNT; i++) _paramFloats[i] = 0.0f;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT;  i++) _paramBools[i]  = false;
    for (int i = 0; i < PARAM_FAST_FLOAT_COUNT; i++) _fastFloats[i]  = 0.0f;

    // Namens-/Overlay-Deskriptor einmalig beim Boot senden (GUI kann per
    // CHANNEL_DESC_REQUEST_MAGIC eine Neuuebertragung anfordern, siehe pollParamUart()).
    startDescriptorSend();
}

void PowerDebugger::update(){

    // ── Kanal-Bindung: gebundene Pointer vor dem Packen automatisch auslesen ──
    sampleBoundChannels();

    // ── Alle 10 ms: Paket senden (100 Hz) ────────────────────────────────────
    if (DBGTimer >= SAMPLE_PERIOD_US) {
        buildPacket();
        DBGTimer = 0;

        // Serial1.write() kopiert 1608 Bytes in den TX-Buffer und kehrt
        // sofort zurück. Der UART-DMA überträgt asynchron (~4 ms bei 4 Mbps).
        // Bei 10 ms Paket-Intervall ist der Buffer stets leer wenn wir schreiben.
        //last_buffer = _pkt_buf;
        //last_bytes = PACKET_BYTES;
        UART_DBG.write(_pkt_buf, PACKET_BYTES);
    }

    // ── Param-Downlink: nicht-blockierend, jede update()-Iteration ──────────
    pollParamUart();

    // ── Namens-/Overlay-Deskriptor: ein Chunk alle 10 ms, solange ein
    //    Sendevorgang laeuft (Boot oder GUI-Anfrage) ──────────────────────────
    if (_descNextChunk != 0xFF && DescChunkTimer >= DESC_CHUNK_PERIOD_MS) {
        DescChunkTimer = 0;
        sendNextDescChunk();
    }
}
