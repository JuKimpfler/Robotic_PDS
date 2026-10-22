# Setup und Update — Haupt-Pi und Nodes

Dieser Guide führt von einem leeren Raspberry Pi bis zum laufenden System und
zeigt danach, wie man es aktuell hält. Er ersetzt alle früheren
Einzelanleitungen in README und Setup-Skripten.

**Kurzfassung für Eilige**

| Was | Befehl |
|---|---|
| Haupt-Pi einrichten | `sudo bash setup_rpi5.sh` (im Repository) |
| Node einrichten | `cd rpi_zero_node && sudo bash setup_node.sh 1` (bzw. `2`) |
| Alles aktualisieren, vom PC | `./deploy.sh all` |
| Ein Gerät direkt aktualisieren | `sudo bash update.sh` |
| Letztes Update zurücknehmen | `sudo bash update.sh --rollback` |
| Was läuft hier? | `sudo bash update.sh --status` |

---

## Inhalt

1. [Überblick: wer ist wer](#1-überblick-wer-ist-wer)
2. [Was man braucht](#2-was-man-braucht)
3. [WLAN: Router oder Haupt-Pi als Access Point](#3-wlan-router-oder-haupt-pi-als-access-point)
4. [Haupt-Pi einrichten](#4-haupt-pi-einrichten)
5. [Nodes einrichten](#5-nodes-einrichten)
6. [Verkabelung Teensy ↔ Node](#6-verkabelung-teensy--node)
7. [Erster Test](#7-erster-test)
8. [Aktualisieren](#8-aktualisieren)
9. [Zurück auf den vorherigen Stand](#9-zurück-auf-den-vorherigen-stand)
10. [Windows-PC statt Haupt-Pi](#10-windows-pc-statt-haupt-pi)
11. [Was wo liegt](#11-was-wo-liegt)
12. [Fehlersuche](#12-fehlersuche)

---

## 1. Überblick: wer ist wer

```
  Roboter 1                         Roboter 2
 ┌──────────┐  UART  ┌──────────┐  ┌──────────┐  UART  ┌──────────┐
 │ Teensy   │◀──────▶│ Node 1   │  │ Teensy   │◀──────▶│ Node 2   │
 │ (PDS-Lib)│ 1 Mbps │ Pi Zero 2│  │ (PDS-Lib)│ 1 Mbps │ Pi Zero 2│
 └──────────┘        └────┬─────┘  └──────────┘        └────┬─────┘
                          │        WLAN "RoboDebug"         │
                          └──────────────┬──────────────────┘
                                         │
                              ┌──────────┴──────────┐
                              │ Haupt-Pi (Pi 4 / 5) │
                              │ GUI, Touchscreen,   │
                              │ PS4-Controller      │
                              └─────────────────────┘
```

* **Teensy** — die Bibliothek `teensy_firmware/src/PDS.*` im Roboter-Code.
* **Node** — Raspberry Pi Zero 2 W im Roboter. Leitet Telemetrie vom Teensy
  ins WLAN weiter und Parameter/Joystick zurück. Flasht den Teensy auf Wunsch
  per Bluetooth.
* **Haupt-Pi** — Raspberry Pi 4 (2 GB) oder Pi 5 mit Bildschirm. Zeigt alles
  an, schickt Parameter und Fernsteuerung.

## 2. Was man braucht

| Gerät | Betriebssystem | Hinweis |
|---|---|---|
| Haupt-Pi | Raspberry Pi OS **mit Desktop**, 64 Bit, Bookworm oder Trixie | Pi 4 (2 GB) reicht |
| Node (×2) | Raspberry Pi OS **Lite**, 64 Bit, Bookworm oder Trixie | Pi Zero 2 W |
| Entwicklungs-PC | beliebig, mit `ssh` und `tar` (Linux, macOS, Git-Bash unter Windows) | nur für `deploy.sh` |

Beim Beschreiben der SD-Karten mit dem **Raspberry Pi Imager** gleich
einstellen (Zahnrad-Symbol):

* **Hostname**: `power-debug-monitor` (Haupt-Pi), `debug-node-1`, `debug-node-2`.
  Die Setup-Skripte setzen genau diese Namen ohnehin — so stimmen sie schon
  beim ersten Start.
* **SSH aktivieren**, Benutzer und Passwort festlegen (im Folgenden `pi`).
* **WLAN** mit Internetzugang für die Ersteinrichtung (apt/pip).
* **WLAN-Land**: `DE`.

Für die Ersteinrichtung braucht jedes Gerät einmal Internet. Danach nie
wieder — Updates gehen auch ohne (siehe [8](#8-aktualisieren)).

## 3. WLAN: Router oder Haupt-Pi als Access Point

Alle Geräte treffen sich im WLAN **`RoboDebug`** mit dem Passwort
**`robodebug123`** (einzustellen in `setup_rpi5.sh` und
`rpi_zero_node/setup_node.sh`, `AP_SSID`/`AP_PASS` — beide müssen gleich
sein). Wer das Netz aufspannt, ist frei:

| Variante | Wann | Haupt-Pi-Setup |
|---|---|---|
| **Router am Spielfeld** (Standard) | Router vorhanden, mehrere Laptops sollen mit ins Netz | `sudo bash setup_rpi5.sh` |
| **Haupt-Pi als Access Point** | kein Router, alles soll aus einer Kiste kommen | `sudo bash setup_rpi5.sh --ap` |

Feste IP-Adressen gibt es nicht. Die Nodes bekommen ihre Adresse per DHCP,
die GUI lernt sie aus den eingehenden Paketen, und die Nodes lernen die
Adresse der GUI aus deren Paketen. Im AP-Modus hat der Haupt-Pi
`192.168.42.1`.

## 4. Haupt-Pi einrichten

```bash
git clone https://github.com/JuKimpfler/Robotic_PDS.git
cd Robotic_PDS
sudo bash setup_rpi5.sh            # Router-WLAN
# oder
sudo bash setup_rpi5.sh --ap       # Pi spannt das WLAN selbst auf
```

Optionen: `--yes` beantwortet alle Rückfragen mit Ja (unbeaufsichtigt),
ein anderes Installationsverzeichnis lässt sich als letztes Argument angeben
(Standard `/opt/power_debug_monitor`).

**Als der Desktop-Benutzer mit `sudo` starten**, nicht als root — das Skript
richtet Autostart und Autologin für den Benutzer ein, der `sudo` aufgerufen
hat.

Das Skript

1. setzt den Hostnamen `power-debug-monitor`,
2. installiert Systempakete und Python-Abhängigkeiten (PyQt6, NumPy und
   pyqtgraph bevorzugt aus apt, der Rest per pip; `pygame` für den
   PS4-Controller ist optional),
3. kopiert die Oberfläche nach `/opt/power_debug_monitor`,
4. richtet das WLAN ein (Client-Profil oder Access Point),
5. legt den Starter `power-debug-monitor` an,
6. trägt die GUI in den Desktop-Autostart ein,
7. schaltet den Autologin ein,
8. merkt sich in `/etc/pds/pds.conf`, was installiert ist (für Updates).

Danach: `sudo reboot`. Die GUI startet von selbst.

Von Hand starten: `power-debug-monitor` — oder mit Testdaten ohne Roboter:
`power-debug-monitor --simulate`.

## 5. Nodes einrichten

Für jeden Node, mit der Node-Nummer **1** oder **2**:

**Variante A — vom PC aus (empfohlen):** der Node braucht nur SSH und
Internet, kein git.

```bash
./deploy.sh --setup-node 1 pi@debug-node-1.local
```

**Variante B — direkt auf dem Node:**

```bash
git clone https://github.com/JuKimpfler/Robotic_PDS.git
cd Robotic_PDS/rpi_zero_node
sudo bash setup_node.sh 1
```

Das Skript

1. installiert die Pakete (pyserial, gpiozero/lgpio für die LEDs,
   `teensy-loader-cli` für das Flashen per Bluetooth),
2. schaltet die UART auf GPIO 14/15 frei (Bluetooth wandert auf die
   Mini-UART und bleibt nutzbar) und entfernt die serielle Konsole,
3. legt das WLAN-Profil `RoboDebug` an,
4. setzt den Hostnamen `debug-node-<N>`,
5. installiert die Programme nach `/opt/power_debug_node`,
6. erzeugt einmalig einen Auth-Token für das Bluetooth-Flashen,
7. richtet die Dienste `uart-receiver` und `bt-flash-receiver` ein,
8. merkt sich in `/etc/pds/pds.conf`, was installiert ist.

Danach: `sudo reboot` — erst dann gelten die UART-Einstellungen.

Am Ende gibt das Skript **MAC-Adresse, Auth-Token und RFCOMM-Kanal** aus.
Diese drei Werte gehören in `pc_flash_tool/bt_targets.json` auf dem PC, von
dem aus per Bluetooth geflasht werden soll (siehe
[`pc_flash_tool/README.md`](../pc_flash_tool/README.md)).

**LEDs nach dem Neustart**

| LED | GPIO | Bedeutung |
|---|---|---|
| 🟢 grün, kurzes Blinken 1×/s | 27 | `uart-receiver` läuft |
| 🔵 blau, dauerhaft | 22 | WLAN verbunden |
| 🟡 gelb, flackert | 24 | Daten vom Teensy kommen an |

## 6. Verkabelung Teensy ↔ Node

| Teensy 4.0 | Raspberry Pi Zero 2 W | |
|---|---|---|
| Pin 14 (TX3) | GPIO 15 (Pin 10, RXD) | Telemetrie |
| Pin 15 (RX3) | GPIO 14 (Pin 8, TXD) | **Pflicht** für Parameter und Fernsteuerung |
| GND | GND (Pin 6) | |
| USB | USB | nur für das Flashen per Bluetooth |

Die Teensy-Seite wählt `UART_DBG` in `teensy_firmware/src/params.h`
(Standard `Serial3`). Baudrate 1 Mbit/s auf beiden Seiten.

## 7. Erster Test

1. Haupt-Pi und Nodes einschalten, Roboter mit laufender PDS-Firmware an.
2. In der GUI oben links leuchtet beim richtigen Node der Punkt grün, unten
   steht „100 Pkt/s".
3. Tab **Diagnose**: Verlust ≈ 0 %, Ping wenige Millisekunden, Node-Status
   mit Temperatur und WLAN-Pegel.

Ohne Roboter: `power-debug-monitor --simulate` erzeugt Testdaten für beide
Nodes, inklusive Ereignissen und Node-Status.

## 8. Aktualisieren

Ein Update tauscht **nur den Code** aus und startet Dienste bzw. GUI neu.
Es fasst **nicht** an: Bootkonfiguration, WLAN, apt-Pakete, `settings.json`
und Profile, `runtime_config/`, `controller_config.json`, gespeicherte
`param_defaults.h`, den Bluetooth-Auth-Token. Das Setup muss dafür nie
wieder laufen.

### Vom PC aus — alle Geräte auf einmal

```bash
./deploy.sh all          # Node 1, Node 2 und Haupt-Pi
./deploy.sh nodes        # nur die beiden Nodes
./deploy.sh node2        # nur Node 2
./deploy.sh monitor      # nur der Haupt-Pi
./deploy.sh pi@192.168.42.11   # beliebige Adresse
```

`deploy.sh` packt den Stand **deines** Arbeitsverzeichnisses (alles, was git
kennt, inklusive lokaler Änderungen), schickt ihn per SSH und ruft dort
`update.sh`. Die Geräte brauchen dafür **kein Internet und kein git** — genau
der Normalfall am Spielfeld.

* Kurznamen: `node1` → `pi@debug-node-1.local`, `node2` →
  `pi@debug-node-2.local`, `monitor` → `pi@power-debug-monitor.local`.
  Anderer Benutzer: `PDS_SSH_USER=robo ./deploy.sh nodes`.
* Lösen die `.local`-Namen nicht auf (manche Router/Windows-Rechner), die
  Adressen in eine Datei `deploy.conf` neben `deploy.sh` schreiben:
  ```bash
  NODE1=pi@192.168.42.11
  NODE2=pi@192.168.42.12
  MONITOR=pi@192.168.42.1
  ```
* Einmal `ssh-copy-id pi@debug-node-1.local` (usw.) — danach fragt SSH
  nicht mehr nach dem Passwort.
* `--no-restart`: nur installieren, Dienste laufen bis zum nächsten Neustart
  mit dem alten Stand weiter (z. B. mitten im Spiel).

### Auf dem Gerät selbst

```bash
cd ~/Robotic_PDS
sudo bash update.sh
```

Holt mit `git pull` den neuen Stand (wenn Internet da ist; sonst wird der
vorhandene installiert), installiert und startet neu. Optionen:

| Option | Wirkung |
|---|---|
| `--no-pull` | kein `git pull`, nur installieren, was im Ordner liegt |
| `--branch NAME` | vorher auf diesen Branch wechseln |
| `--no-restart` | nicht neu starten |
| `--status` | nur anzeigen, was installiert ist (Version, Dienste, Rückweg) |
| `--rollback` | vorherigen Stand zurückholen (siehe [9](#9-zurück-auf-den-vorherigen-stand)) |

Auf dem **Haupt-Pi** startet `update.sh` die laufende GUI in ihrer
Desktop-Sitzung neu — auch wenn man per SSH angemeldet ist. Läuft sie gerade
nicht, startet sie beim nächsten Login mit dem neuen Stand.

### Aus einem Release (ohne git)

Jedes Release auf GitHub (Tags `v*`) enthält `pds-<version>.tar.gz` und die
fertige `firmware.hex`:

```bash
mkdir pds && tar -xzf pds-v2.11.tar.gz -C pds
cd pds && sudo bash update.sh --no-pull
```

### Ältere Installationen

Geräte, die mit einem Setup **vor** `update.sh` eingerichtet wurden, erkennt
`update.sh` an ihren Diensten bzw. am Starter und legt `/etc/pds/pds.conf`
beim ersten Update selbst an. Es ist kein neues Setup nötig.

### Was bei einem Update passiert

1. Neuen Stand holen (`git pull`, außer `--no-pull`).
2. Bisherigen Stand nach `<Installationsordner>.prev` sichern.
3. Code kopieren, Dienste/Starter neu schreiben, `VERSION` vermerken.
   Auf dem Haupt-Pi läuft `pip` nur, wenn sich `requirements.txt` geändert hat.
4. Alle Python-Dateien übersetzen — ein Syntaxfehler bricht hier ab und der
   alte Stand bleibt aktiv.
5. Neu starten. Kommt auf einem Node der Dienst danach nicht hoch, geht es
   **automatisch** zurück auf den alten Stand.

Welche Version läuft, steht beim Start im Log:
`journalctl -u uart-receiver | grep Version` (Node) bzw. in der
Konsolenausgabe der GUI.

## 9. Zurück auf den vorherigen Stand

```bash
sudo bash update.sh --rollback
```

Holt den Stand vor dem letzten Update zurück und startet neu. Auf dem
Haupt-Pi gehört dazu auch `settings.json` in dem Zustand von vor dem Update.

## 10. Windows-PC statt Haupt-Pi

1. Python 3.11–3.13 installieren, dann im Repository:
   `pip install -r requirements.txt`
2. Mobilen Hotspot einrichten (Einstellungen → Netzwerk → Mobiler Hotspot)
   mit SSID `RoboDebug` und Passwort `robodebug123`.
3. `python.exe` in der Windows-Firewall für **private** Netze freigeben —
   sonst kommt keine Telemetrie an.
4. Starten: `rpi5_monitor/64Bit_Version/starter.bat`.

Updates: `git pull` im Repository genügt.

## 11. Was wo liegt

| Gerät | Pfad | Inhalt |
|---|---|---|
| beide | `/etc/pds/pds.conf` | was installiert ist (Rolle, Node-Nummer, Pfade) |
| Haupt-Pi | `/opt/power_debug_monitor/` | die Oberfläche |
| Haupt-Pi | `…/settings.json`, `…/settings.<Name>.json` | Einstellungen, Profile |
| Haupt-Pi | `…/runtime_config/nodeN/` | vom Teensy übernommene Konfiguration |
| Haupt-Pi | `/usr/local/bin/power-debug-monitor` | Starter |
| Haupt-Pi | `/etc/xdg/autostart/power-debug-monitor.desktop` | Autostart |
| Node | `/opt/power_debug_node/` | `uart_receiver.py`, `status_leds.py`, Bluetooth-Flash |
| Node | `/opt/power_debug_node/bt_flash_secret` | Auth-Token für das Flashen |
| Node | `/etc/systemd/system/uart-receiver.service`, `bt-flash-receiver.service` | Dienste |
| beide | `<Installationsordner>.prev` | Stand vor dem letzten Update |
| beide | `<Installationsordner>/VERSION` | installierte Version |

## 12. Fehlersuche

| Symptom | Ursache / Abhilfe |
|---|---|
| `deploy.sh`: „nicht erreichbar" | `.local` löst nicht auf → `deploy.conf` mit IP-Adressen; Gerät im selben Netz? `ssh pi@<adresse>` von Hand probieren. |
| `deploy.sh` fragt nach dem sudo-Passwort | Der Benutzer ist nicht der erste von Raspberry Pi OS. Einmal eingeben oder `sudo visudo` → `pi ALL=(ALL) NOPASSWD: ALL`. |
| `update.sh`: „noch nichts installiert" | Erst das Setup ausführen (Abschnitt 4/5). |
| Node-Update rollt automatisch zurück | `journalctl -u uart-receiver -n 50` zeigt den Grund. |
| GUI nach Update nicht wieder da | `power-debug-monitor` im Terminal des Desktops starten — Fehlermeldungen erscheinen dann direkt. |
| keine Telemetrie | `journalctl -u uart-receiver -f` auf dem Node. `0.0 Pkt/s` → Verkabelung/Baudrate. Pakete fließen, aber nichts in der GUI → Firewall oder falsches Netz. |
| Node-Log: `kaputte Pakete`, `UART-Fehler laut Kernel: oe=…` | Bytes gehen auf der UART verloren, bevor sie gelesen werden (`oe` = Überlauf, `fe` = Baudrate/Masse/Störung). Kabel kurz halten, Masse prüfen. |
| `Pkt/s` deutlich unter 100 ohne Fehler im Node-Log | Der Teensy schickt höchstens ein Paket pro `PDS.update()` — dauert `loop()` länger als 10 ms, ist die Paketrate die Loop-Rate. `PDS.printStatus()` zählt die gesendeten Pakete (`TX=`). |
| Zweite GUI-Instanz: „UDP-Port … belegt" | Es läuft schon eine (Autostart + Handstart). Eine beenden. |

Weitere Themen: [`README.md`](../README.md) (Überblick),
[`FEATURES.md`](../FEATURES.md) (was das System kann),
[`Doku/`](README.md) (Hintergründe).
