# Portierung QML-Version: PyQt6 → PyQt5

Diese Fassung ist eine 1:1-Portierung der QML-GUI auf PyQt5 (Qt 5.15),
damit sie auf 32-Bit-Windows läuft (PyQt6/PySide6 gibt es dafür nicht mehr,
da Qt ab Version 6 keine offiziellen 32-Bit-Windows-Builds mehr liefert).

Getestet headless (`QT_QPA_PLATFORM=offscreen`, `--simulate`): Engine lädt,
Bridges laufen, Telemetrie kommt über den Simulator an, keine Python-Fehler.

## Was geändert wurde

### 1. Python: PyQt6 → PyQt5 (alle .py-Dateien in bridge/ und main_qml.py)
Reines Suchen/Ersetzen der Modul-Präfixe:
```
from PyQt6.QtCore import ...   →   from PyQt5.QtCore import ...
from PyQt6.QtGui import ...    →   from PyQt5.QtGui import ...
from PyQt6.QtQml import ...    →   from PyQt5.QtQml import ...
from PyQt6.QtQuick import ...  →   from PyQt5.QtQuick import ...
```
`pyqtSignal`, `pyqtSlot`, `pyqtProperty`, `qmlRegisterType`,
`qmlRegisterSingletonType` heißen in PyQt5 identisch — hier war nichts
weiter zu tun.

### 2. Python: Gescopte Qt6-Enums → PyQt5-Kurzform
PyQt6 erlaubt/erfordert teils gescopte Enums, PyQt5 kennt nur die alte
flache Schreibweise:
```
bridge/plot_bridge.py:       Qt.PenStyle.DashLine        → Qt.DashLine
bridge/telemetry_bridge.py:  Qt.ItemDataRole.UserRole     → Qt.UserRole
bridge/telemetry_bridge.py:  Qt.ItemDataRole.DisplayRole  → Qt.DisplayRole
```

### 3. main_qml.py: app.exec() → app.exec_()
PyQt5 kennt (je nach Version) nur `exec_()` zuverlässig, `exec()` ist ein
reserviertes Python-Keyword-ähnliches Attribut, das erst später als Alias
nachgerüstet wurde. `exec_()` ist der sichere Weg.

### 4. main_qml.py: High-DPI-Attribute ergänzt
In Qt6 ist High-DPI-Scaling automatisch aktiv, in Qt5 nicht. Für Touch-/
HiDPI-Displays wurden vor der `QGuiApplication`-Erzeugung ergänzt:
```python
QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
```
Falls du das nicht willst (z. B. exaktes 1:1-Pixel-Mapping auf dem
Zieldisplay gewünscht), einfach wieder entfernen.

### 5. QML: Versionsnummern bei Modul-Imports ergänzt
Qt6 erlaubt/verlangt unversionierte Imports (`import QtQuick`), Qt5 braucht
zwingend eine Versionsnummer:
```
import QtQuick                     → import QtQuick 2.15
import QtQuick.Window              → import QtQuick.Window 2.15
import QtQuick.Controls            → import QtQuick.Controls 2.15
import QtQuick.Controls.Material   → import QtQuick.Controls.Material 2.15
import App                         → import App 1.0
```
Betroffen: alle Dateien in `qml/` und `qml/components/`.

### 6. Nicht geändert (funktioniert unverändert unter Qt5)
- `required property` in Delegates (`ListView`, `Repeater`) — eingeführt in
  Qt 5.15, genau die Version, die PyQt5 mitbringt. Kein Problem.
- `pragma Singleton` (Theme.qml, UiState.qml) — seit Jahren in Qt5 verfügbar.
- `qmlRegisterType(...)` / `qmlRegisterSingletonType(...)` — identische
  Signatur in PyQt5 und PyQt6.
- `QQuickPaintedItem` (PlotCanvas) — in PyQt5 genauso vorhanden.

## Rendering-Hinweis für schwache/alte 32-Bit-Hardware
Falls beim Start auf dem Ziel-PC ein Fehler wie
`Failed to create OpenGL context` auftaucht (z. B. alte/fehlende
GPU-Treiber unter 32-Bit-Windows), vor dem Start per Umgebungsvariable auf
Software-Rendering umschalten:
```
set QT_QUICK_BACKEND=software
python main_qml.py
```
oder alternativ `set QT_OPENGL=software` bzw. `set QT_ANGLE_PLATFORM=d3d9`
ausprobieren (ANGLE/Direct3D9 läuft auf sehr altem 32-Bit-Windows oft
zuverlässiger als Desktop-OpenGL).

## Installation auf dem Ziel-PC
```
pip install PyQt5 numpy
python main_qml.py --simulate     # zum Testen ohne Teensy
python main_qml.py                # mit echter Hardware
```

## Unverändert übernommen
`config.py`, `network_worker.py`, `param_io.py`, `platform_utils.py`,
`param_config.json`, `param_defaults.h`, `visuals_overlays.json`, `bild/`
— diese enthalten keine Qt6/PyQt6-Abhängigkeiten und wurden 1:1 kopiert.
