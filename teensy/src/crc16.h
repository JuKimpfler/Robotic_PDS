/*
 * crc16.h — CRC16-CCITT Implementation
 *
 * Polynomial: 0x1021
 * Initial value: 0xFFFF
 * Used for SPI frame validation (both Teensy and RPi bridge).
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

/**
 * Compute CRC16-CCITT over a byte buffer.
 * @param data   Pointer to data bytes
 * @param length Number of bytes
 * @return       16-bit CRC value
 */
static inline uint16_t crc16_ccitt(const uint8_t* data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int bit = 0; bit < 8; bit++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

/**
 * Verify CRC16 appended at end of a frame buffer.
 * The CRC covers bytes [0 .. header_size + channel_count*4 - 1],
 * i.e. everything EXCEPT the CRC field itself.
 * @param buf          Raw frame buffer
 * @param crc_offset   Byte offset of the CRC16 field
 * @return             true if CRC matches
 */
static inline bool crc16_verify(const uint8_t* buf, size_t crc_offset) {
    uint16_t computed = crc16_ccitt(buf, crc_offset);
    uint16_t stored;
    // Read little-endian
    stored = (uint16_t)buf[crc_offset] | ((uint16_t)buf[crc_offset + 1] << 8);
    return computed == stored;
}

/**
 * Write CRC16 (little-endian) into buffer at given offset.
 */
static inline void crc16_write(uint8_t* buf, size_t crc_offset) {
    uint16_t crc = crc16_ccitt(buf, crc_offset);
    buf[crc_offset]     = (uint8_t)(crc & 0xFF);
    buf[crc_offset + 1] = (uint8_t)(crc >> 8);
}
