/*
 * rate_control.h — UART Frame Rate & Parameter Command Handler Interface
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize rate control. Call once from setup().
 * @param default_rate_hz  Initial frame rate (10–300 Hz)
 */
void rate_control_init(uint16_t default_rate_hz);

/**
 * Poll USB Serial for incoming commands. Call from loop().
 * Non-blocking — processes all available bytes.
 */
void rate_control_poll(void);

/**
 * Get the current target frame rate in Hz.
 * Returns 0 if paused.
 */
uint16_t rate_control_get_hz(void);

/**
 * Returns true if frame generation is paused (RATE:0 received).
 */
bool rate_control_is_paused(void);

/**
 * Get a runtime parameter value by index.
 * Returns 0.0f for out-of-range indices.
 */
float rate_control_get_param(uint8_t index);
