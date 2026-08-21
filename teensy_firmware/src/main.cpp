/*
 * ============================================================
 *  main.cpp — Beispiel-/Testsketch fuer die PDS-Bibliothek
 * ============================================================
 *
 *  Dieser Sketch ist NICHT der Roboter-Code. Er zeigt in ~40 Zeilen alles,
 *  was die Bibliothek kann, und laesst sich direkt auf einen Teensy 4.0
 *  flashen, um die komplette Kette
 *
 *      Teensy -> RPi Zero -> WLAN -> GUI
 *
 *  zu testen, ohne dass ein Roboter angeschlossen sein muss: die Kanaele
 *  bekommen synthetische Werte (Sinus/Saegezahn), und die von der GUI
 *  gesendeten Parameter werden 1:1 zurueckgespiegelt.
 *
 *  Fuer das echte Roboter-Projekt kopiert man PDS.h, PDS.cpp, params.h und
 *  channel_config.h in dessen src/-Ordner (oder bindet dieses Verzeichnis
 *  ueber lib_deps/lib_extra_dirs ein) und ruft im eigenen Sketch nur noch
 *  PDS.begin() / PDS.update() auf.
 * ============================================================
 */

#include <Arduino.h>
#include "PDS.h"

// Ein paar Beispielwerte des "Roboters". Alles, was hier steht, taucht in
// der GUI auf — entweder per track() (einmal registriert, danach automatisch)
// oder per plot() (bei jedem Schreiben).
float    akkuVolt   = 0.0f;
float    heading    = 0.0f;
bool     ballSicht  = false;
uint32_t loopHz     = 0;

// Werte, die von der GUI kommen (Fernsteuerung/Tuning).
float speedSoll = 0.0f;
float rotSoll   = 0.0f;

static elapsedMillis blinkTimer;
static elapsedMillis statusTimer;
static uint32_t      loopCounter = 0;

void setup() {
    Serial.begin(115200);            // USB-Serial, nur fuer Diagnose
    pinMode(LED_BUILTIN, OUTPUT);

    // ── Das ist alles, was zum Start noetig ist ──────────────────────────
    PDS.begin();

    // Variablen dauerhaft an die GUI binden: ab jetzt werden sie 100x/s
    // automatisch mitgesendet, ohne dass loop() etwas tun muss.
    PDS.track("Akku_Spannung", &akkuVolt);
    PDS.track("Heading",       &heading);
    PDS.track("Ball_sichtbar", &ballSicht);
    PDS.track("Loop_Hz",       &loopHz);

    // Legt die PDS-eigenen Diagnosezaehler (gesendete Pakete, verworfene
    // Pakete, Latenz des Fast-Kanals, Sync-Verluste) auf die letzten sechs
    // Kanaele. Sehr nuetzlich, um Aussetzer direkt in der GUI zu sehen.
    PDS.enableSelfDiagnostics();
}

void loop() {
    loopCounter++;

    // ── 1. Werte von der GUI holen ───────────────────────────────────────
    //  Fast-Kanal (100 Hz): Joystick / PS4-Controller
    speedSoll = PDS.fastParam(3);        // oder PDS.fastParam("Speed"),
    rotSoll   = PDS.fastParam(2);        // sobald channel_config.h Namen hat

    //  Slow-Kanal (2 Hz): Tuning-Parameter und Schalter
    const float maxSpeed   = PDS.param(0);
    const bool  motorenAus = PDS.paramBool(0);

    // ── 2. Not-Aus, wenn die Verbindung weg ist ──────────────────────────
    //  linkOk() ist genau dafuer da: kein Paket von der GUI -> nicht
    //  weiterfahren. Im echten Roboter hier die Motoren stoppen.
    if (!PDS.linkOk() || motorenAus) {
        speedSoll = 0.0f;
        rotSoll   = 0.0f;
    }

    // ── 3. "Roboter" simulieren ──────────────────────────────────────────
    const float t = millis() / 1000.0f;
    akkuVolt  = 12.4f + 0.15f * sinf(t * 0.7f);
    heading   = fmodf(t * 45.0f, 360.0f);
    ballSicht = (fmodf(t, 4.0f) < 2.0f);

    // ── 4. Weitere Werte anzeigen — Kanal wird automatisch vergeben ──────
    PDS.plot("Speed_Soll", speedSoll);
    PDS.plot("Rot_Soll",   rotSoll);
    PDS.plot("Max_Speed",  maxSpeed);
    PDS.plot("Fast_Alter_ms", PDS.fastParamAgeMs());

    // Alternative fuer sehr schnelle Schleifen (Kanalnummer wird einmalig
    // aufgeloest und danach in einer static-Variable gehalten):
    PDS_PLOT("Loop_Counter", loopCounter);

    // ── 5. Genau ein Aufruf pro Schleifendurchlauf ───────────────────────
    PDS.update();

    // ── Diagnose: LED + eine Statuszeile pro Sekunde auf USB-Serial ──────
    if (blinkTimer >= (PDS.linkOk() ? 500 : 100)) {
        blinkTimer = 0;
        digitalWriteFast(LED_BUILTIN, !digitalReadFast(LED_BUILTIN));
    }
    if (statusTimer >= 1000) {
        statusTimer = 0;
        loopHz      = loopCounter;
        loopCounter = 0;
        PDS.printStatus();
    }
}
