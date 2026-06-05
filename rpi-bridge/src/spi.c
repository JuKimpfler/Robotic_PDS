/* spi.c — spidev wrapper (30 MHz, DMA via kernel driver) */

#include "spi.h"
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <errno.h>

int spi_open(const char* device, uint32_t speed_hz) {
    int fd = open(device, O_RDWR);
    if (fd < 0) {
        perror("spi_open: open");
        return -1;
    }

    // SPI mode 0 (CPOL=0, CPHA=0)
    uint8_t mode = SPI_MODE_0;
    if (ioctl(fd, SPI_IOC_WR_MODE, &mode) < 0) {
        perror("spi_open: SPI_IOC_WR_MODE"); close(fd); return -1;
    }

    // 8 bits per word
    uint8_t bits = 8;
    if (ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0) {
        perror("spi_open: SPI_IOC_WR_BITS_PER_WORD"); close(fd); return -1;
    }

    // Clock speed
    if (ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed_hz) < 0) {
        perror("spi_open: SPI_IOC_WR_MAX_SPEED_HZ"); close(fd); return -1;
    }

    return fd;
}

int spi_transfer(int fd, uint8_t* buf, size_t len) {
    struct spi_ioc_transfer tr = {
        .tx_buf        = (unsigned long)buf,
        .rx_buf        = (unsigned long)buf,
        .len           = (uint32_t)len,
        .speed_hz      = 30000000,
        .bits_per_word = 8,
        .delay_usecs   = 0,
        .cs_change     = 0,
    };

    if (ioctl(fd, SPI_IOC_MESSAGE(1), &tr) < 0) {
        perror("spi_transfer: SPI_IOC_MESSAGE");
        return -1;
    }
    return 0;
}

void spi_close(int fd) {
    close(fd);
}
