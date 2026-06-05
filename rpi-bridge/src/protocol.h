/*
 * protocol.h — SPI Frame & UDP Sub-Packet Protocol
 *
 * Implements §5.1 (SPI frame) and §5.2 (UDP sub-packet) of the spec.
 * All multi-byte fields are little-endian.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

// ─── SPI Frame constants ──────────────────────────────────────────────────────

#define FRAME_MAGIC         0xABCD
#define FRAME_HEADER_SIZE   12
#define FRAME_CRC_SIZE      2
#define FRAME_MIN_CHANNELS  500
#define FRAME_MAX_CHANNELS  1023
#define MAX_FRAME_SIZE      (FRAME_HEADER_SIZE + FRAME_MAX_CHANNELS * 4 + FRAME_CRC_SIZE)

// ─── UDP Sub-Packet constants ─────────────────────────────────────────────────

#define UDP_MAGIC           0xCDAB
#define UDP_HEADER_SIZE     12     // bytes before payload values[]
#define UDP_CRC_SIZE        2
#define MAX_UDP_PKT_SIZE    1200   // well below MTU=1500

// Dummy sentinel (channels with this value are treated as inactive)
#define DUMMY_VALUE         9898.0f

// ─── SPI Frame header (packed, little-endian) ─────────────────────────────────

#pragma pack(push, 1)
typedef struct {
    uint16_t magic;
    uint16_t sequence;
    uint32_t timestamp_us;
    uint16_t channel_count;
    uint16_t flags;
    /* float values[channel_count]; follows */
    /* uint16_t crc16; follows values */
} SpiFrameHeader;

// ─── UDP Sub-Packet header (packed, little-endian) ────────────────────────────

typedef struct {
    uint16_t magic;          // 0xCDAB
    uint16_t frame_seq;      // matches SPI frame sequence
    uint16_t channel_count;  // total channels in this frame
    uint8_t  sub_id;         // 0 = first half, 1 = second half
    uint8_t  sub_total;      // always 2
    uint16_t offset;         // float index of first value in payload
    uint16_t payload_count;  // number of float32 in this sub-packet
    /* float values[payload_count]; follows */
    /* uint16_t crc16; follows values */
} UdpSubHeader;
#pragma pack(pop)

// ─── CRC16-CCITT ──────────────────────────────────────────────────────────────

/**
 * Compute CRC16-CCITT (poly 0x1021, init 0xFFFF) over buffer.
 */
uint16_t crc16_ccitt(const uint8_t* data, size_t len);

// ─── Frame validation ─────────────────────────────────────────────────────────

/**
 * Check SPI frame magic word.
 * @param buf  Raw SPI frame buffer
 * @return     true if magic == 0xABCD
 */
bool frame_magic_ok(const uint8_t* buf);

/**
 * Validate CRC16 of a complete SPI frame.
 * @param buf        Raw frame buffer
 * @param frame_len  Total frame length (header + values + crc)
 * @return           true if CRC matches
 */
bool frame_crc_ok(const uint8_t* buf, size_t frame_len);

/**
 * Extract channel_count from a raw SPI frame buffer.
 */
uint16_t frame_get_channel_count(const uint8_t* buf);

/**
 * Compute total frame length given channel_count.
 */
static inline size_t frame_total_size(uint16_t ch) {
    return FRAME_HEADER_SIZE + (size_t)ch * 4 + FRAME_CRC_SIZE;
}

// ─── Sub-packet builder ───────────────────────────────────────────────────────

/**
 * Build one UDP sub-packet from a validated SPI frame.
 *
 * @param spi_buf       Source SPI frame buffer (validated)
 * @param out_buf       Output UDP packet buffer (at least MAX_UDP_PKT_SIZE)
 * @param sub_id        0 = first half, 1 = second half
 * @param channel_count Total channels in frame
 * @return              Length of the built UDP packet in bytes
 */
size_t build_sub_packet(const uint8_t* spi_buf,
                         uint8_t*       out_buf,
                         uint8_t        sub_id,
                         uint16_t       channel_count);
