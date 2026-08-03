#include "PDS.h"
#include "elapsedMillis.h"
#include "channel_config.h"
#include <stdarg.h>

elapsedMillis DBGTimer;
elapsedMillis DescChunkTimer;

static constexpr uint32_t HEADER_MAGIC     = 0xDEADBEEF;

// MAX_FLOATS ist Teil des WIRE-FORMATS und muss mit rpi_zero_node/
// spi_receiver.py (MAX_FLOATS) und rpi5_monitor/.../config.py (MAX_FLOATS)
// uebereinstimmen. ACTIVE_CHANNELS (Build-Flag) steuert nur, wie viele
// davon benannt/gebunden werden koennen -- es darf MAX_FLOATS nicht
// ueberschreiten, sonst wuerde sampleBoundChannels() ueber debugData[]
// hinausschreiben.
static constexpr int      MAX_FLOATS       = 200;
static_assert(ACTIVE_CHANNELS <= MAX_FLOATS,
              "ACTIVE_CHANNELS darf MAX_FLOATS (Wire-Format) nicht ueberschreiten");

static constexpr int      PACKET_BYTES     = 8 + MAX_FLOATS * 4;  // 808 bei 200 Kanaelen
static constexpr uint32_t SAMPLE_PERIOD_MS = 10;                  // 10 ms -> 100 Hz
static constexpr uint32_t DESC_CHUNK_PERIOD_MS = 10;              // ein Deskriptor-Chunk pro 10 ms

// ── UART-Puffer ───────────────────────────────────────────────────────────
//  TX: 808 B/Paket bei 100 Hz = 80.8 kB/s gegen 100 kB/s Baud-Budget
//      (1 Mbps, 8N1 = 10 Bit/Byte). 4 KB Puffer ueberbrueckt Jitter.
//
//  RX: WICHTIG fuer die Latenz des Fast-/Joystick-Kanals. Der Teensy-Core
//      legt per Default nur 64 Byte RX-Puffer an -- ein einzelnes Slow-
//      Paket (258 B) passt da nicht hinein und laeuft schon waehrend des
//      Empfangs ueber, sobald loop() nicht alle ~0.6 ms pollt. Die dabei
//      verlorenen Bytes bringen den Paket-Parser aus dem Tritt: er wartet
//      dann auf die fehlenden Bytes und frisst dabei die naechsten
//      Fast-Pakete als vermeintliche Nutzlast auf -> ruckartige,
//      hundert Millisekunden lange Aussetzer der Fernsteuerung.
//      2 KB puffern ~600 ms Downlink-Strom und machen den Empfang
//      unabhaengig von der Zykluszeit des Roboter-Hauptprogramms.
static uint8_t _uart_dbg_tx_buf[4096];
static uint8_t _uart_dbg_rx_buf[2048];

static uint8_t _pkt_buf[PACKET_BYTES];

static float debugData[MAX_FLOATS];

// Bereichsgeprueft: ein Channel()-Aufruf mit einem Index >= MAX_FLOATS hat
// vorher hinter debugData[] geschrieben und dabei beliebigen anderen
// Speicher zerstoert (uint8_t-Index reicht bis 255, das Array hat 200).
#define DBG(channel, value)                                                   \
    do {                                                                      \
        if ((int)(channel) < MAX_FLOATS)                                      \
            debugData[(channel)] = static_cast<float>(value);                 \
    } while (0)

static char _descBuf[CHANNEL_DESC_JSON_BUF_BYTES];

// ── Kleine JSON-Bau-Helfer (Deskriptor wird nur einmal beim Boot bzw. auf
//    Anfrage gebaut -- Effizienz ist hier zweitrangig gegenueber Klarheit) ──
static void jsonPut(char* buf, size_t bufSize, size_t& pos, const char* fmt, ...) {
    if (pos + 1 >= bufSize) return;
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf + pos, bufSize - pos, fmt, args);
    va_end(args);
    if (n <= 0) return;
    // vsnprintf liefert die Laenge, die OHNE Abschneiden noetig gewesen waere.
    // Ungeprueft uebernommen konnte pos dadurch hinter das Pufferende wandern
    // -- _descJsonLen waere dann groesser als _descBuf und sendNextDescChunk()
    // haette Fremdspeicher verschickt.
    size_t written = (size_t)n;
    size_t room    = bufSize - pos - 1;
    pos += (written < room) ? written : room;
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

void PowerDebugger::Channel(uint8_t chn, float val){
    DBG(chn, val);
}

void PowerDebugger::Channel(uint8_t chn, float val, const char* name){
    DBG(chn, val);
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
//  drei bekannten Magic-Werte; sobald einer erkannt ist, steht die
//  erwartete Gesamtlänge fest (Slow = 258 Byte, Fast = 28 Byte) und die
//  restlichen Bytes werden einfach angehängt, bis das Paket vollständig
//  ist. Da loop()/update() einzelsträngig laufen (keine ISR greift auf
//  dieselben Arrays zu), ist kein noInterrupts()/interrupts() nötig.
//
//  BUGFIX (Latenz Fernsteuerung): Die alte Fassung hat das Schiebefenster
//  bei JEDEM Byte weitergeschoben, den Magic-Vergleich aber erst ab dem
//  FUENFTEN Byte nach einem Zustands-Reset ausgefuehrt ("if (fill < 4)
//  { fill++; continue; }" uebersprang den Vergleich genau in dem Moment,
//  in dem die vier Magic-Bytes vollstaendig im Fenster standen). Nach
//  jedem fertig geparsten Paket wurde der Magic des unmittelbar folgenden
//  Pakets deshalb systematisch uebersehen und dieses Paket komplett
//  verworfen -- der Fast-Kanal kam so nur mit 50 statt 100 Hz an, der
//  Slow-Kanal mit 1 statt 2 Hz. Jetzt wird das Fenster erst gefuellt und
//  danach bei jedem Byte geprueft, also auch beim vierten.
void PowerDebugger::pollParamUart() {
    static uint8_t buf[PARAM_SLOW_PACKET_BYTES];   // größerer der beiden Pakettypen, wiederverwendet
    static int     fill = 0;
    static int     expectedLen = 0;                // 0 = suche noch nach gültigem Magic

    while (UART_DBG.available()) {
        uint8_t b = (uint8_t)UART_DBG.read();

        if (expectedLen == 0) {
            // Schiebefenster über die letzten 4 Bytes fuer die Magic-Suche:
            // erst auffuellen, danach byteweise nachruecken.
            if (fill < 4) {
                buf[fill++] = b;
                if (fill < 4) continue;    // noch keine 4 Bytes -> kein Magic moeglich
            } else {
                buf[0] = buf[1]; buf[1] = buf[2]; buf[2] = buf[3]; buf[3] = b;
                _paramSyncLosses++;        // das herausgeschobene Byte war Muell
            }

            uint32_t magic;
            memcpy(&magic, buf, 4);

            if (magic == PARAM_SLOW_MAGIC) {
                expectedLen = PARAM_SLOW_PACKET_BYTES;
            } else if (magic == PARAM_FAST_MAGIC) {
                expectedLen = PARAM_FAST_PACKET_BYTES;
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

            if (fill >= expectedLen) {
                if (expectedLen == PARAM_SLOW_PACKET_BYTES) {
                    memcpy(_paramFloats, buf + PARAM_HEADER_BYTES,
                           PARAM_SLOW_FLOAT_COUNT * 4);
                    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
                        _paramBools[i] =
                            buf[PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + i] != 0;
                    }
                    _lastSlowRxMs = millis();
                    _slowPktCount++;
                } else {
                    memcpy(_fastFloats, buf + PARAM_HEADER_BYTES,
                           PARAM_FAST_FLOAT_COUNT * 4);
                    _lastFastRxMs = millis();
                    _fastPktCount++;
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

uint32_t PowerDebugger::fastParamAgeMs() const {
    if (_lastFastRxMs == 0) return 0xFFFFFFFFUL;   // noch nie etwas empfangen
    return millis() - _lastFastRxMs;
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

    // TX- UND RX-Buffer erweitern, danach erst UART starten.
    // Der RX-Buffer ist der entscheidende Teil fuer die Reaktionszeit der
    // Fernsteuerung -- siehe Kommentar bei _uart_dbg_rx_buf oben.
    UART_DBG.addMemoryForWrite(_uart_dbg_tx_buf, sizeof(_uart_dbg_tx_buf));
    UART_DBG.addMemoryForRead(_uart_dbg_rx_buf, sizeof(_uart_dbg_rx_buf));
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

    // ── Param-Downlink ZUERST: nicht-blockierend, jede update()-Iteration.
    //    Bewusst vor dem Telemetrie-Versand, damit getFastParam() direkt nach
    //    update() den zuletzt eingetroffenen Stand liefert und nicht einen um
    //    einen Zyklus alten. ──────────────────────────────────────────────────
    pollParamUart();

    // ── Alle 10 ms: Paket senden (100 Hz) ────────────────────────────────────
    if (DBGTimer >= SAMPLE_PERIOD_MS) {
        // Nachlauf statt Reset auf 0: verhindert, dass sich die Sendefrequenz
        // bei einer laengeren loop()-Iteration dauerhaft nach unten verschiebt.
        // Nur wenn wir mehr als eine ganze Periode hinterherhinken, wird hart
        // resynchronisiert (sonst wuerden Pakete nachgeholt/gebuendelt).
        if (DBGTimer >= 2 * SAMPLE_PERIOD_MS) DBGTimer = 0;
        else                                  DBGTimer -= SAMPLE_PERIOD_MS;

        // ── Kanal-Bindung: gebundene Pointer direkt vor dem Packen auslesen ──
        //    (frueher bei JEDER update()-Iteration -- bei einem schnellen
        //    Hauptprogramm waren das mehrere tausend ueberfluessige
        //    200-Kanal-Durchlaeufe pro Sekunde.)
        sampleBoundChannels();
        buildPacket();

        // UART_DBG.write() kopiert die 808 Bytes in den TX-Buffer und kehrt
        // sofort zurück; die Übertragung läuft asynchron (~8 ms bei 1 Mbps).
        // Bei 10 ms Paket-Intervall ist der Buffer stets leer wenn wir schreiben.
        UART_DBG.write(_pkt_buf, PACKET_BYTES);
        _txPktCount++;
    }

    // ── Namens-/Overlay-Deskriptor: ein Chunk alle 10 ms, solange ein
    //    Sendevorgang laeuft (Boot oder GUI-Anfrage). Nur senden, wenn im
    //    TX-Buffer genug Platz ist -- sonst wuerde write() blockierend auf den
    //    UART warten und dabei den 100-Hz-Takt des Hauptprogramms verzoegern.
    if (_descNextChunk != 0xFF && DescChunkTimer >= DESC_CHUNK_PERIOD_MS) {
        if (UART_DBG.availableForWrite() >= CHANNEL_DESC_CHUNK_PACKET_BYTES) {
            DescChunkTimer = 0;
            sendNextDescChunk();
        }
    }
}
