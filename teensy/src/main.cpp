#include <Arduino.h>
#include "frame.h"
#include "crc16.h"

void spi_slave_init();
void spi_slave_push_frame(const TelemetryFrame *frame, uint16_t frame_len);
uint16_t rate_control_get();
void rate_control_poll();

static TelemetryFrame frame;
static uint16_t seq = 0;
static const uint16_t channel_count = 500;

void setup() {
  Serial.begin(115200);
  spi_slave_init();
}

void loop() {
  rate_control_poll();
  frame.magic = FRAME_MAGIC;
  frame.sequence = seq++;
  frame.timestamp_us = micros();
  frame.channel_count = channel_count;
  frame.flags = 0;
  for (uint16_t i = 0; i < channel_count; ++i) {
    frame.values[i] = (float)i;
  }
  uint32_t payload_len = 12 + channel_count * 4;
  frame.crc16 = crc16_ccitt((const uint8_t *)&frame, payload_len);
  spi_slave_push_frame(&frame, payload_len + 2);

  uint16_t hz = rate_control_get();
  if (hz == 0) {
    delay(1);
  } else {
    delay(1000 / hz);
  }
}
