/*
 * main.c — SPI-UDP Bridge Daemon (Raspberry Pi Zero 2W)
 *
 * Pipeline per §8 of the spec:
 *   1. Set SCHED_FIFO RT scheduling (priority 50)
 *   2. Open SPI master (/dev/spidev0.0 @ 30 MHz)
 *   3. Open UDP socket → PC (192.168.137.1:9000), 4 MB send buffer
 *   4. Open GPIO IRQ (rising edge on Teensy IRQ pin)
 *   5. RT loop:
 *      a. Block on GPIO rising edge (Teensy signals frame ready)
 *      b. SPI read: header first (12 bytes) to get channel_count,
 *         then full frame
 *      c. Validate magic + CRC16
 *      d. Build 2 UDP sub-packets and send
 *
 * Usage:
 *   spi_bridge --spi /dev/spidev0.0 --host 192.168.137.1 --port 9000
 *              --gpio-chip /dev/gpiochip0 --gpio-line 17
 *              [--simulate]
 *
 * --simulate: generate synthetic frames without SPI/GPIO hardware.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <signal.h>
#include <sched.h>
#include <time.h>
#include <math.h>
#include <inttypes.h>

#include "spi.h"
#include "udp.h"
#include "gpio.h"
#include "protocol.h"
#include "stats.h"

// ─── Defaults (overridden by CLI args / bridge.conf) ─────────────────────────

#define DEFAULT_SPI_DEVICE   "/dev/spidev0.0"
#define DEFAULT_SPI_SPEED    30000000
#define DEFAULT_HOST         "192.168.137.1"
#define DEFAULT_PORT         9000
#define DEFAULT_GPIO_CHIP    "/dev/gpiochip0"
#define DEFAULT_GPIO_LINE    17
#define STATS_INTERVAL_S     10      // Print stats every N seconds
#define SIM_CHANNEL_COUNT    500     // Channels in simulate mode

// ─── Globals ──────────────────────────────────────────────────────────────────

static volatile bool s_running = true;

static uint8_t s_spi_buf[MAX_FRAME_SIZE];
static uint8_t s_udp_pkt_a[MAX_UDP_PKT_SIZE];
static uint8_t s_udp_pkt_b[MAX_UDP_PKT_SIZE];

// ─── Signal handler ───────────────────────────────────────────────────────────

static void on_signal(int sig) {
    (void)sig;
    s_running = false;
}

// ─── Simulate mode ────────────────────────────────────────────────────────────

static uint16_t s_sim_seq = 0;

static void sim_build_frame(uint8_t* buf, uint16_t ch_count, uint32_t ts_us) {
    // Header
    uint16_t magic = FRAME_MAGIC;
    memcpy(buf + 0, &magic,    2);
    memcpy(buf + 2, &s_sim_seq, 2);
    memcpy(buf + 4, &ts_us,    4);
    memcpy(buf + 8, &ch_count, 2);
    uint16_t flags = 0;
    memcpy(buf + 10, &flags, 2);
    s_sim_seq++;

    // Values — sine waves per channel
    float* values = (float*)(buf + FRAME_HEADER_SIZE);
    for (uint16_t i = 0; i < ch_count; i++) {
        float freq = 1.0f + (float)(i % 10) * 0.3f;
        values[i]  = 500.0f * sinf(2.0f * 3.14159f * freq * (float)ts_us * 1e-6f
                                    + (float)i * 0.05f);
    }
    // Inject dummy values on channels 7 & 8
    if (ch_count > 9) { values[7] = 9898.0f; values[8] = 9898.0f; }

    // CRC
    size_t crc_off = FRAME_HEADER_SIZE + (size_t)ch_count * 4;
    uint16_t crc = crc16_ccitt(buf, crc_off);
    memcpy(buf + crc_off, &crc, 2);
}

// ─── CLI argument parser ──────────────────────────────────────────────────────

typedef struct {
    const char* spi_device;
    uint32_t    spi_speed;
    const char* host;
    uint16_t    port;
    const char* gpio_chip;
    unsigned    gpio_line;
    bool        simulate;
} Config;

static Config parse_args(int argc, char* argv[]) {
    Config cfg = {
        .spi_device = DEFAULT_SPI_DEVICE,
        .spi_speed  = DEFAULT_SPI_SPEED,
        .host       = DEFAULT_HOST,
        .port       = DEFAULT_PORT,
        .gpio_chip  = DEFAULT_GPIO_CHIP,
        .gpio_line  = DEFAULT_GPIO_LINE,
        .simulate   = false,
    };
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--spi")       && i+1 < argc) cfg.spi_device = argv[++i];
        else if (!strcmp(argv[i], "--host") && i+1 < argc) cfg.host       = argv[++i];
        else if (!strcmp(argv[i], "--port") && i+1 < argc) cfg.port       = (uint16_t)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--gpio-chip") && i+1<argc) cfg.gpio_chip = argv[++i];
        else if (!strcmp(argv[i], "--gpio-line") && i+1<argc) cfg.gpio_line = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--simulate")) cfg.simulate = true;
    }
    return cfg;
}

// ─── Main ─────────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    Config cfg = parse_args(argc, argv);

    fprintf(stderr, "[bridge] starting — host=%s port=%u simulate=%s\n",
            cfg.host, cfg.port, cfg.simulate ? "yes" : "no");

    // ── RT scheduling ──────────────────────────────────────────────────────────
    struct sched_param sp = { .sched_priority = 50 };
    if (sched_setscheduler(0, SCHED_FIFO, &sp) < 0) {
        perror("[bridge] sched_setscheduler (may need CAP_SYS_NICE or root)");
        // Non-fatal in simulation/dev mode
    }

    // ── Signal handling ────────────────────────────────────────────────────────
    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);

    // ── UDP socket ────────────────────────────────────────────────────────────
    if (udp_open(cfg.host, cfg.port, 4 * 1024 * 1024) < 0) {
        fprintf(stderr, "[bridge] failed to open UDP socket\n");
        return 1;
    }

    // ── SPI + GPIO (only in hardware mode) ───────────────────────────────────
    int spi_fd = -1;
    if (!cfg.simulate) {
        spi_fd = spi_open(cfg.spi_device, cfg.spi_speed);
        if (spi_fd < 0) { fprintf(stderr, "[bridge] SPI open failed\n"); return 1; }

        if (gpio_irq_open(cfg.gpio_chip, cfg.gpio_line) < 0) {
            fprintf(stderr, "[bridge] GPIO open failed\n"); return 1;
        }
    }

    // ── Stats timer ───────────────────────────────────────────────────────────
    time_t last_stats = time(NULL);

    // ── Main RT loop ──────────────────────────────────────────────────────────
    while (s_running) {

        if (cfg.simulate) {
            // Simulate ~100 Hz
            struct timespec ts = { .tv_sec = 0, .tv_nsec = 10000000 }; // 10 ms
            nanosleep(&ts, NULL);

            struct timespec now;
            clock_gettime(CLOCK_MONOTONIC, &now);
            uint32_t ts_us = (uint32_t)(now.tv_sec * 1000000 + now.tv_nsec / 1000);

            sim_build_frame(s_spi_buf, SIM_CHANNEL_COUNT, ts_us);

        } else {
            // ── Wait for Teensy IRQ (rising edge) ────────────────────────────
            if (gpio_irq_wait() < 0) {
                g_stats.gpio_errors++;
                continue;
            }

            // ── Read header first to determine full frame size ────────────────
            if (spi_transfer(spi_fd, s_spi_buf, FRAME_HEADER_SIZE) < 0) {
                g_stats.gpio_errors++;
                continue;
            }

            // Validate magic early
            if (!frame_magic_ok(s_spi_buf)) {
                g_stats.magic_errors++;
                continue;
            }

            uint16_t ch_count = frame_get_channel_count(s_spi_buf);
            if (ch_count < FRAME_MIN_CHANNELS || ch_count > FRAME_MAX_CHANNELS) {
                g_stats.magic_errors++;
                continue;
            }

            // Read remaining frame (values + CRC) — continue from FRAME_HEADER_SIZE
            size_t remaining = (size_t)ch_count * 4 + FRAME_CRC_SIZE;
            if (spi_transfer(spi_fd, s_spi_buf + FRAME_HEADER_SIZE, remaining) < 0) {
                g_stats.gpio_errors++;
                continue;
            }
        }

        // ── Extract channel count from assembled buffer ────────────────────────
        uint16_t ch_count = frame_get_channel_count(s_spi_buf);
        size_t   frame_len = frame_total_size(ch_count);

        // ── CRC validation ────────────────────────────────────────────────────
        if (!frame_crc_ok(s_spi_buf, frame_len)) {
            g_stats.crc_errors++;
            continue;
        }

        // ── Build and send 2 UDP sub-packets ─────────────────────────────────
        size_t len_a = build_sub_packet(s_spi_buf, s_udp_pkt_a, 0, ch_count);
        size_t len_b = build_sub_packet(s_spi_buf, s_udp_pkt_b, 1, ch_count);

        if (udp_send(s_udp_pkt_a, len_a) < 0) g_stats.udp_send_errors++;
        if (udp_send(s_udp_pkt_b, len_b) < 0) g_stats.udp_send_errors++;

        g_stats.frames_sent++;

        // ── Periodic stats print ──────────────────────────────────────────────
        time_t now = time(NULL);
        if ((now - last_stats) >= STATS_INTERVAL_S) {
            stats_print();
            last_stats = now;
        }
    }

    // ── Cleanup ───────────────────────────────────────────────────────────────
    fprintf(stderr, "[bridge] shutting down\n");
    stats_print();
    udp_close();
    if (!cfg.simulate) {
        gpio_irq_close();
        spi_close(spi_fd);
    }
    return 0;
}
