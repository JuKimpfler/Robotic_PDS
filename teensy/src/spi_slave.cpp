#include "frame.h"

void spi_slave_init() {}
void spi_slave_push_frame(const TelemetryFrame *frame, uint16_t frame_len) {
  (void)frame;
  (void)frame_len;
}
