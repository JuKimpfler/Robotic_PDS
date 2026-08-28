#pragma once
#include <Arduino.h>

// ============================================================
//  params.h — Wire-Format und Verdrahtung des Power Debug System
// ============================================================
//  ACHTUNG: Alles in diesem Abschnitt ist WIRE-FORMAT. Jede Aenderung muss
//  gleichzeitig in
//      rpi_zero_node/uart_receiver.py            und
//      rpi5_monitor/64Bit_Version/config.py
//  nachgezogen werden, sonst verwirft der Node stillschweigend jedes Paket.
//  Der Test tools/check_wire_format.py prueft genau das automatisch.
// ============================================================

// Wird bei jeder inkompatiblen Aenderung des Wire-Formats hochgezaehlt und
// von tools/check_wire_format.py gegen die Python-Seite geprueft.
#define PDS_WIRE_VERSION 2

// ── Projektspezifische I2C-Zuordnung (nicht Teil des PDS-Protokolls) ──
#define I2C_BNO Wire1
#define I2C_IR Wire1
#define I2C_SW Wire1
#define I2C_US Wire1

#define BNO_ADDRESS 0x28

static constexpr uint32_t UART_DBG_BAUD        = 1'000'000UL; // 1 Mbps

// ============================================================
//  UART-Instanz für den Power-Debug-Kanal
// ============================================================
//  main.cpp verwendet bisher direkt Serial3 fuer TX (Telemetrie).
//  Damit PDS.cpp dieselbe physische Schnittstelle fuer den neuen
//  Param-Downlink (RX) mitbenutzen kann, wird hier EIN Name fuer
//  beide Richtungen festgelegt. Falls eure Verkabelung/Pinbelegung
//  eine andere UART-Instanz vorsieht, hier anpassen -- der Rest des
//  Codes (PDS.cpp) verwendet ausschliesslich das Makro UART_DBG und
//  muss dafuer nicht veraendert werden.
// ============================================================
#ifndef UART_DBG
#define UART_DBG Serial3
#endif

// ============================================================
//  Param-Downlink (RPi 5 -> RPi Zero -> Teensy, ueber UART_DBG RX)
// ============================================================
//  Zwei Pakettypen, unterschieden per Magic-Header:
//
//   Slow-Kanal  (0xCAFEFEED): 50 Floats + 50 Bools, 2 Hz
//                normale Tuning-Parameter (Konfig aus GUI-Widgets)
//
//   Fast-Kanal  (0xFA57DA7A): 5 Floats, 100 Hz
//                Echtzeit-Steuerung (z. B. Joystick), niedrige Latenz
// ============================================================

// ── Slow-Kanal ───────────────────────────────────────────────
static constexpr uint32_t PARAM_SLOW_MAGIC        = 0xCAFEFEEDUL;
static constexpr int      PARAM_SLOW_FLOAT_COUNT  = 50;
static constexpr int      PARAM_SLOW_BOOL_COUNT   = 50;
static constexpr int      PARAM_HEADER_BYTES      = 8;   // magic(4) + seq(4), fuer beide Pakettypen gleich
static constexpr int      PARAM_SLOW_PACKET_BYTES =
    PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + PARAM_SLOW_BOOL_COUNT;      // 258

// ── Fast-Kanal ───────────────────────────────────────────────
static constexpr uint32_t PARAM_FAST_MAGIC        = 0xFA57DA7AUL;
static constexpr int      PARAM_FAST_FLOAT_COUNT  = 5;
static constexpr int      PARAM_FAST_PACKET_BYTES =
    PARAM_HEADER_BYTES + PARAM_FAST_FLOAT_COUNT * 4;                             // 28

// ── Staleness-Watchdog-Schwellen ─────────────────────────────
//   Slow: 2 verpasste Zyklen (500 ms) -> 1000 ms
//   Fast: grosszuegiger als "2 verpasste Zyklen" (20 ms), da bei
//         100 Hz ueber WLAN sonst staendig Fehlalarm ausgeloest wuerde.
//         150 ms ist ein Startwert -- am Feld ggf. nachjustieren.
static constexpr uint32_t PARAM_SLOW_TIMEOUT_MS = 1000;
static constexpr uint32_t PARAM_FAST_TIMEOUT_MS = 150;

// ============================================================
//  Ereignis-/Log-Kanal  (Teensy -> RPi Zero -> RPi 5)
// ============================================================
//  Kurze Textmeldungen aus dem Roboter-Code, in zwei Auspraegungen:
//
//    kind = 0  EREIGNIS  -- PDS.event("Ball verloren")
//                           Zeitpunkt-Marke; die GUI zeichnet sie als
//                           senkrechte Linie in den Plotter.
//    kind = 1  LOGZEILE  -- PDS.log("Kalibrierung fertig")
//                           reine Textausgabe fuer das Logbuch.
//
//  Beides teilt sich absichtlich EIN Paketformat: es ist derselbe
//  Transportweg, dieselbe Warteschlange und dieselbe Anzeige-Liste --
//  nur die Darstellung unterscheidet sich.
//
//   [0..3]   uint32 magic (PDS_EVENT_MAGIC)
//   [4..7]   uint32 micros()          Zeitstempel, gleiche Basis wie Telemetrie
//   [8..11]  float  value             frei belegbar (0.0f, wenn ungenutzt)
//   [12]     uint8  kind              0 = Ereignis, 1 = Logzeile
//   [13]     uint8  level             0 = Info, 1 = Warnung, 2 = Fehler
//   [14]     uint8  text_len          0..PDS_EVENT_TEXT_MAX
//   [15]     uint8  reserved          immer 0 (Plausibilitaetspruefung im Node)
//   [16..]   char   text[text_len]    UTF-8, OHNE Nullterminator
// ============================================================
static constexpr uint32_t PDS_EVENT_MAGIC        = 0xE7E5C0DEUL;
static constexpr int      PDS_EVENT_HEADER_BYTES = 16;
static constexpr int      PDS_EVENT_TEXT_MAX     = 48;
static constexpr int      PDS_EVENT_PACKET_MAX   =
    PDS_EVENT_HEADER_BYTES + PDS_EVENT_TEXT_MAX;                                 // 64

static constexpr uint8_t PDS_EVENT_KIND_EVENT = 0;
static constexpr uint8_t PDS_EVENT_KIND_LOG   = 1;

static constexpr uint8_t PDS_LEVEL_INFO  = 0;
static constexpr uint8_t PDS_LEVEL_WARN  = 1;
static constexpr uint8_t PDS_LEVEL_ERROR = 2;

// Hoechstens so viele Ereignispakete pro Sekunde verlassen den Teensy. Der
// Uplink ist zu 81 % mit Telemetrie belegt; eine Endlosschleife mit log() im
// Roboter-Code darf den 100-Hz-Takt nicht verdraengen. Ueberzaehlige
// Meldungen werden verworfen und in PDS.eventDropCount() gezaehlt.
static constexpr int PDS_EVENT_MAX_PER_SEC = 20;

// ============================================================
//  Parameter-Rueckmeldung  (Teensy -> RPi Zero -> RPi 5, 2 Hz)
// ============================================================
//  Der Param-Downlink ist fire-and-forget: die GUI hat bisher nie erfahren,
//  ob ein Wert tatsaechlich angekommen ist. Dieses Paket schickt den
//  KOMPLETTEN Stand zurueck, den der Teensy gerade haelt -- die GUI kann ihn
//  gegen ihren Soll-Stand vergleichen und Abweichungen anzeigen.
//
//   [0..3]   uint32 magic (PARAM_ACK_MAGIC)
//   [4..7]   uint32 last_slow_seq     Sequenznummer des letzten Slow-Pakets
//   [8..11]  uint32 last_fast_seq     Sequenznummer des letzten Fast-Pakets
//   [12..15] uint32 slow_age_ms       Alter des letzten Slow-Pakets (0xFFFFFFFF = nie)
//   [16..19] uint32 fast_age_ms       Alter des letzten Fast-Pakets (0xFFFFFFFF = nie)
//   [20..]   float  slow_floats[PARAM_SLOW_FLOAT_COUNT]
//            uint8  slow_bools [PARAM_SLOW_BOOL_COUNT]    (0/1)
//            float  fast_floats[PARAM_FAST_FLOAT_COUNT]
// ============================================================
static constexpr uint32_t PARAM_ACK_MAGIC        = 0xACC0FEEDUL;
static constexpr int      PARAM_ACK_HEADER_BYTES = 20;
static constexpr int      PARAM_ACK_PACKET_BYTES =
    PARAM_ACK_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4
    + PARAM_SLOW_BOOL_COUNT + PARAM_FAST_FLOAT_COUNT * 4;                        // 290
static constexpr uint32_t PARAM_ACK_INTERVAL_MS = 500;   // 2 Hz

// ============================================================
//  Kanal-/Param-Namens- und Overlay-Deskriptor
//  (Teensy -> RPi Zero -> RPi 5, einmalig beim Boot + auf Anfrage)
// ============================================================
//  Der Deskriptor ist ein einziger JSON-Text (siehe channel_config.h
//  fuer die Nutzdaten), der wegen seiner Groesse in kleine Pakete
//  ("Chunks") aufgeteilt und ueber dieselbe UART_DBG-Leitung wie
//  Telemetrie/Param-Downlink gesendet wird -- ein Chunk pro
//  update()-Zyklus, damit der 100-Hz-Telemetrieversand nie blockiert.
//
//   Chunk-Paket (Teensy -> GUI):
//     [0..3] magic (CHANNEL_DESC_MAGIC)
//     [4]    chunk_idx    (uint8)
//     [5]    chunk_count  (uint8)
//     [6]    payload_len  (uint8, 0..CHANNEL_DESC_CHUNK_PAYLOAD_MAX)
//     [7..]  payload (UTF-8 JSON-Fragment)
//
//   Request-Paket (GUI -> Teensy, kein Payload):
//     [0..3] magic (CHANNEL_DESC_REQUEST_MAGIC)
// ============================================================
static constexpr uint32_t CHANNEL_DESC_MAGIC         = 0xDE5C0001UL;
static constexpr uint32_t CHANNEL_DESC_REQUEST_MAGIC = 0xDE5C00F0UL;

static constexpr int CHANNEL_DESC_CHUNK_PAYLOAD_MAX = 250;   // Bytes JSON-Text pro Chunk
static constexpr int CHANNEL_DESC_CHUNK_HEADER_BYTES = 7;    // magic(4) + chunk_idx(1) + chunk_count(1) + payload_len(1)
static constexpr int CHANNEL_DESC_CHUNK_PACKET_BYTES =
    CHANNEL_DESC_CHUNK_HEADER_BYTES + CHANNEL_DESC_CHUNK_PAYLOAD_MAX;   // 257
static constexpr int CHANNEL_DESC_REQUEST_PACKET_BYTES = 4;             // nur Magic

// Reicht fuer 200 Kanalnamen + 105 Param-Namen + deren Widget-Konfiguration
// + ~40 Overlays. Liegt auf Teensy 4.x im OCRAM (DMAMEM), nicht im knappen
// DTCM -- siehe PDS_SLOWMEM in PDS.cpp.
static constexpr size_t CHANNEL_DESC_JSON_BUF_BYTES = 24 * 1024;
static constexpr uint8_t CHANNEL_NAME_MAXLEN = 24;                 // inkl. Nullterminator


// ============================================================
//  Konfigurations-Strukturen fuer channel_config.h
// ============================================================
//  Bewusst HIER und nicht in channel_config.h: PDS.cpp muss dieselben Typen
//  kennen, auch wenn channel_config.h gar nicht existiert (die Datei ist
//  optional, siehe __has_include in PDS.cpp). Zwei Definitionen an zwei
//  Orten waeren eine Fehlerquelle, sobald sich ein Feld aendert.
// ============================================================

/// Fester Name fuer einen Debug-Kanal (nur noetig fuer Kanaele, die NICHT
/// per plot()/track()/Channel(...,name) im Sketch benannt werden).
struct ChannelNameDef {
    uint8_t     index;
    const char* name;
    const char* unit = "";    ///< optional, z. B. "V", "cm", "°/s"
};

/// Beschreibung EINES Parameters, den die GUI an den Teensy schickt.
/// Der Teensy ist damit die einzige Quelle der Wahrheit fuer den Aufbau des
/// Parameter-Tabs: Name, Bedienelement, Wertebereich und Gruppe kommen im
/// Deskriptor mit und werden von der GUI dauerhaft gespeichert.
struct ParamDef {
    uint8_t     index;                 ///< 0..PARAM_*_COUNT-1
    const char* name;
    const char* widget    = "slider";  ///< "slider"|"number"|"toggle"|"button"
    float       min_val   = 0.0f;
    float       max_val   = 1.0f;
    float       step      = 0.01f;
    float       def_val   = 0.0f;
    const char* group     = "";        ///< Seitenname im Parameter-Tab
    bool        momentary = false;     ///< nur "button": nur gedrueckt = true
};

/// Zwei Parameter, die die GUI als EIN Joystick-Pad bedienen soll.
struct JoystickDef {
    const char* name;
    const char* source;            ///< "fast" (100 Hz) oder "slow" (2 Hz)
    uint8_t     x_index;
    uint8_t     y_index;
    float       x_min = -100.0f;
    float       x_max =  100.0f;
    float       y_min = -100.0f;
    float       y_max =  100.0f;
    bool        return_to_center = true;
};

/// Ein Anzeige-Element in der Systemansicht der GUI.
/// Feldreihenfolge im Initialisierer:
///   group, type, label, channel, channel2, min_val, max_val, x_pct, y_pct, extra
struct OverlayDef {
    uint8_t     group;                 ///< 1..4 = Bild-/Widget-Gruppe
    const char* type;                  ///< siehe channel_config.h
    const char* label;
    int16_t     channel  = -1;         ///< primaerer Kanal, bei "vector" der Winkel
    int16_t     channel2 = -1;         ///< sekundaerer Kanal, bei "vector" der Betrag
    float       min_val  = 0.0f;
    float       max_val  = 0.0f;
    float       x_pct    = -1.0f;      ///< Position auf dem Bild (0..100, -1 = ungenutzt)
    float       y_pct    = -1.0f;
    const char* extra    = "";         ///< "key=value;..." bzw. Kanalliste
};
