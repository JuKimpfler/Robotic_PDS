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
 * Seit PDS 2.2 kommen drei Abschnitte dazu, die die BLOCKIERFREIHEIT belegen
 * (siehe PDS.h, Abschnitt BLOCKIERFREIHEIT):
 *
 *   Phase 2  Der Deskriptor wird scheibenweise gebaut. Mit laufender Uhr
 *            (pds_sim_micros_step) reicht das Zeitbudget nicht für alles auf
 *            einmal — es MUSS also über mehrere update()-Aufrufe gehen.
 *   Phase 3  Ein abgebrochenes Downlink-Paket darf den Parser nicht
 *            vergiften. Vorher fraß er die erste Hälfte des NÄCHSTEN Pakets
 *            als vermeintliche Nutzlast und legte einen Zufallswert in
 *            fastParam() — bei einem Joystick-Kanal fährt der Roboter davon.
 *   Phase 4  Die Notbremse: ein künstlich überlanges update() muss PDS in
 *            den Sparbetrieb und danach ganz abschalten.
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
 *   SIMMS <ms>        insgesamt simulierte Laufzeit
 *   BUILDUPDATES <n>  update()-Aufrufe für EINEN Deskriptor-Neubau
 *   FASTVALUE <f>     fastParam(0) nach dem abgebrochenen Paket
 *   FASTOK <n>        vollständig empfangene Fast-Pakete danach
 *   RESYNC <n>        wie oft der Parser sich selbst gefangen hat
 *   DEGRADED 0|1      Notbremse: Nebenwege abgeschaltet
 *   PDSOFF 0|1        Notbremse: PDS ganz abgeschaltet
 *   REVIVED 0|1       enable(true) hebt beides wieder auf
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
unsigned long pds_sim_micros_step = 0;
UsbSerial Serial;
HardwareSerial Serial3;

static float akku = 12.4f;
static int   heading = 42;
static short ballX = 0;

// Ein vollständiges Fast-Paket bauen (wie es der RPi Zero schickt).
static void makeFastPacket(uint8_t* out, uint32_t seq, float v0) {
    const uint32_t magic = PARAM_FAST_MAGIC;
    memcpy(out,     &magic, 4);
    memcpy(out + 4, &seq,   4);
    float f[PARAM_FAST_FLOAT_COUNT] = {0};
    f[0] = v0;
    memcpy(out + PARAM_HEADER_BYTES, f, sizeof(f));
}

int main() {
    PDS.begin();
    PDS.setFirmwareVersion("Test \"1.2\"");

    PDS.track("Akku_Live", &akku, "V");
    PDS.track("Heading_Live", &heading, "°");
    PDS.bind("Ball_X_Live", &ballX, 30, "cm");
    PDS.plot("Direkt", 1.0f, "%");
    PDS.enableSelfDiagnostics();

    // Einstellungen der Oberfläche: die Tabelle aus channel_config.h ist
    // schon in begin() eingelesen worden, hier kommt der Weg über den
    // Sketch dazu (überschreibt denselben Schlüssel).
    PDS.setting("ui.fontScale", 1.25f);
    PDS.guiCurveColor(1, "#ff00aa");

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
    // Bis hierher ist der Deskriptor UNVERAENDERT: alle Wiederholungen aus
    // Phase 1 muessen Byte fuer Byte gleich sein (Prueflauf weiter unten).
    const size_t phase1End = Serial3.tx.size();

    // ── Phase 2: der Deskriptor entsteht in Scheiben ─────────────────────
    //  Uhr laufen lassen: jetzt kostet jeder micros()-Aufruf simulierte Zeit,
    //  das Zeitbudget von 400 us ist damit nach wenigen Bauschritten
    //  aufgebraucht und der Bau MUSS sich über mehrere update() verteilen.
    pds_sim_micros_step = 50;
    PDS.setting("ui.kiosk", false);        // erzwingt einen Neubau
    PDS.announceChannelNames();
    int buildUpdates = 0;
    while (!PDS.descriptorReady() && buildUpdates < 2000) {
        PDS.update();
        pds_sim_advance(1);
        buildUpdates++;
    }
    pds_sim_micros_step = 0;

    // Den zweiten Deskriptor noch fertig senden lassen (er darf den
    // Vergleich in der Chunk-Auswertung unten nicht stören, deshalb wird
    // dort nur der ERSTE ausgewertet).
    for (int i = 0; i < 400; i++) {
        PDS.update();
        pds_sim_advance(10);
    }

    // ── Phase 3: abgebrochenes Paket -> Parser fängt sich selbst ─────────
    //  Erst ein halbes Fast-Paket (Magic + halbe Sequenznummer), dann Stille,
    //  dann EIN vollständiges Paket. Ohne den Resync-Timeout verfüttert der
    //  Parser die ersten 20 Bytes des guten Pakets an das abgebrochene und
    //  legt Zufallswerte in fastParam() — genau das darf nicht passieren.
    const uint32_t truncMagic = PARAM_FAST_MAGIC;
    uint8_t trunc[6];
    memcpy(trunc, &truncMagic, 4);
    trunc[4] = 0x11; trunc[5] = 0x22;
    Serial3.feed(trunc, sizeof(trunc));
    PDS.update();
    pds_sim_advance(10);

    for (int i = 0; i < 10; i++) {         // 100 ms Stille -> Resync
        PDS.update();
        pds_sim_advance(10);
    }

    const uint32_t fastBefore = PDS.fastPacketCount();
    uint8_t good[PARAM_FAST_PACKET_BYTES];
    makeFastPacket(good, 4711, 42.5f);
    Serial3.feed(good, sizeof(good));
    PDS.update();
    pds_sim_advance(10);

    const float    fastValue = PDS.fastParam(0);
    const uint32_t fastOk    = PDS.fastPacketCount() - fastBefore;
    const uint32_t resyncs   = PDS.rxResyncCount();

    // ── Phase 4: Notbremse ───────────────────────────────────────────────
    //  Ein update() darf 200 us dauern; die Uhr springt hier je Aufruf um
    //  10 ms weiter. Nach fünf solchen Aufrufen muss der Sparbetrieb stehen,
    //  nach weiteren fünf muss PDS ganz aus sein.
    PDS.setPanicLimit(200, 5);
    pds_sim_micros_step = 5000;            // 2 micros()-Aufrufe = 10 ms
    for (int i = 0; i < 6; i++) { PDS.update(); pds_sim_advance(10); }
    const bool degraded = PDS.degraded();
    for (int i = 0; i < 6; i++) { PDS.update(); pds_sim_advance(10); }
    const bool pdsOff = !PDS.enabled();
    pds_sim_micros_step = 0;
    PDS.enable(true);
    const bool revived = PDS.enabled() && !PDS.degraded();

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
                else if (i < phase1End && current != first_json) {
                    // Nur Phase 1 vergleichen: ab Phase 2 aendert der Test die
                    // Einstellungen und der Deskriptor MUSS sich unterscheiden.
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
    printf("SIMMS %lu\n", (unsigned long)pds_sim_millis);
    printf("BUILDUPDATES %d\n", buildUpdates);
    printf("FASTVALUE %.3f\n", (double)fastValue);
    printf("FASTOK %lu\n", (unsigned long)fastOk);
    printf("RESYNC %lu\n", (unsigned long)resyncs);
    printf("DEGRADED %d\n", degraded ? 1 : 0);
    printf("PDSOFF %d\n", pdsOff ? 1 : 0);
    printf("REVIVED %d\n", revived ? 1 : 0);
    printf("JSON %s\n", first_json.c_str());
    return 0;
}
