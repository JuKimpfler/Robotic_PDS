# PS4-Controller-Integration (Fast-Kanal)

Ergänzt die QML-GUI (`rpi5_monitor/64Bit_Version/`) um automatische
Steuerung des Fast-Kanals (5 Floats, 100 Hz, Port `7011`/`7012`) über
einen per USB angeschlossenen PS4-Controller (DualShock 4). Sobald ein
Controller erkannt wird, übernimmt er die Fast-Params-Seite; die
Touch-Bedienelemente (Slider/SpinBox/Joystick) werden gleichzeitig
gesperrt und zeigen stattdessen live die Controller-Werte an. Wird der
Controller getrennt, ist die Touch-Bedienung sofort wieder aktiv.

## Neue/geänderte Dateien

| Datei | Änderung |
|---|---|
| `rpi5_monitor/64Bit_Version/bridge/controller_bridge.py` | **Neu.** `ControllerBridge(QObject)` — pollt pygame-Joystick mit 100 Hz (eigener `QTimer`, gleiches Intervall wie der Fast-Sendetimer), erkennt Hot-Plug/-Unplug, schreibt Werte direkt in `ParamStore`. |
| `rpi5_monitor/64Bit_Version/bridge/param_bridge.py` | `ControllerBridge`-Instanz wird in `ParamBridge.__init__` angelegt, als `params.controller` (QObject-Property) für QML exponiert. Neue Methoden `fast_float_ranges()` (liefert Min/Max aus `param_config.json`) und `apply_controller_values()` (schreibt in den Store). |
| `rpi5_monitor/64Bit_Version/bridge/app_bridge.py` | `shutdown()` ruft zusätzlich `controller.shutdown()` auf (sauberes `pygame.quit()`). |
| `rpi5_monitor/64Bit_Version/qml/components/TouchSlider.qml` | Neue Properties `externalControl`/`externalValue` — Slider zeigt bei aktivem Controller dessen Wert an und ist deaktiviert. |
| `rpi5_monitor/64Bit_Version/qml/components/Joystick.qml` | Neue Properties `externalControl`/`externalNormX`/`externalNormY` — Knopf folgt bei aktivem Controller dessen Stickposition, `PointHandler` wird deaktiviert. |
| `rpi5_monitor/64Bit_Version/qml/ParamsView.qml` | Statusbanner ("🎮 Controller verbunden: ..."), Verdrahtung von Slider/SpinBox/Joystick der **Fast-Seite** mit `params.controller.*`. |
| `setup_rpi5.sh` | `pygame>=2.5.0` zur Fallback-`pip3 install`-Liste hinzugefügt. |

## Warum Python (Backend) statt nur QML?

Die Werte werden **direkt im `ParamStore`** (Python) gesetzt, nicht über
einen Umweg durch QML. Der bestehende `_fast_timer` in `ParamBridge`
sendet ohnehin alle 10 ms unverändert, was gerade im Store steht — es
musste also nur festgelegt werden, *wer* den Store befüllen darf. QML
bekommt die Controller-Werte separat (über `params.controller.values` /
`stickNormX`/`stickNormY`) nur noch zur **Anzeige**, damit die Slider/der
Joystick optisch mitlaufen, obwohl sie für Touch gesperrt sind.

## Belegung (Standard-Mapping)

Bezogen auf die 5 Fast-Floats aus `param_config.json` (Joystick_X,
Joystick_Y, Rotation, Speed, Dribbler):

| Fast-Float | Quelle |
|---|---|
| Joystick_X / Joystick_Y | linker Stick |
| Rotation | rechter Stick, X-Achse |
| Speed | R2-Trigger (0 = losgelassen, Achsmaximum = voll durchgedrückt) |
| Dribbler | R1 = Maximalwert, L1 = Minimalwert, sonst 0 |

Die Wertebereiche (min/max) kommen live aus `param_config.json` — werden
dort die Grenzen angepasst, respektiert der Controller sie automatisch.

Die Achsen-/Button-Indizes (`AXIS_LEFT_X`, `BUTTON_R1`, …) stehen als
Konstanten am Kopf von `controller_bridge.py`, falls die SDL-Zuordnung
auf einem bestimmten System abweicht (prüfbar z. B. mit dem
eigenständigen Kalibrierskript `ps4_fast_controller.py --list-axes`,
sofern vorhanden).

## Installation

```bash
pip3 install --break-system-packages pygame
```

(ist jetzt auch Teil von `setup_rpi5.sh`). Der PS4-Controller wird per
USB angeschlossen und vom Kernel als Standard-HID-Gamepad erkannt — kein
zusätzlicher Treiber nötig. Falls `pygame` auf einem schlanken
Raspberry-Pi-OS-Image keine passende SDL2-Bibliothek findet, zusätzlich:

```bash
sudo apt-get install -y libsdl2-2.0-0
```

## Bekannte Einschränkung

Nur **ein** Controller/Fast-Joystick wird unterstützt (`Joystick(0)`,
gespiegelt auf den ersten `source: "fast"`-Eintrag aus
`param_config.json`). Bei mehreren Fast-Joysticks in der Konfiguration
müsste `ParamsView.qml` zusätzlich nach `modelData.xIndex` unterscheiden.
