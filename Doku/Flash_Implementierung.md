# Implementierungsplan: Wireless Bluetooth Upload/Flash für Teensy 4.0 über RPi Zero 2 W

**Projekt:** Robotic PDS (Power Debug System)
**Feature:** Windows-PC → Bluetooth → RPi Zero 2 W → USB → Teensy 4.0 (`teensy_loader_cli`)
**Stand der Analyse:** basierend auf `Robotic_PDS-julius` (README.md, `setup_node.sh`, `spi_receiver.py`, `status_leds.py`, `teensy_firmware/platformio.ini`)

---

## 0. Zusammenfassung

Ziel ist es, ein `.hex`-File (kompiliertes Teensy-4.0-Firmware-Image) von einem beliebigen Windows-PC per Bluetooth an einen oder beide RPi Zero 2 W Nodes zu senden. Der jeweilige Node empfängt die Datei, prüft sie, und flasht sie über den bereits vorhandenen USB-Anschluss mit `teensy_loader_cli` auf den angeschlossenen Teensy 4.0.

Kernentscheidungen vorab:

| Thema | Entscheidung | Begründung |
|---|---|---|
| Bluetooth-Technologie | **Classic Bluetooth RFCOMM (SPP)**, kein BLE | Stream-basiert, keine MTU-Fragmentierung nötig, deutlich höherer Durchsatz für Dateien von einigen 100 KB |
| Bibliothek PC-Seite | **Python-Standardbibliothek `socket`** (`AF_BLUETOOTH`, `BTPROTO_RFCOMM`) — seit Python 3.9 nativ unter Windows verfügbar | Keine Fremdabhängigkeit, kein PyBluez nötig (PyBluez ist unter Windows unzuverlässig/unwartet) |
| Bibliothek Pi-Seite | **Python-Standardbibliothek `socket`** für die Datenübertragung, plus **BlueZ-Tools (`bluetoothctl`, `sdptool` via D-Bus/BlueZ-Profile)** ausschließlich zur einmaligen Kopplung/SDP-Registrierung | Auf Linux ist `AF_BLUETOOTH` nativ im Kernel/BlueZ vorhanden; für den SPP-Dienstsatz muss BlueZ trotzdem einen SDP-Record kennen |
| Bluetooth vs. UART-Konflikt | `dtoverlay=disable-bt` → **`dtoverlay=miniuart-bt`** ändern | Aktuell deaktiviert `setup_node.sh` Bluetooth komplett, um PL011 für den Teensy freizugeben. Das widerspricht der Anforderung. Mit `miniuart-bt` bekommt Bluetooth die (langsamere) Mini-UART, GPIO14/15 (PL011) bleiben exklusiv für den Teensy nutzbar |
| Zielauswahl (Node 1 / Node 2 / beide) | Anwendung auf PC verwaltet zwei Bluetooth-Adressen, verbindet **sequenziell** | Ein PC-Bluetooth-Radio kann zwar mehrere ACL-Links halten, sequenzielles Flashen ist aber robuster und einfacher zu debuggen als paralleles |
| Sicherheit | Bluetooth-Pairing (fester PIN) + Anwendungs-Handshake mit Shared Secret | Reicht für Werkstatt-/Wettbewerbsumgebung, verhindert versehentliches Flashen durch fremde Geräte |

---

## 1. Ausgangslage (Ist-Zustand)

- `setup_node.sh` installiert bereits `teensy-loader-cli` per `apt` (Zeile ~129) — das Tool ist also auf dem Node schon vorhanden, wird aber aktuell nirgends aufgerufen.
- Das UART-Overlay (`dtoverlay=disable-bt`, `enable_uart=1`, `dtoverlay=uart0`) reserviert die PL011-UART für die Teensy-Telemetrie und **deaktiviert dabei den onboard Bluetooth-Chip vollständig** (`systemctl disable hciuart.service bluetooth.service`). Das muss für dieses Feature rückgängig gemacht bzw. umgebaut werden.
- Die Firmware (`platformio.ini`) wird mit `-DUSB_SERIAL` gebaut → der Teensy hängt am USB als CDC-Serial-Gerät. Das ist Voraussetzung dafür, dass `teensy_loader_cli` das Board **automatisch** (ohne Tastendruck) in den HalfKay-Bootloader zwingen kann.
- `spi_receiver.py` läuft als systemd-Dienst `uart-receiver` und liest die UART-Telemetrie in einer Single-Thread-Event-Loop. Ein Flash-Vorgang unterbricht diesen Datenstrom kurz (Teensy-Reset) — das ist unkritisch, sofern der Empfänger Verbindungsabbrüche toleriert (in Phase 1 zu verifizieren, siehe Abschnitt 9).
- `status_leds.py` hat aktuell die GPIO-Ansteuerung auskommentiert (kein Hardware-Zugriff aktiv) — LED-Feedback für den Flash-Vorgang ist optional und ohne Risiko nachrüstbar.
---

## 2. Architekturübersicht

```
┌──────────────────────────────┐
│  Windows PC                  │
│  pc_flash_tool/               │
│   bt_flash_sender.py         │  ← CLI/kleine Tkinter-GUI
│   (stdlib socket AF_BLUETOOTH│
│    BTPROTO_RFCOMM)           │
└───────────────┬───────────────┘
                │  Bluetooth Classic (RFCOMM/SPP)
                │  getrennter Kanal je Node
      ┌─────────┴─────────┐
      ▼                   ▼
┌───────────────┐   ┌───────────────┐
│ RPi Zero 2 W  │   │ RPi Zero 2 W  │
│ Node 1        │   │ Node 2        │
│ bt_flash_     │   │ bt_flash_     │
│ receiver.py   │   │ receiver.py   │
│ (systemd)     │   │ (systemd)     │
└──────┬────────┘   └──────┬────────┘
       │ USB                 │ USB
       ▼                     ▼
  Teensy 4.0             Teensy 4.0
  (teensy_loader_cli --mcu=TEENSY40 -w -v -s firmware.hex)
```

Die bestehende UDP-Telemetrie/Parameter-Architektur (siehe README) bleibt komplett unverändert; das neue Feature ist ein zusätzlicher, unabhängiger Kanal (Bluetooth statt WLAN/UDP) nur für den Flash-Vorgang.

---

## 3. Technische Kernentscheidungen im Detail

### 3.1 Der UART/Bluetooth-Konflikt auf dem Pi Zero 2 W

Der Pi Zero 2 W hat **eine** vollwertige PL011-UART und eine schwächere Mini-UART. Standardmäßig hängt der onboard-BT-Chip an der PL011, GPIO14/15 an der Mini-UART. `setup_node.sh` dreht das aktuell um (`dtoverlay=disable-bt`) und schaltet BT dabei komplett ab, damit der Teensy die schnelle PL011 (bis 4 Mbps) über GPIO14/15 bekommt.

**Lösung:** Overlay auf `dtoverlay=miniuart-bt` ändern. Damit:
- bleibt GPIO14/15 weiterhin an der PL011 (volle Baudrate für den Teensy, keine Änderung an `spi_receiver.py` nötig),
- bekommt der Bluetooth-Chip die Mini-UART zugewiesen (getaktet über `core_freq`, ausreichend für HCI/RFCOMM-Kommunikation — Datei-Uploads sind kein Echtzeit-Feature, ein paar zehn KB/s reichen locker),
- `hciuart.service`/`bluetooth.service` bleiben **aktiviert** statt deaktiviert.

Dies ist die einzige Konfigurationsänderung, die für die Koexistenz von Teensy-UART und Bluetooth nötig ist.

### 3.2 Bluetooth-Transport: Classic RFCOMM statt BLE

BLE (`bleak`/`bless`) wäre die "modernere" Wahl, hat aber für diesen Use-Case Nachteile:
- GATT-Attribute sind auf ~20–512 Byte MTU begrenzt → Dateien müssen in viele kleine Chunks mit eigenem Protokoll zerlegt werden.
- Effektiver Durchsatz i. d. R. niedriger als Classic BT SPP.
- Erfordert zusätzliche Bibliotheken auf beiden Seiten (`bleak` PC, `bless`/`bluezero` Pi).

RFCOMM emuliert eine serielle Verbindung (wie ein virtueller COM-Port) und lässt sich 1:1 wie ein TCP-Socket verwenden — Dateiübertragung ist trivial (Bytes schreiben/lesen), und Python unterstützt das **ohne Zusatzpaket**:

```python
import socket
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
```

Das funktioniert laut CPython-Dokumentation (bpo-36590) sowohl unter Windows (ab Python 3.9) als auch nativ unter Linux/BlueZ.

**Wichtige Einschränkung, die im Projekt validiert werden muss (Phase 1):** Windows verlangt für ausgehende RFCOMM-Verbindungen i. d. R., dass das Zielgerät bereits über die Windows-Bluetooth-Einstellungen gekoppelt ("paired") ist — eine spontane, ungekoppelte Verbindung nur per Code ist nicht vorgesehen. Die Kopplung selbst (PIN-Eingabe) erfolgt daher einmalig manuell oder über ein kleines Kopplungs-Skript, siehe 3.3.

### 3.3 Pairing / Kopplung

- **Pi-Seite (einmalig, im Setup-Skript automatisiert):**
  - `bluetoothctl power on`
  - `bluetoothctl discoverable on` / `pairable on`
  - Agent mit festem PIN (z. B. `NoInputNoOutput` + Auto-Accept, oder `DisplayYesNo` falls Bestätigung gewünscht) via `bluetoothctl agent` bzw. eigenem Python-Agent-Skript (`bt-agent` aus `bluez-tools`, falls verfügbar, sonst minimaler D-Bus-Agent).
  - Gerätename z. B. `PDS-Node1-BT` / `PDS-Node2-BT` (leicht unterscheidbar für den Anwender).
- **PC-Seite (einmalig pro PC, manuell):**
  - In Windows-Einstellungen → Bluetooth & Geräte → Gerät hinzufügen → `PDS-Node1-BT` / `PDS-Node2-BT` auswählen, PIN bestätigen.
  - Danach ist die Bluetooth-Adresse des Node dauerhaft im Windows-Gerätespeicher hinterlegt; das Python-Tool kann jederzeit per bekannter MAC-Adresse verbinden.
- Die MAC-Adressen der beiden Nodes werden in einer kleinen Konfigurationsdatei `pc_setup/bt_targets.json` hinterlegt (vom Anwender einmalig einzutragen, wird beim Setup des Nodes ausgegeben).

### 3.4 Warum keine automatische Geräte-Discovery zur Laufzeit?

Wäre technisch möglich (SDP-Suche), erhöht aber Komplexität und Fehleranfälligkeit (Windows-Discovery ist langsam, ~10s+). Da es nur zwei feste, bekannte Nodes gibt, ist eine feste MAC-Adressliste einfacher und zuverlässiger. Discovery kann optional als Komfort-Feature in einer späteren Phase ergänzt werden.

---

## 4. Anwendungsprotokoll (über den RFCOMM-Stream)

Einfaches, robustes Byte-Protokoll mit Länge + Prüfsumme, ähnlich dem bereits im Projekt verwendeten Magic-Number-Muster (`0xDEADBEEF`, `0xCAFEFEED`, `0xFA57DA7A`):

**Frame-Format (Little-Endian):**

| Feld | Bytes | Beschreibung |
|---|---|---|
| `MAGIC` | 4 | `0xB17F1A5H` (fixe Kennung, gegen Fehlsynchronisation) |
| `CMD` | 1 | Kommando-Byte (siehe Tabelle unten) |
| `LEN` | 4 | Länge des Payloads |
| `PAYLOAD` | `LEN` | Nutzdaten |
| `CRC32` | 4 | CRC32 über `PAYLOAD` |

**Kommandos:**

| CMD | Name | Richtung | Payload |
|---|---|---|---|
| `0x01` | `HELLO` | PC → Pi | Auth-Token (String) |
| `0x02` | `HELLO_ACK` | Pi → PC | Node-ID, Firmware-Info, „bereit" |
| `0x03` | `FLASH_START` | PC → Pi | Dateiname, Gesamtgröße, SHA-256-Hash der Datei |
| `0x04` | `FLASH_START_ACK` | Pi → PC | OK oder Fehler (z. B. Teensy nicht per USB gefunden) |
| `0x05` | `DATA_CHUNK` | PC → Pi | Binärer Ausschnitt der `.hex`-Datei (z. B. 4–16 KB je Chunk) |
| `0x06` | `DATA_CHUNK_ACK` | Pi → PC | Empfangsbestätigung (Flusskontrolle) |
| `0x07` | `FLASH_END` | PC → Pi | — (signalisiert: Übertragung vollständig) |
| `0x08` | `FLASH_RESULT` | Pi → PC | Erfolg/Fehler + `teensy_loader_cli`-Ausgabe (gekürzt) |
| `0x09` | `PING`/`PONG` | beidseitig | Keepalive |

Auth-Token: ein statischer, in `bt_targets.json` (PC) bzw. `/opt/power_debug_node/bt_flash_secret` (Pi) hinterlegter String — verhindert, dass ein zufällig gekoppeltes fremdes Gerät den Flash-Befehl auslösen kann. Der SHA-256-Hash aus `FLASH_START` wird nach vollständigem Empfang erneut lokal berechnet und verglichen, bevor geflasht wird (Integritätsschutz gegen Übertragungsfehler).

---

## 5. Komponenten im Detail

### 5.1 PC-Seite: `pc_setup/pc_flash_tool/bt_flash_sender.py`

Aufgaben:
1. `bt_targets.json` laden (`{"node1": {"mac": "AA:BB:CC:DD:EE:FF", "channel": 4}, "node2": {...}}`).
2. `.hex`-Datei auswählen (CLI-Argument oder einfacher Tkinter-Dateidialog).
3. Zielauswahl: `--target node1|node2|both`.
4. Für jedes Ziel sequenziell:
   - RFCOMM-Socket öffnen, `HELLO` senden, `HELLO_ACK` erwarten (Timeout z. B. 5 s).
   - `FLASH_START` mit Dateigröße + Hash senden, `FLASH_START_ACK` abwarten.
   - Datei in Chunks senden, nach jedem Chunk `DATA_CHUNK_ACK` abwarten (einfache Stop-and-Wait-Flusskontrolle — für Dateien dieser Größenordnung ausreichend performant).
   - `FLASH_END` senden, auf `FLASH_RESULT` warten (Timeout großzügig, z. B. 30 s, da `teensy_loader_cli` selbst etwas Zeit braucht).
   - Ergebnis anzeigen (Konsole/GUI), Socket schließen.
5. Fortschrittsanzeige (Prozent je Ziel), klare Fehlermeldungen (Timeout, Verbindungsabbruch, CRC-Fehler, Teensy nicht gefunden, Flash-Fehler).
6. Exit-Code für Automatisierung (0 = alle Ziele erfolgreich, ≠0 sonst).

Empfehlung: zunächst als CLI-Skript umsetzen (`python bt_flash_sender.py firmware.hex --target both`), optional später eine minimale Tkinter-GUI (Dateiauswahl-Button, Zielauswahl-Checkboxen, Fortschrittsbalken je Node, Log-Fenster) — passt zum bestehenden Stil von `rpi5_monitor` (PyQt6 wäre auch möglich, Tkinter ist aber ohne Zusatzabhängigkeit sofort einsatzbereit).

### 5.2 Pi-Seite: `rpi_zero_node/bt_flash_receiver.py`

Aufgaben:
1. RFCOMM-Server-Socket öffnen (`socket.bind((socket.BDADDR_ANY, CHANNEL))`, `listen()`), Kanalnummer fix (z. B. Kanal 4) oder per `bluetooth.PORT_ANY` + SDP-Advertise ermittelt.
2. Beim Verbindungsaufbau: Protokoll-Handshake gemäß Abschnitt 4, Auth-Token prüfen.
3. Datei-Empfang: Chunks in temporäre Datei schreiben (`/opt/power_debug_node/flash_incoming/<timestamp>.hex`), nach Abschluss SHA-256 verifizieren.
4. Prüfen, ob ein Teensy per USB angeschlossen ist (`teensy_loader_cli --list-mcus` liefert keine Geräteliste direkt — stattdessen z. B. `lsusb | grep -i "16c0:0483"` (Teensy HalfKay-VID/PID) oder `teensy_loader_cli` selbst starten und Rückgabewert/stderr auswerten). Falls kein Gerät gefunden: Fehler sofort zurückmelden statt endlos zu warten.
5. Flash-Befehl ausführen:
   ```
   teensy_loader_cli --mcu=TEENSY40 -w -v -s /opt/power_debug_node/flash_incoming/<file>.hex
   ```
   - `-w`: warten, bis Board bereit ist
   - `-v`: verbose (Ausgabe für Ergebnis-Feedback nutzen)
   - `-s`: „soft reboot" — automatischer Neustart in den Bootloader über die USB-Serial-Schnittstelle (funktioniert, weil Firmware mit `-DUSB_SERIAL` gebaut wird, siehe Abschnitt 1) — **kein physischer Tastendruck am Teensy nötig**.
6. `subprocess.run(...)` mit Timeout (z. B. 20 s), Exit-Code + stdout/stderr auswerten, `FLASH_RESULT` an PC zurücksenden.
7. Bei Erfolg: temporäre `.hex`-Datei löschen oder archivieren (letzte 5 Versionen behalten, Rest aufräumen).
8. Vollständiges Logging über `journalctl` (wie bei `uart-receiver`).
9. Läuft als eigener systemd-Dienst `bt-flash-receiver.service`, unabhängig von `uart-receiver.service` (kein gemeinsamer Prozess, kein GIL-Konflikt mit der performancekritischen Telemetrie-Loop).

### 5.3 Koexistenz mit `uart-receiver.service`

- Kein direkter Ressourcenkonflikt: `uart-receiver` nutzt `/dev/ttyAMA0` (PL011/UART), `bt-flash-receiver` nutzt Bluetooth + USB — komplett getrennte Schnittstellen.
- Während des Flashens resettet sich der Teensy kurz; `uart-receiver` verliert kurzzeitig das Telemetrie-Signal. Zu prüfen (Phase 1 Test): verhält sich `spi_receiver.py`s Event-Loop dabei robust (kein Crash, automatische Resynchronisation sobald der Teensy nach dem Flash wieder sendet)? Nach aktueller Kenntnis der Datei ist das wahrscheinlich unkritisch (reine Leseseite, kein Zustand, der durch eine Pause zerstört wird), sollte aber im Test verifiziert werden.
- Optional (spätere Ausbaustufe): `bt_flash_receiver.py` sendet ein Event an `status_leds.py` (z. B. über eine kleine Unix-Domain-Socket-IPC oder eine gemeinsame Datei/State), um während des Flash-Vorgangs ein eigenes LED-Muster zu zeigen (z. B. Blau+Gelb abwechselnd). Da die GPIO-Ansteuerung aktuell auskommentiert ist, hat das keine Priorität für die erste Version.

### 5.4 SDP-Registrierung des SPP-Dienstes (Pi)

Damit sich ein Windows-PC überhaupt mit dem RFCOMM-Kanal verbinden kann, muss BlueZ den Dienst über SDP bekannt machen. Zwei mögliche Wege, in Phase 1 zu evaluieren:

1. **Einfachster Weg:** `sdptool add --channel=4 SP` (klassisches SDP-Tool, Teil der `bluez`-Pakete) direkt beim Dienststart per `ExecStartPre` im systemd-Unit ausführen.
2. **BlueZ-5-„sauberer" Weg** (falls `sdptool` auf aktuellem Bookworm-BlueZ nicht mehr zuverlässig funktioniert): Registrierung über die D-Bus-Schnittstelle `org.bluez.ProfileManager1.RegisterProfile` mit der SPP-UUID (`00001101-0000-1000-8000-00805F9B34FB`) — benötigt `python3-dbus`. Diese Variante ist etwas aufwendiger, aber zukunftssicherer.

**Empfehlung:** Mit Ansatz 1 starten (geringerer Aufwand), in einem kurzen Funktionstest (Phase 1, siehe unten) verifizieren, ob Windows den Dienst zuverlässig findet/verbindet. Bei Problemen auf Ansatz 2 wechseln.

---

## 6. Änderungen an `setup_node.sh`

Konkrete Anpassungen (in der bestehenden Struktur des Skripts):

1. **Schritt 1 (Pakete):** zusätzlich installieren:
   - `bluez` (Bluetooth-Daemon + `bluetoothctl`, i. d. R. schon vorinstalliert, aber explizit sicherstellen)
   - `bluez-tools` (für `bt-agent`, falls für automatisiertes Pairing genutzt)
   - `python3-dbus` (nur falls Ansatz 2 aus 5.4 verwendet wird)
   - `teensy-loader-cli` ist bereits vorhanden (keine Änderung nötig)
2. **Schritt 2 (UART):** `dtoverlay=disable-bt` → `dtoverlay=miniuart-bt` ändern; Zeile `systemctl disable hciuart.service bluetooth.service` entfernen bzw. durch `systemctl enable bluetooth.service` ersetzen.
3. **Neuer Schritt „Bluetooth SPP-Dienst einrichten":**
   - Gerätename setzen: `hostnamectl` bzw. `bluetoothctl system-alias "PDS-Node${NODE_ID}-BT"`.
   - `bluetoothctl power on`, `pairable on`, `discoverable on`.
   - Agenten-Konfiguration für festen PIN (Doku: PIN im Setup-Output ausgeben, damit Anwender ihn beim Pairing eingeben kann).
   - Auth-Token generieren/ablegen unter `/opt/power_debug_node/bt_flash_secret` (falls nicht vorhanden, zufällig erzeugen und am Ende des Setups anzeigen, damit der Anwender ihn in `bt_targets.json` auf dem PC einträgt).
4. **Schritt 4 (Projektdateien installieren):** `bt_flash_receiver.py` zusätzlich nach `$INSTALL_DIR/rpi_zero_node/` kopieren (analog zu `spi_receiver.py`/`status_leds.py`).
5. **Neuer Schritt „Systemdienst: bt-flash-receiver":** analog zum bestehenden `uart-receiver.service`-Block ein zweites Unit-File erzeugen, inkl. `ExecStartPre` für die SDP-Registrierung (siehe 5.4) und `Environment="NODE_ID=..."`.
6. **Schritt „Dienst aktivieren":** `systemctl enable bt-flash-receiver.service` ergänzen.
7. **Verifizierungs-/Abschluss-Ausgabe:** Bluetooth-Status (`bluetoothctl show`), MAC-Adresse des Node (`hciconfig hci0` bzw. `bluetoothctl show | grep Controller`) und den generierten Auth-Token/PIN am Ende ausgeben, damit der Anwender diese Werte direkt für die PC-Konfiguration übernehmen kann.

---

## 7. Neue/geänderte Dateien — Übersicht

| Datei | Status | Zweck |
|---|---|---|
| `rpi_zero_node/bt_flash_receiver.py` | **neu** | RFCOMM-Server, Datei-Empfang, Aufruf `teensy_loader_cli` |
| `rpi_zero_node/setup_node.sh` | **ändern** | Overlay-Umstellung, BT-Setup, neuer systemd-Dienst |
| `pc_setup/pc_flash_tool/bt_flash_sender.py` | **neu** | RFCOMM-Client, Datei-Versand, CLI |
| `pc_setup/pc_flash_tool/bt_targets.json` | **neu** | MAC-Adressen, Kanäle, Auth-Token je Node (Vorlage) |
| `pc_setup/README.md` | **ergänzen** | Abschnitt „Wireless Flashing" mit Bedienungsanleitung |
| `README.md` (Hauptprojekt) | **ergänzen** | Architekturdiagramm um Bluetooth-Flash-Pfad erweitern; Hinweis „Firmware-Flashing wurde entfernt" korrigieren/aktualisieren |
| `rpi_zero_node/status_leds.py` | **optional, später** | Flash-Status-LED-Muster |

---

## 8. Sicherheitsüberlegungen

- **Physische/Pairing-Ebene:** Nur gekoppelte Geräte können überhaupt eine RFCOMM-Verbindung aufbauen (Bluetooth-PIN).
- **Anwendungsebene:** zusätzlicher Auth-Token im `HELLO`-Frame verhindert, dass ein anderes, ebenfalls gekoppeltes Gerät (z. B. Handy) versehentlich einen Flash-Befehl auslösen kann.
- **Integrität:** SHA-256-Prüfung der vollständig empfangenen Datei vor dem Flashen; CRC32 je Frame zur frühen Fehlererkennung.
- **Kein Verschlüsselungsbedarf** über die Bluetooth-Standardverschlüsselung hinaus, da Einsatzumfeld (Werkstatt/Wettbewerb) als vertrauenswürdig gilt — sollte sich das ändern, könnte optional TLS-über-RFCOMM oder ein HMAC über die Frames ergänzt werden.
- **Kein Fallback auf offene/ungesicherte Verbindungen**: schlägt das Pairing fehl, verweigert der Node jede Verbindung (BlueZ-Standardverhalten).

---

## 9. Testplan (Phasen, aufsteigende Integration)

1. **Bluetooth-Grundfunktion:** Overlay-Wechsel (`miniuart-bt`) auf einem Node testen: läuft `uart-receiver` weiterhin stabil bei voller Baudrate? Ist Bluetooth gleichzeitig aktiv (`bluetoothctl show`)?
2. **Pairing:** Windows-PC mit Node koppeln, PIN-Flow verifizieren.
3. **Roh-RFCOMM-Test:** einfaches Echo-Skript (PC sendet Text, Pi spiegelt zurück) — verifiziert, dass Windows' `AF_BLUETOOTH`/`BTPROTO_RFCOMM` tatsächlich mit dem per `sdptool`/D-Bus registrierten Kanal verbindet (kritischster Risikofaktor des Plans, siehe 5.4).
4. **Dateitransfer:** Testdatei (nicht `.hex`) in mehreren Chunk-Größen übertragen, CRC/SHA-256 verifizieren, Abbruch-/Wiederholungsverhalten testen (z. B. Bluetooth-Reichweite verlassen).
5. **`teensy_loader_cli`-Integration isoliert:** manuell per SSH auf dem Node ein bekanntes `.hex` mit `teensy_loader_cli --mcu=TEENSY40 -w -v -s` flashen, um Soft-Reboot-Verhalten und Kommandozeile zu verifizieren, bevor die Automatisierung angebunden wird.
6. **End-to-End Einzelziel:** komplette Kette PC → Bluetooth → Pi → USB → Teensy mit echter PDS-Firmware.
7. **End-to-End Dual-Target:** `--target both`, sequenzieller Durchlauf für Node 1 und Node 2.
8. **Fehlerfälle:** Node nicht erreichbar/nicht gekoppelt, kein Teensy per USB angeschlossen, korrupte/falsche `.hex`-Datei, Verbindungsabbruch mitten in der Übertragung, falscher Auth-Token.
9. **Regressionstest:** bestätigen, dass normale Telemetrie/Parameter-Funktionalität (UDP, GUI) durch die Änderungen unberührt bleibt.

---

## 10. Phasenplan (Umsetzungsreihenfolge)

| Phase | Inhalt |
|---|---|
| **1. Spike/Machbarkeit** | Overlay-Wechsel + Bluetooth-Aktivierung auf einem Test-Node; Roh-RFCOMM-Verbindung Windows↔Pi verifizieren (Punkt 5.4 validieren) |
| **2. Protokoll & Kernlogik** | `bt_flash_receiver.py` und `bt_flash_sender.py` gemäß Abschnitt 4/5 implementieren, gegen Testdateien prüfen |
| **3. Teensy-Loader-Integration** | Subprocess-Aufruf, Geräteerkennung, Ergebnis-Feedback |
| **4. Setup-Skript-Integration** | `setup_node.sh` erweitern (Abschnitt 6), Doku aktualisieren |
| **5. Multi-Target & Komfort** | `--target both`, Fortschrittsanzeige, ggf. einfache GUI |
| **6. Härtung** | Fehlerfälle, Timeouts, Logging, LED-Feedback (optional) |
| **7. Vollständiger Funktionstest** | Testplan aus Abschnitt 9 komplett durchlaufen |

---

## 11. Offene Punkte, die vor der Umsetzung zu klären sind

1. Soll die Bluetooth-Verbindung dauerhaft aktiv/discoverable bleiben oder nur bei Bedarf (z. B. per Taster/Skript) aktiviert werden? (Wirkt sich auf Stromverbrauch und Sicherheitsprofil aus.)
2. Reicht ein CLI-Tool auf dem PC, oder wird von Anfang an eine grafische Oberfläche gewünscht (Tkinter reicht aus, PyQt6 wäre Konsistenz zu `rpi5_monitor`, aber mehr Aufwand)?
3. Sollen beide Nodes wirklich **sequenziell** geflasht werden, oder ist paralleles Flashen (zwei gleichzeitige RFCOMM-Verbindungen, zwei Threads im PC-Tool) gewünscht, trotz höherer Komplexität?
4. Soll das Flash-Ergebnis zusätzlich im bestehenden `rpi5_monitor`-GUI sichtbar gemacht werden (z. B. als neuer Tab), oder bleibt es ein eigenständiges Tool?
5. Feste Kanalnummer (z. B. 4) vs. dynamische Zuweisung per SDP-Suche auf PC-Seite — Empfehlung: feste Nummer für Einfachheit, siehe Abschnitt 3.4.

---

*Dieser Plan wurde auf Basis der hochgeladenen Projektdateien (`Robotic_PDS-julius`) erstellt und verweist auf konkrete, bestehende Skripte (`setup_node.sh`, `spi_receiver.py`, `status_leds.py`, `platformio.ini`). Er beschreibt die Architektur, Protokolle und Umsetzungsschritte; die eigentliche Implementierung (Code) ist der nächste Schritt und kann auf Wunsch direkt begonnen werden.*