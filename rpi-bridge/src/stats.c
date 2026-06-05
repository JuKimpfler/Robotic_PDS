/* stats.c — Runtime counters */

#include "stats.h"
#include <stdio.h>
#include <string.h>

BridgeStats g_stats = {0};

void stats_reset(void) {
    memset(&g_stats, 0, sizeof(g_stats));
}

void stats_print(void) {
    fprintf(stderr,
        "[bridge] sent=%" PRIu64 "  crc_err=%" PRIu64
        "  magic_err=%" PRIu64 "  udp_err=%" PRIu64
        "  gpio_err=%" PRIu64 "\n",
        g_stats.frames_sent,
        g_stats.crc_errors,
        g_stats.magic_errors,
        g_stats.udp_send_errors,
        g_stats.gpio_errors);
}
