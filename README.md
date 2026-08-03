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
- **Addressing**: the node learns the GUI's address from the incoming parameter packets and then sends **unicast**. Until it has learned one — and if the GUI goes quiet for more than 10 s — it falls back to broadcast, so discovery still works out of the box.
  Broadcast is deliberately *not* the default any more: Wi-Fi must send broadcast frames at the lowest basic rate of the BSS, without aggregation and without MAC-level ACKs. At 80.8 kB/s that consumed a large share of the airtime per node and was the main reason the joystick/controller downlink became laggy. See [`Doku/Latenz_Fernsteuerung.md`](Doku/Latenz_Fernsteuerung.md).
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
channel shows up where" mapping, maintained in one file:
`teensy_firmware/src/channel_config.h`. At boot (and whenever the GUI
requests it again) the firmware builds a small JSON descriptor — names for
the 200 debug channels, the 50+50+5 param channels, and the overlay/widget
mapping (gauge/rotation/vector/table/body-object/text-overlay) — and streams
it in small chunks over the same UART path used for telemetry/params:
- **Descriptor chunks (Teensy → GUI)**: Magic `0xDE5C0001`, forwarded by the
  node to UDP port `5011`/`5012`.
- **Resend request (GUI → Teensy)**: Magic `0xDE5C00F0`, sent to UDP port
  `7021`/`7022`.

The GUI merges received names/overlays into its local `config.py`
(`VARIABLE_NAMES`) and `visuals_overlays.json` without ever overwriting
groups you've already customized. See `Doku/Kanalnamen_Implementierung.md`
for the full protocol, the `channel_config.h` authoring format, and the
Teensy-library API (`bind()` for pointer-based auto-sampled channels,
`Channel(chn, val, name)` for named dynamic writes).

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

## ── Directory Structure ──

- **`rpi5_monitor/64Bit_Version/`**: The desktop application (PyQt6). The Qt Quick/QML frontend is the one that is actually shipped and installed — see [`README_QML.md`](rpi5_monitor/64Bit_Version/README_QML.md).
  - `main_qml.py`: **Main entry point** (`setup_rpi5.sh` installs and starts this one). `--simulate` generates synthetic telemetry so the GUI can be tested without a Teensy. `PDS_LOGLEVEL=DEBUG` raises the log level.
  - `main.py` + `gui/`: the older PyQt6-**Widgets** GUI. Kept for reference, not installed by any setup script and not part of the QML feature set (no PS4 controller support, for instance).
  - `starter.bat`: Windows launcher for `main_qml.py`.
  - `network_worker.py`: UDP receiver processes and network backend.
  - `config.py`: Ports, IPs, packet specifications and GUI timing constants.
  - `bridge/`: the QML backend — one bridge per tab plus `controller_bridge.py` (PS4 controller) and `param_bridge.py` (parameter downlink).
  - `channel_registry.py`: Receives/parses the channel-/param-name + overlay descriptor from the Teensy (see Architecture Overview, section 3) and merges it into `VARIABLE_NAMES`/`visuals_overlays.json`.
  - `param_config.json`: Definition of the 50 + 50 + 5 parameters and their widgets.
  - `controller_config.json` *(optional, git-ignored)*: overrides the controller axis/button mapping — see the PS4 doc.
- **`rpi_zero_node/`**: Python scripts and setup scripts for the RPi Zero 2 W nodes.
  - `setup_node.sh`: Auto-installer script for the Pi Zero.
  - `spi_receiver.py` (installed as `uart_receiver.py`): Receives serial data from the Teensy and forwards it over UDP; also relays the parameter downlink and the channel/param descriptor.
  - `status_leds.py`: Drives heartbeat, data transmission, and network status LEDs.
  - `bt_flash_receiver.py`: Bluetooth SPP server; receives `.hex` files and flashes the Teensy via `teensy_loader_cli`.
- **`teensy_firmware/`**: PlatformIO project for the Teensy 4.0 firmware.
  - `src/PDS.h` / `PDS.cpp`: The `PowerDebugger` class.
  - `src/params.h`: Parameter structures and constants.
  - `src/channel_config.h`: Single source of truth for channel/param display names and the graphic-overlay mapping (see Architecture Overview, section 3).
  - Note: `PDS.h` optionally includes `enum.h`, which belongs to the robot project this library is dropped into and is not part of this repository.
- **`shared/`**: Code shared between PC and Pi.
  - `bt_flash_protocol.py`: Frame protocol used by both `bt_flash_sender.py` and `bt_flash_receiver.py`.
- **`pc_flash_tool/`**: Windows-side wireless flashing tool.
  - `bt_flash_sender.py` / `bt_flash_sender_gui.py`: Sends a `.hex` file over Bluetooth to one or both nodes (see Wireless Flashing above).
  - `bt_targets.json`: Bluetooth addresses of the nodes.
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
3. This configures the hostname, installs the required APT and Python packages (including `pygame` for the PS4 controller), brings up the Wi-Fi Access Point (SSID `RoboDebug`, key `robodebug123`, RPi 5 at `192.168.42.1`), and sets up `main_qml.py` to start on desktop login.

### 2. PC Setup (Windows 11 Alternative)
If you prefer running the monitor GUI on a Windows laptop instead of an RPi 5:

1. Install the dependencies:
   ```bash
   pip install PyQt6 numpy pygame
   ```
   `pygame` is optional and only provides PS4 controller support — the GUI runs without it (touch input only). On **Python 3.14 there is no pygame wheel yet** and the source build fails; use `pip install pygame-ce` there instead (same import name, API-compatible).
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

- **🔵 Blue LED**: Connected to the master Wi-Fi hotspot.
- **🟡 Yellow LED (Blinking)**: Receiving serial data from the Teensy.
- **🟢 Green LED (Blinking)**: Heartbeat/system daemon running.

---

## ── Wire Format Constants ──

These three values define the telemetry packet and **must be changed
together**, otherwise the node silently drops every packet as a size
mismatch:

| Constant | File |
|---|---|
| `MAX_FLOATS = 200` | `teensy_firmware/src/PDS.cpp` |
| `MAX_FLOATS = 200` | `rpi_zero_node/spi_receiver.py` |
| `MAX_FLOATS = 200` | `rpi5_monitor/64Bit_Version/config.py` |

The same applies to the baud rate (`UART_DBG_BAUD` in `params.h` ↔
`UART_BAUD` in `spi_receiver.py`) and to the magic numbers and packet sizes
of the parameter/descriptor channels, which are mirrored in `params.h`,
`spi_receiver.py` and `config.py`.

The `ACTIVE_CHANNELS` build flag in `platformio.ini` only controls how many
channels can carry names/bindings; it may not exceed `MAX_FLOATS` (enforced
by a `static_assert`) and does **not** change the packet size.

---

## ── Troubleshooting ──

| Symptom | Where to look |
|---|---|
| Remote control (joystick/PS4 controller) reacts with a delay | [`Doku/Latenz_Fernsteuerung.md`](Doku/Latenz_Fernsteuerung.md) — full latency budget and measurement instructions |
| No telemetry in the GUI at all | `journalctl -u uart-receiver -f` on the node. `0.0 Pkt/s` ⇒ problem between Teensy and node (wiring, baud rate, `MAX_FLOATS`). Packets flowing but nothing in the GUI ⇒ firewall or wrong network. |
| Channel names show as `Var_042` | The descriptor is only sent at Teensy boot; press "Kanalnamen anfordern" in the GUI status bar, or check `channel_config.h`. |
| Node log says `Sync-Verluste` keeps rising | Bytes are being lost on the Teensy → node UART: check wiring/ground and that the baud rates match. |
| Node log says `Telemetrie -> 255.255.255.255` | The node has not seen a parameter packet from the GUI yet — is "Übertragung aktiv" enabled? This also costs a lot of Wi-Fi airtime; see the latency doc. |
