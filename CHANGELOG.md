# Änderungsverlauf

Alle nennenswerten Änderungen am Power Debug System.

## Versionierung — welche Nummer bedeutet was

Es gibt bewusst **zwei** Nummern, und nur die zweite darf einem Sorgen machen:

| Nummer | Wo sie steht | Bedeutung |
|---|---|---|
| `PDS_VERSION` | `teensy_firmware/src/PDS.h` | Version der Bibliothek/GUI. Erscheint in der Fußzeile und in `PDS.printStatus()`. Rein informativ. |
| `PDS_WIRE_VERSION` | `teensy_firmware/src/params.h`, gespiegelt in `uart_receiver.py` und `config.py` | Version des **Wire-Formats**. Ändert sich sie, müssen Teensy, Node und GUI **gemeinsam** aktualisiert werden. |

`tools/check_wire_format.py` vergleicht beide Seiten automatisch und schlägt
fehl, sobald eine der drei Stellen nicht nachgezogen wurde.

Die Version der eigenen **Roboter-Firmware** ist davon unabhängig und wird im
Sketch gesetzt (`PDS.setFirmwareVersion("1.4.2")` oder Build-Flag
`-DPDS_FW_VERSION='"1.4.2"'`). Sie kommt im Deskriptor mit und steht in der
Fußzeile der GUI — damit ist auf einen Blick sichtbar, welcher Stand auf
welchem Roboter läuft.

---

## 2.1 — Ereignisse, Diagnose und Konfiguration vom Teensy

**Wire-Format 1 → 2.** Teensy, Node und GUI müssen zusammen aktualisiert
werden. Der Node nimmt das alte 4-Byte-Discovery-Paket weiterhin an (dann
ohne Round-Trip-Messung), sonst gibt es keine Rückwärtskompatibilität.

### Teensy-Bibliothek

* **`PDS.bind("Name", &wert, 12)`** — feste Kanalnummer mit dem Namen zuerst,
  optional mit Einheit als viertem Argument.
* **`PDS.event("Ball verloren")`** setzt eine senkrechte Marke in den Plotter,
  **`PDS.log/logf/warn/error(...)`** schreiben ins Logbuch der GUI. Beides
  nicht blockierend, höchstens 20 Meldungen pro Sekunde.
* **Einheiten je Kanal**: `PDS.plot("Akku", v, "V")`, `PDS.setUnit(...)`.
  Erscheinen in Kanaltabelle und Plotter-Legende.
* **Watchdog**: `PDS.enableWatchdog(2000)`. `update()` füttert ihn selbst;
  bleibt `loop()` hängen, startet der Teensy neu und meldet das beim nächsten
  Start als Fehler ins Logbuch.
* **Parameter-Rückmeldung** (2 Hz): der Teensy schickt zurück, welche
  Parameter er wirklich hält. Die GUI zeigt Abweichungen an — der Downlink
  war bis hierher fire-and-forget.
* **Firmware-Version** im Deskriptor (`PDS.setFirmwareVersion`).
* `channel_config.h` beschreibt Parameter jetzt **vollständig** (`ParamDef`:
  Name, Bedienelement, Bereich, Schrittweite, Gruppe) statt nur über
  Namensarrays. Die Strukturen liegen in `params.h`, damit der
  `__has_include`-Fallback dieselben Definitionen benutzt.
* Deskriptor-Puffer 12 → 24 kB, ein Chunk je 20 ms statt 10 ms.

**Behoben:** `bind()`/`track()` liefen auf den Festbreiten-Aliasen
`int8_t`/`int16_t`/`int32_t`. Auf dem Teensy ist `int32_t` aber `long` — ein
ganz gewöhnliches `int heading; PDS.track("Heading", &heading);` hat deshalb
gar nicht übersetzt, sondern eine seitenlange Kandidatenliste erzeugt. Die
Überladungen laufen jetzt auf den fundamentalen Typen; ein
`static_assert`-Auffangnetz gibt für alles andere eine lesbare Meldung.

**Behoben:** Deskriptor, Ereignisse und Rückmeldung schreiben nur noch, wenn
im TX-Puffer zusätzlich ein komplettes Telemetriepaket Platz hat. Vorher
konnte eine Deskriptor-Übertragung einzelne Telemetriepakete verdrängen.

### Fernsteuerung

**Behoben — „die Joystick-Abfrage stockt":** Der 100-Hz-Takt der
Fernsteuerung lief im Qt-GUI-Thread. Ein `QTimer` feuert aber erst, wenn die
Ereignisschleife wieder drankommt — also nach dem Neuzeichnen von Plotter,
Tabelle und Oberfläche. Der Abtastzeitpunkt des Controllers ist dadurch
unregelmäßig gewandert. Die komplette Regelstrecke (Controller lesen,
Tastatur, Paket packen, senden, Discovery) läuft jetzt in einem **eigenen
Thread** mit fester Periode; der Wertespeicher ist mit einem Lock
abgesichert, das nie über ein `sendto()` gehalten wird. pygame/SDL wird in
demselben Thread auf- und abgebaut.

Zusätzlich: `pygame.joystick.get_count()` nur noch 2× statt 100× pro Sekunde,
und das doppelte Pumpen der SDL-Ereigniswarteschlange entfällt.

* **Tastatursteuerung**: WASD fahren, Q/E drehen, Shift schneller, R/F
  Dribbler, Leertaste Not-Aus. Ein Controller hat weiterhin Vorrang.
* **Not-Aus-Knopf** in der Kopfzeile.

### Plotter

* **Bis zu acht Kurven gleichzeitig** mit Legende, Min/Max/Aktuell je Kurve
  und wahlweise gemeinsamer oder eigener Skala je Kurve.
* **Oszilloskop-Trigger** mit sechs Bedingungen (über/unter Schwelle,
  steigende/fallende Flanke, Sprung größer als, Band verlassen), einstellbarem
  Nachlauf und „neu scharf machen".
* **Ereignismarken** vom Teensy als senkrechte Linien im Verlauf.
* Komplett auf **NumPy** umgestellt: ein vorab angelegter 2D-Ringpuffer
  (Kurven × Samples, `float32`), blockweises Schreiben, vektorisierte
  Trigger-Auswertung und Koordinatenumrechnung. Kein `deque`, keine
  Python-Schleife über Einzelwerte mehr — der Plotter teilt sich den Thread
  mit dem Renderer, jede Schleife dort kostet Bildrate.

### Diagnose (neuer Tab)

* **Verbindungsqualität**: Pakete/s, geschätzter Paketverlust (aus den
  Zeitstempeln des Teensy, ohne ein Byte Wire-Format zu kosten) und echte
  Round-Trip-Zeit GUI → Node → GUI.
* **Node-Systemstatus**: CPU-Temperatur, Last, Speicher, WLAN-Pegel, Uptime
  und UART-Zähler des Raspberry Pi Zero.
* **Akku-Warnung**: frei wählbarer Kanal, zwei Schwellen und eine Haltezeit
  gegen Fehlalarme beim Anfahren. Rein optisch — es wird nichts am Roboter
  verändert.
* **Logbuch** mit Filter nach Meldungsstufe.
* **Einstellungen**: helles/dunkles Farbschema, Schriftgröße, Kiosk-Modus,
  Tastatursteuerung, Übernahme der Teensy-Konfiguration.

### Konfiguration vom Teensy, reboot-fest

Der Teensy ist die Quelle der Wahrheit für Kanalnamen, Einheiten, den Aufbau
des Parameter-Tabs und die Overlays der Systemansicht. Was im Deskriptor
ankommt, wird **je Node** unter `rpi5_monitor/64Bit_Version/runtime_config/`
dauerhaft abgelegt — nach einem Neustart steht sofort wieder alles da, auch
ohne eingeschalteten Roboter.

Konflikt zwischen Teensy-Konfiguration und lokaler Bearbeitung: ein
Fingerabdruck entscheidet. Neue Firmware setzt sich durch, sonst bleiben
lokale Änderungen stehen. Die Dateien im Repository bleiben unberührte
Vorlagen.

### Systemansicht

* **Neuer Overlay-Typ `textgrid`**: ein einziger Eintrag legt beliebig viele
  Werte als Raster auf ein Bild (`channels=0-11,20;cols=2;dx=24;dy=5`).
  Vorher brauchte jeder Messwert ein eigenes Overlay mit eigener Position.
* **Feldansicht auf Zentimeter und die tatsächliche Ausrichtung umgestellt**:
  x = 0…180 cm nach Osten, y = 0…240 cm nach Norden; dargestellt um 90° nach
  Osten gedreht (Norden rechts, Osten unten), passend zum Querformat-Display.
  Ein Kompasskurs entspricht in dieser Darstellung direkt der
  Bildschirmdrehung. Achsen sind beschriftet.

### Parameter-Tab

* **Suchfeld** über alle Gruppen hinweg.
* **Abweichungen** vom gespeicherten Default auf einen Blick, mit
  „alle zurücksetzen".
* **Rückgängig** (auch Strg+Z); Änderungen am selben Regler innerhalb von
  1,5 s werden zu einem Schritt zusammengefasst.
* **Soll/Ist-Vergleich** gegen die Rückmeldung des Teensy.

### Node

* **Aux-Uplink** (Port 5021/5022): Ereignisse, Parameter-Rückmeldung und
  Node-Status teilen sich einen Port; die GUI trennt sie am Magic.
* Generischer `MagicFrameAssembler` für alle Uplink-Formate mit variabler
  und fester Länge, inklusive Plausibilitätsprüfung gegen Zufallstreffer im
  Telemetriestrom.
* Discovery trägt jetzt Nummer und Sendezeitpunkt und wird zurückgespiegelt.

### Prüfwerkzeuge

* **`tools/desc_json_check.py`** übersetzt `PDS.cpp` mit einer
  Arduino-Attrappe für den PC, **führt sie aus** und prüft den erzeugten
  Deskriptor mit einem echten JSON-Parser — inklusive Anführungszeichen,
  Backslash, Umlauten und Steuerzeichen in Namen. Ein Übersetzungslauf
  allein findet solche Fehler nicht.
* **`tools/qml_smoketest.py`** startet die komplette Oberfläche offscreen,
  füttert synthetische Daten hinein und wertet jede Qt-Warnung als Fehler.
* `tools/selftest.py` von 48 auf 98 Prüfungen erweitert.
* **GitHub Actions**: alle Prüfungen plus PlatformIO-Build bei jedem Push.

---

## 2.0 — Teensy-Bibliothek ohne Kanalnummern

* `PDS` als fertige globale Instanz; `plot()`/`track()` vergeben Kanäle
  automatisch und melden die Namen an die GUI (O(1) über einen Pointer-Cache).
* `channel_config.h` ist optional (`__has_include`), die Bibliothek lässt sich
  unverändert in fremde Projekte kopieren (`library.json`).
* Kanalnamen finden sich nach einem Neustart auf **beiden** Seiten von allein
  wieder ein: Meldung beim Boot, bei jedem Verbindungsaufbau und in Ruhe mit
  wachsendem Abstand; die GUI erkennt am `micros()`-Sprung einen Neustart.
* Discovery-Paket an **beide** Nodes — der inaktive Node hat vorher dauerhaft
  80 kB/s gebroadcastet und damit die Fernsteuerung des aktiven ausgebremst.
* Behoben: `pinMode(10, INPUT)` in `init()` griff auf einen fremden Pin des
  Roboterprojekts zu.
* Behoben: Dummy-Filterung im Empfänger verschob alle folgenden Kanäle.
* Behoben: unbehandelte Ausnahme in einem Qt-Slot beendete die GUI
  (`qFatal()`) — jetzt `safe_slot`.
* Behoben: Teensy ging **vor** der Übertragung in den Bootloader; ein
  abgebrochener Flash-Vorgang hinterließ einen Roboter ohne Firmware.
* Behoben: Status-LEDs des Nodes waren vollständig auskommentiert.
* `tools/selftest.py`, `tools/check_wire_format.py`,
  `tools/check_qml_bindings.py` und `tools/build_teensy_check.sh` eingeführt.
