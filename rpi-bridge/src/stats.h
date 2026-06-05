/* stats.h — Runtime counters for the RPi bridge daemon */
#pragma once

#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint64_t frames_sent;      ///< Successfully validated + forwarded frames
    uint64_t crc_errors;       ///< SPI frames with CRC mismatch
    uint64_t magic_errors;     ///< SPI frames with wrong magic word
    uint64_t udp_send_errors;  ///< sendto() failures
    uint64_t gpio_errors;      ///< gpiod wait/read errors
} BridgeStats;

/** Global stats instance — written from main loop, read for printing */
extern BridgeStats g_stats;

/** Reset all counters to zero. */
void stats_reset(void);

/** Print a one-line stats summary to stderr. */
void stats_print(void);
