# Robotic PDS — Power Debug System

Live-Telemetrie, Parameter und Fernsteuerung für die Roboter im
**RoboCup Junior Soccer 2vs2**: Ein Teensy 4.0 im Roboter schickt bis zu
200 Werte mit 100 Hz über einen Raspberry Pi Zero 2 W ins WLAN, ein
Raspberry Pi 4/5 (oder ein PC) zeigt sie an — als Tabelle, Plotter,
Roboter-Ansicht und Spielfeld — und schickt Einstellwerte und Joystick bzw.
PS4-Controller zurück.

```
 Roboter                                   Spielfeldrand
┌──────────┐  UART   ┌─────────────┐  WLAN  ┌──────────────────────┐
│ Teensy   │◀──────▶ │ Node        │◀──────▶│ Haupt-Pi oder PC     │
│ PDS-Lib  │ 1 Mbit/s│ Pi Zero 2 W │        │ GUI · PS4-Controller │
└──────────┘         └─────────────┘        └──────────────────────┘
```

| Dokument | Inhalt |
|---|---|
| **[FEATURES.md](FEATURES.md)** | Was das System kann — vollständige Liste |
| **[Doku/Setup_und_Update.md](Doku/Setup_und_Update.md)** | Einrichten und Aktualisieren von Haupt-Pi und Nodes |
| [teensy_firmware/README.md](teensy_firmware/README.md) | Die Teensy-Bibliothek: API, Build-Flags, Verkabelung |
| [Doku/Architektur.md](Doku/Architektur.md) | Wie die Teile miteinander reden: Ports, Pakete, Wire-Format |
| [Doku/](Doku/README.md) | Hintergründe zu einzelnen Themen |
| [CHANGELOG.md](CHANGELOG.md) | Was sich wann geändert hat |

---

## Schnellstart

**Haupt-Pi** (Raspberry Pi OS mit Desktop):
```bash
git clone https://github.com/JuKimpfler/Robotic_PDS.git && cd Robotic_PDS
sudo bash setup_rpi5.sh          # oder --ap: der Pi spannt das WLAN selbst auf
```

**Nodes** (Raspberry Pi OS Lite), vom PC aus:
```bash
./deploy.sh --setup-node 1 pi@debug-node-1.local
./deploy.sh --setup-node 2 pi@debug-node-2.local
```

**Aktualisieren** — alles auf einmal, ohne Internet auf den Geräten:
```bash
./deploy.sh all
```

**Ohne Hardware ausprobieren:**
```bash
pip install -r requirements.txt
python rpi5_monitor/64Bit_Version/main_qml.py --simulate
```

Alle Einzelheiten — WLAN-Varianten, Verkabelung, Windows-PC statt Pi,
Rückweg nach einem Update, Fehlersuche — stehen im
[Setup- und Update-Guide](Doku/Setup_und_Update.md).

## Im Roboter-Code

```cpp
#include "PDS.h"

float akkuVolt = 0;
bool  ballVerloren = false;

void setup() {
    PDS.begin();
    PDS.track("Akku", &akkuVolt, "V");   // ab jetzt 100x/s in der GUI
}

void loop() {
    float speed = PDS.fastParam(0);      // Joystick / PS4-Controller
    if (!PDS.linkOk()) speed = 0;        // GUI weg -> anhalten

    PDS.plot("Speed", speed);            // Kanal wird automatisch vergeben
    if (ballVerloren) PDS.event("Ball verloren");   // Marke im Plotter
    PDS.update();                        // genau einmal pro loop()
}
```

`update()` wartet auf nichts — auch nicht ohne Node oder GUI. Die komplette
API steht in [`teensy_firmware/README.md`](teensy_firmware/README.md).

## Aufbau des Repositorys

| Ordner / Datei | Inhalt |
|---|---|
| `teensy_firmware/` | PlatformIO-Projekt mit der Bibliothek (`src/PDS.*`, `params.h`, optional `channel_config.h`) und einem Beispiel-Sketch |
| `rpi_zero_node/` | Node: `uart_receiver.py` (Weiterleitung), `status_leds.py`, `bt_flash_receiver.py`, `setup_node.sh` |
| `rpi5_monitor/64Bit_Version/` | Oberfläche: `main_qml.py`, `qml/`, `bridge/` (eine Python-Brücke je Tab), Einstellungen und Vorlagen — siehe [`README_QML.md`](rpi5_monitor/64Bit_Version/README_QML.md) |
| `shared/` | Code für PC und Node (Bluetooth-Flash-Protokoll) |
| `pc_flash_tool/` | Firmware per Bluetooth vom Windows-PC flashen — siehe [`README.md`](pc_flash_tool/README.md) |
| `setup_rpi5.sh` | Haupt-Pi einrichten |
| `update.sh` | Gerät aktualisieren (läuft auf dem Gerät) |
| `deploy.sh` | Geräte vom PC aus einrichten/aktualisieren |
| `scripts/pds_common.sh` | gemeinsame Schritte von Setup und Update |
| `tools/` | Prüfungen ohne Hardware, Messwerkzeuge |
| `requirements.txt` | Python-Pakete der Oberfläche |

## Entwickeln

```bash
bash tools/check_all.sh            # alle Prüfungen, genau wie die CI
bash tools/check_all.sh lint       # nur die schnellen
```

| Stufe | Was |
|---|---|
| `lint` | pyflakes, ShellCheck, Wire-Format Teensy ↔ Node ↔ GUI, QML-Zugriffe gegen die Brücken, Setup/Update/Deploy in einer Sandbox |
| `python` | Selbsttest (250+ Prüfungen), Plotter Wert für Wert |
| `gui` | komplette Oberfläche offscreen (jede Qt-Warnung = Fehler), Zeitbudget für ein Plotter-Bild |
| `teensy` | Bibliothek auf dem PC ausgeführt und Deskriptor geprüft, Firmware-Build in mehreren Konfigurationen |

Fehlende Werkzeuge werden übersprungen, nicht rot gemeldet. Die CI
(`.github/workflows/ci.yml`) läuft bei jedem Push; ein Tag `v*` erzeugt über
`release.yml` ein GitHub-Release mit `firmware.hex` und installierbarem Paket.

Messen statt raten: `python tools/plotter_bench.py` (Plotter),
`PDS.printStatus()` (Teensy), `journalctl -u uart-receiver -f` (Node).
