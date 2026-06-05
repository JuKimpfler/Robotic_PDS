/*
 * frame.h — Telemetry Frame Definition (Source of Truth)
 *
 * SPI Frame Format (Teensy → RPi), §5.1 of spec.
 * All fields little-endian, packed (no padding).
 *
 * Offset  Size   Type       Field            Description
 * 0       2      uint16     magic            Sync word: 0xABCD
 * 2       2      uint16     sequence         Wrapping frame counter
 * 4       4      uint32     timestamp_us     Teensy micros()
 * 8       2      uint16     channel_count    Number of float32 values (≥ 500)
 * 10      2      uint16     flags            Bit 0: frame_rate_ack; Bits 1-15: reserved
 * 12      N×4    float32[]  values           Telemetry payload (N = channel_count)
 * 12+N×4  2      uint16     crc16            CRC16-CCITT over bytes [0..10+N×4]
 *
 * Minimum frame size (N=500): 12 + 2000 + 2 = 2014 bytes
 * Maximum channel_count: 1023 (max frame < 4 KB, below spidev default buffer)
 */

#pragma once

#include <stdint.h>

// Protocol constants
#define FRAME_MAGIC         0xABCD
#define FRAME_MIN_CHANNELS  500
#define FRAME_MAX_CHANNELS  1023
#define FRAME_HEADER_SIZE   12   // bytes before values[]
#define FRAME_CRC_SIZE      2    // bytes after values[]

// Flags
#define FLAG_FRAME_RATE_ACK 0x0001

// Dummy sentinel value — channels sending this are treated as inactive
#define DUMMY_VALUE         9898.0f

// Computed sizes
#define FRAME_PAYLOAD_SIZE(n)  ((n) * sizeof(float))
#define FRAME_TOTAL_SIZE(n)    (FRAME_HEADER_SIZE + FRAME_PAYLOAD_SIZE(n) + FRAME_CRC_SIZE)
#define FRAME_MIN_SIZE         FRAME_TOTAL_SIZE(FRAME_MIN_CHANNELS)  // 2014 bytes

#pragma pack(push, 1)

typedef struct {
    uint16_t magic;          ///< Always FRAME_MAGIC (0xABCD)
    uint16_t sequence;       ///< Wrapping 16-bit counter
    uint32_t timestamp_us;   ///< Teensy micros() at frame start
    uint16_t channel_count;  ///< Number of float32 values that follow
    uint16_t flags;          ///< Bit 0 = frame_rate_ack
    // float values[channel_count];  // variable length — access via frame_values()
    // uint16_t crc16;               // follows values[] — access via frame_crc_ptr()
} FrameHeader;

#pragma pack(pop)

// Helper: pointer to values array within a raw frame buffer
static inline float* frame_values(uint8_t* buf) {
    return (float*)(buf + FRAME_HEADER_SIZE);
}

// Helper: pointer to CRC16 field within a raw frame buffer
static inline uint16_t* frame_crc_ptr(uint8_t* buf, uint16_t channel_count) {
    return (uint16_t*)(buf + FRAME_HEADER_SIZE + channel_count * sizeof(float));
}
