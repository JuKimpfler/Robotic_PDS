/* gpio.h — libgpiod edge interrupt wrapper */
#pragma once

#include <stdbool.h>

/**
 * Open GPIO chip and request a rising-edge event on a specific line.
 * @param chip_path  e.g. "/dev/gpiochip0"
 * @param line_num   GPIO line number (BCM numbering)
 * @return           0 on success, -1 on error
 */
int gpio_irq_open(const char* chip_path, unsigned int line_num);

/**
 * Block until a rising-edge event is detected on the IRQ line.
 * Returns immediately when the event arrives.
 * @return  0 on event, -1 on error
 */
int gpio_irq_wait(void);

/** Close GPIO resources. */
void gpio_irq_close(void);
