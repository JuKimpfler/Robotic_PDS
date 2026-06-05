# Telemetry Streaming System — Implementation TODO

**Spec Version:** 0.2 + GUI Addendum v0.3  
**Started:** 2026-06-05  
**Status:** 🔄 In Progress

---

## PHASE 1 — Project Scaffolding & Directory Structure

- [x] Create TODO.md (this file)
- [ ] Create full directory structure as per §11 + §GUI.7
- [ ] Create `shared/protocol.md` (authoritative frame spec)
- [ ] Create root `.gitignore`

---

## PHASE 2 — Teensy 4.0 Firmware (PlatformIO / C++)

### Files: `teensy/`

- [ ] `platformio.ini` — board=teensy40, framework=arduino
- [ ] `src/frame.h` — SPI frame struct (§5.1), `#pragma pack(push,1)`, little-endian
- [ ] `src/crc16.h` — CRC16-CCITT, poly 0x1021, init 0xFFFF
- [ ] `src/spi_slave.cpp` — SPISlave_T4 / DMA ISR, IRQ pin signaling
- [ ] `src/rate_control.cpp` — UART command handler: RATE:hz\n, RATE_ACK response
- [ ] `src/main.cpp` — main loop, frame generation, --simulate synthetic data

---

## PHASE 3 — RPi Bridge Daemon (C)

### Files: `rpi-bridge/`

- [ ] `CMakeLists.txt` — build config, link libgpiod
- [ ] `toolchain-aarch64.cmake` — cross-compile toolchain for aarch64-linux-gnu-gcc
- [ ] `src/main.c` — entry point, RT scheduling (SCHED_FIFO prio 50), main loop
- [ ] `src/spi.c` / `src/spi.h` — spidev wrapper (30 MHz, DMA)
- [ ] `src/udp.c` / `src/udp.h` — UDP publisher, 4 MB send buffer
- [ ] `src/gpio.c` / `src/gpio.h` — gpiod edge interrupt wrapper (rising edge)
- [ ] `src/protocol.c` / `src/protocol.h` — frame parse, CRC16 verify, sub-packet builder (§5.2)
- [ ] `src/stats.c` / `src/stats.h` — runtime counters (frames_sent, crc_errors)
- [ ] `config/bridge.conf` — host IP, port, SPI speed, GPIO pin
- [ ] `deploy.sh` — scp binary to RPi + systemctl restart

---

## PHASE 4 — PC Backend (Go 1.22+)

### Files: `pc-backend/`

#### Core Setup
- [ ] `go.mod` — module declaration, dependencies:
  - `github.com/rs/zerolog` (logging)
  - `github.com/gorilla/websocket`
  - `github.com/vmihailenco/msgpack/v5` (MessagePack)
  - `github.com/fsnotify/fsnotify` (hot-reload)
  - `github.com/prometheus/client_golang` (metrics)
  - `github.com/xuri/excelize/v2` (xlsx import)
  - `golang.org/x/sys/windows` (Windows API)
  - `go.bug.st/serial` (UART for Teensy)
- [ ] `main.go` — startup: GC tuning (GOGC=400, GOMEMLIMIT=4GiB), config load, component start, graceful shutdown

#### Configuration
- [ ] `config.yaml` — all tunable parameters (§12)
- [ ] `channels.csv` — sample channel definitions (§6.1), 7 example channels

#### Internal Packages
- [ ] `internal/udp/receiver.go` — UDP listener port 9000, 8 MB SO_RCVBUF, THREAD_PRIORITY_TIME_CRITICAL, sub-packet reassembly (5 ms timeout), zero-allocation hot path
- [ ] `internal/ring/buffer.go` — lock-free ring buffer, 1024 slots, atomic ops (§7.2)
- [ ] `internal/pipeline/pipeline.go` — plugin chain, runs after ring buffer pop
- [ ] `internal/pipeline/plugins/plugin.go` — Plugin interface: Name() string, Process(*DataFrame, ChannelMap) *DataFrame
- [ ] `internal/pipeline/plugins/calibration.go` — apply scale+offset from channel map
- [ ] `internal/pipeline/plugins/moving_average.go` — configurable window size
- [ ] `internal/pipeline/plugins/csv_logger.go` — write frames to CSV file
- [ ] `internal/channels/map.go` — ChannelDef struct, ChannelMap type
- [ ] `internal/channels/csv_loader.go` — CSV parser + xlsx import (excelize)
- [ ] `internal/channels/watcher.go` — fsnotify watcher, debounce 500 ms, atomic swap under sync.RWMutex, push channel_map to WS clients
- [ ] `internal/websocket/hub.go` — fan-out hub, ≤8 clients, drop-on-slow (non-blocking send, cap 32), sync.Pool for buffers
- [ ] `internal/websocket/serializer.go` — MessagePack (default) + JSON (format=json query param) encoding
- [ ] `internal/hotspot/hotspot.go` — PowerShell WinRT wrapper (§4), Start/Stop/Status
- [ ] `internal/ratecontrol/serial.go` — UART serial to Teensy: RATE:hz\n, await RATE_ACK; also PARAM_SET/BATCH/SAVE/LOAD
- [ ] `internal/http/server.go` — HTTP server port 8080, all API routes (§7.3 + §GUI.6 params endpoints), serve embedded frontend
- [ ] `internal/metrics/metrics.go` — Prometheus counters (§13), all 9 metrics

#### Windows-Specific
- [ ] Firewall rule auto-open (`netsh advfirewall`) at startup
- [ ] `scripts/install_windows.ps1` — one-time admin install script (firewall rule)

#### Simulate Mode
- [ ] `--simulate` flag: generate synthetic frames at configured Hz without hardware

---

## PHASE 5 — Frontend (Svelte 5 + Vite + Tailwind CSS v4)

### Files: `frontend/`

#### Setup
- [ ] Initialize Svelte 5 + Vite project
- [ ] Install dependencies: svelte, vite, tailwindcss v4, uplot, lucide-svelte, @msgpack/msgpack
- [ ] `vite.config.js` — proxy `/api` → localhost:8080, `/stream` → ws://localhost:9001
- [ ] `tailwind.config.js`
- [ ] `index.html` — SEO meta tags, title

#### Stores (`src/stores/`)
- [ ] `channelData.js` — channelMap, liveValues (Float32Array), minValues, maxValues, frameRate, wsConnected
- [ ] `connection.js` — wsConnected, frameRate, latency, dropped, rpiIp, hotspotState
- [ ] `plotter.js` — selectedChannels, plotterState (STOPPED/RUNNING/PAUSED), buffer
- [ ] `params.js` — paramDefinitions, dirtyParams, presets

#### WebSocket Client (`src/ws/`)
- [ ] `client.js` — connect/reconnect with backoff, message dispatch (frame/channel_map/status/robot_viz/param_map), MessagePack decode

#### Lib (`src/lib/`)
- [ ] `constants.js` — DUMMY_VALUE=9898.0, etc.
- [ ] `formatters.js` — value formatting (precision, units)
- [ ] `csvExport.js` — CSV export for plotter buffer
- [ ] `colormaps.js` — blue→red, green→red colormaps

#### Components (`src/components/`)
- [ ] `Header.svelte` — connection status dot (green/yellow/red), RPi IP, hotspot toggle, FPS, latency, dropped frames
- [ ] `TabBar.svelte` — 4 tabs with icons (📊📈🤖⚙️)
- [ ] `StatusBadge.svelte` — connection/hotspot indicator dot
- [ ] `VirtualTable.svelte` — virtual-scroll table for 500+ channels
- [ ] `ChannelSelector.svelte` — grouped channel picker with filter + select all/deselect all
- [ ] `uPlotWrapper.svelte` — uPlot lifecycle wrapper (create/destroy/update)

#### Tabs (`src/tabs/`)
- [ ] `DataTable.svelte` [IMPLEMENT] — Tab 1: live data table, dummy filter, min/max tracking, group filter dropdown, text filter, column sort, 30 Hz refresh, virtual scroll
- [ ] `Plotter.svelte` [IMPLEMENT] — Tab 2: uPlot live plot, channel selector (≤8 series), STOPPED/RUNNING/PAUSED state machine, time window buttons, CSV export, pause analysis tools
- [ ] `RobotViz.svelte` [SKELETON] — Tab 3: placeholder with robot_viz.json architecture
- [ ] `Parameters.svelte` [SKELETON] — Tab 4: placeholder with parameters.csv architecture

#### App Root
- [ ] `App.svelte` — header + tab bar + tab router, WebSocket init

---

## PHASE 6 — Scripts & Deployment

- [ ] `scripts/setup_rpi.sh` — OS hardening: disable services, CPU governor, kernel buffers, sysctl, systemd service install
- [ ] `scripts/cross_compile_bridge.sh` — cross-compile C bridge for aarch64
- [ ] `scripts/install_windows.ps1` — firewall rule, verify Go install, build frontend

---

## PHASE 7 — Shared Documentation

- [ ] `shared/protocol.md` — authoritative frame format spec (SPI §5.1 + UDP §5.2 + WS §5.3)
- [ ] Update root `README.md` with project overview and getting-started guide

---

## Progress Tracking

| Phase | Status | Notes |
|---|---|---|
| 1 — Scaffolding | 🔄 Started | TODO.md created |
| 2 — Teensy firmware | ⬜ Pending | |
| 3 — RPi Bridge (C) | ⬜ Pending | |
| 4 — PC Backend (Go) | ⬜ Pending | |
| 5 — Frontend (Svelte) | ⬜ Pending | |
| 6 — Scripts | ⬜ Pending | |
| 7 — Docs | ⬜ Pending | |

---

*This TODO is committed to the repository and updated as work progresses.*
