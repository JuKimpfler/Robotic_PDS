# Telemetry Streaming System

High-throughput, low-latency telemetry pipeline: **Teensy 4.0** → SPI → **Raspberry Pi Zero 2W** (C bridge) → UDP/WiFi → **Windows 11 PC** (Go backend + Svelte frontend).

## Quick Start (ohne Hardware)

```powershell
# Empfohlen (PowerShell — kein && nötig):
.\scripts\run_simulate.ps1

# Oder manuell (zwei Zeilen):
cd pc-backend
& "C:\Program Files\Go\bin\go.exe" run . --simulate
```

Öffne `http://localhost:8080` — WebSocket-Stream auf Port **9001**.

## Projektstruktur

| Verzeichnis | Beschreibung |
|---|---|
| `teensy/` | PlatformIO Firmware (Teensy 4.0, SPI Slave) |
| `rpi-bridge/` | C-Daemon: SPI → UDP (Raspberry Pi) |
| `pc-backend/` | Go-Backend: UDP-Empfang, WebSocket, HTTP-API |
| `frontend/` | Svelte 5 + uPlot + Tailwind CSS v4 |
| `shared/protocol.md` | Autoritative Protokollspezifikation |
| `scripts/` | Deployment- und Setup-Skripte |

## Ports

| Dienst | Port |
|---|---|
| UDP (RPi → PC) | 9000 |
| WebSocket (PC → Browser) | 9001 |
| HTTP (Frontend + API) | 8080 |

## Konfiguration

- Backend: `pc-backend/config.yaml`
- Kanäle: `pc-backend/channels.csv` (Hot-Reload)
- Parameter: `pc-backend/parameters.csv`
- RPi Bridge: `rpi-bridge/config/bridge.conf`

## Deployment

```powershell
# Windows (einmalig, als Admin)
.\scripts\install_windows.ps1

# RPi Bridge cross-compilieren
./scripts/cross_compile_bridge.sh

# RPi einrichten
./scripts/setup_rpi.sh
```

## Simulate-Modus

Alle Komponenten unterstützen `--simulate`:

```bash
# Teensy (PlatformIO): build_flags = -DSIMULATE
go run . --simulate          # PC Backend
./spi_bridge --simulate      # RPi Bridge
```

## Dokumentation

Vollständige Spezifikation: [README_TELEMETRY_SYSTEM.md](README_TELEMETRY_SYSTEM.md)  
Protokoll-Referenz: [shared/protocol.md](shared/protocol.md)  
Implementierungs-Fortschritt: [TODO.md](TODO.md)
