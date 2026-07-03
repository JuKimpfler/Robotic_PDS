#pragma once
#include <Arduino.h>

#define I2C_BNO Wire1
#define I2C_IR Wire1
#define I2C_SW Wire1
#define I2C_US Wire1

#define BNO_ADDRESS 0x28

static constexpr uint32_t UART_DBG_BAUD        = 1'000'000UL; // 1 Mbps 