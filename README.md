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
                │ UDP Broadcast (5001/5002)                                  ┌─────────────────────────┐
                └─────────────────────────────────────────────────────────── │ Teensy 4.0 (Firmware)   │
                                                                             │ - PowerDebugger (PDS)   │
                                                                             └─────────────────────────┘
```

### 1. Telemetry Uplink (Teensy 4.0 → RPi Zero → GUI Monitor)
- **Teensy 4.0** transmits telemetry packets over UART (`Serial3` at `1'000'000` Baud) to the Raspberry Pi Zero.
- **RPi Zero Node** runs `uart_receiver.py` which reads the serial stream, packages it, and broadcasts it over UDP (ports `5001` for Node 1, `5002` for Node 2) to the local Wi-Fi network.
- **GUI Monitor** receives these broadcasts. The monitor automatically detects the node IP addresses from the sender IP of the incoming UDP packets.

### 2. Parameter Downlink (GUI Monitor → RPi Zero → Teensy 4.0)
Parameters can be configured directly in the GUI and sent back to the active node via UDP Unicast:
- **Slow Channel (2 Hz)**: Sends 50 Floats + 50 Bools (Port `7001` or `7002`, Magic `0xCAFEFEED`). Used for robot configuration.
- **Fast Channel (100 Hz)**: Sends 5 Floats (Port `7011` or `7012`, Magic `0xFA57DA7A`). Used for real-time joystick/motion controls.
- **RPi Zero Node** listens to these UDP ports and forwards the raw bytes immediately over UART to the Teensy.
- **Teensy 4.0** parses the incoming packet stream via a synchronized parser in the `PowerDebugger` class, updating the RAM values for the robot logic.

*Note: Firmware flashing and USB-C gadget network features have been completely removed from this project.*

---

## ── Directory Structure ──

- **`rpi5_monitor/`**: The PyQt6 PyQt-based desktop application.
  - `main.py`: Main entry point for the GUI.
  - `network_worker.py`: UDP receivers and network backend.
  - `config.py`: Port, IP, and packet specifications.
- **`rpi_zero_node/`**: Python scripts and setup scripts for the RPi Zero 2 W nodes.
  - `setup_node.sh`: Auto-installer script for the Pi Zero.
  - `spi_receiver.py` (installed as `uart_receiver.py`): Receives serial data from Teensy and sends UDP broadcasts.
  - `status_leds.py`: Drives heartbeat, data transmission, and network status LEDs.
- **`teensy_firmware/`**: PlatformIO project for the Teensy 4.0 firmware.
  - `src/PDS.h` / `PDS.cpp`: The `PowerDebugger` class.
  - `src/params.h`: Parameter structures and constants.
- **`pc_setup/`**: Batch file and documentation to run the GUI on a Windows 11 PC.
  - `setup_windows.bat`: Opens Windows firewall rules and opens mobile hotspot settings.

---

## ── Setup Instructions ──

### 1. Central Monitor (Raspberry Pi 5)
1. Copy the project files to the RPi 5.
2. Run the master setup script:
   ```bash
   sudo bash setup_rpi5.sh
   ```
3. This configures the hostname, installs necessary APT and Python packages, configures the Wi-Fi Access Point (`PowerDebugAP`), and sets up the GUI to start on desktop login.

### 2. PC Setup (Windows 11 Alternative)
If you prefer running the monitor GUI on a Windows laptop instead of an RPi 5:
1. Run `pc_setup/setup_windows.bat` **as Administrator**.
2. Configure your Windows Mobile Hotspot settings as prompted (SSID: `RoboDebug`, Key: `robodebug123`).
3. Connect the Pi Zero nodes to your laptop's hotspot.

### 3. Debug Nodes (Raspberry Pi Zero 2 W)
1. Install a clean Raspberry Pi OS Lite (64-bit).
2. Run the node setup script:
   ```bash
   sudo bash setup_node.sh <NODE_ID>
   ```
   *(where `<NODE_ID>` is `1` or `2` depending on the robot)*
3. The script disables the serial console, configures the Wi-Fi client connection, installs `uart_receiver.py` and `status_leds.py` as systemd services, and registers them to auto-start.

---

## ── Hardware Wiring (Teensy ↔ RPi Zero) ──

Ensure the following connections are made between the Teensy 4.0 and the RPi Zero 2 W:
- **Teensy Pin 14 (TX3)** ──▶ **RPi GPIO 15 (Pin 10, RXD)**
- **Teensy Pin 15 (RX3)** ◀── **RPi GPIO 14 (Pin 8,  TXD)** *(optional, for parameter downlink)*
- **Teensy GND** ────────── **RPi GND (Pin 6)**

---

## ── LED Status Indicators (RPi Zero) ──

- **🔵 Blue LED**: Connected to the master Wi-Fi hotspot.
- **🟡 Yellow LED (Blinking)**: Receiving serial data from the Teensy.
- **🟢 Green LED (Blinking)**: Heartbeat/system daemon running.
