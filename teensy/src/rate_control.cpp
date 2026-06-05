#include <Arduino.h>

static uint16_t g_rate_hz = 100;

uint16_t rate_control_get() { return g_rate_hz; }

void rate_control_set(uint16_t hz) { g_rate_hz = hz; }

void rate_control_poll() {
  if (!Serial.available()) {
    return;
  }
  String cmd = Serial.readStringUntil('\n');
  if (cmd.startsWith("RATE:")) {
    int hz = cmd.substring(5).toInt();
    if (hz < 0) {
      hz = 0;
    }
    g_rate_hz = (uint16_t)hz;
    Serial.print("RATE_ACK:");
    Serial.println(g_rate_hz);
  }
}
