/*
 * spi_slave.h — SPI Slave Interface (SPISlave_T4 / DMA ISR)
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "frame.h"

/** Maximum frame buffer size (N=1023 channels) */
#define SPI_SLAVE_BUF_SIZE  FRAME_TOTAL_SIZE(FRAME_MAX_CHANNELS)  // ~4 KB

/** IRQ output pin — asserted HIGH when frame is ready for RPi to read */
#define IRQ_PIN  2   // Teensy digital pin 2 → RPi GPIO (configure to match hardware)

/**
 * Initialize SPI slave and IRQ pin.
 * Call once from setup().
 * @param channel_count  Number of channels to include per frame (≥ 500, ≤ 1023)
 */
void spi_slave_init(uint16_t channel_count);

/**
 * Write a prepared frame buffer to the SPI transmit region and
 * assert the IRQ pin to signal the RPi.
 * Must be called with a fully formed (header + values + CRC) buffer.
 * @param buf   Frame buffer (at least FRAME_TOTAL_SIZE(channel_count) bytes)
 * @param len   Total frame length in bytes
 */
void spi_slave_send_frame(const uint8_t* buf, size_t len);

/**
 * Returns true if the RPi has completed reading the last frame
 * (CS returned HIGH), i.e. the slave is ready for the next frame.
 */
bool spi_slave_ready(void);
