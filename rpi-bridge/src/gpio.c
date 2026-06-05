/* gpio.c — libgpiod rising-edge IRQ detection */

#include "gpio.h"
#include <stdio.h>
#include <gpiod.h>
#include <errno.h>

static struct gpiod_chip* s_chip = NULL;
static struct gpiod_line* s_line = NULL;

int gpio_irq_open(const char* chip_path, unsigned int line_num) {
    s_chip = gpiod_chip_open(chip_path);
    if (!s_chip) {
        perror("gpio_irq_open: gpiod_chip_open");
        return -1;
    }

    s_line = gpiod_chip_get_line(s_chip, line_num);
    if (!s_line) {
        perror("gpio_irq_open: gpiod_chip_get_line");
        gpiod_chip_close(s_chip);
        return -1;
    }

    // Request rising-edge events (IRQ pin goes HIGH when Teensy frame is ready)
    if (gpiod_line_request_rising_edge_events(s_line, "spi-bridge") < 0) {
        perror("gpio_irq_open: gpiod_line_request_rising_edge_events");
        gpiod_chip_close(s_chip);
        return -1;
    }

    return 0;
}

int gpio_irq_wait(void) {
    struct gpiod_line_event event;

    // Block indefinitely until rising edge
    int ret = gpiod_line_event_wait(s_line, NULL);
    if (ret < 0) {
        perror("gpio_irq_wait: gpiod_line_event_wait");
        return -1;
    }

    // Consume the event
    if (gpiod_line_event_read(s_line, &event) < 0) {
        perror("gpio_irq_wait: gpiod_line_event_read");
        return -1;
    }

    return 0;
}

void gpio_irq_close(void) {
    if (s_line)  gpiod_line_release(s_line);
    if (s_chip)  gpiod_chip_close(s_chip);
    s_line = NULL;
    s_chip = NULL;
}
