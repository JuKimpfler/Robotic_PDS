/*
 * spi_slave.cpp — SPI Slave Driver (SPISlave_T4 + IRQ handshake)
 *
 * Hardware wiring (Teensy 4.0 SPI0):
 *   MOSI = pin 11
 *   MISO = pin 12
 *   SCK  = pin 13
 *   CS   = pin 10  (driven by RPi)
 *   IRQ  = pin  2  (OUTPUT — asserted HIGH when frame is ready)
 *
 * Protocol:
 *   1. Teensy fills DMA-safe frame buffer
 *   2. Asserts IRQ HIGH (~1 µs)
 *   3. RPi drives CS LOW, provides SPI clock
 *   4. DMA transfer: up to 4 KB @ 30 MHz ≈ 1.1 ms max
 *   5. RPi drives CS HIGH
 *   6. Teensy deasserts IRQ LOW, begins next frame
 */

#include "spi_slave.h"
#include "crc16.h"
#include <Arduino.h>
#include <SPISlave_T4.h>

// ─── Internal state ───────────────────────────────────────────────────────────

static SPISlave_T4<&SPI, SPI_8_BITS> s_spi_slave;

// DMA-safe frame buffer (aligned to 32 bytes for cache coherency on iMXRT)
static uint8_t s_tx_buf[SPI_SLAVE_BUF_SIZE] __attribute__((aligned(32)));
static volatile bool s_transfer_complete = true;
static uint16_t s_channel_count = FRAME_MIN_CHANNELS;

// ─── Callbacks ────────────────────────────────────────────────────────────────

static void on_transfer_complete(void) {
    // CS returned HIGH — transfer done
    s_transfer_complete = true;
    digitalWriteFast(IRQ_PIN, LOW);
}

// ─── Public API ───────────────────────────────────────────────────────────────

void spi_slave_init(uint16_t channel_count) {
    if (channel_count < FRAME_MIN_CHANNELS) channel_count = FRAME_MIN_CHANNELS;
    if (channel_count > FRAME_MAX_CHANNELS) channel_count = FRAME_MAX_CHANNELS;
    s_channel_count = channel_count;

    // Configure IRQ output pin
    pinMode(IRQ_PIN, OUTPUT);
    digitalWriteFast(IRQ_PIN, LOW);

    // Initialize SPI slave
    s_spi_slave.begin();
    s_spi_slave.onTransfer(on_transfer_complete);
}

void spi_slave_send_frame(const uint8_t* buf, size_t len) {
    if (len > SPI_SLAVE_BUF_SIZE) return;  // Safety guard

    // Copy frame into DMA-safe buffer
    memcpy(s_tx_buf, buf, len);

    // Arm SPI slave with frame data
    s_spi_slave.setMOSI(s_tx_buf, len);

    s_transfer_complete = false;

    // Assert IRQ HIGH — signals RPi to start SPI master transfer
    digitalWriteFast(IRQ_PIN, HIGH);
}

bool spi_slave_ready(void) {
    return s_transfer_complete;
}
