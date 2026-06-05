# Telemetry Streaming System - Implementation TODO

## Phase 1: Project Skeleton & Basic Setup
- [ ] Create directory structure (`teensy/`, `rpi-bridge/`, `pc-backend/`, `frontend/`, `shared/`, `scripts/`)
- [ ] Create `shared/protocol.md` from the README specification

## Phase 2: Shared Configs & Data Definitions
- [ ] Create `pc-backend/config.yaml`
- [ ] Create `pc-backend/channels.csv`
- [ ] Create `frontend/src/lib/constants.js`

## Phase 3: RPi Bridge (C)
- [ ] Create `rpi-bridge/CMakeLists.txt` and `toolchain-aarch64.cmake`
- [ ] Implement C UDP bridge (`rpi-bridge/src/main.c`, `spi.c`, `udp.c`, etc.)

## Phase 4: PC Backend (Go)
- [ ] Initialize Go module (`go mod init pc-backend`)
- [ ] Implement lock-free ring buffer
- [ ] Implement UDP Receiver & Parser
- [ ] Implement HTTP & WebSocket Servers
- [ ] Implement Channel Map Loading (CSV)
- [ ] Implement Mobile Hotspot Control (PowerShell WinRT)
- [ ] Main entrypoint

## Phase 5: Frontend (Svelte + uPlot)
- [ ] Initialize Vite + Svelte 5 project
- [ ] Setup Tailwind CSS
- [ ] Implement WebSocket client and Stores
- [ ] Implement Tab 1 (DataTable)
- [ ] Implement Tab 2 (Plotter)
- [ ] Skeleton for Tabs 3 & 4

## Phase 6: Teensy Firmware (C++)
- [ ] PlatformIO project initialization
- [ ] Implement SPI Slave with DMA (or placeholder)
- [ ] Frame generation and rate control
