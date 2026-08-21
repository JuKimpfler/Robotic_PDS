#pragma once
#include <Arduino.h>
#include "params.h"   // PARAM_SLOW_FLOAT_COUNT / PARAM_SLOW_BOOL_COUNT / PARAM_FAST_FLOAT_COUNT

/* ============================================================
 *  channel_config.h — die EINZIGE Datei, die man von Hand pflegt
 * ============================================================
 *
 *  Hier stehen:
 *    1. Namen fuer Parameter, die von der GUI kommen  (PFLICHT, wenn man
 *       PDS.param("Kp") statt PDS.param(3) schreiben will)
 *    2. Overlays: welcher Kanal in der GUI wo/wie angezeigt wird
 *    3. Optional: feste Namen fuer Debug-Kanaele
 *
 *  Beim Boot baut PDS.cpp daraus ein JSON-Deskriptor-Paket und schickt es
 *  ueber UART_DBG -> RPi Zero -> UDP -> GUI. Dort landen die Namen in der
 *  Kanaltabelle, im Param-Tab und in den Grafik-Overlays.
 *
 *  ── MUSS ICH DAS AUSFUELLEN? ────────────────────────────────────────────
 *  Nein. Diese Datei darf komplett leer bleiben:
 *    * Debug-Kanaele benennt man am einfachsten direkt im Sketch mit
 *          PDS.plot("Ball_X", ballX);      // Kanal wird automatisch vergeben
 *          PDS.track("Akku", &akkuVolt);   // einmal in setup()
 *      Diese Namen landen genauso im Deskriptor wie die hier eingetragenen.
 *    * Nicht benannte Kanaele heissen in der GUI weiterhin "Var_042".
 *
 *  Hier eintragen lohnt sich fuer:
 *    * Param-Namen (kommen von der GUI, koennen im Sketch nicht "beim
 *      Schreiben" benannt werden)
 *    * Overlays (Gauges/Feldansicht/Tabellen)
 *    * Kanaele, die tief in Library-Code geschrieben werden
 * ============================================================ */

// ══════════════════════════════════════════════════════════════════════════
//  1) Namen fuer den Param-Downlink (GUI -> Teensy)
// ══════════════════════════════════════════════════════════════════════════
//  Reihenfolge = Index. Nicht belegte Plaetze einfach mit nullptr auffuellen
//  oder das Array frueher enden lassen (der Rest wird automatisch nullptr).
//
//  Danach im Sketch:  PDS.param("Kp_Heading")  statt  PDS.param(0)
//  Und in der GUI steht derselbe Name am Regler.

static const char* const PARAM_SLOW_FLOAT_NAMES[PARAM_SLOW_FLOAT_COUNT] = {
    // Index 0..49 — Beispiel:
    // "Kp_Heading",     // 0
    // "Ki_Heading",     // 1
    // "Kd_Heading",     // 2
    // "Max_Speed",      // 3
};

static const char* const PARAM_SLOW_BOOL_NAMES[PARAM_SLOW_BOOL_COUNT] = {
    // Index 0..49 — Beispiel:
    // "Motoren_frei",   // 0
    // "Dribbler_an",    // 1
};

static const char* const PARAM_FAST_FLOAT_NAMES[PARAM_FAST_FLOAT_COUNT] = {
    // Index 0..4 — die 5 Echtzeit-Kanaele (Joystick / PS4-Controller).
    // Die Standardbelegung des Controllers (siehe controller_bridge.py):
    // "Joystick_X",     // 0  linker Stick links/rechts
    // "Joystick_Y",     // 1  linker Stick hoch/runter
    // "Rotation",       // 2  rechter Stick links/rechts
    // "Speed",          // 3  R2-Trigger
    // "Dribbler",       // 4  R1 / L1
};


// ══════════════════════════════════════════════════════════════════════════
//  2) Feste Namen fuer Debug-Kanaele (optional)
// ══════════════════════════════════════════════════════════════════════════
//  Nur noetig fuer Kanaele, die NICHT ueber plot()/track()/Channel(...,name)
//  im Sketch benannt werden — z. B. weil sie tief in fremdem Library-Code
//  geschrieben werden. Hier eingetragene Kanaele werden von der
//  Auto-Vergabe (plot()/track()) uebersprungen.

struct ChannelNameDef {
    uint8_t     index;
    const char* name;
};

static const ChannelNameDef CHANNEL_NAMES[] = {
    // {10, "Akku_Spannung"},
    // {11, "System_Temp"},
};
static constexpr size_t CHANNEL_NAMES_COUNT = sizeof(CHANNEL_NAMES) / sizeof(CHANNEL_NAMES[0]);


// ══════════════════════════════════════════════════════════════════════════
//  3) Overlays — welcher Kanal wird in der GUI wo angezeigt
// ══════════════════════════════════════════════════════════════════════════
//  `group` = Bild-/Widget-Gruppe 1..4 (entspricht bild/Bild1.png ... Bild4.png).
//
//  type       | benutzt                         | Bedeutung
//  -----------|---------------------------------|------------------------------
//  "text"     | channel, x_pct, y_pct           | Wert als Text auf dem Bild
//  "gauge"    | channel, min_val, max_val       | Balkenanzeige
//  "rotation" | channel, max_val                | Drehrate/Winkel als Zeiger
//  "vector"   | channel(=Winkel), channel2(=Betrag), max_val
//  "table"    | extra = Kanalliste, z. B. "0-9,15,20-22"
//  "bodies"   | extra = "key=value;..."         | Feldansicht mit 2 Objekten
//
//  `extra` fuer "bodies" (Praefixe body1_/body2_):
//      "field_width=2.0;field_height=1.5;"
//      "body1_label=Ball;body1_color=#ffffff;body1_diameter=0.15;"
//      "body1_channel_x=0;body1_channel_y=1;body1_channel_angle=2;"
//      "body2_label=Bot;body2_color=#4ec9b0;body2_diameter=0.4;"
//      "body2_channel_x=3;body2_channel_y=4;body2_channel_angle=5"
//
//  Feldreihenfolge im Initialisierer:
//      group, type, label, channel, channel2, min_val, max_val, x_pct, y_pct, extra

struct OverlayDef {
    uint8_t     group;                 // 1..4 = Bild-/Widget-Gruppe
    const char* type;                  // "text"|"gauge"|"rotation"|"vector"|"table"|"bodies"
    const char* label;
    int16_t     channel  = -1;         // primaerer Kanal (gauge/rotation/text) bzw. Winkel (vector)
    int16_t     channel2 = -1;         // sekundaerer Kanal (vector: Betrag/Speed)
    float       min_val  = 0.0f;
    float       max_val  = 0.0f;
    float       x_pct    = -1.0f;      // nur "text": Position auf dem Bild (0..100, -1 = ungenutzt)
    float       y_pct    = -1.0f;
    const char* extra    = "";
};

static const OverlayDef CHANNEL_OVERLAYS[] = {
    // {1, "gauge",  "Motor L",      0, -1, -5.0f, 5.0f},
    // {1, "gauge",  "Motor R",      1, -1, -5.0f, 5.0f},
    // {1, "text",   "Akku",        10, -1,  0.0f, 0.0f, 10.0f, 15.0f},
    // {1, "table",  "Status 0-9",  -1, -1,  0.0f, 0.0f, -1.0f, -1.0f, "0-9"},
    // {2, "vector", "Fahrtrichtung", 2,  3,  0.0f, 100.0f},
};
static constexpr size_t CHANNEL_OVERLAYS_COUNT = sizeof(CHANNEL_OVERLAYS) / sizeof(CHANNEL_OVERLAYS[0]);
