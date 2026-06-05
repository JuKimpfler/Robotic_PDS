/*
 * protocol.c — SPI Frame Validation and UDP Sub-Packet Builder
 * See protocol.h for API documentation.
 */

#include "protocol.h"
#include <string.h>
#include <stdint.h>

// ─── CRC16-CCITT ──────────────────────────────────────────────────────────────

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

// ─── Frame validation ─────────────────────────────────────────────────────────

bool frame_magic_ok(const uint8_t* buf) {
    uint16_t magic;
    memcpy(&magic, buf, 2);
    return magic == FRAME_MAGIC;
}

uint16_t frame_get_channel_count(const uint8_t* buf) {
    uint16_t ch;
    memcpy(&ch, buf + 8, 2);  // offset 8 in FrameHeader
    return ch;
}

bool frame_crc_ok(const uint8_t* buf, size_t frame_len) {
    if (frame_len < FRAME_HEADER_SIZE + FRAME_CRC_SIZE) return false;
    size_t crc_offset = frame_len - FRAME_CRC_SIZE;
    uint16_t computed = crc16_ccitt(buf, crc_offset);
    uint16_t stored;
    memcpy(&stored, buf + crc_offset, 2);
    return computed == stored;
}

// ─── Sub-packet builder ───────────────────────────────────────────────────────

size_t build_sub_packet(const uint8_t* spi_buf,
                         uint8_t*       out_buf,
                         uint8_t        sub_id,
                         uint16_t       channel_count) {
    /*
     * Split channel_count floats evenly into 2 sub-packets.
     * sub_id=0: channels [0 .. half-1]
     * sub_id=1: channels [half .. channel_count-1]
     */
    uint16_t half      = channel_count / 2;
    uint16_t offset    = (sub_id == 0) ? 0 : half;
    uint16_t pkt_count = (sub_id == 0) ? half : (channel_count - half);

    // Read frame sequence from SPI buffer (offset 2)
    uint16_t frame_seq;
    memcpy(&frame_seq, spi_buf + 2, 2);

    // Build UDP sub-packet header
    UdpSubHeader hdr;
    hdr.magic         = UDP_MAGIC;
    hdr.frame_seq     = frame_seq;
    hdr.channel_count = channel_count;
    hdr.sub_id        = sub_id;
    hdr.sub_total     = 2;
    hdr.offset        = offset;
    hdr.payload_count = pkt_count;

    memcpy(out_buf, &hdr, UDP_HEADER_SIZE);

    // Copy float values
    size_t values_offset = FRAME_HEADER_SIZE + (size_t)offset * 4;
    size_t values_bytes  = (size_t)pkt_count * 4;
    memcpy(out_buf + UDP_HEADER_SIZE, spi_buf + values_offset, values_bytes);

    // Append CRC16 over [0 .. UDP_HEADER_SIZE + values_bytes - 1]
    size_t crc_offset = UDP_HEADER_SIZE + values_bytes;
    uint16_t crc = crc16_ccitt(out_buf, crc_offset);
    memcpy(out_buf + crc_offset, &crc, 2);

    return crc_offset + UDP_CRC_SIZE;
}
