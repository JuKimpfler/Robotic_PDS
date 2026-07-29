#pragma once
#include <Arduino.h>
#include "params.h"   // PARAM_SLOW_FLOAT_COUNT / PARAM_SLOW_BOOL_COUNT / PARAM_FAST_FLOAT_COUNT

// ============================================================
//  channel_config.h — EINZIGE Quelle für Kanal-/Param-Namen
//                     und die Overlay-Zuordnung (GUI-Anzeige)
// ============================================================
//  Diese Datei wird vom Nutzer gepflegt. Beim Boot baut PDS.cpp
//  daraus (+ evtl. per bind()/Channel(...,name) registrierten
//  Namen) einmalig ein JSON-Deskriptor-Paket und schickt es über
//  UART_DBG -> RPi Zero -> UDP -> RPi 5, wo die GUI es anzeigt
//  (Kanaltabelle, Param-Tab, Grafik-Overlays).
//
//  Es müssen NICHT alle Indizes belegt werden — nicht benannte
//  Kanäle bekommen GUI-seitig weiterhin den generischen Fallback
//  "Var_NNN".
// ============================================================

// ── Namen für die 200 Debug-Kanäle (nur für Kanäle, die NICHT über
//    bind()/Channel(...,name) im Sketch benannt werden, z. B. Kanäle,
//    die tief in Library-Code geschrieben werden) ──────────────────
struct ChannelNameDef {
    uint8_t     index;
    const char* name;
};

static const ChannelNameDef CHANNEL_NAMES[] = {
    // {10, "Akku_Spannung"},
    // {11, "System_Temp"},
};
static constexpr size_t CHANNEL_NAMES_COUNT = sizeof(CHANNEL_NAMES) / sizeof(CHANNEL_NAMES[0]);

// ── Namen für den Param-Downlink (kommen per UART-RX, nie über
//    einen Schreibaufruf im Sketch — daher hier vollständig gelistet) ─
static const char* const PARAM_SLOW_FLOAT_NAMES[PARAM_SLOW_FLOAT_COUNT] = {
    // Index 0..49, unbelegte Einträge bleiben nullptr -> GUI-Fallback
};

static const char* const PARAM_SLOW_BOOL_NAMES[PARAM_SLOW_BOOL_COUNT] = {
    // Index 0..49
};

static const char* const PARAM_FAST_FLOAT_NAMES[PARAM_FAST_FLOAT_COUNT] = {
    // Index 0..4 (z. B. Joystick-Achsen)
};

// ── Overlay-Zuordnung: welche Kanäle wo angezeigt werden ──────────
//  (Body-Objekte, Gauges, Rotations-/Vektor-Anzeigen, Tabellen).
//  Feldnamen entsprechen 1:1 dem, was die GUI schon aus
//  visuals_overlays.json kennt — `extra` trägt Freitext für Typen
//  mit zu vielen/variablen Feldern:
//    "table"  -> extra = Kanalliste, z. B. "0-9,15,20-22"
//    "bodies" -> extra = "key=value;..."-Liste (Praefixe body1_/body2_,
//                Feldnamen wie in visuals_overlays.json), z. B.
//                "field_width=2.0;field_height=1.5;"
//                "body1_label=Ball;body1_color=#ffffff;body1_diameter=0.15;"
//                "body1_channel_x=0;body1_channel_y=1;body1_channel_angle=2;"
//                "body2_label=Bot;body2_color=#4ec9b0;body2_diameter=0.4;"
//                "body2_channel_x=3;body2_channel_y=4;body2_channel_angle=5"
struct OverlayDef {
    uint8_t     group;                 // 1..4 = Bild-/Widget-Gruppe
    const char* type;                  // "text" | "gauge" | "rotation" | "vector" | "table" | "bodies"
    const char* label;
    int16_t     channel  = -1;         // primärer Kanal (gauge/rotation/text) bzw. Winkel-Kanal (vector)
    int16_t     channel2 = -1;         // sekundärer Kanal (vector: Speed-Kanal)
    float       min_val  = 0.0f;
    float       max_val  = 0.0f;
    float       x_pct    = -1.0f;      // nur "text"-Overlays auf dem Bild (0..100, -1 = ungenutzt)
    float       y_pct    = -1.0f;
    const char* extra    = "";
};

static const OverlayDef CHANNEL_OVERLAYS[] = {
    // {1, "gauge", "Motor L Speed", 0, -1, -5.0f, 5.0f},
    // {1, "text",  "Akku",          10, -1, 0.0f, 0.0f, 10.0f, 15.0f},
    // {1, "table", "Status 0-9",   -1, -1, 0.0f, 0.0f, -1.0f, -1.0f, "0-9"},
};
static constexpr size_t CHANNEL_OVERLAYS_COUNT = sizeof(CHANNEL_OVERLAYS) / sizeof(CHANNEL_OVERLAYS[0]);
