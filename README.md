# Robotic PDS (Power Debug System)

This repository contains the software and firmware components for the **Power Debug System (PDS)**, designed for the RoboCup Junior Soccer 2vs2 robot telemetry and configuration. 

It provides real-time telemetry from Teensy microcontrollers via Raspberry Pi Zero nodes to a central Raspberry Pi 5 (or PC) running a PyQt6-based monitoring and configuration interface.

---

## ── Architecture Overview ──

```
┌────────────────────────────────┐       UDP Unicast (Downlink)      ┌─────────────────────────┐
│ RPi 5 / PC (GUI Monitor)       │ ────────────────────────────────▶ │ RPi Zero 2 W (Node)     │
│ - Live-Tabelle                 │   - Slow (2 Hz): Port 7001/7002   │ - uart_receiver.py      │
│ - Live-Plotter                 │   - Fast (100 Hz): Port 7011/7012 │ - status_leds.py        │
│ - Parameter-Editor             │                                   └────────────┬────────────┘
└────────────────────────────────┘                                                │
                ▲                                                                 │ UART (1 Mbps)
                │                                                                 ▼
                │ UDP Unicast (5001/5002)                                    ┌─────────────────────────┐
                └─────────────────────────────────────────────────────────── │ Teensy 4.0 (Firmware)   │
                                                                             │ - PowerDebugger (PDS)   │
                                                                             └─────────────────────────┘
```

### 1. Telemetry Uplink (Teensy 4.0 → RPi Zero → GUI Monitor)
- **Teensy 4.0** transmits telemetry packets over UART (`Serial3` at `1'000'000` Baud) to the Raspberry Pi Zero. Each packet is `8 + 200 × 4 = 808` bytes; at 100 Hz that is 80.8 kB/s against the 100 kB/s the link provides (~81 % utilisation).
- **RPi Zero Node** runs `uart_receiver.py`, which reads the serial stream and forwards each packet over UDP (ports `5001` for Node 1, `5002` for Node 2).
- **Addressing**: the node learns the GUI's address from incoming packets and then sends **unicast**. Until it has learned one — and if the GUI goes quiet for more than 10 s — it falls back to broadcast, so discovery still works out of the box.
  Broadcast is deliberately *not* the default any more: Wi-Fi must send broadcast frames at the lowest basic rate of the BSS, without aggregation and without MAC-level ACKs. At 80.8 kB/s that consumed a large share of the airtime per node and was the main reason the joystick/controller downlink became laggy. See [`Doku/Latenz_Fernsteuerung.md`](Doku/Latenz_Fernsteuerung.md).
  Parameter packets only ever go to the *active* node, so the inactive one used to never learn an address and broadcast its full 80 kB/s forever — degrading the link for the active node too. A 12-byte **discovery packet** (magic `0xD15C0BE5`, UDP `7031`/`7032`) now goes to **both** nodes once per second; it carries no parameters and is never forwarded to the Teensy, so it cannot write values into the wrong robot. It also carries a sequence number and a send timestamp that the node mirrors straight back (magic `0xD15CEC40`), which is where the round-trip time in the Diagnostics tab comes from.
  Override with `PDS_TELEMETRY_DEST=<ip>` (fixed target) or `PDS_TELEMETRY_BROADCAST=1` (old behaviour).
- **GUI Monitor** detects the node IP addresses from the sender IP of the incoming UDP packets.

### 2. Parameter Downlink (GUI Monitor → RPi Zero → Teensy 4.0)
Parameters can be configured directly in the GUI and sent back to the active node via UDP Unicast:
- **Slow Channel (2 Hz)**: Sends 50 Floats + 50 Bools (Port `7001` or `7002`, Magic `0xCAFEFEED`). Used for robot configuration.
- **Fast Channel (100 Hz)**: Sends 5 Floats (Port `7011` or `7012`, Magic `0xFA57DA7A`). Used for real-time joystick/motion controls. Can be driven either by the touch UI (`ParamsView.qml`) or, if a PS4 controller (DualShock 4) is plugged into the RPi 5 via USB, automatically by the controller instead — the touch widgets lock and mirror the live controller values while it's connected. See `Doku/PS4_Controller_Implementierung.md`.
- **RPi Zero Node** listens to these UDP ports and forwards the raw bytes immediately over UART to the Teensy.
- **Teensy 4.0** parses the incoming packet stream via a synchronized parser in the `PowerDebugger` class, updating the RAM values for the robot logic.

### 3. Channel-/Param-Name + Overlay Descriptor (Teensy 4.0 → RPi Zero → GUI Monitor)
The Teensy is the single source of truth for display names and the "which
channel shows up where" mapping. Names come from two places: the sketch
itself (`PDS.plot("Ball_X", x)` / `PDS.track("Akku", &v)` register a name
along with the value) and `teensy_firmware/src/channel_config.h` (param
names and overlays). The firmware builds a small JSON descriptor — names for
the 200 debug channels, the 50+50+5 param channels, and the overlay/widget
mapping (gauge/rotation/vector/table/body-object/text-overlay) — and streams
it in small chunks over the same UART path used for telemetry/params:
- **Descriptor chunks (Teensy → GUI)**: Magic `0xDE5C0001`, forwarded by the
  node to UDP port `5011`/`5012`.
- **Resend request (GUI → Teensy)**: Magic `0xDE5C00F0`, sent to UDP port
  `7021`/`7022`.

**Restarts are handled automatically** — no button press needed in any of
these cases:

| What restarted | How the names come back |
|---|---|
| Teensy (GUI already running) | Firmware re-sends on boot; GUI additionally spots the `micros()` reset in the packet header and asks again |
| GUI or node (Teensy running) | Firmware detects the link coming back up and re-sends |
| Teensy boots before GUI/node exist | Firmware repeats the announcement every 5 s until the GUI answers (`PDS_DESC_REPEAT_MS`) |

Since wire format 2 the descriptor also carries **channel units**, the
**firmware version**, and the **complete parameter widget configuration**
(name, widget type, range, step, group, joystick pairing) from
`channel_config.h`. The Teensy is therefore the single source of truth for
the entire Parameters tab, not just for the labels on it.

**The GUI stores all of it on disk, per node**, under
`rpi5_monitor/64Bit_Version/runtime_config/nodeN/` — after a restart of the
GUI (or of the whole Pi) everything is back immediately, without the robot
being switched on.

Conflict between the Teensy's configuration and something you edited in the
GUI is resolved by a fingerprint: **new firmware wins, otherwise your local
edits stay.** So "change `channel_config.h` and re-flash" always takes
effect, and nothing else does. The files in the repository stay untouched
templates; deleting the `runtime_config` folder (or pressing "Gespeicherte
Konfiguration verwerfen" in the Diagnostics tab) resets everything.

See `Doku/Kanalnamen_Implementierung.md` for the full protocol and
[`teensy_firmware/README.md`](teensy_firmware/README.md) for the library API.

### 3b. Aux Uplink — Events, Parameter Feedback, Node Health (→ GUI Monitor)

Three small streams share one UDP port (`5021`/`5022`); the GUI tells them
apart by magic. A separate port per type would have meant another receiver
process for no gain.

| Stream | Magic | Rate | What it is |
|---|---|---|---|
| Event / log line | `0xE7E5C0DE` | ≤ 20/s | `PDS.event("Ball verloren")` draws a vertical marker in the plotter; `PDS.log/warn/error(...)` writes a line into the GUI log book. |
| Parameter feedback | `0xACC0FEED` | 2 Hz | The Teensy sends back the parameters it *actually* holds. The downlink used to be fire-and-forget — nobody noticed when a value never arrived. The Parameters tab now shows target vs. actual. |
| Node health | `0x0DE57A75` | 1 Hz | CPU temperature, load, memory, Wi-Fi signal, uptime and UART counters of the Pi Zero itself — generated by the node, not the Teensy. |

Everything the Teensy sends is rate-limited and only written when a full
telemetry packet still fits in the UART TX buffer on top, so none of it can
displace the 100 Hz telemetry stream.

### 4. Wireless Firmware Flashing (Windows PC → Bluetooth → RPi Zero 2 W → USB → Teensy 4.0)
A `.hex` firmware image can be sent wirelessly from any Windows PC to one or both
RPi Zero 2 W nodes over Bluetooth Classic (RFCOMM/SPP), independent of the
WLAN/UDP telemetry path above. The node receives the file, verifies its SHA-256
hash, and flashes it via `teensy_loader_cli` over the existing USB connection —
no physical button press on the Teensy needed. See
[`Doku/Flash_Implementierung.md`](Doku/Flash_Implementierung.md) for the full
architecture/protocol and [`pc_flash_tool/README.md`](pc_flash_tool/README.md)
for usage instructions.

```
Windows PC ──Bluetooth (RFCOMM/SPP)──▶ RPi Zero 2 W ──USB──▶ Teensy 4.0
 bt_flash_sender.py                    bt_flash_receiver.py   (teensy_loader_cli)
```

### 5. Remote Control via PS4 Controller
If a DualShock 4 is plugged into the RPi 5 / PC via USB, it takes over the
fast channel automatically: the touch widgets lock and mirror the live
controller values while it is connected. Axis/button assignment is
configurable without touching code. See
[`Doku/PS4_Controller_Implementierung.md`](Doku/PS4_Controller_Implementierung.md).

The end-to-end reaction time of that path, how it is budgeted, and how to
measure it if it degrades, is documented separately in
[`Doku/Latenz_Fernsteuerung.md`](Doku/Latenz_Fernsteuerung.md).

---

## ── Teensy Library: Quick Start ──

The robot side is a drop-in library. `PDS` is a ready-made global instance —
there is no object to create and **no channel numbers to manage**:

```cpp
#include "PDS.h"

float akkuVolt = 0;

void setup() {
    PDS.begin();
    PDS.track("Akku", &akkuVolt);       // sampled automatically at 100 Hz
}

void loop() {
    float speed = PDS.fastParam(0);     // joystick / PS4 controller
    if (!PDS.linkOk()) speed = 0;       // GUI silent -> stop

    PDS.plot("Speed", speed);           // channel assigned on first call
    PDS.update();                       // exactly once per loop()
}
```

| Task | Call |
|---|---|
| Show a value under a name | `PDS.plot("Ball_X", x)` |
| ... with a unit | `PDS.plot("Akku", v, "V")` |
| Register a variable once, forever | `PDS.track("Akku", &v)` |
| ... on a **fixed** channel | `PDS.bind("Akku", &v, 12)` |
| Use a fixed channel number | `PDS.Channel(12, v)` |
| Mark a moment in the plotter | `PDS.event("Ball verloren")` |
| Write a line to the GUI log book | `PDS.log("Kalibrierung fertig")`, `PDS.warn(...)`, `PDS.error(...)` |
| Read joystick / controller (100 Hz) | `PDS.fastParam(0)` or `PDS.fastParam("Speed")` |
| Read tuning values (2 Hz) | `PDS.param(3)`, `PDS.paramBool(0)`, `PDS.param("Kp")` |
| Emergency stop criterion | `PDS.linkOk()` |
| Reset if `loop()` hangs | `PDS.enableWatchdog(2000)` |
| Show the firmware version in the GUI | `PDS.setFirmwareVersion("1.4.2")` |
| Built-in diagnostics on 6 channels | `PDS.enableSelfDiagnostics()` |

Any integer type works — `int`, `long`, `short`, `uint8_t`, `size_t` — and so
do `float`, `double` and `bool`.

Full API, build flags and integration options:
[`teensy_firmware/README.md`](teensy_firmware/README.md).

---

## ── Directory Structure ──

- **`rpi5_monitor/64Bit_Version/`**: The desktop application (PyQt6). The Qt Quick/QML frontend is the one that is actually shipped and installed — see [`README_QML.md`](rpi5_monitor/64Bit_Version/README_QML.md).
  - `main_qml.py`: **Main entry point** (`setup_rpi5.sh` installs and starts this one). `--simulate` generates synthetic telemetry so the GUI can be tested without a Teensy. `PDS_LOGLEVEL=DEBUG` raises the log level.
  - `starter.bat`: Windows launcher for `main_qml.py`.
  - `network_worker.py`: UDP receiver processes and network backend.
  - `aux_receiver.py`: receiver for the aux uplink (events, parameter feedback, node health) — the parsing is a plain function so it can be unit-tested without a socket.
  - `config.py`: Ports, IPs, packet specifications and GUI timing constants.
  - `bridge/`: the QML backend — one bridge per tab, plus `controller_bridge.py` (PS4 controller), `param_bridge.py` (parameter downlink + the 100 Hz control thread), `diag_bridge.py` (link quality, node health, battery alarm, log book) and `settings_bridge.py` (theme, font size, kiosk mode — persisted).
  - `channel_registry.py`: Receives/parses the descriptor from the Teensy (see Architecture Overview, section 3).
  - `runtime_config.py`: turns the Teensy's configuration into `param_config.json`/`visuals_overlays.json` and stores it per node under `runtime_config/` — including the fingerprint that decides who wins on a conflict.
  - `param_config.json`, `visuals_overlays.json`: **templates**. Once a Teensy has reported its configuration, the copies under `runtime_config/nodeN/` are used instead; these two stay untouched.
  - `controller_config.json` *(optional, git-ignored)*: overrides the controller axis/button mapping — see the PS4 doc.
  - `runtime_config/` *(git-ignored)*: everything the GUI persists — per-node configuration from the Teensy plus the UI settings.
- **`rpi_zero_node/`**: Python scripts and setup scripts for the RPi Zero 2 W nodes.
  - `setup_node.sh`: Auto-installer script for the Pi Zero.
  - `uart_receiver.py`: Receives serial data from the Teensy and forwards it over UDP; also relays the parameter downlink and the channel/param descriptor.
  - `status_leds.py`: Drives heartbeat, data transmission, and network status LEDs.
  - `bt_flash_receiver.py`: Bluetooth SPP server; receives `.hex` files and flashes the Teensy via `teensy_loader_cli`.
- **`teensy_firmware/`**: PlatformIO project + the drop-in Teensy library — see [`teensy_firmware/README.md`](teensy_firmware/README.md) for the full API.
  - `src/PDS.h` / `PDS.cpp`: the `PowerDebugger` class and the ready-made global instance `PDS`.
  - `src/params.h`: wire-format constants and the `UART_DBG` selection.
  - `src/channel_config.h`: **optional** — the complete GUI configuration: parameters (name, widget, range, step, group), joysticks and the graphic-overlay mapping (see Architecture Overview, section 3). Debug-channel names are easier to set in the sketch via `PDS.plot()`/`PDS.track()`/`PDS.bind()`.
  - `src/main.cpp`: a runnable example sketch that exercises the whole chain without a robot attached.
  - `library.json`: lets the folder be pulled into another PlatformIO project via `lib_deps`.
  - Note: `PDS.h` optionally includes `enum.h`, which belongs to the robot project this library is dropped into and is not part of this repository.
- **`tools/`**: developer checks that need no hardware — all of them run in CI.
  - `selftest.py`: frame assemblers, descriptor reassembly, param I/O, Bluetooth protocol, aux uplink, Teensy→config conversion — 98 checks, standard library only.
  - `check_wire_format.py`: verifies that Teensy, node and GUI agree on every magic number, packet size and the wire version.
  - `check_qml_bindings.py`: every `appBridge.…` access in the QML against the real Python bridges.
  - `desc_json_check.py` + `hostsim/`: compiles the Teensy library for the PC against a small Arduino stub, **runs it**, and validates the descriptor with a real JSON parser.
  - `qml_smoketest.py`: starts the whole GUI offscreen and treats any Qt warning as a failure.
  - `build_teensy_check.sh` + `teensy_bind_types_test.cpp`: compiles the Teensy library in four configurations using the toolchain PlatformIO already installed.
- **`shared/`**: Code shared between PC and Pi.
  - `bt_flash_protocol.py`: Frame protocol used by both `bt_flash_sender.py` and `bt_flash_receiver.py`.
- **`pc_flash_tool/`**: Windows-side wireless flashing tool.
  - `bt_flash_sender.py` / `bt_flash_sender_gui.py`: Sends a `.hex` file over Bluetooth to one or both nodes (see Wireless Flashing above).
  - `bt_targets.json`: Bluetooth addresses of the nodes.
- **`requirements.txt`**: Python dependencies of the monitor GUI (`pip install -r requirements.txt`).
- **[`CHANGELOG.md`](CHANGELOG.md)**: what changed, and which of the two version numbers (`PDS_VERSION` / `PDS_WIRE_VERSION`) matters when.
- **`.github/workflows/ci.yml`**: runs every check above plus a PlatformIO build on each push.
- **`Doku/`**: Design and implementation documents (German):
  - [`Latenz_Fernsteuerung.md`](Doku/Latenz_Fernsteuerung.md) — latency of the fast/control channel: where it comes from, which bugs caused it, how to measure it.
  - [`Param_Implementierung.md`](Doku/Param_Implementierung.md) — parameter downlink (slow + fast channel).
  - [`Kanalnamen_Implementierung.md`](Doku/Kanalnamen_Implementierung.md) — channel/param name + overlay descriptor protocol.
  - [`PS4_Controller_Implementierung.md`](Doku/PS4_Controller_Implementierung.md) — PS4 controller integration and calibration.
  - [`Flash_Implementierung.md`](Doku/Flash_Implementierung.md) — wireless firmware flashing over Bluetooth.

---

## ── Setup Instructions ──

### 1. Central Monitor (Raspberry Pi 5)
1. Copy the project files to the RPi 5.
2. Run the master setup script:
   ```bash
   sudo bash setup_rpi5.sh
   ```
3. This configures the hostname, installs the required APT and Python packages (`requirements.txt`, preferring the prebuilt `python3-pyqt6`/`python3-numpy` packages over pip), brings up the Wi-Fi Access Point (SSID `RoboDebug`, key `robodebug123`, RPi 5 at `192.168.42.1`), and sets up `main_qml.py` to start on desktop login. An optional package that fails to install (e.g. `pygame`) no longer aborts the setup.

### 2. PC Setup (Windows 11 Alternative)
If you prefer running the monitor GUI on a Windows laptop instead of an RPi 5:

1. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   `pygame` is optional and only provides PS4 controller support — the GUI runs without it (touch input only). On **Python 3.14 there is no pygame wheel yet** and the source build fails; `requirements.txt` therefore selects `pygame-ce` automatically on 3.14+ (same import name, API-compatible).
2. Set up a Windows Mobile Hotspot (Settings → Network & Internet → Mobile hotspot) with SSID `RoboDebug` and key `robodebug123` — those are the values `setup_node.sh` provisions on the nodes (`AP_SSID`/`AP_PASS`). Then connect the Pi Zero nodes to it.
3. Allow `python.exe` through the Windows Firewall for **private** networks; without that, the inbound UDP telemetry on ports 5001/5002 is silently dropped.
4. Start the GUI with `rpi5_monitor/64Bit_Version/starter.bat` (or `python main_qml.py` from that directory).

> There is no `setup_windows.bat` in this repository — earlier revisions of
> this README referenced one under a `pc_setup/` directory that does not
> exist. The manual steps above replace it.

### 3. Debug Nodes (Raspberry Pi Zero 2 W)
1. Install a clean Raspberry Pi OS Lite (64-bit).
2. Run the node setup script:
   ```bash
   sudo bash setup_node.sh <NODE_ID>
   ```
   *(where `<NODE_ID>` is `1` or `2` depending on the robot)*
3. The script disables the serial console, configures the Wi-Fi client connection, installs `uart_receiver.py` and `status_leds.py` as systemd services, and registers them to auto-start.
4. Check that it is running:
   ```bash
   journalctl -u uart-receiver -f
   ```

---

## ── Hardware Wiring (Teensy ↔ RPi Zero) ──

Ensure the following connections are made between the Teensy 4.0 and the RPi Zero 2 W:
- **Teensy Pin 14 (TX3)** ──▶ **RPi GPIO 15 (Pin 10, RXD)**
- **Teensy Pin 15 (RX3)** ◀── **RPi GPIO 14 (Pin 8,  TXD)** — **required** for the parameter downlink (joystick / PS4 controller). Without this wire the robot receives no control commands at all.
- **Teensy GND** ────────── **RPi GND (Pin 6)**

The UART instance is selected by the `UART_DBG` macro in
`teensy_firmware/src/params.h` (default `Serial3`). Change it there if your
wiring uses different pins — the rest of the firmware follows automatically.

---

## ── LED Status Indicators (RPi Zero) ──

| LED | GPIO | Meaning |
|---|---|---|
| 🟢 Green, short blink 1×/s | 27 | Heartbeat — `uart-receiver` is running |
| 🔵 Blue, steady | 22 | Wi-Fi connection to the RPi 5 is up |
| 🟡 Yellow, flickering | 24 | Serial data arriving from the Teensy |

The LEDs are driven by `status_leds.py` directly from `uart_receiver.py` —
there is no separate service. `gpiozero` is optional: without it (or on a
PC) the node runs unchanged, just without LED output. Wiring can be tested
on its own with `python3 status_leds.py`.

---

## ── Wire Format Constants ──

These three values define the telemetry packet and **must be changed
together**, otherwise the node silently drops every packet as a size
mismatch:

| Constant | File |
|---|---|
| `MAX_FLOATS = 200` | `teensy_firmware/src/PDS.cpp` |
| `MAX_FLOATS = 200` | `rpi_zero_node/uart_receiver.py` |
| `MAX_FLOATS = 200` | `rpi5_monitor/64Bit_Version/config.py` |

The same applies to the baud rate (`UART_DBG_BAUD` in `params.h` ↔
`UART_BAUD` in `uart_receiver.py`) and to the magic numbers and packet sizes
of the parameter/descriptor channels, which are mirrored in `params.h`,
`uart_receiver.py` and `config.py`.

The `ACTIVE_CHANNELS` build flag in `platformio.ini` only controls how many
channels can carry names/bindings; it may not exceed `MAX_FLOATS` (enforced
by a `static_assert`) and does **not** change the packet size.

`PDS_WIRE_VERSION` (in `params.h`, mirrored in `uart_receiver.py` and
`config.py`) is bumped whenever the format changes incompatibly — see
[`CHANGELOG.md`](CHANGELOG.md) for which of the two version numbers matters
when.

**You don't have to check this by hand.** `tools/check_wire_format.py` reads
all three files and reports any mismatch, including the resulting packet
sizes and both the steady-state and the peak UART load:

```bash
python tools/check_wire_format.py
```

---

## ── Developer Checks (no hardware needed) ──

Six scripts cover everything that can be verified without a Teensy, a node
or a Wi-Fi link. All of them also run in CI on every push
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

```bash
python tools/selftest.py
```

| Script | What it covers |
|---|---|
| `tools/selftest.py` | 98 checks: frame assemblers (resync, split packets, garbage), descriptor reassembly across restarts, channel registry robustness, overlay defaults, `param_io` round-trip, Bluetooth frame protocol + CRC, aux uplink parsing, Teensy→`param_config.json` conversion, `textgrid` layout. Standard library only — numpy/PyQt6/pyserial may be missing. |
| `tools/check_wire_format.py` | Magic numbers, packet sizes, channel count, baud rate and wire version across Teensy, node and GUI, plus the UART budget. |
| `tools/check_qml_bindings.py` | Every `appBridge.…` access in the QML against the actual Python bridge classes. A typo there is silently `undefined` at runtime — this catches it statically. Also checks brace balance. |
| `tools/desc_json_check.py` | Compiles `PDS.cpp` against a small Arduino stub for the PC, **runs it**, and validates the descriptor it produces with a real JSON parser — including quotes, backslashes, umlauts and control characters in names. Compiling alone does not find that class of bug. Skips silently if no `g++` is installed. |
| `tools/qml_smoketest.py` | Starts the whole GUI offscreen, feeds synthetic data through it, operates the controls and treats **any Qt warning as a failure**. Needs `PyQt6` and `numpy`. |
| `tools/build_teensy_check.sh` | Compiles the Teensy library with `-Wall` in four configurations (default, without `channel_config.h`, 32 channels, full `bind()` type coverage) using the ARM toolchain PlatformIO already installed. |

The GUI itself can be exercised without any hardware — the simulator also
generates events, parameter feedback and node health, so the Diagnostics tab
and the plotter markers work too:

```bash
python rpi5_monitor/64Bit_Version/main_qml.py --simulate
```

---

## ── Troubleshooting ──

| Symptom | Where to look |
|---|---|
| Remote control (joystick/PS4 controller) reacts with a delay | [`Doku/Latenz_Fernsteuerung.md`](Doku/Latenz_Fernsteuerung.md) — full latency budget and measurement instructions |
| No telemetry in the GUI at all | `journalctl -u uart-receiver -f` on the node. `0.0 Pkt/s` ⇒ problem between Teensy and node (wiring, baud rate, `MAX_FLOATS`). Packets flowing but nothing in the GUI ⇒ firewall or wrong network. |
| Channel names show as `Var_042` | Press "🏷 Kanalnamen" in the header, or check `channel_config.h`. Normally not needed — the firmware repeats the announcement by itself. |
| Parameters tab looks wrong after a firmware change | The stored configuration only gets replaced when the Teensy's fingerprint changes. Press "Gespeicherte Konfiguration verwerfen" in the Diagnostics tab. |
| Joystick/controller feels jerky | Check "Verlust" and "Ping" per node in the Diagnostics tab, and whether the node log still says `Telemetrie -> 255.255.255.255`. |
| Robot restarted for no apparent reason | Look in the Diagnostics log book: with `PDS.enableWatchdog(...)` active, a watchdog reset is reported there as an error on the next boot. |
| Node log says `Sync-Verluste` keeps rising | Bytes are being lost on the Teensy → node UART: check wiring/ground and that the baud rates match. |
| Node log says `Telemetrie -> 255.255.255.255` | The node has not seen a parameter packet from the GUI yet — is "Übertragung aktiv" enabled? This also costs a lot of Wi-Fi airtime; see the latency doc. |
