#include "PDS.h"

void buildPacket() {
    // ── Header: Magic + Timestamp ─────────────────────────────────────────────
    const uint32_t magic = HEADER_MAGIC;
    const uint32_t ts    = micros();
    memcpy(_pkt_buf,     &magic, 4);
    memcpy(_pkt_buf + 4, &ts,    4);

    // ── Nutzdaten: debugData[] direkt kopieren ────────────────────────────────
    memcpy(_pkt_buf + 8, debugData, MAX_FLOATS * sizeof(float));
}