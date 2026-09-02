# Power Debug Monitor — QML-Migration (Umsetzungsstand)

Diese Umsetzung folgt `QML_Migrationsplan_RPi5_Monitor.md` und ist
abgeschlossen: die Oberfläche besteht nur noch aus QML. Die frühere
PyQt6-**Widgets**-GUI (`main.py` + `gui/`, rund 3700 Zeilen) ist entfernt —
sie kannte weder PS4-Controller noch automatische Kanalnamen noch die
Überwachung der Empfängerprozesse.

**Der Live-Plotter (Tab 2) nutzt seit dem Umbau wieder `pyqtgraph`**, diesmal
allerdings eingebettet in die QML-Szene (siehe `bridge/plot_host.py`):
pyqtgraph zeichnet die Kurven als C++-Polylinien direkt aus NumPy-Arrays —
deutlich günstiger als das alte `QPainter`-Verfahren, das den Raspberry Pi 4
(2 GB) bei mehreren Kurven überlastet hat. Bei anhaltender Überlastung
schaltet ein Performance-Watchdog den Plotter ab und zeigt einen Hinweis,
statt die GUI einzufrieren (siehe unten, „Performance-Watchdog").

**Getestet:** headless (`QT_QPA_PLATFORM=offscreen`) mit `--simulate`,
mehrere Minuten Dauerlauf ohne QML-/Python-Fehler, 30 Hz Poll-Takt,
alle Bindings (Tabelle, Plot, Gauges/Rotation/Vektor/Tabelle, Parameter)
laufen sauber durch.

## Starten

```bash
cd rpi5_monitor/64Bit_Version
pip install PyQt6 numpy pyqtgraph --break-system-packages   # falls noch nicht vorhanden

# Mit synthetischen Testdaten (kein Teensy nötig):
python3 main_qml.py --simulate

# Mit echter Hardware:
python3 main_qml.py
```

## Was wurde umgesetzt

| Bereich | Datei(en) | Stand |
|---|---|---|
| Bootstrap / Engine | `main_qml.py` | ✅ vollständig, inkl. Simulator-Modus |
| Theme/Design-Tokens | `qml/Theme.qml` | ✅ vollständig |
| Hauptshell (SwipeView+TabBar+NodeSelector+StatusBar) | `qml/Main.qml`, `qml/components/{NodeSelector,StatusBar}.qml` | ✅ vollständig |
| Tab 1 — Live-Tabelle | `qml/TelemetryView.qml`, `bridge/telemetry_bridge.py` | ✅ vollständig, inkl. Filterfeld (neu ggü. Original) |
| Tab 2 — Live-Plotter | `qml/PlotterView.qml`, `bridge/plot_bridge.py` (Daten/Trigger/Marken), `bridge/plot_host.py` (PyQtGraphHost, pyqtgraph) | ✅ funktional; Pinch-to-Zoom für Punktezahl; pyqtgraph statt QPainter; **Performance-Watchdog** schaltet bei Überlastung ab |
| Tab 3 — Systemansicht | `qml/SystemView.qml`, `bridge/visuals_bridge.py`, `overlay_schema.py`, `qml/components/{Gauge,RotationIndicator,VectorIndicator,MiniTable,OverlayEditor,FieldEditor,ChannelPicker}.qml` | ✅ vollständig, inkl. **Editor** (Ziehen im Bild, Formular je Element, Gruppen, Rückgängig, dauerhaft je Node gespeichert) — siehe unten |
| Tab 4 — Parameter | `qml/ParamsView.qml`, `bridge/param_bridge.py`, `qml/components/{Joystick,TouchSlider}.qml` | ✅ vollständig (Slider/Zahl/Text/Toggle/Button/Joystick, Fast+Slow-Downlink, Save-Default) |
| Tab 5 — Diagnose | `qml/DiagnosticsView.qml`, `bridge/diag_bridge.py` | ✅ vollständig — Verbindungsqualität, Round-Trip-Zeit, Node-Systemstatus, Akku-Warnung, Logbuch, Einstellungen (siehe Architektur-Übersicht in der Haupt-`README.md`, Abschnitt 3b) |
| PS4-Controller | `bridge/controller_bridge.py` | ✅ vollständig — übernimmt den Fast-Channel automatisch, sobald ein DualShock 4 verbunden ist; siehe `Doku/PS4_Controller_Implementierung.md` |
| Einstellungen (alles: Theme, Schriftgröße, Reglergrenzen, Fenster, Akku, Controller) | `app_settings.py`, `settings.json`, `bridge/settings_bridge.py` | ✅ vollständig — eine Datei neben `main_qml.py`, mehrere Einstellungssätze speicher-/ladbar (siehe unten) |
| Kanal-/Param-Namen + Overlay-Defaults vom Teensy | `channel_registry.py` (Modulwurzel), `bridge/app_bridge.py::_poll_descriptor`/`requestChannelNames` | ✅ vollständig — siehe `Doku/Kanalnamen_Implementierung.md`; Namens-Refresh baut `params.groups` neu auf, gibt dabei aber die aktuellen Live-Werte statt der JSON-Defaults mit, damit kein Regler zurückspringt |

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
Version 2.7 von selbst an), `maxCurves`, `defaultPoints`. Gemessen wird das
mit `python tools/plotter_bench.py`.

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
   `QSG_RENDER_LOOP=basic` bei Flackern testen (Migrationsplan Abschnitt 7).
2. **Plotter-Performance auf schwacher Hardware** (RPi 4, 2 GB): der
   pyqtgraph-basierte Plotter ist deutlich günstiger als das alte
   `QPainter`-Verfahren, wird aber bei anhaltender Überlastung durch den
   **Performance-Watchdog** automatisch abgeschaltet (Hinweis + „Erneut
   versuchen"). Seit Version 2.7 senkt der Plotter vorher von selbst den
   Bildtakt (`plotter.adaptiveFps`, bis herunter auf `plotter.minFps`) —
   der Watchdog ist damit wieder das letzte Netz statt der ersten Reaktion.
   Empfehlung, wenn es trotzdem nicht reicht: Kurvenzahl reduzieren
   (`settings.json` → `plotter.maxCurves`), `plotter.defaultPoints`
   verkleinern, oder den Aufbau auf `QT_QPA_PLATFORM=xcb` umstellen (siehe
   oben — das spart die ganze Pixmap-Kette).
3. Tooling: Qt Design Studio zum visuellen Feintuning der Touch-Layouts
   nutzen (Migrationsplan Abschnitt 10).

## Projektstruktur (neu)

```
rpi5_monitor/64Bit_Version/
├── main_qml.py               # QML-Einstiegspunkt (--simulate, PDS_LOGLEVEL)
├── app_settings.py            # settings.json: laden, prüfen, speichern, Profile
├── settings.json              # git-ignored: ALLE Einstellungen (wird beim 1. Start angelegt)
├── settings.<Name>.json       # git-ignored: gespeicherte Einstellungssätze (Profile)
├── starter.bat                # Windows-Starter für main_qml.py
├── overlay_schema.py          # Felder der Anzeige-Elemente als Daten (ohne PyQt)
├── runtime_config.py          # vom Teensy uebernommene Konfiguration, je Node
├── channel_registry.py        # Deskriptor-Empfang/-Parsing vom Teensy
├── aux_receiver.py            # Ereignisse, Parameter-Rückmeldung, Node-Status
├── param_defaults.h           # von der GUI generiert: Parameter-Defaults als C-Header zum Rückkopieren in channel_config.h
├── runtime_config/            # git-ignored: gespeicherte Node-Konfiguration + UI-Settings
├── bridge/                    # Python↔QML-Brücke (kein QtWidgets-Import)
│   ├── app_bridge.py          # Fassade, Poll-Loop, Node-Umschaltung
│   ├── telemetry_bridge.py    # Tab 1
│   ├── plot_bridge.py         # Tab 2: Daten/Trigger/Marken + Watchdog-Logik
│   ├── plot_host.py           # Tab 2: PyQtGraphHost (pyqtgraph in QML einbetten)
│   ├── perf_watchdog.py       # Tab 2: Überlast-Erkennung (Event-Loop-Stall)
│   ├── visuals_bridge.py      # Tab 3 samt Editor
│   ├── param_bridge.py        # Tab 4 (ParamStore, Fast-Channel-Thread)
│   ├── diag_bridge.py         # Tab 5: Link-Qualität, Node-Status, Akku-Alarm, Logbuch
│   ├── controller_bridge.py   # PS4-Controller (übernimmt Fast-Channel automatisch)
│   ├── settings_bridge.py     # Fenster nach QML auf settings.json (inkl. Profile)
│   └── utils.py                # parse_channels, expand_textgrid
└── qml/
    ├── Theme.qml               # als App-1.0-Singleton registriert (main_qml.py)
    ├── Main.qml
    ├── UiState.qml
    ├── TelemetryView.qml
    ├── PlotterView.qml
    ├── SystemView.qml
    ├── ParamsView.qml
    ├── DiagnosticsView.qml      # Tab 5
    └── components/
        ├── NodeSelector.qml
        ├── StatusBar.qml
        ├── AppButton.qml
        ├── AppSwitch.qml
        ├── Joystick.qml
        ├── TouchSlider.qml
        ├── Gauge.qml
        ├── RotationIndicator.qml
        ├── VectorIndicator.qml
        ├── BodiesField.qml         # Feldansicht (Spielfeld, Zentimeter)
        ├── MiniTable.qml
        ├── OverlayEditor.qml       # Bedienfeld des Editors
        ├── FieldEditor.qml         # ein Feld, datengetrieben aus overlay_schema
        └── ChannelPicker.qml       # Kanalauswahl mit Suche
```

Unverändert wiederverwendet: `network_worker.py`, `param_io.py`,
`param_config.json`, `visuals_overlays.json`, `bild/`. `config.py` hält
weiterhin alles, was zur Firmware passen muss; die einstellbaren Werte holt es
aus `settings.json`.
