# Power Debug Monitor — QML-Migration (Umsetzungsstand)

Diese Umsetzung folgt `QML_Migrationsplan_RPi5_Monitor.md` und ist
abgeschlossen: die Oberfläche besteht nur noch aus QML. Die frühere
PyQt6-**Widgets**-GUI (`main.py` + `gui/`, rund 3700 Zeilen) ist entfernt —
sie wurde von keinem Setup-Skript mehr installiert, brauchte mit `pyqtgraph`
eine zusätzliche Abhängigkeit und kannte weder PS4-Controller noch
automatische Kanalnamen noch die Überwachung der Empfängerprozesse.

**Getestet:** headless (`QT_QPA_PLATFORM=offscreen`) mit `--simulate`,
mehrere Minuten Dauerlauf ohne QML-/Python-Fehler, 30 Hz Poll-Takt,
alle Bindings (Tabelle, Plot, Gauges/Rotation/Vektor/Tabelle, Parameter)
laufen sauber durch.

## Starten

```bash
cd rpi5_monitor
pip install PyQt6 numpy --break-system-packages   # falls noch nicht vorhanden

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
| Tab 2 — Live-Plotter | `qml/PlotterView.qml`, `bridge/plot_bridge.py` (PlotCanvas, Option C aus dem Plan) | ✅ funktional; Pinch-to-Zoom für Punktezahl |
| Tab 3 — Systemansicht | `qml/SystemView.qml`, `bridge/visuals_bridge.py`, `overlay_schema.py`, `qml/components/{Gauge,RotationIndicator,VectorIndicator,MiniTable,OverlayEditor,FieldEditor,ChannelPicker}.qml` | ✅ vollständig, inkl. **Editor** (Ziehen im Bild, Formular je Element, Gruppen, Rückgängig, dauerhaft je Node gespeichert) — siehe unten |
| Tab 4 — Parameter | `qml/ParamsView.qml`, `bridge/param_bridge.py`, `qml/components/{Joystick,TouchSlider}.qml` | ✅ vollständig (Slider/Zahl/Text/Toggle/Button/Joystick, Fast+Slow-Downlink, Save-Default) |
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
2. **PlotCanvas-Performance** bei sehr hoher Punktzahl (>500) auf
   schwacher RPi5-GPU messen; ggf. Umstieg auf Option D (QSGGeometryNode)
   falls Option C (aktuell umgesetzt) nicht ausreicht.
3. Tooling: Qt Design Studio zum visuellen Feintuning der Touch-Layouts
   nutzen (Migrationsplan Abschnitt 10).

## Projektstruktur (neu)

```
rpi5_monitor/
├── main_qml.py               # neuer QML-Einstiegspunkt
├── overlay_schema.py         # Felder der Anzeige-Elemente als Daten (ohne PyQt)
├── runtime_config.py         # vom Teensy uebernommene Konfiguration, je Node
├── bridge/                   # Python↔QML-Brücke (kein QtWidgets-Import)
│   ├── app_bridge.py         # Fassade, Poll-Loop, Node-Umschaltung
│   ├── telemetry_bridge.py   # Tab 1
│   ├── plot_bridge.py        # Tab 2 (inkl. PlotCanvas QQuickPaintedItem)
│   ├── param_bridge.py       # Tab 4 (ParamStore unverändert übernommen)
│   ├── visuals_bridge.py     # Tab 3 samt Editor
│   └── utils.py              # parse_channels, expand_textgrid
└── qml/
    ├── Theme.qml              # als App-1.0-Singleton registriert (main_qml.py)
    ├── Main.qml
    ├── TelemetryView.qml
    ├── PlotterView.qml
    ├── SystemView.qml
    ├── ParamsView.qml
    └── components/
        ├── NodeSelector.qml
        ├── StatusBar.qml
        ├── Joystick.qml
        ├── TouchSlider.qml
        ├── Gauge.qml
        ├── RotationIndicator.qml
        ├── VectorIndicator.qml
        ├── MiniTable.qml
        ├── OverlayEditor.qml      # Bedienfeld des Editors
        ├── FieldEditor.qml        # ein Feld, datengetrieben aus overlay_schema
        └── ChannelPicker.qml      # Kanalauswahl mit Suche
```

Unverändert wiederverwendet: `config.py`, `network_worker.py`, `param_io.py`,
`param_config.json`, `visuals_overlays.json`, `bild/`.
