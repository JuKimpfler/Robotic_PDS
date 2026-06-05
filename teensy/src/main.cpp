/*
 * main.cpp — Teensy 4.0 Telemetry Firmware
 *
 * Responsibilities:
 *  - Generate telemetry frames at configurable rate (10–300 Hz)
 *  - Fill frame buffer with sensor values (or synthetic data in --simulate mode)
 *  - Compute CRC16-CCITT and assemble frame
 *  - Signal RPi via IRQ + SPI slave DMA transfer
 *  - Handle UART rate/parameter commands from PC backend
 *
 * Compile-time flags:
 *  -DSIMULATE   Generate synthetic sine wave data instead of real sensor reads
 */

#include <Arduino.h>
#include "frame.h"
#include "crc16.h"
#include "spi_slave.h"
#include "rate_control.h"

// ─── Configuration ────────────────────────────────────────────────────────────

/** Number of telemetry channels. Must match channels.csv on the PC. */
static constexpr uint16_t CHANNEL_COUNT     = 500;

/** Default frame rate at startup (Hz). Overridden by RATE: command. */
static constexpr uint16_t DEFAULT_RATE_HZ   = 100;

// ─── Frame buffer ─────────────────────────────────────────────────────────────

/** Total frame size for CHANNEL_COUNT channels */
static constexpr size_t FRAME_SIZE = FRAME_TOTAL_SIZE(CHANNEL_COUNT);

/** Working frame buffer — populated each cycle */
static uint8_t  s_frame_buf[FRAME_SIZE];
static uint16_t s_sequence = 0;

// ─── Timing ───────────────────────────────────────────────────────────────────

static uint32_t s_last_frame_us = 0;

// ─── Simulate mode synthetic data ─────────────────────────────────────────────

#ifdef SIMULATE
static float s_sim_phase = 0.0f;

static void fill_simulate_values(float* values, uint16_t count, uint32_t ts_us) {
    // Generate distinct sine waves per channel group for visual variety
    for (uint16_t i = 0; i < count; i++) {
        float freq  = 1.0f + (float)(i % 10) * 0.5f;
        float ampl  = 500.0f + (float)(i % 4) * 500.0f;
        values[i]   = ampl * sinf(2.0f * (float)M_PI * freq * (float)ts_us * 1e-6f
                                  + (float)i * 0.1f);
    }
    // Simulate some inactive channels (dummy value)
    if (count > 10) {
        values[7] = DUMMY_VALUE;
        values[8] = DUMMY_VALUE;
    }
}
#else
// ─── Real sensor fill — replace with actual sensor reads ──────────────────────
static void fill_sensor_values(float* values, uint16_t count) {
    // TODO: populate from actual hardware (encoders, IMU, etc.)
    // Placeholder: output zeros until hardware is wired
    for (uint16_t i = 0; i < count; i++) {
        values[i] = 0.0f;
    }
}
#endif  // SIMULATE

// ─── Frame assembly ───────────────────────────────────────────────────────────

static void build_frame(uint32_t ts_us) {
    FrameHeader* hdr = (FrameHeader*)s_frame_buf;
    hdr->magic         = FRAME_MAGIC;
    hdr->sequence      = s_sequence++;
    hdr->timestamp_us  = ts_us;
    hdr->channel_count = CHANNEL_COUNT;
    hdr->flags         = 0;  // frame_rate_ack set below if applicable

    float* values = frame_values(s_frame_buf);

#ifdef SIMULATE
    fill_simulate_values(values, CHANNEL_COUNT, ts_us);
#else
    fill_sensor_values(values, CHANNEL_COUNT);
#endif

    // Compute CRC over header + values (everything before CRC field)
    size_t crc_offset = FRAME_HEADER_SIZE + CHANNEL_COUNT * sizeof(float);
    crc16_write(s_frame_buf, crc_offset);
}

// ─── Setup ────────────────────────────────────────────────────────────────────

void setup() {
    // Initialize USB Serial for rate/parameter commands
    rate_control_init(DEFAULT_RATE_HZ);

    // Initialize SPI slave
    spi_slave_init(CHANNEL_COUNT);

    s_last_frame_us = micros();

#ifdef SIMULATE
    Serial.println("Teensy telemetry firmware — SIMULATE mode");
#else
    Serial.println("Teensy telemetry firmware — HARDWARE mode");
#endif
    Serial.print("Channels: ");
    Serial.println(CHANNEL_COUNT);
    Serial.print("Default rate: ");
    Serial.print(DEFAULT_RATE_HZ);
    Serial.println(" Hz");
}

// ─── Loop ─────────────────────────────────────────────────────────────────────

void loop() {
    // 1. Poll for UART commands from PC backend (non-blocking)
    rate_control_poll();

    uint16_t target_hz = rate_control_get_hz();

    // 2. If paused, nothing to do
    if (target_hz == 0) {
        delay(10);
        return;
    }

    // 3. Rate limiting — busy-wait for next frame deadline
    uint32_t period_us = 1000000UL / target_hz;
    uint32_t now_us    = micros();
    if ((now_us - s_last_frame_us) < period_us) {
        return;  // Not yet time for next frame
    }
    s_last_frame_us = now_us;

    // 4. Wait for SPI slave to be ready (previous transfer done)
    //    Timeout after 2× period to avoid deadlock
    uint32_t wait_start = micros();
    while (!spi_slave_ready()) {
        if ((micros() - wait_start) > (period_us * 2)) {
            // Transfer stuck — abort previous and continue
            break;
        }
    }

    // 5. Build and send frame
    build_frame(now_us);
    spi_slave_send_frame(s_frame_buf, FRAME_SIZE);
}
