# toolchain-aarch64.cmake
# Cross-compilation toolchain file for aarch64-linux-gnu (Raspberry Pi Zero 2W)
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt install gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu
#   sudo apt install libgpiod-dev:arm64  (or build libgpiod from source for aarch64)
#
# Usage:
#   cmake -DCMAKE_TOOLCHAIN_FILE=../toolchain-aarch64.cmake \
#         -DCMAKE_BUILD_TYPE=Release \
#         -B build && cmake --build build -j4

set(CMAKE_SYSTEM_NAME    Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

# Cross-compiler
set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

# Sysroot — adjust if you have a dedicated RPi sysroot
# Leave empty to rely on multiarch headers installed via apt
# set(CMAKE_SYSROOT /path/to/rpi-sysroot)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
