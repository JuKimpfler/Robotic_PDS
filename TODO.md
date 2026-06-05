# Telemetry Streaming System — Implementation TODO

**Spec Version:** 0.2 + GUI Addendum v0.3  
**Started:** 2026-06-05  
**Last Updated:** 2026-06-05  
**Status:** ✅ Implementierung abgeschlossen (Simulationsmodus einsatzbereit)

---

## PHASE 1 — Project Scaffolding & Directory Structure

- [x] Create TODO.md (this file)
- [x] Create full directory structure as per §11 + §GUI.7
- [x] Create `shared/protocol.md` (authoritative frame spec)
- [x] Create root `.gitignore`

---

## PHASE 2 — Teensy 4.0 Firmware (PlatformIO / C++)

### Files: `teensy/`

- [x] `platformio.ini` — board=teensy40, framework=arduino
- [x] `src/frame.h` — SPI frame struct (§5.1), `#pragma pack(push,1)`, little-endian
- [x] `src/crc16.h` — CRC16-CCITT, poly 0x1021, init 0xFFFF
- [x] `src/spi_slave.cpp` — SPISlave_T4 / DMA ISR, IRQ pin signaling
- [x] `src/rate_control.cpp` — UART command handler: RATE:hz\n, RATE_ACK response
- [x] `src/main.cpp` — main loop, frame generation, --simulate synthetic data

---

## PHASE 3 — RPi Bridge Daemon (C)

### Files: `rpi-bridge/`

- [x] `CMakeLists.txt` — build config, link libgpiod
- [x] `toolchain-aarch64.cmake` — cross-compile toolchain for aarch64-linux-gnu-gcc
- [x] `src/main.c` — entry point, RT scheduling (SCHED_FIFO prio 50), main loop
- [x] `src/spi.c` / `src/spi.h` — spidev wrapper (30 MHz, DMA)
- [x] `src/udp.c` / `src/udp.h` — UDP publisher, 4 MB send buffer
- [x] `src/gpio.c` / `src/gpio.h` — gpiod edge interrupt wrapper (rising edge)
- [x] `src/protocol.c` / `src/protocol.h` — frame parse, CRC16 verify, sub-packet builder (§5.2)
- [x] `src/stats.c` / `src/stats.h` — runtime counters (frames_sent, crc_errors)
- [x] `config/bridge.conf` — host IP, port, SPI speed, GPIO pin
- [x] `deploy.sh` — scp binary to RPi + systemctl restart

---

## PHASE 4 — PC Backend (Go 1.22+)

### Files: `pc-backend/`

#### Core Setup
- [x] `go.mod` — module declaration, all dependencies
- [x] `main.go` — startup: GC tuning, config load, component start, graceful shutdown, `--simulate`

#### Configuration
- [x] `config.yaml` — all tunable parameters (§12)
- [x] `channels.csv` — sample channel definitions (§6.1)

#### Internal Packages
- [x] `internal/udp/receiver.go` — UDP listener, reassembly, TIME_CRITICAL
- [x] `internal/ring/buffer.go` — lock-free ring buffer, 1024 slots
- [x] `internal/pipeline/` — plugin chain + calibration, moving_average, csv_logger
- [x] `internal/channels/` — map, csv_loader, watcher (fsnotify, 500 ms debounce)
- [x] `internal/websocket/` — hub, serializer, dedicated server port 9001
- [x] `internal/hotspot/hotspot.go` — PowerShell WinRT wrapper
- [x] `internal/ratecontrol/` — serial UART + parameters + presets
- [x] `internal/http/server.go` — HTTP port 8080, all API routes (§7.3 + §GUI.6)
- [x] `internal/metrics/metrics.go` — Prometheus counters (§13), all 9 metrics

#### Windows-Specific
- [x] Firewall rule auto-open (`netsh advfirewall`) at startup
- [x] `scripts/install_windows.ps1` — one-time admin install script

#### Simulate Mode
- [x] `--simulate` flag: synthetic frames at configured Hz

---

## PHASE 5 — Frontend (Svelte 5 + Vite + Tailwind CSS v4)

### Files: `frontend/`

- [x] Svelte 5 + Vite project with all dependencies
- [x] `vite.config.js` — proxy `/api` → :8080, `/stream` → ws://localhost:9001, outDir → pc-backend/frontend/dist
- [x] Stores: channelData, connection, plotter, params
- [x] WebSocket client with MessagePack + JSON, reconnect backoff
- [x] Tab 1 DataTable — virtual scroll, dummy filter, min/max, 30 Hz refresh
- [x] Tab 2 Plotter — uPlot, channel selector (≤8), STOPPED/RUNNING/PAUSED, CSV export
- [x] Tab 3 RobotViz — skeleton placeholder
- [x] Tab 4 Parameters — functional editor with dirty tracking + API integration
- [x] Header, TabBar, VirtualTable, ChannelSelector, uPlotWrapper, StatusBadge
- [x] lib: constants, formatters, csvExport, colormaps

---

## PHASE 6 — Scripts & Deployment

- [x] `scripts/setup_rpi.sh`
- [x] `scripts/cross_compile_bridge.sh`
- [x] `scripts/install_windows.ps1` — firewall, Go check, frontend build

---

## PHASE 7 — Shared Documentation

- [x] `shared/protocol.md` — authoritative frame format spec
- [x] Update root `README.md` with project overview and getting-started guide

---

## Progress Tracking

| Phase | Status | Notes |
|---|---|---|
| 1 — Scaffolding | ✅ Done | protocol.md, .gitignore |
| 2 — Teensy firmware | ✅ Done | SIMULATE build flag in platformio.ini |
| 3 — RPi Bridge (C) | ✅ Done | --simulate flag |
| 4 — PC Backend (Go) | ✅ Done | WS port 9001, param presets API |
| 5 — Frontend (Svelte) | ✅ Done | JSON field names fixed, WS client |
| 6 — Scripts | ✅ Done | install_windows.ps1 erweitert |
| 7 — Docs | ✅ Done | README.md + protocol.md |

---

## Bekannte Einschränkungen / Nächste Schritte

- Tab 3 (RobotViz): Vollimplementierung wartet auf `robot_viz.json` + Assets
- Teensy EEPROM: `PARAM_SAVE`/`PARAM_LOAD` sind Stubs bis Hardware verfügbar
- Hardware-Test: End-to-End mit echtem Teensy/RPi noch nicht verifiziert
- Go/Node müssen lokal installiert sein (`go 1.22+`, `node 18+`)

---

*Zuletzt aktualisiert: 2026-06-05 — Alle Phasen implementiert, Simulate-Modus einsatzbereit.*
