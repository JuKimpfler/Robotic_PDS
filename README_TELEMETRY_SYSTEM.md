# Telemetry Streaming System — Project Specification (AI Agent Reference)

**Version:** 0.2  
**Status:** Planning Phase — Spec Complete (GUI pending)  
**Last Updated:** 2026-06-05  
**GUI Specification:** Pending (separate document)

---

## 1. Project Overview

A high-throughput, low-latency telemetry streaming pipeline for real-time data acquisition and browser-based visualization, deployed on Windows 11.

A **Teensy 4.0** microcontroller produces telemetry data (≥ 500 × float32 per frame at variable frame rate), transfers it via **SPI** to a **Raspberry Pi Zero 2W** (C bridge daemon), which forwards raw frames via **UDP over WiFi** to a **Windows 11 PC** running a **Go backend** that serves a browser-based frontend over WebSocket. The PC provides the WiFi network via Windows Mobile Hotspot, controlled programmatically by the GUI.

### Core Design Philosophy

> **Performance-first. Resource efficiency is NOT a priority.**  
> The system MUST be dimensioned for **2–3× the minimum bandwidth requirement** to guarantee stable performance at the 200 KB/s operating point. Allocate CPU, RAM, and buffer resources aggressively.

### Confirmed Technology Decisions

| Layer | Technology | Rationale |
|---|---|---|
| Teensy firmware | C++ / PlatformIO | Fixed |
| RPi bridge daemon | **C** (bare `spidev` + POSIX sockets) | Maximum RT determinism, no GC, ~30% lower latency vs Go |
| PC backend | **Go 1.22+** | Goroutine model fits pipeline; good Windows support |
| PC hotspot control | **Go → PowerShell** (WinRT) | Windows 11 Mobile Hotspot API |
| Frontend | Browser (Svelte + uPlot) | Modern, flexible, high-performance plotting |
| Channel config | **CSV** (primary) + `.xlsx` import | User-editable on Windows, hot-reloaded at runtime |

### Performance Requirements

| Metric | Minimum (Guaranteed) | Design Target |
|---|---|---|
| Payload bandwidth | **200 KB/s** | **400–600 KB/s** |
| Frame rate | Variable (100 Hz baseline) | Scalable to 300 Hz |
| Payload per frame | ≥ 500 × float32 = 2000 B | Configurable (see §6) |
| SPI transfer latency | < 1 ms | < 0.6 ms |
| UDP network latency | < 1 ms | < 0.5 ms |
| End-to-end (Teensy → Browser) | < 10 ms | < 5 ms |
| PC CPU / RAM | **Unrestricted** | **Unrestricted** |

---

## 2. System Architecture

```
┌────────────────────────┐   SPI (30 MHz, DMA)    ┌───────────────────────────┐
│      Teensy 4.0        │ ──────────────────────▶ │   Raspberry Pi Zero 2W    │
│  (PlatformIO / C++)    │ ◀── IRQ handshake (GPIO)│   Bridge Node (C daemon)  │
│                        │                         │                           │
│  - Generates frames    │                         │  - SPI Master (spidev)    │
│  - Variable frame rate │                         │  - gpiod edge IRQ         │
│  - Binary framing      │                         │  - UDP publisher          │
│  - CRC16 per frame     │                         │  - SCHED_FIFO RT prio     │
└────────────────────────┘                         └────────────┬──────────────┘
                                                                │
                                                    UDP unicast (port: 9000)
                                                    WiFi 802.11n / 2.4 GHz
                                                    PC hosts Mobile Hotspot
                                                                │
                                          ┌─────────────────────▼──────────────────────┐
                                          │             Windows 11 PC                   │
                                          │                                             │
                                          │  ┌──────────────────────────────────────┐  │
                                          │  │          Go Backend Process           │  │
                                          │  │                                      │  │
                                          │  │  UDP Rx → Ring Buffer → WS Hub       │  │
                                          │  │  Channel Map (hot-reload from CSV)   │  │
                                          │  │  Plugin Pipeline                     │  │
                                          │  │  Hotspot Control (PowerShell/WinRT)  │  │
                                          │  │  HTTP + WebSocket server             │  │
                                          │  └──────────────────────────────────────┘  │
                                          │                   │                         │
                                          │       ws://localhost:9001/stream            │
                                          │       http://localhost:8080                 │
                                          │                   │                         │
                                          │  ┌────────────────▼─────────────────────┐  │
                                          │  │        Browser (localhost)            │  │
                                          │  │    Svelte + uPlot  (spec: TBD)        │  │
                                          │  └──────────────────────────────────────┘  │
                                          └─────────────────────────────────────────────┘
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
| IRQ pin | Dedicated GPIO output → RPi GPIO (signals "frame ready") |
| Library | `SPISlave_T4` or custom DMA ISR |
| Frame rate | Variable — set via config register / serial command at runtime |

**SPI Slave timing contract:**
```
Teensy fills frame buffer in DMA-safe region
  → asserts IRQ pin HIGH  (~1 µs)
  → RPi drives CS LOW, provides SPI clock
  → DMA transfer: 2014 bytes @ 30 MHz ≈ 0.54 ms
  → RPi drives CS HIGH
  → Teensy deasserts IRQ, begins next frame
```

**Frame rate scaling:** Teensy exposes a configuration channel (e.g., via a dedicated UART or a "command frame" over the same SPI bus in reverse direction) allowing the PC backend to request a target frame rate at runtime. Supported range: **10–300 Hz**.

---

### 3.2 Raspberry Pi Zero 2W

| Property | Value |
|---|---|
| SoC | BCM2710A1, Quad-core ARM Cortex-A53 @ 1 GHz |
| RAM | 512 MB |
| OS | **Raspberry Pi OS Lite 64-bit** (headless, minimal) |
| SPI interface | `/dev/spidev0.0` |
| SPI role | **Master** |
| SPI clock | **30 MHz** |
| IRQ detection | `gpiod` edge interrupt (rising edge on IRQ pin) |
| Bridge language | **C** (`gcc -O3 -march=armv8-a`) |
| Scheduling | `SCHED_FIFO`, priority 50 |
| CPU governor | `performance` (frequency scaling disabled) |

**Rationale for C over Go on the bridge:**
The bridge performs exactly one task: SPI read → CRC check → UDP send. There is no benefit from Go's concurrency model here. C with direct `spidev` syscalls and a tight real-time loop eliminates GC pauses and reduces IRQ-to-UDP latency by ~25–35% compared to the equivalent Go implementation.

**Required `/boot/config.txt`:**
```ini
dtparam=spi=on
dtoverlay=spi0-1cs
core_freq=250
force_turbo=1
```

**OS hardening:**
```bash
# Disable unnecessary services
systemctl disable bluetooth avahi-daemon triggerhappy

# CPU governor
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Kernel network buffers
echo "net.core.rmem_max = 67108864" >> /etc/sysctl.conf
echo "net.core.wmem_max = 67108864" >> /etc/sysctl.conf
sysctl -p
```

**Systemd unit (`/etc/systemd/system/spi-bridge.service`):**
```ini
[Unit]
Description=SPI-UDP Bridge
After=network.target

[Service]
ExecStart=/usr/local/bin/spi_bridge --spi /dev/spidev0.0 --host 192.168.137.1 --port 9000
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=50
Restart=always
RestartSec=500ms
StandardOutput=journal

[Install]
WantedBy=multi-user.target
```

---

### 3.3 PC — Windows 11

| Property | Value |
|---|---|
| OS | Windows 11 (exclusive target) |
| Runtime | Go 1.22+, target `GOOS=windows GOARCH=amd64` |
| Network role | **Hosts WiFi Mobile Hotspot** |
| Hotspot control | Go → PowerShell (WinRT `NetworkOperatorTetheringManager`) |
| UDP | Port 9000 (inbound from RPi) |
| WebSocket | Port 9001 (to browser) |
| HTTP | Port 8080 (serves frontend, API, metrics) |
| Firewall | Programmatically opened via `netsh` at startup |

**Windows-specific UDP tuning (Go):**
```go
import "golang.org/x/sys/windows"

conn, _ := net.ListenUDP("udp4", &net.UDPAddr{Port: 9000})
rawConn, _ := conn.SyscallConn()
rawConn.Control(func(fd uintptr) {
    // 8 MB receive buffer
    windows.SetsockoptInt(windows.Handle(fd),
        windows.SOL_SOCKET, windows.SO_RCVBUF, 8*1024*1024)
})
```

**Auto-open Windows Firewall rule at startup:**
```go
func openFirewallRule() {
    exec.Command("netsh", "advfirewall", "firewall", "add", "rule",
        "name=TelemetryBridge", "protocol=UDP", "dir=in",
        "localport=9000", "action=allow").Run()
}
```

**Windows thread priority for UDP receive goroutine:**
```go
import "golang.org/x/sys/windows"
// Called inside the UDP receive goroutine:
windows.SetThreadPriority(
    windows.CurrentThread(),
    windows.THREAD_PRIORITY_TIME_CRITICAL,
)
```

---

## 4. Windows Mobile Hotspot Control

The GUI controls the PC's WiFi hotspot. The Go backend exposes HTTP API endpoints (`POST /api/hotspot/start`, `POST /api/hotspot/stop`, `GET /api/hotspot/status`) that internally invoke PowerShell.

### SSID / Passphrase Configuration
Defined in `config.yaml` — applied at hotspot start.

### PowerShell WinRT Implementation

```go
// hotspot/hotspot.go

package hotspot

import (
    "fmt"
    "os/exec"
    "strings"
)

const psStart = `
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,
         Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
$null = [Windows.Networking.Connectivity.NetworkInformation,
         Windows.Networking.Connectivity, ContentType=WindowsRuntime]

$profile  = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
$manager  = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)

$config = $manager.GetCurrentAccessPointConfiguration()
$newCfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
$newCfg.Ssid       = "%s"
$newCfg.Passphrase = "%s"
$manager.ConfigureAccessPointAsync($newCfg).AsTask().Wait()
$manager.StartTetheringAsync().AsTask().Wait()
Write-Output "OK"
`

const psStop = `
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,
         Windows.Networking.NetworkOperators, ContentType=WindowsRuntime]
$null = [Windows.Networking.Connectivity.NetworkInformation,
         Windows.Networking.Connectivity, ContentType=WindowsRuntime]
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
$manager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
$manager.StopTetheringAsync().AsTask().Wait()
Write-Output "OK"
`

func Start(ssid, passphrase string) error {
    script := fmt.Sprintf(psStart, ssid, passphrase)
    return runPS(script)
}

func Stop() error {
    return runPS(psStop)
}

func runPS(script string) error {
    out, err := exec.Command("powershell",
        "-NoProfile", "-NonInteractive", "-Command", script,
    ).CombinedOutput()
    if err != nil || !strings.Contains(string(out), "OK") {
        return fmt.Errorf("hotspot PS error: %v — %s", err, out)
    }
    return nil
}
```

**Note on Windows 11 permissions:** `NetworkOperatorTetheringManager` requires the application to run as the logged-in user (not elevated/admin). The Go backend must NOT run as Administrator for this API to work. Firewall rule creation (`netsh advfirewall`) requires elevation — use a one-time install script for this.

**Hotspot IP range:** Windows Mobile Hotspot always assigns the host `192.168.137.1`. The RPi will receive a DHCP address in `192.168.137.x`. The Go backend must either:
- Accept UDP from any source on port 9000 (simplest), or
- Discover the RPi's IP via the hotspot's DHCP lease table

---

## 5. Communication Protocol Specification

### 5.1 SPI Frame Format (Teensy → RPi)

`#pragma pack(push, 1)` — all fields little-endian.

```
Offset   Size    Type          Field             Description
──────   ────    ──────────    ──────────────    ──────────────────────────────
0        2       uint16        magic             Sync: 0xABCD
2        2       uint16        sequence          Wrapping frame counter
4        4       uint32        timestamp_us      Teensy micros()
8        2       uint16        channel_count     Number of float32 values (≥ 500)
10       2       uint16        flags             Bit 0: frame_rate_ack
                                                 Bits 1-15: reserved (0)
12       N×4     float32[N]    values            Telemetry payload (N = channel_count)
12+N×4   2       uint16        crc16             CRC16-CCITT over bytes [0 .. 10+N×4]
──────
Minimum frame size (N=500): 12 + 2000 + 2 = 2014 bytes
```

**CRC:** CRC16-CCITT, polynomial `0x1021`, init `0xFFFF`.  
**Maximum channel_count:** 1023 (keeps max frame size under 4 KB, below RPi spidev default buffer).

---

### 5.2 UDP Packet Layout (RPi → PC)

#### MTU Handling

Standard WiFi MTU = 1500 bytes. The 2014-byte frame exceeds this.  
**Default strategy: split into 2 sub-packets** (avoids IP fragmentation, lower loss rate on WiFi).

```
Sub-packet structure:
Offset   Size    Type         Field
──────   ────    ──────────   ─────────────────────────────
0        2       uint16       magic         0xCDAB
2        2       uint16       frame_seq     Matches SPI frame sequence
4        2       uint16       channel_count Total channels in this frame
6        1       uint8        sub_id        0 = first half, 1 = second half
7        1       uint8        sub_total     Always 2 (for N ≤ 1000)
8        2       uint16       offset        Float index of first value in payload
10       2       uint16       payload_count Number of float32 in this sub-packet
12       M×4     float32[M]   values        Payload (M = payload_count)
12+M×4   2       uint16       crc16         CRC16-CCITT over bytes [0 .. 10+M×4]
──────
Typical: M=250 → 12 + 1000 + 2 = 1014 bytes per sub-packet ✅ (< 1500 MTU)
```

**Reassembly on PC:** The Go backend holds a small reassembly map keyed on `frame_seq`. If both sub-packets arrive within 5 ms, the frame is assembled and pushed to the ring buffer. Timeout → frame dropped, counter incremented.

**Alternative (if AP supports jumbo frames, MTU=9000):** Disable splitting, send full frame in one datagram. Controlled by `config.yaml: udp.split_frames: false`.

---

### 5.3 WebSocket Wire Format (PC → Browser)

**Endpoint:** `ws://localhost:9001/stream`

**Format A — MessagePack binary** (default, high-frequency):
```
struct WsFrame {
    seq:     uint16
    ts_us:   uint32
    rate_hz: float32   // measured frame rate
    values:  float32[] // channel_count floats, ordered by channel index
}
```

**Format B — JSON** (debug / fallback, activated via `?format=json` query param):
```json
{
  "seq": 12345,
  "ts_us": 9876543,
  "rate_hz": 100.2,
  "values": [0.1, 0.2, "..."]
}
```

**Channel metadata push** (sent once on connect, and on every hot-reload):
```json
{
  "type": "channel_map",
  "channels": [
    { "index": 0, "name": "motor_fl_rpm", "unit": "rpm",
      "scale": 1.0, "offset": 0.0, "min": -3000, "max": 3000,
      "group": "Motors", "color": "#E74C3C", "precision": 1, "enabled": true },
    ...
  ]
}
```

---

## 6. Channel Definition System

### 6.1 Channel Config File (`channels.csv`)

Primary format: **UTF-8 CSV**, editable in Excel or any text editor.  
Location: configurable in `config.yaml` (`channel_map.path`).  
Hot-reload: file is watched via `fsnotify`; changes apply within 500 ms without backend restart.

**Schema:**

```csv
# Telemetry Channel Definition
# Generated: 2026-06-05 | Version: 1
#
# index   : float32 array index in SPI frame (0-based, must be contiguous, no gaps)
# name    : unique identifier, alphanumeric + underscore, max 32 chars
# unit    : display unit string (e.g. rpm, m/s, °C, V, A, %)
# scale   : multiplier applied to raw float before display  (display = raw * scale + offset)
# offset  : additive offset applied after scale
# min/max : expected range for UI scaling (NOT clamped)
# group   : display group / tab name in frontend
# color   : hex color for plot line (#RRGGBB)
# precision: decimal places in display
# enabled : true/false — disabled channels are received but not displayed

index,name,unit,scale,offset,min,max,group,color,precision,enabled
0,motor_fl_rpm,rpm,1.0,0.0,-3000,3000,Motors,#E74C3C,0,true
1,motor_fr_rpm,rpm,1.0,0.0,-3000,3000,Motors,#E74C3C,0,true
2,motor_rl_rpm,rpm,1.0,0.0,-3000,3000,Motors,#C0392B,0,true
3,motor_rr_rpm,rpm,1.0,0.0,-3000,3000,Motors,#C0392B,0,true
4,imu_accel_x,m/s²,1.0,0.0,-50,50,IMU,#3498DB,2,true
5,imu_accel_y,m/s²,1.0,0.0,-50,50,IMU,#2980B9,2,true
6,imu_accel_z,m/s²,1.0,0.0,-50,50,IMU,#1ABC9C,2,true
# ... up to N=channel_count rows
```

**Rules:**
- `index` values MUST be a contiguous sequence starting at 0, matching the SPI frame layout exactly.
- Adding/removing channels requires a corresponding Teensy firmware update to match.
- Comments (`#`) and blank lines are allowed and ignored.
- A `channels.xlsx` import is supported (Go `excelize` library) — it is converted to CSV on import.

### 6.2 Hot-Reload Behavior

```
File system event (channels.csv modified)
  → fsnotify fires (< 100 ms)
  → Backend reloads and validates CSV
  → If valid: atomically replaces channel map (sync.RWMutex)
  → Pushes "channel_map" message to all connected WebSocket clients
  → Frontend re-renders channel list, re-binds plot series
  → If invalid: logs error, retains previous channel map
```

### 6.3 Runtime Frame Rate Control

The backend can command the Teensy to change its frame rate.  
Mechanism: A separate **UART command channel** (Teensy USB Serial / HW Serial) receives rate commands.

```
PC Backend  →  USB Serial (or secondary UART)  →  Teensy
             "RATE:100\n"   (set 100 Hz)
             "RATE:200\n"   (set 200 Hz)
             "RATE:0\n"     (pause)
```

The Teensy acknowledges with `"RATE_ACK:100\n"`. The backend exposes `POST /api/rate/{hz}` HTTP endpoint.

---

## 7. PC Backend — Go Architecture

### 7.1 Component Map

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Go Backend (Windows 11)                           │
│                                                                          │
│  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────────────┐   │
│  │  UDP Receiver    │  │  Ring Buffer     │  │  WebSocket Hub       │   │
│  │  goroutine       │─▶│  1024 frames    │─▶│  goroutine           │   │
│  │  port 9000       │  │  lock-free      │  │  fan-out ≤ 8 clients │   │
│  │  8 MB SO_RCVBUF  │  │  atomic ops     │  │  drop-on-slow client │   │
│  │  TIME_CRITICAL   │  └─────────────────┘  └──────────────────────┘   │
│  └──────────────────┘           │                       │               │
│                                 ▼                       │               │
│                        ┌─────────────────┐              │               │
│                        │  Data Pipeline  │     ┌────────▼─────────┐    │
│                        │  goroutine      │     │  HTTP Server      │    │
│                        │                │     │  port 8080        │    │
│                        │  - seq gap chk │     │  GET /            │    │
│                        │  - CRC verify  │     │  GET /metrics     │    │
│                        │  - channel map │     │  POST /api/rate/  │    │
│                        │  - plugin chain│     │  POST /api/hotspot│    │
│                        │  - rate meas.  │     │  GET /api/channels│    │
│                        └─────────────────┘    └───────────────────┘    │
│                                 │                                        │
│  ┌──────────────────────────────▼────────────────────────────────────┐  │
│  │  Plugin Interface                                                  │  │
│  │  type Plugin interface {                                           │  │
│  │      Name()    string                                              │  │
│  │      Process(f *DataFrame, ch ChannelMap) *DataFrame               │  │
│  │  }                                                                 │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────────┐  │
│  │  Channel Map    │  │  fsnotify Watch  │  │  Hotspot Controller    │  │
│  │  sync.RWMutex   │◀─│  channels.csv   │  │  PowerShell / WinRT    │  │
│  │  hot-reloadable │  │  hot-reload     │  │  POST /api/hotspot/    │  │
│  └─────────────────┘  └─────────────────┘  └────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Critical Implementation Patterns

#### Lock-Free Ring Buffer
```go
const RingSize = 1024 // power of 2

type DataFrame struct {
    Seq      uint16
    TsUs     uint32
    Values   []float32   // len = channel_count
    RateHz   float32
}

type RingBuffer struct {
    slots  [RingSize]DataFrame
    head   atomic.Uint64
    tail   atomic.Uint64
}

func (rb *RingBuffer) Push(f DataFrame) bool {
    h := rb.head.Load()
    next := (h + 1) & (RingSize - 1)
    if next == rb.tail.Load() { return false } // full → drop
    rb.slots[h] = f
    rb.head.Store(next)
    return true
}
```

#### Zero-Allocation UDP Receive Loop
```go
// Pre-allocate reassembly map and packet buffer — never allocate in hot path
reassembly := make(map[uint16][2][]byte)
buf         := make([]byte, 65535)

for {
    n, _, _ := conn.ReadFromUDP(buf)
    pkt := parseSubPacket(buf[:n]) // in-place, no alloc
    key := pkt.FrameSeq
    slot := reassembly[key]
    slot[pkt.SubID] = buf[:n] // store reference
    reassembly[key] = slot
    if slot[0] != nil && slot[1] != nil {
        frame := assembleFrame(slot[0], slot[1])
        ring.Push(frame)
        delete(reassembly, key)
    }
    // Timeout cleanup: purge keys older than 5ms (run every 100 iterations)
}
```

#### Non-Blocking WebSocket Fan-Out
```go
type Client struct {
    send chan []byte // buffered, cap 32
}

func (h *Hub) Broadcast(data []byte) {
    h.mu.RLock()
    defer h.mu.RUnlock()
    for _, c := range h.clients {
        select {
        case c.send <- data:
        default:
            h.stats.DroppedFrames.Add(1) // never block producer
        }
    }
}
```

#### GC Tuning
```go
// Set in main() before any allocation:
os.Setenv("GOGC", "400")          // Reduce GC frequency 4×
os.Setenv("GOMEMLIMIT", "4GiB")   // Hard memory cap → GC before OOM
```

Use `sync.Pool` for `[]byte` encoding buffers in the WebSocket serializer to avoid per-frame allocations.

### 7.3 HTTP API Surface

| Method | Path | Description |
|---|---|---|
| GET | `/` | Redirect to `/index.html` |
| GET | `/metrics` | Prometheus metrics |
| GET | `/api/channels` | Current channel map as JSON |
| POST | `/api/channels/reload` | Force hot-reload of channels.csv |
| POST | `/api/rate/{hz}` | Set Teensy frame rate (10–300) |
| GET | `/api/hotspot/status` | Hotspot state: `on/off/transitioning` |
| POST | `/api/hotspot/start` | Start Windows Mobile Hotspot |
| POST | `/api/hotspot/stop` | Stop Windows Mobile Hotspot |
| GET | `/api/stats` | Live stats: fps, dropped, CRC errors |
| WS | `/stream` | WebSocket data stream |

---

## 8. RPi Bridge — C Implementation

### Architecture

```c
// spi_bridge.c — simplified pseudocode

#include <spidev/spidev.h>
#include <gpiod.h>            // libgpiod for edge IRQ
#include <sys/socket.h>
#include <netinet/in.h>
#include <pthread.h>
#include <sched.h>

#define SPI_SPEED_HZ   30000000
#define FRAME_MAGIC    0xABCD
#define PC_PORT        9000
#define MAX_FRAME_SIZE 4096

static uint8_t  spi_buf[MAX_FRAME_SIZE];
static uint8_t  udp_pkt_a[1200];
static uint8_t  udp_pkt_b[1200];

int main(int argc, char* argv[]) {
    // 1. Set RT scheduling
    struct sched_param sp = { .sched_priority = 50 };
    sched_setscheduler(0, SCHED_FIFO, &sp);

    // 2. Open SPI
    int spi_fd = spi_open("/dev/spidev0.0", SPI_SPEED_HZ);

    // 3. Open UDP socket, set 4 MB send buffer
    int udp_fd = udp_open(argv_host, PC_PORT, 4*1024*1024);

    // 4. Open GPIO IRQ (gpiod edge interrupt)
    struct gpiod_chip* chip = gpiod_chip_open("/dev/gpiochip0");
    struct gpiod_line* irq  = gpiod_chip_get_line(chip, IRQ_GPIO_NUM);
    gpiod_line_request_rising_edge_events(irq, "spi-bridge");

    // 5. Main RT loop
    while (1) {
        // Block on GPIO edge (µs-accurate)
        gpiod_line_event_wait(irq, NULL);
        gpiod_line_event_read(irq, &event);

        // SPI read (DMA via kernel spidev)
        uint16_t channel_count = read_header_channel_count(spi_fd);
        size_t frame_len = 12 + channel_count * 4 + 2;
        spi_transfer(spi_fd, spi_buf, frame_len);

        // Validate
        if (!magic_ok(spi_buf) || !crc16_ok(spi_buf, frame_len)) {
            stats.crc_errors++;
            continue;
        }

        // Split into 2 UDP sub-packets and send
        build_sub_packet(spi_buf, udp_pkt_a, 0, channel_count);
        build_sub_packet(spi_buf, udp_pkt_b, 1, channel_count);
        sendto(udp_fd, udp_pkt_a, pkt_a_len, 0, ...);
        sendto(udp_fd, udp_pkt_b, pkt_b_len, 0, ...);
        stats.frames_sent++;
    }
}
```

**Build system:** `CMakeLists.txt` — cross-compiled on PC:
```bash
# From PC (requires aarch64-linux-gnu-gcc):
cmake -DCMAKE_TOOLCHAIN_FILE=toolchain-aarch64.cmake -DCMAKE_BUILD_TYPE=Release ..
make -j4
# Deploy:
scp spi_bridge pi@192.168.137.x:/usr/local/bin/
```

**Dependencies:** `libgpiod2`, `libgpiod-dev` (apt). No other external dependencies.

---

## 9. Latency Budget

```
Teensy: data ready
  ├─ IRQ pin assert                        ~1 µs
RPi: gpiod edge interrupt
  ├─ IRQ detection latency (gpiod)         ~20–100 µs
  ├─ SPI DMA transfer (30 MHz, 2014 B)     ~540 µs
  ├─ CRC check (C, inline)                 ~5 µs
  ├─ Build 2 UDP sub-packets               ~3 µs
  ├─ sendto() × 2                          ~30–80 µs
WiFi (RPi → PC, 2.4 GHz, 1 hop)
  ├─ TX queue + air time                   ~200–600 µs
Windows 11 UDP receive
  ├─ Kernel → userspace                    ~50–150 µs
  ├─ Sub-packet reassembly                 ~5 µs
  ├─ Ring buffer push                      ~2 µs
  ├─ Pipeline + serialize                  ~30 µs
  ├─ WebSocket send                        ~50 µs
Browser
  └─ requestAnimationFrame + uPlot render  ~1–16 ms

────────────────────────────────────────────────────────────
SPI transfer:                    < 0.6 ms  ✅
UDP hop (RPi → Windows):         < 1.0 ms  ✅  (target: < 0.5 ms)
Teensy → WebSocket client:       < 3 ms    ✅
Teensy → browser pixel:          < 20 ms   ✅  (display-bound @60 Hz)
```

**Dominant latency factor on Windows:** kernel UDP buffer → userspace handoff (~50–150 µs) and WiFi layer. Both are within spec. Thread priority `TIME_CRITICAL` on the receiver goroutine minimizes scheduling jitter.

---

## 10. Compression Strategy

| Scenario | Strategy | Rationale |
|---|---|---|
| Normal (local hotspot, ≤ 300 Hz) | **None** | 600 KB/s << WiFi capacity; latency budget too tight |
| Congested / range-limited WiFi | **float16 quantization** | 50% bandwidth reduction, zero algorithm latency |
| Disk logging / archival | **LZ4** | Post-receive, off the hot path |

Default: **no compression**. Quantization toggle: `config.yaml: pipeline.quantize_float16: false`.

---

## 11. Project Directory Structure

```
project-root/
│
├── teensy/                            # PlatformIO project
│   ├── platformio.ini                 # board=teensy40, framework=arduino
│   └── src/
│       ├── main.cpp
│       ├── spi_slave.cpp              # SPISlave_T4 / DMA ISR
│       ├── frame.h                    # DataFrame struct (source of truth)
│       ├── rate_control.cpp           # UART command handler for frame rate
│       └── crc16.h                    # CRC16-CCITT
│
├── rpi-bridge/                        # RPi C bridge daemon
│   ├── CMakeLists.txt
│   ├── toolchain-aarch64.cmake        # Cross-compile toolchain
│   ├── src/
│   │   ├── main.c                     # Entry point, RT setup, main loop
│   │   ├── spi.c / spi.h              # spidev wrapper
│   │   ├── udp.c / udp.h              # UDP publisher
│   │   ├── gpio.c / gpio.h            # gpiod IRQ wrapper
│   │   ├── protocol.c / protocol.h   # Frame parse, CRC, sub-packet builder
│   │   └── stats.c / stats.h         # Runtime counters
│   ├── config/
│   │   └── bridge.conf                # host IP, port, SPI speed, GPIO pin
│   └── deploy.sh                      # scp + systemctl restart
│
├── pc-backend/                        # Go backend (Windows 11)
│   ├── go.mod
│   ├── main.go
│   ├── config.yaml                    # All tunable parameters
│   ├── channels.csv                   # Channel definition (hot-reloaded)
│   ├── internal/
│   │   ├── udp/
│   │   │   └── receiver.go            # UDP listener + sub-packet reassembly
│   │   ├── ring/
│   │   │   └── buffer.go              # Lock-free ring buffer
│   │   ├── pipeline/
│   │   │   ├── pipeline.go            # Plugin chain
│   │   │   └── plugins/
│   │   │       ├── plugin.go          # Interface definition
│   │   │       ├── calibration.go
│   │   │       ├── moving_average.go
│   │   │       └── csv_logger.go
│   │   ├── channels/
│   │   │   ├── map.go                 # Channel definition type
│   │   │   ├── csv_loader.go          # CSV + xlsx import
│   │   │   └── watcher.go             # fsnotify hot-reload
│   │   ├── websocket/
│   │   │   ├── hub.go                 # Fan-out hub
│   │   │   └── serializer.go          # MessagePack + JSON
│   │   ├── hotspot/
│   │   │   └── hotspot.go             # PowerShell WinRT wrapper
│   │   ├── ratecontrol/
│   │   │   └── serial.go              # UART command to Teensy
│   │   ├── http/
│   │   │   └── server.go              # HTTP + API routes
│   │   └── metrics/
│   │       └── metrics.go             # Prometheus counters
│   └── frontend/                      # Embedded via Go embed.FS
│       └── dist/                      # Built frontend assets
│
├── frontend/                          # Svelte + uPlot browser UI
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.svelte
│       ├── ws/
│       │   └── client.js              # WebSocket + reconnect
│       ├── components/
│       │   ├── LivePlot.svelte        # uPlot wrapper
│       │   ├── Dashboard.svelte       # Layout + channel binding
│       │   ├── HotspotControl.svelte  # Hotspot on/off UI
│       │   ├── RateControl.svelte     # Frame rate slider
│       │   └── ChannelList.svelte     # Channel map display
│       └── stores/
│           ├── channelMap.js
│           └── dataStream.js
│
├── shared/
│   └── protocol.md                    # Authoritative frame format spec
│
└── scripts/
    ├── setup_rpi.sh                   # OS hardening, spidev config, service install
    ├── install_windows.ps1            # Firewall rule, Go install, build frontend
    └── cross_compile_bridge.sh        # Build C bridge for aarch64
```

---

## 12. Configuration (`pc-backend/config.yaml`)

```yaml
# ── Network ──────────────────────────────────────────────
udp:
  listen_port: 9000
  recv_buffer_bytes: 8388608        # 8 MB
  reassembly_timeout_ms: 5
  split_frames: true                # false = expect jumbo frames

websocket:
  port: 9001
  max_clients: 8
  frame_drop_policy: drop_newest    # drop_newest | drop_oldest

http:
  port: 8080

# ── Hotspot ───────────────────────────────────────────────
hotspot:
  ssid: "TelemetryNet"
  passphrase: "changeme123"
  auto_start: false                 # true = start on backend launch

# ── Channel Map ───────────────────────────────────────────
channel_map:
  path: "channels.csv"
  xlsx_import_path: ""              # Optional: path to .xlsx, auto-converts to CSV
  reload_debounce_ms: 500

# ── Frame Rate Control ────────────────────────────────────
rate_control:
  enabled: true
  serial_port: "COM3"               # Teensy USB serial port
  baud: 115200
  default_rate_hz: 100

# ── Ring Buffer ───────────────────────────────────────────
ring_buffer:
  size: 1024                        # Must be power of 2

# ── Pipeline ──────────────────────────────────────────────
pipeline:
  quantize_float16: false
  plugins:
    - name: calibration
      enabled: true
    - name: csv_logger
      enabled: false
      path: "C:/telemetry/log.csv"
    - name: moving_average
      enabled: false
      window: 5

# ── Performance ───────────────────────────────────────────
performance:
  gogc: 400
  gomemlimit: "4GiB"
  udp_thread_priority: time_critical  # Windows THREAD_PRIORITY_TIME_CRITICAL

# ── Logging ───────────────────────────────────────────────
logging:
  level: info                       # debug | info | warn | error
  format: json                      # json | text
```

---

## 13. Prometheus Metrics (exposed at `/metrics`)

| Metric | Type | Description |
|---|---|---|
| `telemetry_frames_received_total` | Counter | UDP frames fully reassembled |
| `telemetry_frames_dropped_total` | Counter | Frames dropped (ring full / reassembly timeout) |
| `telemetry_crc_errors_total` | Counter | CRC validation failures |
| `telemetry_udp_bytes_total` | Counter | Raw UDP bytes received |
| `telemetry_frame_rate_hz` | Gauge | Measured incoming frame rate |
| `telemetry_ws_clients` | Gauge | Active WebSocket clients |
| `telemetry_ws_frames_dropped_total` | Counter | Frames dropped due to slow WS clients |
| `telemetry_reassembly_timeouts_total` | Counter | Sub-packet reassembly timeouts |
| `telemetry_hotspot_state` | Gauge | 1=on, 0=off |

---

## 14. Resolved & Open Items

### Resolved
- [x] **PC OS:** Windows 11 exclusive
- [x] **Data structure:** Predefined, dynamically adjustable via `channels.csv`
- [x] **Network topology:** PC hosts Windows Mobile Hotspot; RPi connects as client
- [x] **Frame rate:** Variable / scalable (10–300 Hz), runtime-controlled via UART
- [x] **RPi bridge language:** C (for RT determinism)
- [x] **PC backend language:** Go
- [x] **Frontend:** Svelte + uPlot

### Open (requires GUI specification)
- [ ] **GUI layout and panels** — awaiting detailed spec
- [ ] **uPlot vs custom canvas renderer** — depends on required plot types
- [ ] **Channel grouping UI** — tabs / sidebar / overlay?
- [ ] **Teensy UART command port** — confirm `COMx` assignment or auto-detect
- [ ] **channels.xlsx primary vs CSV primary** — confirm user preference

---

## 15. Implementation Notes for AI Agents

- **Numeric encoding:** Little-endian throughout (both SPI and UDP layers)
- **float32:** IEEE 754, standard C/Go representation
- **CRC:** CRC16-CCITT, poly `0x1021`, init `0xFFFF`
- **Compression:** Disabled by default. float16 quantization = config toggle only
- **Plugin system:** All custom data processing via `plugins/` — never modify core pipeline
- **No hardcoded values:** All addresses, ports, paths, and tuning constants in `config.yaml`
- **Simulate mode:** Every component MUST implement `--simulate` flag generating synthetic data at configured rate. Full-stack development must be possible without any hardware connected.
- **Hot-reload:** Channel map reloads without restart. Backend never drops frames during reload (swap under RWMutex)
- **Firewall:** Backend opens UDP 9000 firewall rule automatically on first start (requires one-time admin elevation via a separate installer script)
- **Hotspot:** Backend does NOT require Administrator rights. Firewall rule is set separately.
- **Graceful shutdown:** All goroutines must exit cleanly on SIGINT/SIGTERM (use `context.WithCancel`). Hotspot is NOT stopped automatically on shutdown (user decision).
- **Logging:** `zerolog` with structured JSON output
- **Error philosophy:** Never block the receive pipeline. All errors are logged + counted; data flow continues.
- **Windows paths:** Use `filepath.Join` everywhere — no hardcoded `/` separators

---

*GUI specification to be provided in a follow-up document. All other sections are stable for implementation.*
