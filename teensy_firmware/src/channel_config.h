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
    // {10, "Akku_Spannung", "V"},
    // {11, "System_Temp",   "°C"},
    // {12, "Ball_X",        "cm"},
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

static const OverlayDef CHANNEL_OVERLAYS[] = {
    // { 1, "gauge",    "Akku",       10, -1,  0.0f, 16.8f },
    // { 1, "rotation", "Heading",     5, -1,  0.0f, 360.0f },
    // { 1, "vector",   "Fahrt",       6,  7,  0.0f, 100.0f },
    // { 1, "textgrid", "Sensoren",   -1, -1,  0.0f, 0.0f, 4.0f, 6.0f,
    //     "channels=0-11;cols=2;dx=24;dy=5" },
    // { 2, "bodies",   "Spielfeld",  -1, -1,  0.0f, 0.0f, -1.0f, -1.0f,
    //     "field_x_cm=180;field_y_cm=240;"
    //     "body1_label=Ball;body1_color=#ff9800;body1_diameter=7;"
    //     "body1_channel_x=0;body1_channel_y=1;"
    //     "body2_label=Roboter;body2_color=#4ec9b0;body2_diameter=18;"
    //     "body2_channel_x=2;body2_channel_y=3;body2_channel_angle=4" },
};
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
