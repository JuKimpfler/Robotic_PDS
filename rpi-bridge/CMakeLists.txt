cmake_minimum_required(VERSION 3.16)
project(spi_bridge C)

set(CMAKE_C_STANDARD 11)

# ── Release build with ARM Cortex-A53 optimizations ──────────────────────────
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_compile_options(
    -O3
    -march=armv8-a
    -Wall
    -Wextra
    -Wno-unused-parameter
)

# ── Sources ───────────────────────────────────────────────────────────────────
add_executable(spi_bridge
    src/main.c
    src/spi.c
    src/udp.c
    src/gpio.c
    src/protocol.c
    src/stats.c
)

# ── Include dirs ──────────────────────────────────────────────────────────────
target_include_directories(spi_bridge PRIVATE src)

# ── Link libraries ────────────────────────────────────────────────────────────
# libgpiod  — GPIO edge interrupt (apt: libgpiod-dev)
# libm      — math functions (sinf in simulate mode)
target_link_libraries(spi_bridge
    gpiod
    m
)

# ── Install target ────────────────────────────────────────────────────────────
install(TARGETS spi_bridge DESTINATION /usr/local/bin)
