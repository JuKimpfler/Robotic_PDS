# Telemetry Streaming System — Protocol Specification

**Version:** 0.2 + GUI Addendum v0.3  
**Status:** Authoritative frame format reference  
**Last Updated:** 2026-06-05

> This document is the single source of truth for all binary and wire formats.
> Implementations in `teensy/`, `rpi-bridge/`, and `pc-backend/` MUST conform exactly.

---

## 1. Numeric Encoding

| Property | Value |
|---|---|
| Byte order | **Little-endian** throughout (SPI, UDP, WS metadata) |
| float32 | IEEE 754 single precision |
| CRC | CRC16-CCITT, polynomial `0x1021`, init `0xFFFF` |

---

## 2. SPI Frame Format (Teensy → RPi)

`#pragma pack(push, 1)` — no padding between fields.

```
Offset   Size    Type          Field             Description
──────   ────    ──────────    ──────────────    ──────────────────────────────
0        2       uint16        magic             Sync: 0xABCD
2        2       uint16        sequence          Wrapping frame counter
4        4       uint32        timestamp_us      Teensy micros()
8        2       uint16        channel_count     Number of float32 values (≥ 500)
10       2       uint16        flags             Bit 0: frame_rate_ack; Bits 1-15: reserved
12       N×4     float32[N]    values            Telemetry payload (N = channel_count)
12+N×4   2       uint16        crc16             CRC16-CCITT over bytes [0 .. 10+N×4]
──────
Minimum frame size (N=500): 12 + 2000 + 2 = 2014 bytes
Maximum channel_count: 1023 (max frame < 4 KB)
```

**Dummy sentinel:** Channels with value `9898.0f` are treated as inactive by the frontend.

---

## 3. UDP Sub-Packet Format (RPi → PC)

Standard WiFi MTU = 1500 bytes. A full SPI frame (2014 B) is split into **2 sub-packets**.

```
Offset   Size    Type         Field
──────   ────    ──────────   ─────────────────────────────
0        2       uint16       magic         0xCDAB
2        2       uint16       frame_seq     Matches SPI frame sequence
4        2       uint16       channel_count Total channels in this frame
6        1       uint8        sub_id        0 = first half, 1 = second half
7        1       uint8        sub_total     Always 2 (for N ≤ 1000)
8        2       uint16       offset        Float index of first value in payload
10       2       uint16       payload_count Number of float32 in this sub-packet
12       M×4     float32[M]   values        Payload (M = payload_count)
12+M×4   2       uint16       crc16         CRC16-CCITT over bytes [0 .. 10+M×4]
──────
Typical: M=250 → 12 + 1000 + 2 = 1014 bytes per sub-packet (< 1500 MTU)
```

**Reassembly on PC:** Keyed on `frame_seq`. Both sub-packets must arrive within **5 ms** or the frame is dropped.

**Alternative:** Set `config.yaml: udp.split_frames: false` when jumbo frames (MTU ≥ 2014) are supported.

---

## 4. WebSocket Wire Format (PC → Browser)

**Endpoint:** `ws://localhost:9001/stream`  
**HTTP API / Frontend:** `http://localhost:8080`

### 4.1 Data Frame (high frequency)

**Format A — MessagePack** (default):

```
type:    "frame"
seq:     uint16
ts_us:   uint32
rate_hz: float32
values:  float32[]   // channel_count floats, ordered by index
```

**Format B — JSON** (debug, `?format=json` query param):

```json
{
  "type": "frame",
  "seq": 12345,
  "ts_us": 9876543,
  "rate_hz": 100.2,
  "values": [0.1, 0.2, "..."]
}
```

### 4.2 Channel Map (on connect + hot-reload)

```json
{
  "type": "channel_map",
  "channels": [
    {
      "index": 0, "name": "motor_fl_rpm", "unit": "rpm",
      "scale": 1.0, "offset": 0.0, "min": -3000, "max": 3000,
      "group": "Motors", "color": "#E74C3C", "precision": 1, "enabled": true
    }
  ]
}
```

### 4.3 System Status (1 Hz)

```json
{
  "type": "status",
  "hotspot": "on" | "off" | "transitioning",
  "rpi_ip": "192.168.137.42",
  "frames_rx": 123456,
  "frames_dropped": 12,
  "crc_errors": 0,
  "rate_hz": 100.2
}
```

### 4.4 Parameter Map (on connect)

```json
{
  "type": "param_map",
  "params": [
    {
      "index": 0, "name": "pid_fl_kp", "type": "float32",
      "default": 1.2, "min": 0.0, "max": 100.0,
      "unit": "", "group": "PID Motors", "description": "...", "value": 1.2
    }
  ]
}
```

### 4.5 Robot Viz Config (future)

```json
{
  "type": "robot_viz",
  "config": { "...": "robot_viz.json content" }
}
```

**Message encoding:** Data frames use MessagePack (binary WebSocket frame). Control messages (`channel_map`, `status`, `param_map`) use JSON text frames.

---

## 5. UART Command Protocol (PC → Teensy)

Port: USB Serial (Windows `COMx`), 115200 baud.

### Frame Rate Control

```
RATE:100\n     → set 100 Hz (range 0–300; 0 = pause)
RATE_ACK:100\n → acknowledgment
RATE_ACK:ERR:out_of_range\n
```

### Parameter Control

```
PARAM_SET:0:1.250\n                    → set parameter index 0
PARAM_BATCH:0:1.250,1:0.060,2:0.012\n  → batch (≤ 50 params)
PARAM_SAVE\n                           → persist to EEPROM
PARAM_LOAD:1\n                         → load EEPROM preset slot
PARAM_ACK:OK\n
PARAM_ACK:ERR:index_out_of_range\n
```

---

## 6. CRC16-CCITT Reference Implementation

```c
uint16_t crc16_ccitt(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int bit = 0; bit < 8; bit++) {
            if (crc & 0x8000)
                crc = (crc << 1) ^ 0x1021;
            else
                crc <<= 1;
        }
    }
    return crc;
}
```

---

*End of protocol specification.*
