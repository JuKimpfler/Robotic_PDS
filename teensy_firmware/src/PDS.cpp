#include "PDS.h"
#include "elapsedMillis.h"

elapsedMillis DBGTimer;

static constexpr uint32_t HEADER_MAGIC     = 0xDEADBEEF;
static constexpr int      MAX_FLOATS       = 200;
static constexpr int      PACKET_BYTES     = 8 + MAX_FLOATS * 4;  // 1608
static constexpr uint32_t SAMPLE_PERIOD_US = 10;            // 50 Hz
static uint8_t _serial1_tx_buf[4096];
static uint8_t _pkt_buf[PACKET_BYTES];
uint32_t pkt_count = 0;

static float debugData[MAX_FLOATS];
#define DBG(channel, value)  debugData[(channel)] = static_cast<float>(value);



void PowerDebugger::Channel(u_int8_t chn , float val){
    DBG(chn,val);
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

    // Serial1 TX-Buffer erweitern und UART starten
    UART_DBG.addMemoryForWrite(_serial1_tx_buf, sizeof(_serial1_tx_buf));
    UART_DBG.begin(UART_DBG_BAUD, SERIAL_8N1);

    pinMode(10,INPUT);

    // Param-Downlink: RAM-only, alle Werte starten bei 0.0f / false,
    // bis das erste Paket von der GUI eintrifft (siehe paramsAreFresh()).
    for (int i = 0; i < PARAM_SLOW_FLOAT_COUNT; i++) _paramFloats[i] = 0.0f;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT;  i++) _paramBools[i]  = false;
    for (int i = 0; i < PARAM_FAST_FLOAT_COUNT; i++) _fastFloats[i]  = 0.0f;
}

void PowerDebugger::update(){

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
}
