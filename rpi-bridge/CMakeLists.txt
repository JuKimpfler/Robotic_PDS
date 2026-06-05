cmake_minimum_required(VERSION 3.10)
project(spi_bridge C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O3 -Wall -Wextra")

find_package(PkgConfig REQUIRED)
pkg_check_modules(GPIOD REQUIRED libgpiod)

add_executable(spi_bridge
    src/main.c
    src/spi.c
    src/udp.c
    src/gpio.c
    src/protocol.c
    src/stats.c
)

target_include_directories(spi_bridge PRIVATE src)
target_link_libraries(spi_bridge PRIVATE ${GPIOD_LIBRARIES} pthread)
