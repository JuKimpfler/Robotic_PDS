/*
 * rate_control.cpp — UART Frame Rate Command Handler
 *
 * Listens on USB Serial for rate commands from the PC backend:
 *   "RATE:100\n"  → set 100 Hz
 *   "RATE:0\n"    → pause
 * Responds with:
 *   "RATE_ACK:100\n"
 *
 * Also handles parameter commands (§GUI.6):
 *   "PARAM_SET:0:1.250\n"
 *   "PARAM_BATCH:0:1.250,1:0.060\n"
 *   "PARAM_SAVE\n"
 *   "PARAM_LOAD:1\n"
 * Responds with:
 *   "PARAM_ACK:OK\n"
 *   "PARAM_ACK:ERR:index_out_of_range\n"
 */

#include "rate_control.h"
#include <Arduino.h>
#include <string.h>
#include <stdlib.h>

// ─── Internal state ───────────────────────────────────────────────────────────

static uint16_t s_target_rate_hz = 100;   ///< Current target frame rate
static bool     s_paused         = false;  ///< True when rate == 0

static char s_rx_buf[256];
static int  s_rx_pos = 0;

// Parameter table — up to 256 float32 params (extended as needed)
#define MAX_PARAMS 256
static float s_params[MAX_PARAMS];
static bool  s_params_init = false;

// ─── Public API ───────────────────────────────────────────────────────────────

void rate_control_init(uint16_t default_rate_hz) {
    s_target_rate_hz = default_rate_hz;
    s_paused = (default_rate_hz == 0);
    if (!s_params_init) {
        memset(s_params, 0, sizeof(s_params));
        s_params_init = true;
    }
    Serial.begin(115200);
}

uint16_t rate_control_get_hz(void) {
    return s_paused ? 0 : s_target_rate_hz;
}

bool rate_control_is_paused(void) {
    return s_paused;
}

float rate_control_get_param(uint8_t index) {
    if (index >= MAX_PARAMS) return 0.0f;
    return s_params[index];
}

// ─── Command parsers ──────────────────────────────────────────────────────────

static void handle_rate_cmd(const char* arg) {
    int hz = atoi(arg);
    if (hz < 0 || hz > 300) {
        Serial.println("RATE_ACK:ERR:out_of_range");
        return;
    }
    s_target_rate_hz = (uint16_t)hz;
    s_paused = (hz == 0);
    Serial.print("RATE_ACK:");
    Serial.println(hz);
}

static void handle_param_set(const char* arg) {
    // arg format: "index:value"
    char* colon = strchr(arg, ':');
    if (!colon) { Serial.println("PARAM_ACK:ERR:bad_format"); return; }
    *colon = '\0';
    int   idx = atoi(arg);
    float val = atof(colon + 1);
    if (idx < 0 || idx >= MAX_PARAMS) {
        Serial.println("PARAM_ACK:ERR:index_out_of_range"); return;
    }
    s_params[idx] = val;
    Serial.println("PARAM_ACK:OK");
}

static void handle_param_batch(const char* arg) {
    // arg format: "0:1.250,1:0.060,2:0.012"
    char buf[256];
    strncpy(buf, arg, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char* token = strtok(buf, ",");
    while (token) {
        char* colon = strchr(token, ':');
        if (colon) {
            *colon = '\0';
            int idx = atoi(token);
            float val = atof(colon + 1);
            if (idx >= 0 && idx < MAX_PARAMS) {
                s_params[idx] = val;
            }
        }
        token = strtok(NULL, ",");
    }
    Serial.println("PARAM_ACK:OK");
}

static void handle_param_save(void) {
    // TODO: persist to EEPROM via EEPROM.put() when hardware is available
    Serial.println("PARAM_ACK:OK");
}

static void handle_param_load(const char* arg) {
    // TODO: load preset slot from EEPROM when hardware is available
    (void)arg;
    Serial.println("PARAM_ACK:OK");
}

// ─── Main poll function — call from loop() ────────────────────────────────────

void rate_control_poll(void) {
    while (Serial.available() > 0) {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r') {
            if (s_rx_pos > 0) {
                s_rx_buf[s_rx_pos] = '\0';
                s_rx_pos = 0;

                // Dispatch command
                if (strncmp(s_rx_buf, "RATE:", 5) == 0) {
                    handle_rate_cmd(s_rx_buf + 5);
                } else if (strncmp(s_rx_buf, "PARAM_SET:", 10) == 0) {
                    handle_param_set(s_rx_buf + 10);
                } else if (strncmp(s_rx_buf, "PARAM_BATCH:", 12) == 0) {
                    handle_param_batch(s_rx_buf + 12);
                } else if (strcmp(s_rx_buf, "PARAM_SAVE") == 0) {
                    handle_param_save();
                } else if (strncmp(s_rx_buf, "PARAM_LOAD:", 11) == 0) {
                    handle_param_load(s_rx_buf + 11);
                }
                // Unknown commands silently ignored
            }
        } else {
            if (s_rx_pos < (int)(sizeof(s_rx_buf) - 1)) {
                s_rx_buf[s_rx_pos++] = c;
            }
        }
    }
}
