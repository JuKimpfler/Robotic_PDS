# Power Debug Monitor — die Oberfläche

Qt Quick/QML-Oberfläche auf PyQt6, für den Haupt-Pi (Raspberry Pi 4/5) oder
einen PC. Die frühere Widgets-GUI (`main.py` + `gui/`) ist entfernt.

Der Live-Plotter (Tab 2) zeichnet mit `pyqtgraph`, eingebettet in die
QML-Szene (`bridge/plot_host.py`). Ein Bild kostet 2–7 ms; der Bildtakt
(höchstens 25 fps) passt sich der gemessenen Bilddauer an, ein
Performance-Wächter schaltet den Plotter bei anhaltender Überlastung ab,
statt die GUI einzufrieren.

Installation und Updates: [`Doku/Setup_und_Update.md`](../../Doku/Setup_und_Update.md).

## Dateien

| Datei | Aufgabe |
|---|---|
| `main_qml.py` | Einstieg. `--simulate` erzeugt Testdaten für beide Nodes; `PDS_LOGLEVEL=DEBUG` für mehr Log. |
| `starter.bat` | Starter unter Windows. |
| `network_worker.py` | Empfängerprozesse (je Port einer) und ihre Überwachung. |
| `udp_socket.py` | Öffnet die Empfangsports — bewusst ohne `SO_REUSEADDR`: eine zweite Instanz meldet „Port belegt", statt der ersten die Daten wegzunehmen. |
| `aux_receiver.py` | Ereignisse, Parameter-Rückmeldung, Node-Status (Auswertung als Funktion, ohne Socket testbar). |
| `channel_registry.py` | Setzt den Deskriptor des Teensy zusammen (Namen, Einheiten, Konfiguration). |
| `runtime_config.py` | Speichert die Teensy-Konfiguration je Node unter `runtime_config/`, inklusive Fingerabdruck für die Konfliktregel. |
| `config.py` | Was zur Firmware passen muss: Ports, Magic-Zahlen, Paketgrößen (geprüft von `tools/check_wire_format.py`). |
| `app_settings.py` | Alles Einstellbare, Standardwerte, Prüfung, Profile — siehe unten. |
| `overlay_schema.py` | Felder der Overlay-Arten als Daten (daraus baut der Editor seine Formulare). |
| `param_io.py` | Liest/schreibt `param_config.json` und `param_defaults.h`. |
| `bridge/` | Eine Python-Brücke je Tab (`telemetry_`, `plot_`, `visuals_`, `param_`, `diag_bridge.py`), dazu `app_bridge.py` (verteilt die Daten), `controller_bridge.py` (PS4), `settings_bridge.py`, `plot_host.py` (pyqtgraph in QML), `perf_watchdog.py`. |
| `qml/` | Die Ansichten; `qml/components/` die wiederverwendbaren Bausteine. |
| `param_config.json`, `visuals_overlays.json` | **Vorlagen**. Hat ein Teensy seine Konfiguration gemeldet, gelten die Kopien unter `runtime_config/nodeN/`. |
| `settings.json`, `settings.<Name>.json` | *(zur Laufzeit angelegt, nicht im Repository)* Einstellungen und Profile. |
| `controller_config.json` | *(optional, nicht im Repository)* abweichende Controller-Belegung. |
| `runtime_config/` | *(zur Laufzeit angelegt)* vom Teensy übernommene Konfiguration je Node. |
| `VERSION` | *(nur in der Installation)* installierter Stand, steht beim Start im Log. |

## Starten

```bash
cd rpi5_monitor/64Bit_Version
pip install PyQt6 numpy pyqtgraph --break-system-packages   # falls noch nicht vorhanden

# Mit synthetischen Testdaten (kein Teensy nötig):
python3 main_qml.py --simulate

# Mit echter Hardware:
python3 main_qml.py
```

## Die Tabs

| Tab | Ansicht | Brücke | Inhalt |
|---|---|---|---|
| 1 Tabelle | `qml/TelemetryView.qml` | `bridge/telemetry_bridge.py` | alle Kanäle mit Name, Wert, Einheit, Min/Max/Δ, Filter |
| 2 Plotter | `qml/PlotterView.qml` | `bridge/plot_bridge.py` (Daten, Trigger, Marken), `bridge/plot_host.py` (pyqtgraph) | bis 8 Kurven, Trigger, Einfrieren mit Live-Kurve, Pinch-Zoom |
| 3 System | `qml/SystemView.qml` | `bridge/visuals_bridge.py`, `overlay_schema.py` | Roboterbild mit Overlays, Grafiken, Spielfeld mit Spur, **Editor** (siehe unten) |
| 4 Parameter | `qml/ParamsView.qml` | `bridge/param_bridge.py`, `bridge/controller_bridge.py` | Regler/Zahl/Text/Schalter/Taster/Joystick, Fast- und Slow-Kanal, PS4-Controller, Tastatur |
| 5 Diagnose | `qml/DiagnosticsView.qml` | `bridge/diag_bridge.py`, `bridge/settings_bridge.py` | Verbindungsqualität, Ping, Node-Status, Akku-Warnung, Logbuch, Einstellungen und Profile |

Kanalnamen, Einheiten und Konfiguration kommen vom Teensy
(`channel_registry.py`, `bridge/app_bridge.py`) — siehe
[`Doku/Kanalnamen_Implementierung.md`](../../Doku/Kanalnamen_Implementierung.md)
und [`Doku/Architektur.md`](../../Doku/Architektur.md).

## Der Editor der Systemansicht

„✎ Bearbeiten" in Tab 3 macht aus der Anzeige einen Editor. Bewusst **kein
eigener Dialog**: Beschriftungen auf einem Bild positioniert man nur sinnvoll,
wenn man dabei das Bild in Originalgröße und die echten Messwerte sieht.

* **Ziehen im Bild** verschiebt ein Textfeld. Bei einem **Textraster** zieht
  man damit den ganzen Block — gemeint ist immer dessen linke obere Ecke.
* **Formular rechts** für das ausgewählte Element. Es gibt kein Formular je
  Element-Art: `overlay_schema.py` beschreibt die Felder als Daten, und
  `FieldEditor.qml` rendert daraus mit einem Repeater das passende
  Bedienelement. Ein neues Feld ist eine Zeile Python und in QML gar nichts.
* **Kanalauswahl** mit Suche über Nummer *und* Name (`ChannelPicker.qml`) —
  bei 200 Kanälen ist eine ComboBox unbedienbar.
* **Warnhinweise** statt Sperren: ein Kanal, den es (noch) nicht gibt, ein
  Minimum ≥ Maximum oder eine leere Kanalliste werden gemeldet, verhindern
  aber weder Bearbeiten noch Speichern. Ein Editor, der beim Umbauen der
  Firmware das Speichern verweigert, wäre nur im Weg.
* **Rückgängig** über 50 Schritte, **Speichern** und **Verwerfen** getrennt.

### Was gespeichert wird — und warum das Format gleich bleibt

Bearbeitet wird das **Rohformat** von `visuals_overlays.json`, nicht die
aufbereitete Fassung, die die Ansicht zeigt. Das ist der ganze Trick beim
Textraster: angezeigt werden dreißig Textfelder, gespeichert bleibt **ein**
Eintrag. Würde der Editor zurückschreiben, was er anzeigt, wäre das Raster
nach dem ersten Speichern in dreißig Einzelpositionen zerfallen — sichtbar
identisch, aber beim nächsten Verschieben müsste man jede einzeln anfassen.
`tools/qml_smoketest.py` liest die gespeicherte Datei deshalb nach und prüft
genau das.

Gespeichert wird **je Node** unter `runtime_config/nodeN/` und damit
neustartfest.

### Wenn der Teensy etwas anderes meldet

Sobald hier von Hand bearbeitet wurde, wird die Anordnung **nicht mehr
stillschweigend** von einer neuen Firmware überschrieben. Stattdessen
erscheint ein Balken mit „Teensy übernehmen" / „Eigene behalten". Ohne diese
Rückfrage wäre eine halbe Stunde Positionierarbeit beim nächsten Flashen weg,
und zwar ohne jeden Hinweis. Die Regel selbst steht als reine Funktion in
`runtime_config.merge_decision()` und wird im Selbsttest durchgespielt.

## Einstellungen: `settings.json`

Alles Einstellbare steht in **einer** Datei neben `main_qml.py`:

```
rpi5_monitor/64Bit_Version/settings.json
```

Sie wird beim ersten Start mit den Standardwerten angelegt (`app_settings.py`,
dort ist `DEFAULTS` gleichzeitig die vollständige Liste aller Schlüssel) und
ist ausdrücklich zum Bearbeiten von Hand gedacht. Sie liegt **nicht** im
Repository — genau wie `runtime_config/`, damit ein `git pull` auf dem Pi
nicht an lokal geänderten Einstellungen scheitert.

Was dort steht, stand vorher an drei Stellen verteilt: in
`runtime_config/ui_settings.json`, fest verdrahtet in `qml/Theme.qml` und als
Zahlenliteral am jeweiligen Bedienelement (`from: 0.8; to: 1.6`).

| Abschnitt | Inhalt | Wirkt |
|---|---|---|
| `ui` | Farbschema, Schriftgröße, Kiosk, Tastatursteuerung, Start-Tab | sofort |
| `battery` | Akku-Warnung: Kanal, Schwellen, Haltezeit | sofort |
| `ranges` | **Grenzen aller Schieberegler und Drehfelder** (min/max/step) | sofort |
| `theme` | alle Farben (hell/dunkel), Abstände, Radien, Schriftgrößen | sofort |
| `window` | Fenstergröße, Vollbild, Kopfzeilenhöhe, Blinktakt | nach Neustart |
| `plotter` | Verlaufslänge, Kurvenzahl, Kurven-/Markenfarben | nach Neustart |
| `params` | Undo-Tiefe, Anzeigefaktor der Parameter-Drehfelder | nach Neustart |
| `network` | Node-Adressen, Poll-Takt, Zeitüberschreitung, Puffergrößen | nach Neustart |
| `diagnostics` | Länge des Logbuchs | nach Neustart |
| `controller` | Achsen-/Buttonbelegung und Totzone des PS4-Controllers | nach Neustart |

Nicht dabei sind Ports, Magic-Zahlen und Paketgrößen: die müssen zur Firmware
passen und stehen weiterhin in `config.py` (`tools/check_wire_format.py`
prüft sie dagegen).

**Ein Tippfehler kostet höchstens ein Feld.** Fehlt ein Schlüssel oder steht
Unsinn darin (`"dark": "ja"`, eine Farbe ohne `#`, ein Bereich mit
`max <= min`), gilt für genau dieses Feld der Standardwert, es gibt eine
Zeile im Log, und die Oberfläche startet normal. Unbekannte Schlüssel bleiben
erhalten. Werte außerhalb ihres eigenen Bereichs werden hineingelegt — sonst
zeigte ein Regler auf etwas, wohin er nie wieder zurückkäme.

### Mehrere Einstellungssätze

Jede Datei `settings.<Name>.json` im selben Ordner ist ein Profil:

```
settings.Spiel.json        # Kiosk an, große Schrift, dunkel
settings.Werkstatt.json    # Kiosk aus, helles Schema, Tastatur an
```

Im Tab **Diagnose → Einstellungssätze** lässt sich der aktuelle Stand unter
einem Namen ablegen, ein Profil laden oder löschen und alles auf die
Standardwerte zurücksetzen. Von Hand geht dasselbe mit einem Kopieren der
Datei — ein Einstellungssatz ist absichtlich eine Datei und kein verstecktes
Format.

Beim ersten Start nach dem Update wird eine vorhandene
`runtime_config/ui_settings.json` einmalig übernommen (Schriftgröße,
Kiosk-Modus, Akku-Warnung) und danach in `ui_settings.json.uebernommen`
umbenannt.

## Der Plotter: nativ oder als Bild — und warum das die Rechenlast bestimmt

pyqtgraph ist eine QWidget-Bibliothek, Qt Quick ist es nicht. Der Plotter
bettet das Widget deshalb auf einem von zwei Wegen ein, und der Unterschied
ist keine Kleinigkeit:

| Betriebsart | Wann | Was der Plotter tut |
|---|---|---|
| **nativ** | nur auf der QPA-Plattform `xcb` (X11 bzw. XWayland) | Das Widget hängt als echtes Kindfenster im QML-Fenster und zeichnet selbst. |
| **Bild** | überall sonst (Wayland, eglfs, offscreen) | pyqtgraph rastert in ein QPixmap, das per `QQuickPaintedItem` in die Szene geblittet wird — pro Bild einmal die ganze Fläche. |

Die Bildbetriebsart ist auf jeder Plattform gleich robust, aber sie kostet
die komplette Pixmap-Kette obendrauf. Wer auf einem Pi jede Millisekunde
braucht — Kiosk-Aufbau am Spielfeldrand —, fährt mit **`QT_QPA_PLATFORM=xcb`
am günstigsten**, weil dann der native Weg greift.

```bash
QT_QPA_PLATFORM=xcb python3 main_qml.py
```

Warum das trotzdem **nicht** die Vorgabe ist: der Launcher aus
`setup_rpi5.sh` wählt in einer Wayland-Sitzung bewusst `wayland;xcb`. `xcb`
läuft dort über XWayland, und Touch-Eingabe und DPI-Skalierung müssen darauf
erst abgenommen werden. Die Umstellung ist also eine bewusste Entscheidung
für einen konkreten Aufbau, kein Schalter, den man blind umlegt. In welcher
Betriebsart der Plotter gerade läuft, steht im Log
(`bridge.plot.host`) und in der Eigenschaft `mode` des Hosts.

Was in beiden Betriebsarten hilft, wenn es knapp wird, steht in
`settings.json` → `plotter`: `maxFps`/`minFps` (der Takt passt sich seit
Version 2.7 von selbst an), `maxCurves`, `defaultPoints`, `lineWidth`
(1 px ist der schnelle Weg), `gridAlpha`. Gemessen wird das mit
`python tools/plotter_bench.py`.

## Bewusste Abweichungen vom Original

- **Keine virtuelle Bildschirmtastatur** — auf Wunsch, da eine externe
  USB-Tastatur verwendet wird. `TextField`/`SpinBox` funktionieren damit
  unverändert.
- **Bilder werden per `file://`-URL geladen**, nicht über einen
  `QQuickImageProvider`. Funktional gleichwertig; ein Provider (Caching,
  Vorskalierung fürs Display) ist die im Plan vorgesehene spätere
  Ausbaustufe, aber nicht notwendig für die Funktionsfähigkeit.
- **`table`-Grafiktyp** in der Systemansicht ist bewusst simpel gehalten
  (zweispaltiges Text-Grid) statt einer vollen Tabellen-Widget-Nachbildung.

## Offene Punkte

1. **Test auf echter RPi5-Hardware**: `QT_QPA_PLATFORM=eglfs` prüfen,
   `QSG_RENDER_LOOP=basic` bei Flackern testen.
2. **Plotter auf schwacher Hardware** (RPi 4, 2 GB): seit 2.10 kostet ein
   Bild 2–7 ms statt 40–55 ms (deckendes Gitter, 1-px-Kurven). Reicht es
   trotzdem nicht, senkt der Plotter von selbst den Bildtakt
   (`plotter.adaptiveFps`, bis `plotter.minFps`); der Performance-Wächter
   bleibt das letzte Netz. Weitere Stellschrauben: `plotter.maxCurves`,
   `plotter.defaultPoints`, oder `QT_QPA_PLATFORM=xcb` (siehe oben — spart
   die Pixmap-Kette).
3. Tooling: Qt Design Studio zum visuellen Feintuning der Touch-Layouts
   nutzen.
