# Power Debug System — Funktionsübersicht

Alles, was das System kann, nach Bereichen. Wie man es einrichtet und
aktualisiert: [`Doku/Setup_und_Update.md`](Doku/Setup_und_Update.md). Was
sich wann geändert hat: [`CHANGELOG.md`](CHANGELOG.md).

---

## Teensy-Bibliothek (`teensy_firmware/src/PDS.*`)

**Werte anzeigen**
* `PDS.plot("Name", wert)` — Kanal wird beim ersten Aufruf automatisch
  vergeben, der Name geht an die GUI. Namen dürfen auch aus einem Puffer
  kommen (`snprintf`).
* `PDS.track("Name", &variable)` — einmal in `setup()`, danach wird der Wert
  mit 100 Hz von selbst abgeholt.
* `PDS.bind("Name", &variable, kanal)` — wie `track()`, auf fester
  Kanalnummer (für Overlays, die genau dorthin zeigen).
* `PDS.Channel(kanal, wert)` — klassisch, ohne Namen.
* `PDS_PLOT(name, wert)` — Variante ohne jeden Overhead für sehr heiße
  Schleifen.
* Alle Ganzzahltypen, `float`, `double`, `bool`.
* **Einheiten** je Kanal (`PDS.plot("Akku", v, "V")`), erscheinen in Tabelle
  und Legende.
* Bis zu **200 Kanäle** mit 100 Hz über UART (1 Mbit/s).

**Ereignisse und Logbuch**
* `PDS.event("Ball verloren")` — senkrechte Marke im Plotter.
* `PDS.log/warn/error("…", …)` — mit `printf`-Formatierung ins Logbuch der GUI.
* Rate-begrenzt, nicht blockierend, verdrängt nie die Telemetrie.

**Von der GUI lesen**
* `PDS.fastParam(i)` / `PDS.fastParam("Name")` — Joystick/Controller, 100 Hz.
* `PDS.param(i)`, `PDS.paramBool(i)`, `PDS.param("Kp")` — Einstellwerte, 2 Hz.
* `PDS.linkOk()` — Not-Aus-Kriterium: ist die GUI noch da?
* **Parameter-Rückmeldung**: der Teensy meldet 2×/s zurück, was er wirklich
  hält.

**Robustheit**
* **`update()` blockiert nie** — Zeitbudget je Aufruf, Empfangsbudget,
  Deskriptor scheibchenweise, Notbremse bei Fehlfunktion
  ([`Doku/Blockierfreiheit.md`](Doku/Blockierfreiheit.md)).
* **Watchdog**: `PDS.enableWatchdog(2000)`; ein Watchdog-Reset wird beim
  nächsten Start im Logbuch gemeldet.
* Abgebrochene Downlink-Pakete setzen den Parser zurück — kein Zufallswert im
  Joystick-Kanal.
* Diagnosezähler (`printStatus()`, `txDropCount()`, `maxUpdateMicros()`, …)
  und optional sechs Diagnosekanäle (`enableSelfDiagnostics()`).

**Konfiguration aus der Firmware**
* `channel_config.h` (optional): Parameter mit Name, Bedienelement, Bereich,
  Schrittweite und Gruppe; Joysticks; Overlays der Systemansicht.
* `PDS.setting("ui.dark", true)` bzw. `GUI_SETTINGS` — die Firmware kann
  jede Einstellung der Oberfläche vorgeben
  ([`Doku/Teensy_Einstellungen.md`](Doku/Teensy_Einstellungen.md)).
* `PDS.setFirmwareVersion("1.4.2")` — Version erscheint in der GUI.
* Kanalnamen finden sich nach jedem Neustart (Teensy, Node oder GUI) von
  selbst wieder ein.
* Zur Laufzeit einstellbar: Telemetrierate, Timeouts, Ereignisrate, …
* Drop-in-Bibliothek (`library.json`), Build-Flags für Kanalzahl, Puffer und
  Budgets.

## Node (Raspberry Pi Zero 2 W)

* Leitet Telemetrie, Namen, Ereignisse und Parameter-Rückmeldung vom Teensy
  ins WLAN, Parameter und Fernsteuerung zurück — alles in **einem** Thread
  über eine Event-Loop.
* **Unicast statt Broadcast**: lernt die Adresse der GUI aus deren Paketen
  (Rückfall auf Broadcast, solange keine bekannt ist).
* **Nur der neueste Joystick-Stand** geht über die UART; überholte Pakete
  werden verworfen.
* **Kaputte Pakete erkennen**: fehlen Bytes auf der UART, wird das Paket
  verworfen statt mit Müllwerten weitergeschickt.
* **Node-Status** (1 Hz): CPU-Temperatur, Last, Speicher, WLAN-Pegel,
  Uptime, UART-Zähler.
* **Round-Trip-Messung**: Discovery-Pakete werden zurückgespiegelt.
* Log mit Paketraten, Sync-Verlusten, kaputten Paketen und den
  UART-Fehlerzählern des Kernels.
* UART wird nach einem Fehler von selbst neu geöffnet.
* **Status-LEDs**: läuft / WLAN / Daten.
* **Firmware per Bluetooth flashen** vom Windows-PC aus, ohne Knopfdruck am
  Teensy (Software-Bootloader), mit Auth-Token und SHA-256-Prüfung
  ([`Doku/Flash_Implementierung.md`](Doku/Flash_Implementierung.md),
  [`pc_flash_tool/`](pc_flash_tool/README.md)); auch direkt aus PlatformIO
  („Upload BT: Node 1/2/Both").

## Oberfläche (Haupt-Pi oder Windows-PC)

**Allgemein**
* Qt Quick/QML, für Touchscreens ausgelegt; helles und dunkles Farbschema
  (Strg+D), Schriftgröße einstellbar, Kiosk-Modus.
* Umschalten zwischen **zwei Robotern** (Node 1/2) mit Verbindungsanzeige.
* Fußzeile mit Pakete/s, Firmware-Version des Roboters und Meldungen.
* **Simulator** (`--simulate`): Testdaten für beide Nodes inklusive
  Ereignissen und Node-Status — alles ohne Hardware testbar.
* Strg+S fährt den Pi herunter, Esc beendet (beides im Kiosk-Modus gesperrt).

**Tab 1 — Tabelle**
* Alle Kanäle mit Name, Wert, Einheit, Min/Max/Δ, Filter nach Name/Nummer.

**Tab 2 — Plotter**
* Bis zu **8 Kurven**, Legende mit Min/Max/Aktuell, eigene oder gemeinsame
  Skala.
* **25 Bilder/s**, Bildtakt passt sich der Hardware an (bis 4 fps hinunter
  statt einzufrieren); Performance-Wächter als letztes Netz.
* **Oszilloskop-Trigger**: über/unter Schwelle, steigende/fallende Flanke,
  Sprung, Band verlassen; Nachlauf einstellbar; einfrieren oder nur Marke.
* **Einfrieren** mit weiterlaufender, gestrichelter Live-Kurve; nichts geht
  dabei verloren.
* **Ereignismarken** vom Teensy und vom Trigger.
* Zoom per Pinch-Geste, Kanalauswahl mit Suche.
* Spitzen bleiben beim Verkleinern sichtbar (Peak-Downsampling).

**Tab 3 — Systemansicht**
* Bild des Roboters mit **Text-Overlays** an beliebigen Stellen, als
  Einzelwert oder ganzes **Textraster**; Farbe fest oder abhängig vom Wert
  (Schwelle oder Verlauf).
* Grafiken: **Zeiger** (Gauge), **Drehanzeige**, **Vektor**, **Tabelle**.
* **Spielfeld**: Draufsicht 240 × 180 cm (einstellbar) mit Toren,
  Mittelkreis oder Foto; zwei Körper (z. B. Ball und Roboter) mit Position,
  Richtung und Durchmesser aus Kanälen; **Bewegungsspur** der letzten
  Sekunden; ungültige Werte werden ausgeblendet, Werte außerhalb des Feldes
  am Rand markiert.
* **Editor** direkt in der Ansicht: Elemente anlegen, im Bild ziehen,
  Formular je Element, Gruppen mit eigenem Bild, Rückgängig über 50 Schritte.
* Mehrere **Gruppen** (Ansichten), umschaltbar.

**Tab 4 — Parameter**
* Bedienelemente aus der Konfiguration: Schieberegler, Zahlenfeld, Text,
  Schalter, Taster, **Joystick** (2 Achsen).
* **Fast-Kanal** 100 Hz (Fahren) und **Slow-Kanal** 2 Hz (Einstellwerte).
* **PS4-Controller** per USB übernimmt den Fast-Kanal automatisch, Belegung
  konfigurierbar ([`Doku/PS4_Controller_Implementierung.md`](Doku/PS4_Controller_Implementierung.md)).
* **Tastatur**: WASD fahren, Q/E drehen, Shift schneller, R/F Dribbler,
  Leertaste Not-Aus.
* Suche über alle Gruppen, **Rückgängig** (Strg+Z), **Abweichungen** vom
  gespeicherten Default mit „alle zurücksetzen", **Soll/Ist-Vergleich** gegen
  die Rückmeldung des Teensy.
* „Als Default speichern" schreibt `param_defaults.h` für die Firmware.
* Fernsteuerung läuft in einem eigenen Thread mit fester Periode — der
  Renderer bremst sie nicht.

**Tab 5 — Diagnose**
* **Verbindungsqualität** je Node: Pakete/s, Verlust (aus den Zeitstempeln,
  passt sich der Telemetrierate an), Round-Trip-Zeit.
* **Node-Status**: Temperatur, Last, Speicher, WLAN-Pegel, Uptime.
* **Akku-Warnung**: Kanal, zwei Schwellen, Haltezeit; rein optisch.
* **Logbuch** mit Filter nach Stufe.
* **Einstellungen** und **Einstellungssätze** (Profile) speichern, laden,
  löschen.
* Übernahme der Teensy-Konfiguration und des Aussehens getrennt abschaltbar;
  gespeicherte Konfiguration verwerfen.

**Konfiguration**
* **Eine Datei** `settings.json` für alles Einstellbare: Farben, Abstände,
  Schriftgrößen, Grenzen aller Regler, Plotter, Netzwerk, Controller. Ein
  Tippfehler kostet höchstens ein Feld.
* Vom Teensy gemeldete Konfiguration wird **je Node dauerhaft** gespeichert;
  neue Firmware setzt sich durch, sonst bleiben lokale Änderungen.
* Neue Standardwerte erreichen auch eingerichtete Geräte (Versionsumstellung
  der Datei), ohne Handänderungen zu überschreiben.

**Robustheit**
* Empfänger in eigenen Prozessen, werden nach einem Absturz neu gestartet.
* Eine zweite, versehentlich gestartete Instanz meldet „Port belegt", statt
  der ersten die Daten wegzunehmen.
* Keine Ausnahme in einem Qt-Slot kann die Oberfläche beenden.

## Einrichten, Aktualisieren, Ausliefern

* **Setup** je Gerät in einem Befehl (`setup_rpi5.sh`, `setup_node.sh`),
  Raspberry Pi OS Bookworm und Trixie; WLAN über Router oder Haupt-Pi als
  Access Point.
* **`deploy.sh`**: alle Geräte vom PC aus aktualisieren — per SSH, ohne
  Internet und git auf den Geräten; frische Geräte komplett einrichten.
* **`update.sh`**: Update auf dem Gerät selbst; erkennt die Rolle, sichert
  den alten Stand, prüft den neuen, startet Dienste bzw. GUI neu, rollt bei
  Fehlern automatisch zurück; `--rollback`, `--status`.
* **Releases**: ein Tag `v*` erzeugt ein GitHub-Release mit `firmware.hex`
  und installierbarem Paket.

## Prüfungen (ohne Hardware)

* **`tools/check_all.sh`** — alles in einem Befehl, lokal wie in der CI:
  * Selbsttest (250+ Prüfungen): Paket-Zusammenbau, Deskriptor, Parameter,
    Bluetooth-Protokoll, Einstellungen, Plotter, Diagnose, …
  * Wire-Format Teensy ↔ Node ↔ GUI, QML-Zugriffe gegen die Python-Brücken
  * Teensy-Bibliothek **auf dem PC ausgeführt**, Deskriptor mit echtem
    JSON-Parser geprüft; Firmware-Build in mehreren Konfigurationen
  * komplette Oberfläche offscreen (jede Qt-Warnung ist ein Fehler)
  * Zeitbudget für ein Plotter-Bild
  * Setup/Update/Deploy in einer Sandbox
  * pyflakes, ShellCheck
* **CI** auf GitHub bei jedem Push, Python 3.11 und 3.13 (Bookworm/Trixie).
* **`tools/plotter_bench.py`** misst Datenpfad, Rastern und Legende.
