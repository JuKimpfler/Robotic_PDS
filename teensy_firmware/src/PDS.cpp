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

void PowerDebugger::init(){
    // Debug-Array initialisieren (alle Kanäle = inaktiv / Dummy)
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0;  // 9898.0f Dummy wert

    // Serial1 TX-Buffer erweitern und UART starten
    UART_DBG.addMemoryForWrite(_serial1_tx_buf, sizeof(_serial1_tx_buf));
    UART_DBG.begin(UART_DBG_BAUD, SERIAL_8N1);

    pinMode(10,INPUT);
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
}