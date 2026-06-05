# Telemetry Protocol Specification

This document mirrors the authoritative protocol definitions from `README_TELEMETRY_SYSTEM.md`.

## SPI Frame Format (Teensy → RPi)

`#pragma pack(push, 1)` — all fields little-endian.

| Offset | Size | Type    | Field         | Description |
|---:|---:|---|---|---|
| 0 | 2 | uint16 | magic | Sync: `0xABCD` |
| 2 | 2 | uint16 | sequence | Wrapping frame counter |
| 4 | 4 | uint32 | timestamp_us | Teensy micros() |
| 8 | 2 | uint16 | channel_count | Number of float32 values (≥ 500) |
| 10 | 2 | uint16 | flags | Bit 0: frame_rate_ack; bits 1-15 reserved |
| 12 | N×4 | float32[N] | values | Telemetry payload (N = channel_count) |
| 12+N×4 | 2 | uint16 | crc16 | CRC16-CCITT over bytes `[0 .. 10+N×4]` |

CRC16-CCITT, polynomial `0x1021`, init `0xFFFF`.

## UDP Sub-Packet Format (RPi → PC)

| Offset | Size | Type    | Field         | Description |
|---:|---:|---|---|---|
| 0 | 2 | uint16 | magic | `0xCDAB` |
| 2 | 2 | uint16 | frame_seq | SPI frame sequence |
| 4 | 2 | uint16 | channel_count | Total channels in frame |
| 6 | 1 | uint8 | sub_id | 0 = first half, 1 = second half |
| 7 | 1 | uint8 | sub_total | Always 2 |
| 8 | 2 | uint16 | offset | Float index of first value |
| 10 | 2 | uint16 | payload_count | Number of float32 in this sub-packet |
| 12 | M×4 | float32[M] | values | Payload (M = payload_count) |
| 12+M×4 | 2 | uint16 | crc16 | CRC16-CCITT over bytes `[0 .. 10+M×4]` |

## WebSocket Frame (PC → Browser)

Default binary encoding: MessagePack. The `values` field is encoded as msgpack bin containing a little-endian float32 array.

```json
{ "type": "frame", "seq": 123, "ts_us": 456, "rate_hz": 100.0, "values": "<bin float32[]>" }
```

Channel maps and status messages are sent as JSON/MessagePack maps as described in the spec.
