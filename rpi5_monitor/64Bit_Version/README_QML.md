# Power Debug Monitor — QML-Migration (Umsetzungsstand)

Diese Umsetzung folgt `QML_Migrationsplan_RPi5_Monitor.md` und deckt die
**Phasen 0–5** ab: ein vollständig lauffähiges QML-Frontend parallel zur
alten Widgets-GUI, mit allen vier Tabs funktional nachgebaut.

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

Die alte Widgets-GUI (`python3 main.py`) bleibt unverändert nutzbar —
beide Versionen laufen komplett unabhängig nebeneinander (Migrationsplan
Phase 6 sieht das Entfernen von `gui/` erst nach vollständiger Validierung
auf echter Hardware vor).

## Was wurde umgesetzt

| Bereich | Datei(en) | Stand |
|---|---|---|
| Bootstrap / Engine | `main_qml.py` | ✅ vollständig, inkl. Simulator-Modus |
| Theme/Design-Tokens | `qml/Theme.qml` | ✅ vollständig |
| Hauptshell (SwipeView+TabBar+NodeSelector+StatusBar) | `qml/Main.qml`, `qml/components/{NodeSelector,StatusBar}.qml` | ✅ vollständig |
| Tab 1 — Live-Tabelle | `qml/TelemetryView.qml`, `bridge/telemetry_bridge.py` | ✅ vollständig, inkl. Filterfeld (neu ggü. Original) |
| Tab 2 — Live-Plotter | `qml/PlotterView.qml`, `bridge/plot_bridge.py` (PlotCanvas, Option C aus dem Plan) | ✅ funktional; Pinch-to-Zoom für Punktezahl |
| Tab 3 — Systemansicht | `qml/SystemView.qml`, `bridge/visuals_bridge.py`, `qml/components/{Gauge,RotationIndicator,VectorIndicator,MiniTable}.qml` | ✅ Anzeige vollständig (Bild+Overlays+Gauges/Rotation/Vektor/Tabelle); **Editier-Modus (Overlays per Drag verschieben) noch nicht umgesetzt**, siehe TODO |
| Tab 4 — Parameter | `qml/ParamsView.qml`, `bridge/param_bridge.py`, `qml/components/{Joystick,TouchSlider}.qml` | ✅ vollständig (Slider/Zahl/Text/Toggle/Button/Joystick, Fast+Slow-Downlink, Save-Default) |

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

## Offene Punkte / nächste Schritte (aus dem Migrationsplan)

1. **Systemansicht-Editiermodus**: Overlay-Label per Drag verschieben und
   `visuals_overlays.json` daraus neu schreiben (Migrationsplan 4.5,
   „Drag-Handles statt Eingabefeldern"). Aktuell nur Lesedarstellung.
2. **Test auf echter RPi5-Hardware**: `QT_QPA_PLATFORM=eglfs` prüfen,
   `QSG_RENDER_LOOP=basic` bei Flackern testen (Migrationsplan Abschnitt 7).
3. **PlotCanvas-Performance** bei sehr hoher Punktzahl (>500) auf
   schwacher RPi5-GPU messen; ggf. Umstieg auf Option D (QSGGeometryNode)
   falls Option C (aktuell umgesetzt) nicht ausreicht.
4. Alte `gui/`-Widgets-Tabs erst entfernen, wenn Punkt 2 erfolgreich war
   (Migrationsplan Phase 6).
5. Tooling: Qt Design Studio zum visuellen Feintuning der Touch-Layouts
   nutzen (Migrationsplan Abschnitt 10).

## Projektstruktur (neu)

```
rpi5_monitor/
├── main_qml.py               # neuer QML-Einstiegspunkt
├── bridge/                   # Python↔QML-Brücke (kein QtWidgets-Import)
│   ├── app_bridge.py         # Fassade, Poll-Loop, Node-Umschaltung
│   ├── telemetry_bridge.py   # Tab 1
│   ├── plot_bridge.py        # Tab 2 (inkl. PlotCanvas QQuickPaintedItem)
│   ├── param_bridge.py       # Tab 4 (ParamStore unverändert übernommen)
│   ├── visuals_bridge.py     # Tab 3
│   └── utils.py              # parse_channels (portiert)
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
        └── MiniTable.qml
```

Unverändert wiederverwendet: `config.py`, `network_worker.py`, `param_io.py`,
`param_config.json`, `visuals_overlays.json`, `bild/`.
