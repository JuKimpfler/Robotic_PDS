/*
 * ============================================================
 *  Beispiel-Sketch fuer die PDS-Bibliothek
 * ============================================================
 *  Laeuft unveraendert auf einem Teensy 4.0 ohne weitere Hardware und zeigt
 *  alles, was man im Alltag braucht. In einem echten Roboterprojekt wird
 *  diese Datei nicht mitkompiliert (siehe library.json) — dort ruft der
 *  eigene Sketch einfach PDS.begin() / PDS.update() auf.
 *
 *  Flashen:   pio run -t upload
 *  Beobachten: GUI starten oder `pio device monitor` (USB-Serial)
 * ============================================================
 */

#include <Arduino.h>
#include "PDS.h"

// Beliebige Variablen aus dem Roboter-Code. Einmal gebunden, tauchen sie ab
// da mit 100 Hz in der GUI auf — im loop() muss man sie nicht mehr anfassen.
float  akkuVolt   = 12.4f;
float  ballX      = 0.0f;
float  ballY      = 0.0f;
int    heading    = 0;
bool   dribblerAn = false;

elapsedMillis statusTimer;
elapsedMillis eventTimer;

void setup() {
    Serial.begin(115200);          // USB-Serial, nur fuer Diagnose

    PDS.begin();                   // UART starten, Namen an die GUI melden

    // Version der eigenen Roboter-Firmware — erscheint in der GUI, damit man
    // sieht, welcher Stand auf welchem Roboter laeuft.
    String Version = "v" + String(BUILD_VERSION) + " (Build " + String(BUILD_DATE) + " " + String(BUILD_TIME) + ")";
    PDS.setFirmwareVersion(Version.c_str());

    // ── Variablen an Kanaele binden ───────────────────────────────────────
    PDS.track("Akku",     &akkuVolt, "V");    // Kanal automatisch, mit Einheit
    PDS.track("Heading",  &heading,  "°");
    PDS.track("Dribbler", &dribblerAn);

    // ... oder mit fester Kanalnummer, wenn die GUI-Overlays darauf zeigen:
    PDS.bind("Ball_X", &ballX, 20, "cm");
    PDS.bind("Ball_Y", &ballY, 21, "cm");

    // Diagnosezaehler auf die letzten sechs Kanaele legen (optional).
    PDS.enableSelfDiagnostics();

    // Watchdog: bleibt loop() laenger als 2 s haengen, startet der Teensy neu.
    PDS.enableWatchdog(2000);

    PDS.log("Setup abgeschlossen");
}

void loop() {
    const uint32_t t = millis();

    // ── Fernsteuerung lesen ───────────────────────────────────────────────
    float speed    = PDS.fastParam(3);     // R2-Trigger / Schieberegler
    float rotation = PDS.fastParam(2);

    // Not-Aus: sobald die GUI stumm ist, alles auf 0. Das ist das wichtigste
    // Sicherheitsnetz der ganzen Bibliothek.
    if (!PDS.linkOk()) {
        speed = 0.0f;
        rotation = 0.0f;
    }

    // ── Simulierte Sensorwerte (im echten Projekt: echte Messwerte) ───────
    akkuVolt   = 12.4f + 0.2f * sinf(t / 5000.0f);
    ballX      = 90.0f + 60.0f * sinf(t / 1300.0f);
    ballY      = 120.0f + 80.0f * cosf(t / 1700.0f);
    heading    = (int)((t / 20) % 360);
    dribblerAn = PDS.fastParam(4) > 50.0f;

    // ── Werte direkt anzeigen (Kanal wird automatisch vergeben) ──────────
    PDS.plot("Speed", speed);
    PDS.plot("Rotation", rotation);

    // Fuer sehr heisse Schleifen: identisch, aber ohne jeden Overhead.
    PDS_PLOT("Loop_us", micros() % 1000);

    // ── Ereignisse: senkrechte Marke im Plotter der GUI ──────────────────
    if (eventTimer >= 5000) {
        eventTimer = 0;
        PDS.event("Testmarke", speed);
        if (akkuVolt < 11.0f) PDS.warn("Akku schwach: %.1f V", akkuVolt);
    }

    // ── Eine Zeile Diagnose ueber USB-Serial ─────────────────────────────
    if (statusTimer >= 1000) {
        statusTimer = 0;
        PDS.printStatus();
    }

    PDS.update();   // genau einmal pro loop()
}
