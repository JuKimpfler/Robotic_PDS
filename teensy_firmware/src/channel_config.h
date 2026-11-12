#pragma once
#include <Arduino.h>
#include "params.h"   // PARAM_*_COUNT und die Strukturen ChannelNameDef/ParamDef/OverlayDef

/* ============================================================
 *  channel_config.h — die EINZIGE Datei, die man von Hand pflegt
 * ============================================================
 *
 *  Der Teensy ist die Quelle der Wahrheit fuer die komplette Oberflaeche:
 *  beim Boot baut PDS.cpp aus dieser Datei einen JSON-Deskriptor und schickt
 *  ihn ueber UART_DBG -> RPi Zero -> UDP -> GUI. Die GUI uebernimmt daraus
 *
 *      * die Kanalnamen und -einheiten fuer Tabelle und Plotter,
 *      * den kompletten Aufbau des Parameter-Tabs (Name, Bedienelement,
 *        Wertebereich, Schrittweite, Gruppe),
 *      * alle Anzeige-Elemente der Systemansicht (Overlays),
 *
 *  und SPEICHERT das dauerhaft auf dem Raspberry Pi (siehe
 *  rpi5_monitor/64Bit_Version/runtime_config/) — nach einem Neustart der GUI
 *  steht also alles sofort wieder da, auch ohne eingeschalteten Roboter.
 *
 *  ── MUSS ICH DAS AUSFUELLEN? ────────────────────────────────────────────
 *  Nein. Diese Datei darf komplett leer bleiben, und man kann sie sogar
 *  ganz weglassen:
 *    * Debug-Kanaele benennt man am einfachsten direkt im Sketch:
 *          PDS.plot("Ball_X", ballX);      // Kanal wird automatisch vergeben
 *          PDS.track("Akku", &akkuVolt);   // einmal in setup()
 *          PDS.bind(12, &ballX, "Ball_X"); // fester Kanal, wenn man will
 *    * Nicht benannte Kanaele heissen in der GUI weiterhin "Var_042".
 *
 *  Hier eintragen lohnt sich fuer:
 *    * Parameter (die kommen von der GUI — der Sketch kann sie nicht
 *      "beim Schreiben" benennen)
 *    * Overlays (Gauges, Feldansicht, Tabellen, Textblöcke)
 *    * Kanaele, die tief in fremdem Library-Code geschrieben werden
 * ============================================================ */


// ══════════════════════════════════════════════════════════════════════════
//  1) Parameter (GUI -> Teensy) — Name, Bedienelement und Wertebereich
// ══════════════════════════════════════════════════════════════════════════
//  Was hier steht, baut die GUI im Parameter-Tab exakt so auf.
//  Im Sketch danach:   PDS.param("Kp_Heading")   statt   PDS.param(0)
//
//  Felder:  index, name, widget, min, max, step, default, gruppe [, momentary]
//  widget:  "slider" | "number"      (Floats)
//           "toggle" | "button"      (Bools; button + momentary = Taster)

static const ParamDef PARAM_SLOW_FLOATS[] = {
    // {  0, "Kp_Heading",  "slider",   0.0f,  10.0f, 0.05f,  2.5f, "Regler" },
    // {  1, "Ki_Heading",  "slider",   0.0f,   5.0f, 0.01f,  0.2f, "Regler" },
    // {  2, "Kd_Heading",  "slider",   0.0f,   5.0f, 0.01f,  0.8f, "Regler" },
    // {  3, "Max_Speed",   "number",   0.0f, 100.0f, 1.0f,  60.0f, "Fahren" },
};
static constexpr size_t PARAM_SLOW_FLOATS_COUNT =
    sizeof(PARAM_SLOW_FLOATS) / sizeof(PARAM_SLOW_FLOATS[0]);

static const ParamDef PARAM_SLOW_BOOLS[] = {
    // {  0, "Motoren_frei", "toggle", 0, 1, 1, 0, "Schalter" },
    // {  1, "Not_Aus",      "button", 0, 1, 1, 0, "Schalter", true },   // Taster
};
static constexpr size_t PARAM_SLOW_BOOLS_COUNT =
    sizeof(PARAM_SLOW_BOOLS) / sizeof(PARAM_SLOW_BOOLS[0]);

static const ParamDef PARAM_FAST_FLOATS[] = {
    // Die 5 Echtzeit-Kanaele (Joystick / PS4-Controller / Tastatur).
    // Standardbelegung siehe rpi5_monitor/.../bridge/controller_bridge.py:
    // {  0, "Joystick_X", "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    // {  1, "Joystick_Y", "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    // {  2, "Rotation",   "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    // {  3, "Speed",      "slider",    0.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    // {  4, "Dribbler",   "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
};
static constexpr size_t PARAM_FAST_FLOATS_COUNT =
    sizeof(PARAM_FAST_FLOATS) / sizeof(PARAM_FAST_FLOATS[0]);


// ══════════════════════════════════════════════════════════════════════════
//  2) Joysticks im Parameter-Tab (je zwei Parameter zu einem Pad gebuendelt)
// ══════════════════════════════════════════════════════════════════════════
//  Felder: name, source ("fast"|"slow"), x_index, y_index,
//          x_min, x_max, y_min, y_max, return_to_center

static const JoystickDef PARAM_JOYSTICKS[] = {
    // { "Fahrtrichtung", "fast", 0, 1, -100.0f, 100.0f, -100.0f, 100.0f, true },
};
static constexpr size_t PARAM_JOYSTICKS_COUNT =
    sizeof(PARAM_JOYSTICKS) / sizeof(PARAM_JOYSTICKS[0]);


// ══════════════════════════════════════════════════════════════════════════
//  3) Feste Namen (+ Einheiten) fuer Debug-Kanaele — optional
// ══════════════════════════════════════════════════════════════════════════
//  Nur noetig fuer Kanaele, die NICHT ueber plot()/track()/Channel(...,name)
//  im Sketch benannt werden. Hier eingetragene Kanaele werden von der
//  Auto-Vergabe (plot()/track()) uebersprungen.
//  Die Einheit ist optional und erscheint in Tabelle/Plotter hinter dem Wert.

static const ChannelNameDef CHANNEL_NAMES[] = {
    { 0, "Main_00", ""}, { 1, "Akku_V", "V"},
    { 2, "Main_02", ""}, { 3, "Main_03", ""},
    { 4, "Main_04", ""}, { 5, "Heading", "deg"},
    { 6, "Main_06", ""}, { 7, "Main_07", ""},
    { 8, "Main_08", ""}, { 9, "Main_09", ""},
    {10, "Main_10", ""}, {11, "Main_11", ""},
    {12, "Main_12", ""}, {13, "Main_13", ""},
    {14, "Main_14", ""}, {15, "Main_15", ""},
    {16, "Position_X", "cm"}, {17, "Position_Y", "cm"},
    {18, "Position_Quality", ""}, {19, "Main_19", ""},
    {20, "Motor_VL_Soll", "%"}, {21, "Motor_VR_Soll", "%"},
    {22, "Motor_HL_Soll", "%"}, {23, "Motor_HR_Soll", "%"},
    {24, "Motor_DR_Soll", "%"}, {25, "Motor_VL_Ist", "%"},
    {26, "Motor_VR_Ist", "%"}, {27, "Motor_HL_Ist", "%"},
    {28, "Motor_HR_Ist", "%"}, {29, "Motor_DR_Ist", "%"},
    {30, "Main_30", ""}, {31, "Main_31", ""},
    {32, "Main_32", ""}, {33, "Main_33", ""},
    {34, "Main_34", ""},
    {35, "Line_01", ""}, {36, "Line_02", ""}, {37, "Line_03", ""},
    {38, "Line_04", ""}, {39, "Line_05", ""}, {40, "Line_06", ""},
    {41, "Line_07", ""}, {42, "Line_08", ""}, {43, "Line_09", ""},
    {44, "Line_10", ""}, {45, "Line_11", ""}, {46, "Line_12", ""},
    {47, "Line_13", ""}, {48, "Line_14", ""}, {49, "Line_15", ""},
    {50, "Line_16", ""}, {51, "Line_17", ""}, {52, "Line_18", ""},
    {53, "Line_19", ""}, {54, "Line_20", ""}, {55, "Line_21", ""},
    {56, "Line_22", ""}, {57, "Line_23", ""}, {58, "Line_24", ""},
    {59, "Line_25", ""}, {60, "Line_26", ""}, {61, "Line_27", ""},
    {62, "Line_28", ""}, {63, "Line_29", ""}, {64, "Line_30", ""},
    {65, "Line_31", ""}, {66, "Line_32", ""}, {67, "Line_33", ""},
    {68, "Line_34", ""}, {69, "Line_35", ""}, {70, "Line_36", ""},
    {71, "Line_37", ""}, {72, "Line_38", ""}, {73, "Line_39", ""},
    {74, "Line_40", ""}, {75, "Line_41", ""}, {76, "Line_42", ""},
    {77, "Line_43", ""}, {78, "Line_44", ""}, {79, "Line_45", ""},
    {80, "Line_46", ""}, {81, "Line_47", ""}, {82, "Line_48", ""},
    {83, "Line_49", ""}, {84, "Line_50", ""},
    {85, "IR_01", ""}, {86, "IR_02", ""}, {87, "IR_03", ""},
    {88, "IR_04", ""}, {89, "IR_05", ""}, {90, "IR_06", ""},
    {91, "IR_07", ""}, {92, "IR_08", ""}, {93, "IR_09", ""},
    {94, "IR_10", ""}, {95, "IR_11", ""}, {96, "IR_12", ""},
    {97, "IR_13", ""}, {98, "IR_14", ""}, {99, "IR_15", ""},
    {100, "IR_16", ""},
    {101, "Switch_1", ""}, {102, "Switch_2", ""}, {103, "Switch_3", ""},
    {104, "Switch_4", ""}, {105, "Switch_5", ""}, {106, "START", ""},
    {107, "RCJ", ""}, {108, "RCJ_OFF", ""}, {109, "RCJ_OK", ""},
    {110, "Button_1", ""}, {111, "Button_2", ""}, {112, "Button_3", ""},
    {113, "Button_4", ""}, {114, "Button_5", ""},
};
static constexpr size_t CHANNEL_NAMES_COUNT = sizeof(CHANNEL_NAMES) / sizeof(CHANNEL_NAMES[0]);


// ══════════════════════════════════════════════════════════════════════════
//  4) Overlays — was die Systemansicht der GUI anzeigt
// ══════════════════════════════════════════════════════════════════════════
//  `group` = Bild-/Widget-Gruppe 1..4 (entspricht bild/Bild1.png ... Bild4.png).
//
//  type        | benutzt                          | Bedeutung
//  ------------|----------------------------------|---------------------------
//  "text"      | channel, x_pct, y_pct            | EIN Wert als Text auf dem Bild
//  "textgrid"  | x_pct, y_pct, extra              | VIELE Werte als Raster (s. u.)
//  "gauge"     | channel, min_val, max_val        | Balkenanzeige
//  "rotation"  | channel, max_val                 | Drehrate/Winkel als Zeiger
//  "vector"    | channel(=Winkel), channel2(=Betrag), max_val
//  "table"     | extra = Kanalliste "0-9,15,20-22"| Wertetabelle
//  "bodies"    | extra = "key=value;..."          | Spielfeld mit 2 Objekten
//
//  ── "textgrid": viele Werte mit EINER Zeile aufs Bild legen ──────────────
//  Genau dafuer gedacht, dass man bei 30 Messwerten nicht 30 Overlays mit je
//  eigener x/y-Position pflegen muss. Angegeben wird nur die linke obere Ecke
//  (x_pct/y_pct); den Rest legt die GUI selbst aus.
//
//      extra = "channels=0-11,20,25-27;cols=2;dx=22;dy=5;labels=1"
//
//        channels  Kanalliste, Bereiche mit '-' (PFLICHT)
//        cols      Spalten (Default 1)
//        dx        Spaltenabstand in % der Bildbreite (Default 20)
//        dy        Zeilenabstand in % der Bildhoehe   (Default 4.5)
//        labels    1 = "Name: Wert" (Default), 0 = nur der Wert
//
//  ── "bodies": Spielfeld-Draufsicht ──────────────────────────────────────
//  Koordinatensystem (RoboCup Junior Soccer, Angaben in ZENTIMETERN):
//      x =    0..180 cm, steigend nach OSTEN
//      y =    0..240 cm, steigend nach NORDEN
//  Die GUI stellt das Feld um 90 Grad nach Osten gedreht dar (Querformat):
//  die Nordachse (y) laeuft auf dem Bildschirm nach RECHTS, die Ostachse (x)
//  nach UNTEN. Das passt zum 13"-Querformat-Touchscreen.
//
//      extra = "field_x_cm=180;field_y_cm=240;"
//              "body1_label=Ball;body1_color=#ff9800;body1_diameter=7;"
//              "body1_channel_x=0;body1_channel_y=1;"
//              "body2_label=Roboter;body2_color=#4ec9b0;body2_diameter=18;"
//              "body2_channel_x=2;body2_channel_y=3;body2_channel_angle=4"
//
//  Durchmesser ebenfalls in cm. `body*_channel_diameter` kann einen Kanal
//  angeben, der den Durchmesser zur Laufzeit liefert (z. B. Ballgroesse aus
//  der Kamera). Nicht benutzte Kanaele einfach weglassen.

#define PDS_TEXT(g, label, ch, x, y) \
    { g, "text", label, ch, -1, 0.0f, 0.0f, x##f, y##f }

static const OverlayDef CHANNEL_OVERLAYS[] = {
    // Mainboard: compact key values plus a complete table (0..34).
    PDS_TEXT(1, "Heading", 5, 46.0, 16.0),
    PDS_TEXT(1, "Akku V", 1, 46.0, 82.0),
    PDS_TEXT(1, "Pos X", 16, 8.0, 18.0),
    PDS_TEXT(1, "Pos Y", 17, 8.0, 23.0),
    PDS_TEXT(1, "Pos Guete", 18, 8.0, 28.0),
    { 1, "gauge", "Akku-Spannung", 1, -1, 0.0f, 16.8f },
    { 1, "gauge", "Motor VL Soll", 20, -1, -100.0f, 100.0f },
    { 1, "gauge", "Motor VR Soll", 21, -1, -100.0f, 100.0f },
    { 1, "gauge", "Motor HL Soll", 22, -1, -100.0f, 100.0f },
    { 1, "gauge", "Motor HR Soll", 23, -1, -100.0f, 100.0f },
    { 1, "gauge", "Motor DR Soll", 24, -1, -100.0f, 100.0f },
    { 1, "rotation", "Motor VL Ist", 25, -1, 0.0f, 100.0f },
    { 1, "rotation", "Motor VR Ist", 26, -1, 0.0f, 100.0f },
    { 1, "rotation", "Motor HL Ist", 27, -1, 0.0f, 100.0f },
    { 1, "rotation", "Motor HR Ist", 28, -1, 0.0f, 100.0f },
    { 1, "rotation", "Motor DR Ist", 29, -1, 0.0f, 100.0f },
    { 1, "table", "Mainboard / System", -1, -1, 0.0f, 0.0f,
      -1.0f, -1.0f, "0-34" },

    // IR ring: IR01 is at twelve o'clock, then clockwise.
    PDS_TEXT(2, "IR01", 85, 58.2, 8.8), PDS_TEXT(2, "IR02", 86, 73.3, 15.1),
    PDS_TEXT(2, "IR03", 87, 84.9, 26.7), PDS_TEXT(2, "IR04", 88, 91.2, 41.8),
    PDS_TEXT(2, "IR05", 89, 91.2, 58.2), PDS_TEXT(2, "IR06", 90, 84.9, 73.3),
    PDS_TEXT(2, "IR07", 91, 73.3, 84.9), PDS_TEXT(2, "IR08", 92, 58.2, 91.2),
    PDS_TEXT(2, "IR09", 93, 41.8, 91.2), PDS_TEXT(2, "IR10", 94, 26.7, 84.9),
    PDS_TEXT(2, "IR11", 95, 15.1, 73.3), PDS_TEXT(2, "IR12", 96, 8.8, 58.2),
    PDS_TEXT(2, "IR13", 97, 8.8, 41.8), PDS_TEXT(2, "IR14", 98, 15.1, 26.7),
    PDS_TEXT(2, "IR15", 99, 26.7, 15.1), PDS_TEXT(2, "IR16", 100, 41.8, 8.8),
    { 2, "table", "16 IR-Sensoren", -1, -1, 0.0f, 0.0f,
      -1.0f, -1.0f, "85-100" },

    // Line sensors: L01 is at twelve o'clock, then clockwise.
    PDS_TEXT(3, "L01", 35, 50.0, 8.0), PDS_TEXT(3, "L02", 36, 55.3, 8.3),
    PDS_TEXT(3, "L03", 37, 60.4, 9.3), PDS_TEXT(3, "L04", 38, 65.5, 10.9),
    PDS_TEXT(3, "L05", 39, 70.2, 13.2), PDS_TEXT(3, "L06", 40, 74.7, 16.0),
    PDS_TEXT(3, "L07", 41, 78.8, 19.4), PDS_TEXT(3, "L08", 42, 82.4, 23.2),
    PDS_TEXT(3, "L09", 43, 85.5, 27.5), PDS_TEXT(3, "L10", 44, 88.0, 32.1),
    PDS_TEXT(3, "L11", 45, 89.9, 37.0), PDS_TEXT(3, "L12", 46, 91.3, 42.1),
    PDS_TEXT(3, "L13", 47, 91.9, 47.4), PDS_TEXT(3, "L14", 48, 91.9, 52.6),
    PDS_TEXT(3, "L15", 49, 91.3, 57.9), PDS_TEXT(3, "L16", 50, 89.9, 63.0),
    PDS_TEXT(3, "L17", 51, 88.0, 67.9), PDS_TEXT(3, "L18", 52, 85.5, 72.5),
    PDS_TEXT(3, "L19", 53, 82.4, 76.8), PDS_TEXT(3, "L20", 54, 78.8, 80.6),
    PDS_TEXT(3, "L21", 55, 74.7, 84.0), PDS_TEXT(3, "L22", 56, 70.2, 86.8),
    PDS_TEXT(3, "L23", 57, 65.5, 89.1), PDS_TEXT(3, "L24", 58, 60.4, 90.7),
    PDS_TEXT(3, "L25", 59, 55.3, 91.7), PDS_TEXT(3, "L26", 60, 50.0, 92.0),
    PDS_TEXT(3, "L27", 61, 44.7, 91.7), PDS_TEXT(3, "L28", 62, 39.6, 90.7),
    PDS_TEXT(3, "L29", 63, 34.5, 89.1), PDS_TEXT(3, "L30", 64, 29.8, 86.8),
    PDS_TEXT(3, "L31", 65, 25.3, 84.0), PDS_TEXT(3, "L32", 66, 21.2, 80.6),
    PDS_TEXT(3, "L33", 67, 17.6, 76.8), PDS_TEXT(3, "L34", 68, 14.5, 72.5),
    PDS_TEXT(3, "L35", 69, 12.0, 67.9), PDS_TEXT(3, "L36", 70, 10.1, 63.0),
    PDS_TEXT(3, "L37", 71, 8.7, 57.9), PDS_TEXT(3, "L38", 72, 8.1, 52.6),
    PDS_TEXT(3, "L39", 73, 8.1, 47.4), PDS_TEXT(3, "L40", 74, 8.7, 42.1),
    PDS_TEXT(3, "L41", 75, 10.1, 37.0), PDS_TEXT(3, "L42", 76, 12.0, 32.1),
    PDS_TEXT(3, "L43", 77, 14.5, 27.5), PDS_TEXT(3, "L44", 78, 17.6, 23.2),
    PDS_TEXT(3, "L45", 79, 21.2, 19.4), PDS_TEXT(3, "L46", 80, 25.3, 16.0),
    PDS_TEXT(3, "L47", 81, 29.8, 13.2), PDS_TEXT(3, "L48", 82, 34.5, 10.9),
    PDS_TEXT(3, "L49", 83, 39.6, 9.3), PDS_TEXT(3, "L50", 84, 44.7, 8.3),
    { 3, "table", "50 Linien-Sensoren", -1, -1, 0.0f, 0.0f,
      -1.0f, -1.0f, "35-84" },

    // Switchboard: all five switches, four status lines and five buttons.
    PDS_TEXT(4, "SW1", 101, 65.0, 49.0), PDS_TEXT(4, "SW2", 102, 73.0, 49.0),
    PDS_TEXT(4, "SW3", 103, 81.0, 49.0), PDS_TEXT(4, "SW4", 104, 89.0, 49.0),
    PDS_TEXT(4, "SW5", 105, 97.0, 49.0), PDS_TEXT(4, "BTN1", 110, 39.0, 31.0),
    PDS_TEXT(4, "BTN2", 111, 49.0, 31.0), PDS_TEXT(4, "BTN3", 112, 59.0, 31.0),
    PDS_TEXT(4, "BTN4", 113, 69.0, 31.0), PDS_TEXT(4, "BTN5", 114, 79.0, 31.0),
    PDS_TEXT(4, "START", 106, 43.0, 17.0), PDS_TEXT(4, "RCJ", 107, 43.0, 74.0),
    PDS_TEXT(4, "RCJ OFF", 108, 13.0, 17.0), PDS_TEXT(4, "RCJ OK", 109, 13.0, 74.0),
    { 4, "table", "Schalter und Taster", -1, -1, 0.0f, 0.0f,
      -1.0f, -1.0f, "101-114" },

    // Field view uses the position and heading channels already shown on Bild 1.
    { 5, "bodies", "Roboterposition", -1, -1, 0.0f, 0.0f,
      -1.0f, -1.0f,
      "field_x_cm=180;field_y_cm=240;goal_width_cm=45;goal_depth_cm=10;"
      "show_image=1;body1_label=Roboter;body1_color=#4ec9b0;body1_diameter=18;"
      "body1_channel_x=16;body1_channel_y=17;body1_channel_angle=5;"
      "body2_label=Ball;body2_color=#f0c060;body2_diameter=7" },
};
#undef PDS_TEXT
static constexpr size_t CHANNEL_OVERLAYS_COUNT = sizeof(CHANNEL_OVERLAYS) / sizeof(CHANNEL_OVERLAYS[0]);


// ══════════════════════════════════════════════════════════════════════════
//  5) Einstellungen der OBERFLAECHE, die der Roboter vorgibt
// ══════════════════════════════════════════════════════════════════════════
//  Derselbe Punktpfad wie in der settings.json der GUI. Was hier steht,
//  reist im Deskriptor mit, wird auf dem Raspberry Pi dauerhaft gespeichert
//  und gilt damit auch beim naechsten Start ohne eingeschalteten Roboter.
//
//  Der Typ ergibt sich aus dem geschriebenen Wert:
//      { "ui.dark",                true      }   Wahrheitswert
//      { "ui.fontScale",           1.2f      }   Zahl
//      { "plotter.historySeconds", 20        }   Zahl (ganz)
//      { "theme.colors.dark.bg",   "#101010" }   Text/Farbe
//
//  ── Was geht (Auszug aus settings.json — es gilt JEDER Schluessel) ──────
//    ui.dark  ui.fontScale  ui.kiosk  ui.keyboardControl  ui.startTab
//    battery.enabled  battery.channel  battery.warn_below
//    battery.critical_below  battery.hold_seconds
//    ranges.fontScale.min|max|step   (Grenzen der Bedienelemente)
//    theme.fontSize.base|table|large|small|xlarge   theme.touchTargetMin
//    theme.spacing.xs|s|m|l          theme.radius.s|m|l
//    theme.colors.dark.<name>        theme.colors.light.<name>
//    window.fullscreen  window.width  window.height  window.headerHeight
//    plotter.historySeconds  plotter.defaultPoints  plotter.maxCurves
//    plotter.curveColors.0 .. .7     plotter.markerColors.0 .. .2
//    params.undoDepth  params.spinBoxFactor
//    diagnostics.eventLogMax
//    controller.deadzone  controller.axis_left_x  controller.button_r1  ...
//
//  ── Was NICHT geht ─────────────────────────────────────────────────────
//    "network.*" — eine falsche IP in der Firmware wuerde genau die Leitung
//    kappen, ueber die man sie korrigieren muesste. Die GUI verwirft diesen
//    Abschnitt aus dem Deskriptor grundsaetzlich.
//
//  Unsinnige Werte kosten hoechstens IHR Feld: die GUI prueft jeden Wert
//  gegen ihren eigenen Standardwert und behaelt bei einem Typfehler den
//  eigenen (siehe rpi5_monitor/64Bit_Version/app_settings.py).
//
//  Dasselbe geht auch im Sketch:  PDS.setting("ui.dark", true);
//  Der Bediener kann die Uebernahme im Diagnose-Tab abschalten.

#define PDS_HAS_GUI_SETTINGS 1
static const SettingDef GUI_SETTINGS[] = {
    // { "ui.dark",                  true      },
    // { "ui.fontScale",             1.1f      },
    // { "ui.startTab",              2         },   // 2 = Systemansicht
    // { "battery.enabled",          true      },
    // { "battery.channel",          10        },
    // { "battery.warn_below",       11.5f     },
    // { "battery.critical_below",   10.8f     },
    // { "plotter.historySeconds",   20        },
    // { "plotter.curveColors.0",    "#00ff88" },
    // { "theme.colors.dark.bg",     "#101010" },
};
static constexpr size_t GUI_SETTINGS_COUNT =
    sizeof(GUI_SETTINGS) / sizeof(GUI_SETTINGS[0]);
