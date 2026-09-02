#pragma once
#include <Arduino.h>
#include "params.h"

/*
 * tools/hostsim/channel_config.h — AUSGEFÜLLTE Testkonfiguration
 * ===============================================================
 * Wird nur vom Host-Test benutzt (tools/desc_json_check.py) und liegt
 * deshalb im Include-Pfad VOR teensy_firmware/src/. Sie enthält absichtlich
 * die unangenehmen Fälle: Anführungszeichen und Backslash im Namen,
 * Umlaute, ein Steuerzeichen, ein leerer Overlay-Typ, sehr lange Texte.
 * Genau daran ist die JSON-Erzeugung schon einmal gescheitert.
 */

static const ParamDef PARAM_SLOW_FLOATS[] = {
    {  0, "Kp_Heading",   "slider",   0.0f,  10.0f, 0.05f,  2.5f, "Regler" },
    {  1, "Ki_Heading",   "slider",   0.0f,   5.0f, 0.01f,  0.2f, "Regler" },
    {  2, "Kd \"quoted\"", "number",  -1.0f,   1.0f, 0.001f, 0.0f, "Regler" },
    {  3, "Pfad\\Test",   "slider",   0.0f, 100.0f, 1.0f,  60.0f, "Fahren" },
    {  4, "Größe_Ö",      "number",   0.0f,   1.0f, 0.01f,  0.5f, "Fahren" },
};
static constexpr size_t PARAM_SLOW_FLOATS_COUNT =
    sizeof(PARAM_SLOW_FLOATS) / sizeof(PARAM_SLOW_FLOATS[0]);

static const ParamDef PARAM_SLOW_BOOLS[] = {
    {  0, "Motoren_frei", "toggle", 0, 1, 1, 0, "Schalter" },
    {  1, "Not_Aus",      "button", 0, 1, 1, 0, "Schalter", true },
};
static constexpr size_t PARAM_SLOW_BOOLS_COUNT =
    sizeof(PARAM_SLOW_BOOLS) / sizeof(PARAM_SLOW_BOOLS[0]);

static const ParamDef PARAM_FAST_FLOATS[] = {
    {  0, "Joystick_X", "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    {  1, "Joystick_Y", "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    {  2, "Rotation",   "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    {  3, "Speed",      "slider",    0.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
    {  4, "Dribbler",   "slider", -100.0f, 100.0f, 1.0f, 0.0f, "Fahren" },
};
static constexpr size_t PARAM_FAST_FLOATS_COUNT =
    sizeof(PARAM_FAST_FLOATS) / sizeof(PARAM_FAST_FLOATS[0]);

static const JoystickDef PARAM_JOYSTICKS[] = {
    { "Fahrtrichtung", "fast", 0, 1, -100.0f, 100.0f, -100.0f, 100.0f, true },
};
static constexpr size_t PARAM_JOYSTICKS_COUNT =
    sizeof(PARAM_JOYSTICKS) / sizeof(PARAM_JOYSTICKS[0]);

static const ChannelNameDef CHANNEL_NAMES[] = {
    {10, "Akku_Spannung", "V"},
    {11, "System_Temp",   "°C"},
    {12, "Steuer\x01Zeichen", ""},
};
static constexpr size_t CHANNEL_NAMES_COUNT = sizeof(CHANNEL_NAMES) / sizeof(CHANNEL_NAMES[0]);

static const OverlayDef CHANNEL_OVERLAYS[] = {
    { 1, "gauge",    "Akku",      10, -1,  0.0f, 16.8f },
    { 1, "rotation", "Heading",    5, -1,  0.0f, 360.0f },
    { 1, "vector",   "Fahrt \"V\"",6,  7,  0.0f, 100.0f },
    { 1, "textgrid", "Sensoren",  -1, -1,  0.0f, 0.0f, 4.0f, 6.0f,
        "channels=0-11,20;cols=2;dx=24;dy=5" },
    { 2, "bodies",   "Spielfeld", -1, -1,  0.0f, 0.0f, -1.0f, -1.0f,
        "field_x_cm=180;field_y_cm=240;"
        "body1_label=Ball;body1_color=#ff9800;body1_diameter=7;"
        "body1_channel_x=0;body1_channel_y=1;"
        "body2_label=Roboter;body2_color=#4ec9b0;body2_diameter=18;"
        "body2_channel_x=2;body2_channel_y=3;body2_channel_angle=4" },
    { 3, "",         "leerer Typ wird uebersprungen" },
    { 3, "table",    "Tabelle",   -1, -1,  0.0f, 0.0f, -1.0f, -1.0f, "0-9,15,20-22" },
};
static constexpr size_t CHANNEL_OVERLAYS_COUNT = sizeof(CHANNEL_OVERLAYS) / sizeof(CHANNEL_OVERLAYS[0]);

// ── Einstellungen der Oberflaeche (PDS 2.2) ───────────────────────────────
//  Absichtlich mit den unangenehmen Faellen: alle drei Werttypen, ein
//  Anfuehrungszeichen im Wert, ein Listenindex im Punktpfad und ein
//  "network."-Schluessel, den die GUI verwerfen MUSS.
#define PDS_HAS_GUI_SETTINGS 1
static const SettingDef GUI_SETTINGS[] = {
    { "ui.dark",                true      },
    { "ui.fontScale",           1.15f     },
    { "ui.startTab",            2         },
    { "battery.channel",        10        },
    { "battery.warn_below",     11.5f     },
    { "plotter.historySeconds", 20        },
    { "plotter.curveColors.0",  "#00ff88" },
    { "theme.colors.dark.bg",   "#101010" },
    { "network.rpi5Ip",         "1.2.3.4" },
};
static constexpr size_t GUI_SETTINGS_COUNT =
    sizeof(GUI_SETTINGS) / sizeof(GUI_SETTINGS[0]);

