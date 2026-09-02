# Die Oberfläche vom Roboter aus einstellen

Der Teensy war schon bisher die Quelle der Wahrheit für die Kanalnamen, den
Aufbau des Parameter-Tabs und die Anzeige-Elemente der Systemansicht (siehe
[Kanalnamen_Implementierung.md](Kanalnamen_Implementierung.md) und
[Param_Implementierung.md](Param_Implementierung.md)). Nicht dazu gehörte das
**Aussehen** der Oberfläche — Farben, Schriftgrößen, Akku-Warnung,
Plotter-Voreinstellungen. Das stand ausschließlich in der `settings.json` auf
dem Raspberry Pi und musste dort von Hand gepflegt werden, für jeden Pi
einzeln.

Seit PDS 2.2 kann die Firmware auch das vorgeben — mit **genau demselben
Punktpfad**, den `settings.json` benutzt.

---

## Im Sketch

```cpp
void setup() {
    PDS.begin();

    PDS.setting("ui.dark", true);                            // Wahrheitswert
    PDS.setting("ui.fontScale", 1.2f);                       // Zahl
    PDS.setting("plotter.historySeconds", 20);               // ganze Zahl
    PDS.setting("theme.colors.dark.accentGreen", "#00ff88"); // Farbe/Text
}
```

Der Typ ergibt sich aus dem geschriebenen Wert — das ist wichtiger, als es
aussieht: die GUI prüft jeden Wert gegen ihren eigenen Standardwert, und eine
`1` an einem Schalter wäre kein Wahrheitswert und würde verworfen. Die
Überladungen von `setting()` sorgen dafür, dass im JSON wirklich `true`
steht.

Für die häufigsten Fälle gibt es benannte Abkürzungen — reine Bequemlichkeit,
sie rufen dasselbe `setting()` auf:

```cpp
PDS.guiDarkMode(true);
PDS.guiFontScale(1.2f);
PDS.guiKiosk(true);
PDS.guiKeyboardControl(false);
PDS.guiStartTab(2);                            // 2 = Systemansicht
PDS.guiBatteryWarning(10, 11.5f, 10.8f);       // Kanal, Warnung, Alarm
PDS.guiPlotter(20, 500, 8);                    // Sekunden, Punkte, Kurven
PDS.guiCurveColor(0, "#00ff88");
PDS.guiColor("accentGreen", "#00ff88");        // Theme-Farbe (dunkles Schema)
PDS.guiColor("accentGreen", "#0d7a63", false); // ... helles Schema
```

## In `channel_config.h`

Dieselbe Wirkung, aber an einer Stelle statt verteilt im Sketch:

```cpp
#define PDS_HAS_GUI_SETTINGS 1
static const SettingDef GUI_SETTINGS[] = {
    { "ui.dark",                  true      },
    { "ui.fontScale",             1.1f      },
    { "ui.startTab",              2         },
    { "battery.channel",          10        },
    { "battery.warn_below",       11.5f     },
    { "plotter.historySeconds",   20        },
    { "plotter.curveColors.0",    "#00ff88" },
    { "theme.colors.dark.bg",     "#101010" },
};
static constexpr size_t GUI_SETTINGS_COUNT =
    sizeof(GUI_SETTINGS) / sizeof(GUI_SETTINGS[0]);
```

`begin()` liest die Tabelle ein; im Sketch gesetzte Werte gewinnen, weil
`setup()` danach weiterläuft.

Eine `channel_config.h` aus einem bestehenden Roboterprojekt kennt die
Tabelle nicht. Das ist eingeplant: ohne `#define PDS_HAS_GUI_SETTINGS` legt
`PDS.cpp` eine leere Ersatztabelle an, und die Datei übersetzt unverändert
weiter.

---

## Der Weg dorthin

```
channel_config.h / PDS.setting()
        │
        ├─ PowerDebugger::_settings[]          Punktpfad + Wert + Typ
        │
        ▼
   Deskriptor-JSON, Abschnitt "settings"
   {"ui.dark":true,"ui.fontScale":1.2,"theme.colors.dark.bg":"#101010"}
        │   UART → RPi Zero → UDP → RPi 5
        ▼
   channel_registry.ChannelRegistry.settings     nur Skalare, defensiv gelesen
        │
        ▼
   runtime_config.sync_gui_settings()            Fingerabdruck je Node
        │
        ▼
   app_settings.apply_teensy_settings()          Pfad auflösen, Typ prüfen
        │
        ▼
   settings.json + SettingsBridge.reloadExternal()
```

Der Abschnitt ist **kein** neues Wire-Format: der Deskriptor ist JSON, ein
zusätzlicher Abschnitt ist für eine ältere GUI schlicht unsichtbar.
`PDS_WIRE_VERSION` bleibt deshalb bei 2.

---

## Wer gewinnt bei einem Konflikt?

Dieselbe Regel wie für Kanalnamen und Overlays (siehe „Wer gewinnt bei einem
Konflikt?" in `runtime_config.py`):

| | |
|---|---|
| Fingerabdruck unverändert | **nichts tun** — wer die Schriftgröße in der GUI nachgestellt hat, behält sie |
| Fingerabdruck geändert | **übernehmen** — eine neue Firmware setzt sich durch |

Gemerkt wird der Fingerabdruck in `runtime_config/node<N>/gui_settings.json`.
Diese Datei enthält zusätzlich, was übernommen und was verworfen wurde — im
Zweifelsfall am Spielfeldrand ist das die einzige Stelle, an der man
nachsehen kann, warum eine Einstellung aus der Firmware nicht angekommen ist.

Auch eine Vorgabe, von der **nichts** durchkommt, wird gemerkt. Sonst würde
dieselbe unbrauchbare Zeile bei jedem Deskriptor erneut durchprobiert und
jedes Mal dieselbe Warnung ins Logbuch schreiben.

---

## Was nicht durchkommt

Es gilt dasselbe Prinzip wie für die Datei selbst: **ein unsinniger Wert
kostet höchstens sein eigenes Feld.**

| Fall | Folge |
|---|---|
| Pfad gibt es nicht (`gibtesnicht.foo`) | verworfen, steht im Logbuch |
| Typ passt nicht (`"ja"` an einem Schalter) | verworfen, der lokale Wert bleibt |
| Text ohne `#` an einer Farbstelle | verworfen (Qt macht daraus stillschweigend Schwarz) |
| Pfad zeigt auf einen ganzen Abschnitt | verworfen |
| Listenindex außerhalb (`plotter.curveColors.99`) | verworfen |
| Wert außerhalb seines Bereichs (`ui.fontScale = 99`) | hineingelegt |
| `network.*` | **grundsätzlich** verworfen |

Die Sperre für `network.*` ist keine Bequemlichkeit, sondern die einzige
Stelle, an der die Zusage „ein Fehler kostet ein Feld" nicht mehr gälte: eine
falsche IP in der Firmware würde genau die Leitung kappen, über die man sie
korrigieren müsste. Der Roboter darf sein Aussehen bestimmen, nicht den Weg
zu sich selbst.

Verworfene Schlüssel landen im Logbuch der GUI (Stufe „Warnung"), damit ein
Tippfehler in `channel_config.h` nicht still verschwindet.

---

## Abschalten

Im Diagnose-Tab stehen zwei Schalter untereinander:

* **„Konfiguration vom Teensy übernehmen"** (`ui.autoApplyTeensyConfig`) —
  betrifft alles: Namen, Parameter-Tab, Overlays, Einstellungen.
* **„Aussehen vom Teensy übernehmen"** (`ui.autoApplyTeensySettings`) —
  betrifft nur die Einstellungen.

Zwei Schalter, weil es zwei Entscheidungen sind: die Kanalnamen will man
praktisch immer vom Roboter, das Aussehen des eigenen Tablets nicht
unbedingt.

---

## Grenzen

* `PDS_MAX_SETTINGS` (Vorgabe 32) Einträge, Schlüssel bis 31 Zeichen,
  Textwerte bis 23 Zeichen. Alles per Build-Flag änderbar; der RAM-Bedarf ist
  `PDS_MAX_SETTINGS × (32 + 24 + 8)` Byte, in der Vorgabe also 2 kB.
* Ein zu langer Schlüssel wird **abgelehnt**, nicht abgeschnitten: abgeschnitten
  wäre der Punktpfad ein anderer, und die GUI legte still einen unbenutzten
  Eintrag an.
* Änderungen zur Laufzeit sind erlaubt; damit sie ankommen, muss der
  Deskriptor neu gemeldet werden: `PDS.announceChannelNames()`.
