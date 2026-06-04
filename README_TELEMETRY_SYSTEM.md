# Telemetry Streaming System — Project Specification (AI Agent Reference)

**Version:** 0.1-draft  
**Status:** Planning Phase  
**Last Updated:** 2026-06-05  
**GUI Specification:** Pending (separate document, to be added)

---

## 1. Project Overview

A high-throughput, low-latency telemetry streaming pipeline for real-time data acquisition and browser-based visualization.

A **Teensy 4.0** microcontroller produces telemetry data (500 × float32 per frame at ≥ 100 Hz), transfers it via **SPI** to a **Raspberry Pi Zero 2W** acting as a wireless bridge, which forwards the data via **UDP over WiFi** to a **PC/Laptop** running a **Go** backend that serves a modern browser-based frontend over WebSocket.

### Core Design Philosophy

> **Performance-first. Resource efficiency is NOT a priority.**  
> The system MUST be dimensioned for **2–3× the minimum bandwidth requirement** to guarantee stable, optimal performance at the 200 KB/s operating point.

### Performance Requirements

| Metric | Minimum (Guaranteed) | Design Target (Headroom) |
|---|---|---|
| Payload bandwidth | **200 KB/s** | **400–600 KB/s** |
| Frame rate | 100 Hz | 200–300 Hz |
| Payload per frame | 500 × float32 = 2000 B | 500 × float32 = 2000 B |
| SPI transfer latency | < 1 ms | < 0.6 ms |
| UDP network latency | < 1 ms | < 0.5 ms |
| End-to-end latency (Teensy → Browser) | < 10 ms | < 5 ms |
| PC CPU budget | Unrestricted | Unrestricted |
| PC RAM budget | Unrestricted | Unrestricted |

---

## 2. System Architecture

```
┌────────────────────────┐   SPI (30 MHz, DMA)    ┌─────────────────────────┐
│      Teensy 4.0        │ ──────────────────────▶ │   Raspberry Pi Zero 2W  │
│  (PlatformIO / C++)    │ ◀── IRQ / CS handshake  │   (Bridge Node)         │
│                        │                         │                         │
│  Role: SPI Slave       │                         │  Role: SPI Master       │
│  - Generates 500 f32   │                         │  - Polls via IRQ        │
│  - 100 Hz baseline     │                         │  - UDP Publisher        │
│  - Binary frames       │                         │  - RT-scheduled process │
│  - CRC16 per frame     │                         │  - Go (cross-compiled)  │
│  - IRQ: data ready     │                         │  - CPU governor: perf.  │
└────────────────────────┘                         └────────────┬────────────┘
                                                                │
                                                    UDP unicast (port: TBD)
                                                    ~2000 B/packet @ 100+ pkt/s
                                                    WiFi 802.11n / 802.11ac
                                                                │
                                                   ┌────────────▼────────────┐
                                                   │      PC / Laptop        │
                                                   │                         │
                                                   │   Go Backend            │
                                                   │   - UDP Receiver        │
                                                   │   - Lock-free RingBuf   │
                                                   │   - Data Pipeline       │
                                                   │   - WebSocket Hub       │
                                                   │   - HTTP File Server    │
                                                   │   - Plugin system       │
                                                   └────────────┬────────────┘
                                                                │
                                                    ws://localhost:PORT/stream
                                                                │
                                                   ┌────────────▼────────────┐
                                                   │   Browser Frontend      │
                                                   │   (Spec: TBD)           │
                                                   │   - Live Plotter        │
                                                   │   - Data Dashboard      │
                                                   │   - uPlot / custom      │
                                                   └─────────────────────────┘
```

---

## 3. Hardware Stack

### 3.1 Teensy 4.0

| Property | Value |
|---|---|
| MCU | NXP iMXRT1062, ARM Cortex-M7 @ 600 MHz |
| Framework | PlatformIO + Teensyduino |
| SPI Role | **Slave** |
| SPI Bus | SPI0 (MOSI=11, MISO=12, SCK=13, CS=10) |
| IRQ/Handshake | Dedicated GPIO output → RPi GPIO (signals "frame ready") |
| Max SPI speed | up to 40–50 MHz (driven by RPi master) |
| Library | `SPISlave_T4` or custom DMA-based ISR |

**Timing contract:**
```
Teensy fills frame buffer
  → asserts IRQ pin HIGH
  → RPi drives CS LOW, initiates clock
  → SPI DMA transfer (~0.54 ms @ 30 MHz)
  → RPi drives CS HIGH
  → Teensy deasserts IRQ, prepares next frame
```

---

### 3.2 Raspberry Pi Zero 2W

| Property | Value |
|---|---|
| SoC | BCM2710A1, Quad-core ARM Cortex-A53 @ 1 GHz |
| RAM | 512 MB |
| OS | Raspberry Pi OS Lite 64-bit (headless) |
| SPI interface | `/dev/spidev0.0` via `spidev` kernel module |
| SPI role | **Master** |
| SPI clock | 25–30 MHz |
| WiFi | 802.11n 2.4 GHz (onboard) |
| Bridge language | **Go** (cross-compiled from PC: `GOARCH=arm64 GOOS=linux`) |
| Scheduling | `SCHED_FIFO` real-time priority for bridge process |
| CPU governor | `performance` — frequency scaling disabled |

**Required `/boot/config.txt` entries:**
```ini
dtparam=spi=on
dtoverlay=spi0-1cs
core_freq=250          # Stabilize SPI clock source
force_turbo=1          # Disable dynamic underclocking
```

**OS hardening for real-time performance:**
```bash
# Disable unnecessary services
systemctl disable bluetooth avahi-daemon triggerhappy

# Set CPU governor at boot (add to /etc/rc.local or systemd unit)
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Increase SPI and UDP kernel buffers
echo "net.core.rmem_max = 67108864" >> /etc/sysctl.conf
echo "net.core.wmem_max = 67108864" >> /etc/sysctl.conf
sysctl -p
```

---

### 3.3 PC / Laptop (Host)

| Property | Value |
|---|---|
| OS | TBD — Linux preferred; Windows/macOS supported |
| Runtime | Go 1.22+ |
| Network | WiFi or Ethernet to same L2 network as RPi |
| RAM | Minimum 4 GB (no upper limit imposed) |
| Frontend | Browser (Chrome/Firefox) |

---

## 4. Communication Protocol Specification

### 4.1 SPI Frame Format (Teensy → RPi)

All fields little-endian. Struct is `#pragma pack(push, 1)` packed.

```
Offset   Size    Type        Field              Description
──────   ────    ──────      ──────             ──────────────────────────────
0        2       uint16      magic              Sync marker: 0xABCD
2        2       uint16      sequence           Wrapping frame counter (0–65535)
4        4       uint32      timestamp_us       Teensy micros() at frame capture
8        2       uint16      payload_count      Always 500 in current version
10       2       uint16      flags              Reserved, set 0x0000
12       2000    float32[500] values            Sensor/telemetry payload (IEEE 754)
2012     2       uint16      crc16              CRC16-CCITT over bytes [0..2011]
──────
Total:   2014 bytes per frame
```

**CRC16 variant:** CRC16-CCITT, polynomial `0x1021`, initial value `0xFFFF`.

---

### 4.2 UDP Packet Layer (RPi → PC)

#### ⚠️ MTU Constraint

Standard WiFi MTU = **1500 bytes**. A 2014-byte SPI frame exceeds this.  
**Solution A (preferred):** Split each SPI frame into **2 UDP sub-packets** (no IP fragmentation, lower loss risk):

```
Sub-packet structure (per UDP datagram):
Offset   Size   Type       Field
──────   ────   ──────     ──────
0        2      uint16     magic        0xCDAB
2        2      uint16     frame_seq    Matches SPI frame sequence
4        1      uint8      sub_id       0 = first half, 1 = second half
5        1      uint8      sub_count    Always 2
6        2      uint16     payload_len  Bytes of float data in this packet (1000)
8        1000   uint8      payload      250 × float32 (raw bytes)
1008     2      uint16     crc16        CRC16-CCITT over bytes [0..1007]
──────
Total per sub-packet: 1010 bytes ✅ (< 1500 MTU)
```

**Solution B (alternative):** Enable jumbo frames (MTU 9000) on AP and PC NIC — single packet. Only viable if network infrastructure supports it.

#### PC-Side Socket Configuration:
```go
conn, err := net.ListenUDP("udp4", &net.UDPAddr{Port: 9000})
// Set 8 MB receive buffer (performance-first)
rawConn, _ := conn.SyscallConn()
rawConn.Control(func(fd uintptr) {
    syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET,
        syscall.SO_RCVBUF, 8*1024*1024)
})
```

---

### 4.3 WebSocket Layer (PC Backend → Browser)

**Endpoint:** `ws://localhost:{PORT}/stream`

**Wire format — Binary MessagePack** (preferred for high-frequency use):
```
{
  "seq":    uint16,          // frame sequence number
  "ts_us":  uint32,          // Teensy timestamp
  "values": [float32 × 500]  // telemetry payload
}
```

**Fallback — JSON** (for debugging / compatibility):
```json
{ "seq": 12345, "ts_us": 9876543, "values": [0.1, 0.2, "..."] }
```

Frontend selects format via initial handshake query parameter: `?format=msgpack|json`

---

## 5. PC Backend — Software Architecture

### 5.1 Technology Stack

**Language: Go 1.22+**

| Criterion | Rationale |
|---|---|
| Concurrency | Goroutine-per-concern — clean, minimal boilerplate |
| UDP throughput | `net.UDPConn` with pre-allocated buffers → zero alloc hot path |
| GC impact | Mitigated via `sync.Pool`, pre-allocated ring buffer, `GOGC=400` |
| Extensibility | Interface-based plugin system, config-driven |
| WebSocket | `nhooyr.io/websocket` (low-dependency, performant) |
| Logging | `zerolog` (structured JSON, zero-allocation) |
| Config | `viper` + `config.yaml` |
| Metrics | Prometheus-compatible `/metrics` endpoint (via `promhttp`) |

### 5.2 Component Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Go Backend Process                             │
│                                                                        │
│  ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │  UDP Receiver   │    │   Ring Buffer    │    │  WebSocket Hub   │  │
│  │  goroutine      │───▶│  (lock-free)     │───▶│  goroutine       │  │
│  │  port: 9000     │    │  1024 frames     │    │  fan-out to N    │  │
│  │  pre-alloc buf  │    │  atomic head/tail│    │  clients (≤ 8)   │  │
│  └─────────────────┘    └────────┬─────────┘    └──────────────────┘  │
│                                  │                        │            │
│                                  ▼                        │ ws://       │
│                         ┌──────────────────┐             ▼            │
│                         │  Data Pipeline   │   ┌──────────────────┐   │
│                         │  - seq gap check │   │ HTTP File Server │   │
│                         │  - CRC verify    │   │ serves frontend/ │   │
│                         │  - drop counter  │   │ port: 8080       │   │
│                         │  - plugin chain  │   └──────────────────┘   │
│                         └──────────────────┘                          │
│                                  │                                     │
│  ┌───────────────────────────────▼──────────────────────────────────┐ │
│  │  Plugin Interface (extensibility point)                          │ │
│  │  type Plugin interface {                                         │ │
│  │      Name() string                                               │ │
│  │      Process(frame *DataFrame) *DataFrame                        │ │
│  │  }                                                               │ │
│  │                                                                  │ │
│  │  Example plugins: Calibration, Filtering, Channel Mapping,       │ │
│  │  Logging-to-disk, Anomaly Detection, Unit Conversion            │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Critical Go Implementation Patterns

#### Lock-Free Ring Buffer (zero allocation):
```go
const RingSize = 1024 // Must be power of 2

type RingBuffer struct {
    frames [RingSize]DataFrame
    head   atomic.Uint64
    tail   atomic.Uint64
}

func (rb *RingBuffer) Push(f *DataFrame) bool {
    head := rb.head.Load()
    next := (head + 1) & (RingSize - 1)
    if next == rb.tail.Load() { return false } // full, drop
    rb.frames[head] = *f
    rb.head.Store(next)
    return true
}
```

#### Zero-Allocation UDP Receive Loop:
```go
buf := make([]byte, 65535)           // pre-allocated once, never reallocated
for {
    n, _, err := conn.ReadFromUDP(buf)
    if err != nil { continue }
    var frame DataFrame
    parseFrameInPlace(buf[:n], &frame) // no heap alloc
    ringBuf.Push(&frame)
}
```

#### WebSocket Broadcast (non-blocking fan-out):
```go
type Client struct {
    ch chan []byte // buffered, size 32
}
// Slow clients: drop frame, never block the producer goroutine
func (hub *Hub) Broadcast(data []byte) {
    for _, c := range hub.clients {
        select {
        case c.ch <- data:
        default: // client too slow — drop frame, increment counter
        }
    }
}
```

#### GC Tuning for low-latency:
```go
// main.go init
os.Setenv("GOGC", "400")         // Reduce GC frequency
os.Setenv("GOMEMLIMIT", "2GiB")  // Cap memory, trigger GC before OOM
```

---

## 6. RPi Bridge Software Architecture

### Language: Go (cross-compiled)

```
GOARCH=arm64 GOOS=linux go build -o rpi-bridge ./rpi-bridge/
```

**Bridge main loop (conceptual):**
```go
for {
    waitForIRQ(irqPin)               // Block until Teensy signals ready
    raw := spi.ReadBytes(2014)       // DMA SPI transfer
    if !validateCRC(raw) {
        stats.crcErrors++
        continue
    }
    frame := parseFrame(raw)
    udp.SendFrame(frame)             // Non-blocking, pre-serialized
    stats.framesForwarded++
}
```

**Process scheduling (systemd unit):**
```ini
[Service]
ExecStart=/usr/local/bin/rpi-bridge
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=50
Restart=always
RestartSec=1
```

---

## 7. Latency Budget Analysis

```
Teensy: frame ready
  │
  ├─ [asserts IRQ pin]                    ~1 µs
  │
RPi: detects IRQ (GPIO poll / interrupt)
  ├─ [IRQ detection + CS assert]          ~50–200 µs (depends on polling rate)
  ├─ [SPI DMA transfer @ 30 MHz]          ~540 µs   ← 0.54 ms
  ├─ [CRC validation (SW)]               ~10 µs
  ├─ [serialize + sendmsg() syscall]      ~50 µs
  │
WiFi stack (RPi → AP → PC)
  ├─ [WiFi TX queuing + air time]         ~300–800 µs
  │
PC kernel: UDP receive
  ├─ [kernel RX buffer → userspace]       ~20–50 µs
  ├─ [parse + ring buffer write]          ~5 µs
  ├─ [WebSocket encode + send]            ~50–100 µs
  │
Browser
  └─ [requestAnimationFrame + plot]       ~1–16 ms (display-limited)

──────────────────────────────────────────────────────
SPI transfer latency:                 < 0.6 ms  ✅
UDP network latency (RPi → PC):      < 1.0 ms  ✅  (local WiFi)
Full pipeline (excl. display):       < 3 ms    ✅
Full pipeline (incl. 60Hz display):  < 20 ms   ✅
```

**Bottleneck:** IRQ detection latency on RPi (50–200 µs). Use `pigpio` with DMA-timed GPIO polling or `gpiod` edge interrupt for < 100 µs response.

---

## 8. Compression Decision

| Scenario | Compression | Rationale |
|---|---|---|
| Normal operation (wired / strong WiFi) | **None** | 200 KB/s << WiFi capacity; no latency overhead |
| Congested WiFi / weak signal | **float16 quantization** | Halves bandwidth; zero algorithm latency |
| Archival / disk logging | **LZ4** | 500 MB/s compression speed; ~30% reduction |

**float16 quantization (optional, toggle via config):**
```go
// Encode: float32 → uint16 with configurable scale/offset per channel
packed[i] = uint16((value - offset) / scale * 65535)
// Bandwidth: 500 × 2 bytes = 1000 B/frame → 100 KB/s (50% reduction)
```

Default: **compression disabled**.

---

## 9. Project Directory Structure

```
project-root/
│
├── teensy/                        # PlatformIO project
│   ├── platformio.ini             # board = teensy40, framework = arduino
│   └── src/
│       ├── main.cpp               # Main loop, SPI slave init
│       ├── spi_slave.cpp          # SPISlave_T4 / DMA ISR implementation
│       ├── frame.h                # DataFrame struct — single source of truth
│       └── crc16.h                # CRC16-CCITT implementation
│
├── rpi-bridge/                    # Raspberry Pi bridge daemon (Go)
│   ├── main.go                    # Entry point, GPIO IRQ setup
│   ├── spi.go                     # /dev/spidev0.0 wrapper
│   ├── udp.go                     # UDP publisher with send buffer tuning
│   ├── frame.go                   # SPI frame parser + CRC validator
│   ├── stats.go                   # Runtime metrics (frames/s, errors)
│   ├── config.go                  # Config struct (YAML)
│   ├── config.yaml                # Runtime configuration
│   └── Makefile                   # Cross-compile targets
│
├── pc-backend/                    # PC Go backend
│   ├── main.go                    # Entry point, goroutine startup
│   ├── config.yaml                # All tunable parameters
│   ├── udp_receiver.go            # UDP listener, sub-packet reassembly
│   ├── ring_buffer.go             # Lock-free ring buffer (1024 frames)
│   ├── pipeline.go                # Plugin chain execution
│   ├── ws_hub.go                  # WebSocket hub, client fan-out
│   ├── http_server.go             # Serves frontend/, /metrics, /api
│   ├── frame.go                   # DataFrame type, shared definitions
│   ├── metrics.go                 # Prometheus metrics exposition
│   └── plugins/
│       ├── plugin.go              # Plugin interface definition
│       ├── calibration.go         # Example: scale/offset per channel
│       ├── moving_average.go      # Example: windowed smoothing
│       └── csv_logger.go          # Example: disk logging
│
├── frontend/                      # Browser UI (spec: TBD)
│   ├── index.html
│   ├── src/
│   │   ├── ws_client.js           # WebSocket + reconnect logic
│   │   ├── plotter.js             # uPlot wrapper
│   │   └── dashboard.js           # Layout + channel binding
│   └── package.json
│
├── shared/
│   └── protocol.md                # Authoritative protocol spec (this doc)
│
├── scripts/
│   ├── deploy_rpi.sh              # Cross-compile + rsync to RPi
│   └── setup_rpi.sh               # RPi OS hardening + service install
│
└── README.md                      # This file
```

---

## 10. Configuration Schema (`config.yaml`)

Both `rpi-bridge` and `pc-backend` consume their respective `config.yaml` at startup. No hardcoded values in source code.

**pc-backend/config.yaml:**
```yaml
udp:
  listen_port: 9000
  recv_buffer_bytes: 8388608    # 8 MB

websocket:
  port: 9001
  max_clients: 8
  frame_drop_policy: drop_oldest # drop_oldest | drop_newest

http:
  port: 8080
  frontend_dir: "../frontend"

pipeline:
  plugins:
    - name: calibration
      enabled: true
    - name: csv_logger
      enabled: false
      path: "/tmp/telemetry.csv"

ring_buffer:
  size: 1024                    # Must be power of 2

performance:
  gogc: 400
  gomemlimit: "2GiB"
  worker_goroutines: 4
```

---

## 11. Open Questions (To Be Resolved)

> AI agents: do not make assumptions on these items without explicit user input.

- [ ] **PC operating system target** — Linux/Windows/macOS? (affects UDP socket tuning, deployment scripts)
- [ ] **WiFi network topology** — home router / dedicated AP / ad-hoc direct connection?
- [ ] **UDP port numbers** — confirm `9000` (UDP data) and `9001` (WebSocket), `8080` (HTTP)
- [ ] **Jumbo frames** — does the target WiFi AP support MTU > 1500? (determines single vs. split-packet approach)
- [ ] **Data structure of 500 floats** — named channels? grouped by subsystem? fixed index semantics? (critical for frontend channel binding)
- [ ] **RPi bridge language** — Go confirmed? or C for even lower latency?
- [ ] **IRQ strategy on RPi** — `gpiod` edge interrupt vs. `pigpio` DMA polling (affects IRQ latency)
- [ ] **Frontend framework** — Vanilla JS / React / Svelte? (detailed GUI spec pending)
- [ ] **Wireless 5 GHz** — is an 802.11ac AP available? (reduces interference vs. 2.4 GHz)
- [ ] **Frame rate flexibility** — is 100 Hz fixed, or variable (up to 300 Hz)?

---

## 12. Implementation Notes for AI Agents

- **All numeric encoding:** Little-endian throughout
- **float32:** IEEE 754 single-precision, standard Go/C representation
- **CRC variant:** CRC16-CCITT, poly `0x1021`, init `0xFFFF`
- **Compression:** Disabled by default; float16 quantization as config toggle
- **Plugin system:** All custom data processing goes through `plugins/` — never modify core pipeline
- **Config-first:** Zero hardcoded addresses, ports, or tuning constants in source code
- **Simulator mode:** Every component (`rpi-bridge`, `pc-backend`) MUST implement a `--simulate` flag that generates synthetic data without hardware, enabling full-stack development without physical devices
- **Dropped frames:** Log + count via metrics; NEVER block the receive pipeline on any error condition
- **Sequence gaps:** Detect and expose via `/metrics`; do not attempt retransmission (UDP is fire-and-forget)
- **Logging:** `zerolog` structured JSON; log level configurable via `config.yaml`
- **Metrics:** Prometheus exposition at `http://localhost:8080/metrics`; minimum counters: `frames_received_total`, `frames_dropped_total`, `crc_errors_total`, `udp_bytes_received_total`, `websocket_clients_connected`
- **Graceful shutdown:** All goroutines terminate cleanly on `SIGINT`/`SIGTERM`; no goroutine leaks
- **Cross-compilation:** `rpi-bridge` is always cross-compiled on the PC — do not attempt native RPi compilation

---

*GUI specification to be added in a follow-up document. All other sections are considered stable for initial implementation.*
