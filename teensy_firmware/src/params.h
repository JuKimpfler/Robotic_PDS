#pragma once
#include <Arduino.h>

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

static constexpr size_t CHANNEL_DESC_JSON_BUF_BYTES = 12 * 1024;   // reicht fuer 200+105 Namen + ~30 Overlays
static constexpr uint8_t CHANNEL_NAME_MAXLEN = 24;                 // inkl. Nullterminator
