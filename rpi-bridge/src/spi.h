/* spi.h — spidev wrapper for Raspberry Pi */
#pragma once

#include <stdint.h>
#include <stddef.h>

/**
 * Open and configure the SPI device.
 * @param device   e.g. "/dev/spidev0.0"
 * @param speed_hz SPI clock frequency in Hz (e.g. 30000000)
 * @return         file descriptor, or -1 on error
 */
int spi_open(const char* device, uint32_t speed_hz);

/**
 * Full-duplex SPI transfer (reads and writes simultaneously).
 * @param fd    SPI file descriptor
 * @param buf   Buffer to send (TX) and receive into (RX)
 * @param len   Transfer length in bytes
 * @return      0 on success, -1 on error
 */
int spi_transfer(int fd, uint8_t* buf, size_t len);

/** Close the SPI device. */
void spi_close(int fd);
