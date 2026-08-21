/*
 * tools/hostsim/desc_dump.cpp
 * ============================
 * Fährt die PDS-Bibliothek auf dem PC hoch, lässt sie den Namens-/Overlay-
 * Deskriptor senden, setzt die Chunks wieder zusammen und schreibt das
 * Ergebnis nach stdout. tools/desc_json_check.py prüft das mit einem echten
 * JSON-Parser.
 *
 * Zusätzlich laufen Ereignisse, Parameter-Rückmeldung und die automatische
 * Wiederholung des Deskriptors mit — so ist das komplette Uplink-Format aus
 * params.h einmal wirklich AUSGEFÜHRT und nicht nur übersetzt.
 *
 * Ausgabe (zeilenweise, damit die Python-Seite sie einfach lesen kann):
 *   CHUNKS <n>        Chunks des ersten vollständigen Deskriptors
 *   DESCRIPTORS <n>   wie oft der Deskriptor insgesamt kam (Wiederholung)
 *   JSONLEN <bytes>
 *   OVERFLOW 0|1
 *   EVENTS <n>
 *   ACKS <n>
 *   TELEMETRY <n>
 *   USED <n>
 *   JSON <die komplette JSON-Zeile>
 */
#include "PDS.h"

#include <string>
#include <vector>
#include <cstdio>
#include <cstring>

// Der Telemetrie-Magic ist in PDS.cpp dateilokal (static constexpr) und
// deshalb hier nicht sichtbar. Dass er auf allen drei Seiten gleich ist,
// prüft tools/check_wire_format.py — hier wird er nur zum Überspringen der
// Telemetriepakete gebraucht.
static constexpr uint32_t TELEMETRY_MAGIC = 0xDEADBEEF;
static constexpr int TELEMETRY_BYTES = 8 + 200 * 4;

unsigned long pds_sim_millis = 0;
unsigned long pds_sim_micros = 0;
UsbSerial Serial;
HardwareSerial Serial3;

static float akku = 12.4f;
static int   heading = 42;
static short ballX = 0;

int main() {
    PDS.begin();
    PDS.setFirmwareVersion("Test \"1.2\"");

    PDS.track("Akku_Live", &akku, "V");
    PDS.track("Heading_Live", &heading, "°");
    PDS.bind("Ball_X_Live", &ballX, 30, "cm");
    PDS.plot("Direkt", 1.0f, "%");
    PDS.enableSelfDiagnostics();

    // Ereignisse und Logzeilen in die Warteschlange legen
    PDS.event("Ball verloren", 3.5f);
    PDS.log("Kalibrierung fertig");
    PDS.warn("Akku schwach: %.1f V", 10.9);
    PDS.error("Sensor %d antwortet nicht", 3);

    PDS.announceChannelNames();

    // 12 s simulierte Laufzeit: reicht für den Deskriptor (ein Chunk je
    // 20 ms), für alle Ereignisse, für mehrere Ack-Pakete (2 Hz) und für
    // mindestens eine automatische Wiederholung des Deskriptors (5 s).
    for (int i = 0; i < 1200; i++) {
        PDS.update();
        pds_sim_advance(10);
    }

    // ── Uplink-Strom auseinandersortieren ─────────────────────────────────
    const std::vector<uint8_t>& tx = Serial3.tx;
    std::string first_json, current;
    int chunks_seen = 0, first_chunks = 0, descriptors = 0;
    int events = 0, acks = 0, telemetry = 0;
    int expected = -1;

    size_t i = 0;
    while (i + 4 <= tx.size()) {
        uint32_t magic;
        memcpy(&magic, &tx[i], 4);

        if (magic == TELEMETRY_MAGIC) {
            telemetry++;
            i += TELEMETRY_BYTES;
        } else if (magic == CHANNEL_DESC_MAGIC) {
            if (i + CHANNEL_DESC_CHUNK_HEADER_BYTES > tx.size()) break;
            const int idx = tx[i + 4];
            const int cnt = tx[i + 5];
            const int len = tx[i + 6];
            if (idx == 0) { current.clear(); chunks_seen = 0; expected = cnt; }
            if (idx != chunks_seen || cnt != expected) {
                fprintf(stderr, "FEHLER: Chunk %d/%d kam ausser der Reihe "
                                "(erwartet %d/%d)\n", idx, cnt, chunks_seen, expected);
                return 2;
            }
            current.append((const char*)&tx[i + CHANNEL_DESC_CHUNK_HEADER_BYTES], len);
            chunks_seen++;
            if (chunks_seen == expected) {
                descriptors++;
                if (first_json.empty()) { first_json = current; first_chunks = chunks_seen; }
                else if (current != first_json) {
                    fprintf(stderr, "FEHLER: Wiederholter Deskriptor weicht ab\n");
                    return 2;
                }
            }
            i += CHANNEL_DESC_CHUNK_HEADER_BYTES + len;
        } else if (magic == PDS_EVENT_MAGIC) {
            if (i + PDS_EVENT_HEADER_BYTES > tx.size()) break;
            const int len = tx[i + 14];
            if (tx[i + 12] > 1 || tx[i + 13] > 2 || tx[i + 15] != 0
                    || len > PDS_EVENT_TEXT_MAX) {
                fprintf(stderr, "FEHLER: unplausibler Ereignis-Kopf an Offset %zu\n", i);
                return 2;
            }
            events++;
            i += PDS_EVENT_HEADER_BYTES + len;
        } else if (magic == PARAM_ACK_MAGIC) {
            acks++;
            i += PARAM_ACK_PACKET_BYTES;
        } else {
            fprintf(stderr, "FEHLER: unbekanntes Magic 0x%08X an Offset %zu\n",
                    (unsigned)magic, i);
            return 2;
        }
    }

    printf("CHUNKS %d\n", first_chunks);
    printf("DESCRIPTORS %d\n", descriptors);
    printf("JSONLEN %zu\n", first_json.size());
    printf("OVERFLOW %d\n", PDS.descriptorTruncated() ? 1 : 0);
    printf("EVENTS %d\n", events);
    printf("ACKS %d\n", acks);
    printf("TELEMETRY %d\n", telemetry);
    printf("USED %u\n", (unsigned)PDS.usedChannels());
    printf("JSON %s\n", first_json.c_str());
    return 0;
}
