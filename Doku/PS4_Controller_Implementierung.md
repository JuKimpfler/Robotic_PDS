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
| `rpi5_monitor/64Bit_Version/bridge/controller_bridge.py` | **Neu.** `ControllerBridge(QObject)` — liest den pygame-Joystick, erkennt Hot-Plug/-Unplug, schreibt Werte direkt in `ParamStore`. `poll()` wird von `ParamBridge` mit 100 Hz aufgerufen (**kein eigener Timer**, siehe unten). |
| `rpi5_monitor/64Bit_Version/bridge/param_bridge.py` | `ControllerBridge`-Instanz wird in `ParamBridge.__init__` angelegt, als `params.controller` (QObject-Property) für QML exponiert. Neue Methoden `fast_float_ranges()` (liefert Min/Max aus `param_config.json`) und `apply_controller_values()` (schreibt in den Store). |
| `rpi5_monitor/64Bit_Version/bridge/app_bridge.py` | `shutdown()` ruft zusätzlich `controller.shutdown()` auf (sauberes `pygame.quit()`). |
| `rpi5_monitor/64Bit_Version/qml/components/TouchSlider.qml` | Neue Properties `externalControl`/`externalValue` — Slider zeigt bei aktivem Controller dessen Wert an und ist deaktiviert. |
| `rpi5_monitor/64Bit_Version/qml/components/Joystick.qml` | Neue Properties `externalControl`/`externalNormX`/`externalNormY` — Knopf folgt bei aktivem Controller dessen Stickposition, `PointHandler` wird deaktiviert. |
| `rpi5_monitor/64Bit_Version/qml/ParamsView.qml` | Statusbanner ("🎮 Controller verbunden: ..."), Verdrahtung von Slider/SpinBox/Joystick der **Fast-Seite** mit `params.controller.*`. |
| `setup_rpi5.sh` | `pygame>=2.5.0` zur Fallback-`pip3 install`-Liste hinzugefügt. |

## Warum Python (Backend) statt nur QML?

Die Werte werden **direkt im `ParamStore`** (Python) gesetzt, nicht über
einen Umweg durch QML. Der `_fast_timer` in `ParamBridge` sendet ohnehin alle
10 ms, was gerade im Store steht — es musste also nur festgelegt werden,
*wer* den Store befüllen darf. QML bekommt die Controller-Werte separat (über
`params.controller.values` / `stickNormX`/`stickNormY`) nur noch zur
**Anzeige**, damit die Slider/der Joystick optisch mitlaufen, obwohl sie für
Touch gesperrt sind.

## Warum der Controller keinen eigenen Timer hat

Ursprünglich lief in `ControllerBridge` ein eigener `QTimer` mit 10 ms,
zusätzlich zum 10-ms-Timer, der in `ParamBridge` das Paket verschickt. Zwei
gleich schnelle, aber nicht gekoppelte Timer haben eine zufällige, über die
Laufzeit driftende Phasenlage: schreibt der Controller-Timer den neuen Stand
unmittelbar *nachdem* der Sende-Timer gepackt hat, wartet dieser Wert volle
10 ms auf den nächsten Sendeslot. Das kostete im Mittel 5 ms, im Maximum
10 ms — und zwar schwankend.

`ParamBridge._send_fast_tick()` ruft deshalb jetzt zuerst
`controller.poll()` auf und packt danach. Der gesendete Stand ist damit
garantiert der zuletzt gelesene. Details und der Rest der Latenzkette:
[Latenz_Fernsteuerung.md](Latenz_Fernsteuerung.md).

Zwei weitere Punkte, die aus demselben Grund so gelöst sind:

* **Anzeige entkoppelt vom Senden.** Der `ParamStore` wird mit 100 Hz
  gefüttert, das `valuesChanged`-Signal an QML aber nur mit 25 Hz
  (`CONTROLLER_UI_NOTIFY_MS` in `config.py`). Jede Signalauslösung wertet
  sämtliche daran hängenden QML-Bindings neu aus, und zwar im selben Thread,
  der den 10-ms-Sendetimer bedienen muss. Das Display schafft ohnehin nur
  60 fps.
* **SDL-Event-Queue wird geleert.** `pygame.event.pump()` legt bei jeder
  Achsenbewegung Events in eine Warteschlange. Da die Werte direkt über
  `get_axis()`/`get_button()` gelesen werden, holt sie niemand ab — ohne das
  `pygame.event.clear()` nach jedem Pump läuft die Queue mit rund
  1000 Events/s voll.

## Sicherheitsverhalten

* **Beim Einstecken** werden die ersten zwei Abtastzyklen verworfen. SDL
  liefert für eine noch nie bewegte Achse 0 statt des Ruhewerts; beim
  R2-Trigger (Ruhewert −1) wäre 0 exakt die Mitte des Wertebereichs — der
  Roboter wäre im Moment des Einsteckens mit halbem Speed losgefahren.
* **Beim Abziehen** werden alle fünf Fast-Floats auf 0 gesetzt, statt den
  letzten Stand stehen zu lassen. Ein herausgerissenes USB-Kabel darf den
  Roboter nicht mit dem letzten Gasstand weiterfahren lassen.

Beides ersetzt **keinen** Watchdog auf dem Roboter. `fastParamsAreFresh()`
(Teensy, Schwelle `PARAM_FAST_TIMEOUT_MS` = 150 ms) bleibt die einzige
Absicherung gegen einen Ausfall der Funkstrecke selbst — die Firmware sollte
bei `false` die Motoren stoppen.

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

## Kalibrierung: abweichende Achsen-/Button-Zuordnung

Welcher SDL-Index zu welchem Knopf gehört, hängt vom Kernel-Treiber und der
SDL-Version ab und kann sich zwischen Raspberry Pi OS und Windows
unterscheiden. Die Standardwerte stehen in `DEFAULT_MAPPING` am Kopf von
`controller_bridge.py`.

**Schritt 1 — Rohwerte ansehen.** Die GUI mit erhöhtem Log-Level starten;
dann werden 1× pro Sekunde alle Achsen und Buttons ausgegeben:

```bash
PDS_LOGLEVEL=DEBUG python3 main_qml.py
```

```
[bridge.controller] DEBUG Rohwerte 'Sony Interactive Entertainment Wireless Controller':
                          Achsen=[0.0, 0.0, -1.0, 0.0, 0.0, -1.0] Buttons=[0, 0, ..., 1, 0]
```

Nacheinander jeden Stick/Trigger/Knopf betätigen und ablesen, welcher Index
sich ändert.

**Schritt 2 — Zuordnung eintragen.** Statt den Code zu ändern (was beim
nächsten `git pull` kollidiert), eine Datei `controller_config.json` neben
`config.py` anlegen. Nur die abweichenden Schlüssel sind nötig:

```json
{
  "axis_r2":    4,
  "button_r1":  5,
  "button_l1":  4,
  "deadzone":   0.10
}
```

Verfügbare Schlüssel: `axis_left_x`, `axis_left_y`, `axis_right_x`,
`axis_r2`, `button_r1`, `button_l1`, `deadzone`. Ein Index von `-1`
deaktiviert die jeweilige Funktion. Die Datei steht in `.gitignore`, bleibt
also lokal. Beim Start bestätigt eine Log-Zeile die Übernahme:

```
[bridge.controller] INFO  Controller-Mapping aus controller_config.json übernommen.
```

## Installation

```bash
pip3 install --break-system-packages pygame
```

(ist auch Teil von `setup_rpi5.sh`). Der PS4-Controller wird per USB
angeschlossen und vom Kernel als Standard-HID-Gamepad erkannt — kein
zusätzlicher Treiber nötig. Falls `pygame` auf einem schlanken
Raspberry-Pi-OS-Image keine passende SDL2-Bibliothek findet, zusätzlich:

```bash
sudo apt-get install -y libsdl2-2.0-0
```

### pygame ist optional — und auf Python 3.14 nicht installierbar

`pygame` ist eine **optionale** Abhängigkeit. Fehlt es, läuft die komplette
GUI unverändert weiter; nur die Controller-Unterstützung ist dann aus und die
Fast-Params werden wie bisher per Touch bedient. Beim Start steht dann eine
Warnung im Log:

```
[bridge.controller] WARNING  pygame nicht verfuegbar (...) — Controller-Unterstuetzung
                             ist deaktiviert, die Fast-Params bleiben per Touch bedienbar.
```

> Das war bis zu diesem Review **nicht** so: `import pygame` stand auf
> Modulebene und hat bei einem fehlenden Paket den Import von
> `controller_bridge` → `param_bridge` → `app_bridge` mitgerissen — die
> gesamte Oberfläche startete dann gar nicht mehr.

**Für Python 3.14 gibt es (Stand 08/2026) kein `pygame`-Wheel**, und der
Build aus dem Quelltext scheitert (`ModuleNotFoundError: No module named
'setuptools._distutils.msvccompiler'`). Auf einem so neuen Python
stattdessen die Community-Variante verwenden — gleicher Import-Name,
API-kompatibel:

```bash
pip install pygame-ce
```

Auf Raspberry Pi OS Bookworm (Python 3.11) und den dort üblichen
Windows-Installationen (3.11–3.13) funktioniert das normale `pygame`.

## Bekannte Einschränkung

Nur **ein** Controller/Fast-Joystick wird unterstützt (`Joystick(0)`,
gespiegelt auf den ersten `source: "fast"`-Eintrag aus
`param_config.json`). Bei mehreren Fast-Joysticks in der Konfiguration
müsste `ParamsView.qml` zusätzlich nach `modelData.xIndex` unterscheiden.

## Fehlersuche

| Symptom | Ursache / Prüfung |
|---|---|
| Banner „Controller verbunden“ erscheint nie | `pygame` installiert? Log auf `pygame/SDL konnte nicht initialisiert werden` prüfen. Unter Linux muss der Benutzer in der Gruppe `input` sein bzw. `/dev/input/js0` lesbar sein. |
| Banner erscheint, aber nichts bewegt sich | Achsen-/Button-Zuordnung weicht ab → Kalibrierung oben. |
| Roboter fährt sofort beim Einstecken los | Sollte durch den Warmup abgefangen sein; wenn nicht, liefert `axis_r2` nicht −1 im Ruhezustand → Rohwerte prüfen und ggf. anderen Achsindex eintragen. |
| Steuerung reagiert verzögert | → [Latenz_Fernsteuerung.md](Latenz_Fernsteuerung.md), Abschnitt 3 (Nachmessen). |
| Werte „springen“ um die Mittelstellung | `deadzone` in `controller_config.json` erhöhen (Standard 0.08). |
