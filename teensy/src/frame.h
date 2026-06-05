#pragma once
#include <stdint.h>

#pragma pack(push, 1)
typedef struct {
  uint16_t magic;
  uint16_t sequence;
  uint32_t timestamp_us;
  uint16_t channel_count;
  uint16_t flags;
  float values[1023];
  uint16_t crc16;
} TelemetryFrame;
#pragma pack(pop)

static const uint16_t FRAME_MAGIC = 0xABCD;
