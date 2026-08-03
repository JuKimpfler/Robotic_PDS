# Implementierung: Kanal-/Param-Namen + Overlay-Mapping (Teensy → GUI)

**Projekt:** Robotic_PDS (RoboCup Junior Soccer 2vs2)
**Betrifft:** `teensy_firmware/` (Firmware), `rpi_zero_node/spi_receiver.py` (Relay),
`rpi5_monitor/64Bit_Version` (PyQt6: QML-GUI `main_qml.py` sowie die ältere Widgets-GUI `main.py`/`gui/`)
**Nicht betroffen:** `rpi5_monitor/Old_PySide` (nicht mehr aktiv gepflegt)

---

## 1. Ausgangslage und Ziel

Vorher lagen alle Anzeigenamen und die Zuordnung „welcher Kanal wird wo angezeigt"
ausschließlich GUI-seitig, von Hand gepflegt:

- `config.py::VARIABLE_NAMES` — generische `Var_000..Var_199`-Namen für die 200 Debug-Kanäle.
- `param_config.json` — Namen/Widget-Typ für die 50 Slow-Floats, 50 Slow-Bools, 5 Fast-Floats.
- `visuals_overlays.json` — welche Kanäle auf welchem Bild/Body-Objekt/Widget
  (Gauge, Rotation, Vektor, Tabelle) erscheinen.

Jetzt ist die **Firmware** (Teensy) die Quelle für Namen und Overlay-Zuordnung,
gepflegt in einer einzigen Datei (`channel_config.h`). Der Teensy schickt diese
Information beim Verbindungsaufbau über den bestehenden
UART → RPi-Zero → UDP → RPi-5-Pfad an die GUI, die sie anzeigt. Die lokalen
JSON-Dateien bleiben bestehen — sie sind jetzt die **Anpassungsschicht** (Widget-
Typ, Wertebereiche, Overlay-Positionen), während die Firmware nur die
**Standard-/Anfangswerte** für Namen und Overlay-Zuordnung liefert. Bereits
lokal editierte Gruppen/Namen werden nie überschrieben.

Zusätzlich wurde die Teensy-Lib erweitert: Kanäle können entweder per Pointer
im `setup()` an eine Variable gebunden werden (inkl. Name, automatisches
Sampling jeden Zyklus) oder weiterhin dynamisch/namenlos wie bisher per
`Channel(chn, val)` beschrieben werden.

---

## 2. Protokoll

### 2.1 Neue Magics/Konstanten

Definiert in `teensy_firmware/src/params.h`, gespiegelt in
`rpi5_monitor/*/config.py` und `rpi_zero_node/spi_receiver.py`:

```
CHANNEL_DESC_MAGIC          = 0xDE5C0001   // Teensy -> GUI, gechunktes JSON
CHANNEL_DESC_REQUEST_MAGIC  = 0xDE5C00F0   // GUI -> Teensy, 4-Byte Anforderung
```

Neue UDP-Ports (Schema: 5000er = Downlink zum RPi 5, 7000er = Uplink zum Teensy,
analog zu den bestehenden Telemetrie-/Param-Ports):

```
UDP_CHANNEL_DESC_PORT_NODE{1,2}          = 5011 / 5012   (Pi Zero -> Pi 5, Chunks)
UDP_CHANNEL_DESC_REQUEST_PORT_NODE{1,2}  = 7021 / 7022   (Pi 5 -> Pi Zero -> Teensy, Request)
```

### 2.2 Chunk-Paket (Teensy → GUI, über UART_DBG wie Telemetrie/Params)

```
[0..3] magic        (CHANNEL_DESC_MAGIC)
[4]    chunk_idx    (uint8)
[5]    chunk_count  (uint8)
[6]    payload_len  (uint8, 0..250)
[7..]  payload       (UTF-8-JSON-Fragment, <=250 Bytes)
```

Maximale Paketgröße ~257 Bytes — vergleichbar mit dem bestehenden
`PARAM_SLOW_PACKET_BYTES` (258). Die Chunks werden mit maximal einem Chunk pro
10-ms-`update()`-Zyklus verschickt, damit der 100-Hz-Telemetrieversand nie
blockiert. Ausgelöst: einmal beim ersten `update()` nach `init()` (Boot), und
erneut bei Empfang eines `CHANNEL_DESC_REQUEST_MAGIC`-Pakets.

### 2.3 Request-Paket (GUI → Teensy)

Nur die 4 Magic-Bytes, kein Payload. Wird vom `pollParamUart()`-Parser als
dritter Zweig neben dem Slow-/Fast-Param-Magic erkannt.

### 2.4 JSON-Inhalt

Von `PDS.cpp` aus `channel_config.h` + zur Laufzeit registrierten `bind()`-
Namen gebaut, einmalig zum Sendezeitpunkt:

```json
{
  "channels": {"10": "Akku_Spannung", "11": "System_Temp"},
  "param_slow_floats": {"0": "Kp"},
  "param_slow_bools":  {"0": "Enable_X"},
  "param_fast_floats": {"0": "Joy_X"},
  "overlays": [
    {"group":1,"type":"gauge","label":"Motor L Speed","channel":0,"min":-5,"max":5},
    {"group":1,"type":"text","label":"Akku","channel":10,"x_pct":10,"y_pct":15},
    {"group":1,"type":"table","label":"Status 0-9","extra":"0-9"},
    {"group":2,"type":"bodies","label":"Feld","extra":"field_width=2.0;field_height=1.5;body1_label=Ball;body1_channel_x=0;body1_channel_y=1;..."}
  ]
}
```

Nur belegte Indizes werden gesendet (sparse) — passt zum bestehenden
Fallback-Muster (`VARIABLE_NAMES.get(i, f"Var_{i:03d}")`). Die `overlays`-Liste
verwendet dieselben Feldnamen wie `visuals_overlays.json`s `graphics`-Einträge;
`extra` trägt Freitext für Typen mit zu vielen/variablen Feldern:

| `type` | Pflichtfelder | `extra`-Inhalt |
|---|---|---|
| `text` | `channel`, `x_pct`, `y_pct` | — |
| `gauge` | `channel`, `min`, `max` | — |
| `rotation` | `channel` | — (optional `max` für die Pfeillängen-Skalierung) |
| `vector` | `channel` (=Winkel), `channel2` (=Speed), `max` | — |
| `table` | `label` (=Titel) | Kanalliste, z. B. `"0-9,15,20-22"` |
| `bodies` | `label` | `key=value;`-Liste mit `field_width`, `field_height`, `body1_label`, `body1_color`, `body1_diameter`, `body1_channel_x`, `body1_channel_y`, `body1_channel_angle`, `body1_channel_diameter`, analog `body2_*` |

---

## 3. Firmware (`teensy_firmware/src/`)

### 3.1 `channel_config.h` — die eine Datei, die der Nutzer pflegt

```cpp
// Namen für Debug-Kanäle, die NICHT per bind()/Channel(...,name) benannt werden
static const ChannelNameDef CHANNEL_NAMES[] = {
    {10, "Akku_Spannung"},
    {11, "System_Temp"},
};

// Namen für den Param-Downlink (kommen per UART-RX, nie über einen Schreibaufruf)
static const char* const PARAM_SLOW_FLOAT_NAMES[PARAM_SLOW_FLOAT_COUNT] = {
    "Kp", "Kd", /* ... */
};
static const char* const PARAM_SLOW_BOOL_NAMES[PARAM_SLOW_BOOL_COUNT]  = { "Enable_X" };
static const char* const PARAM_FAST_FLOAT_NAMES[PARAM_FAST_FLOAT_COUNT] = { "Joy_X" };

// Overlay-Zuordnung: welche Kanäle wo angezeigt werden
static const OverlayDef CHANNEL_OVERLAYS[] = {
    {1, "gauge", "Motor L Speed", 0, -1, -5.0f, 5.0f},
    {1, "text",  "Akku",          10, -1, 0.0f, 0.0f, 10.0f, 15.0f},
    {1, "table", "Status 0-9",   -1, -1, 0.0f, 0.0f, -1.0f, -1.0f, "0-9"},
};
```

Beide Listen sind **sparse** — nicht belegte Indizes/Kanäle bekommen GUI-seitig
weiterhin den generischen Fallback (`Var_NNN`) bzw. bleiben in
`visuals_overlays.json` unangetastet.

### 3.2 `PDS.h` / `PDS.cpp` — neue Bibliotheks-API

```cpp
// Pointer-Bindung, Auto-Sampling: liest *ptr bei jedem update()-Zyklus
// automatisch aus, kein weiterer Channel()-Aufruf im Sketch nötig.
void bind(uint8_t chn, float* ptr, const char* name = nullptr);
void bind(uint8_t chn, bool*  ptr, const char* name = nullptr);
void bind(uint8_t chn, int*   ptr, const char* name = nullptr);

// Bestehend, unverändert: dynamischer, namenloser Wert-Write pro Zyklus.
void Channel(uint8_t chn, float val);

// Neu: dynamischer Write + einmalige Namensregistrierung.
void Channel(uint8_t chn, float val, const char* name);
```

Beispiel im Sketch:

```cpp
float akkuSpannung;
bool  motorEnable;

void setup() {
    debugger.init();
    debugger.bind(10, &akkuSpannung, "Akku_Spannung");   // ab jetzt automatisch gesampelt
    debugger.bind(20, &motorEnable);                      // Name kommt aus CHANNEL_NAMES[]
}

void loop() {
    debugger.update();                     // sampelt gebundene Kanäle automatisch
    debugger.Channel(5, sin(millis()));     // weiterhin: dynamisch, namenlos wie bisher
}
```

Intern: eine Namens-Registry (`_names[ACTIVE_CHANNELS][CHANNEL_NAME_MAXLEN]`,
befüllt aus `CHANNEL_NAMES[]` in `init()`, danach von `bind()`/`Channel(...,name)`
überschreibbar) und eine Bindungs-Tabelle (`_bound[ACTIVE_CHANNELS]`), die vor
`buildPacket()` in `update()` abgetastet wird. Das JSON wird einmalig in einen
~12-KB-Puffer gebaut (`buildDescriptorJson()`) und über eine kleine
Zustandsmaschine (`startDescriptorSend()` / `sendNextDescChunk()`) chunkweise
versendet.

---

## 4. Pi-Zero-Relay (`rpi_zero_node/spi_receiver.py`)

`ChunkFrameAssembler` (analog zu `TelemetryFrameAssembler`, aber variable
Länge über das `payload_len`-Byte statt fester Paketgröße) läuft unabhängig
neben dem bestehenden Telemetrie-Assembler auf demselben Rohbyte-Strom — beide
bekommen denselben `ser.read()`-Chunk und verwerfen, was nicht zum eigenen
Magic gehört. Das ist unproblematisch, da der Telemetrie-Header (`0xDEADBEEF`)
und der Deskriptor-Header (`0xDE5C0001`, gefolgt von reinem ASCII-JSON) sich
nicht überschneiden können.

Chunks werden 1:1 auf `UDP_CHANNEL_DESC_PORT` gebroadcastet; Request-Pakete
vom RPi 5 werden auf einem eigenen, nicht-blockierenden Socket empfangen und
direkt an den Teensy weitergereicht — alles in derselben bestehenden
`selectors`-Event-Loop.

---

## 5. RPi-5-GUI (`channel_registry.py`, in allen drei GUI-Varianten dupliziert)

Neues Modul (gleiche Duplikations-Konvention wie `param_io.py`/`config.py`):

- **`ChannelRegistry`** — Dataclass mit `channel_names`, `param_slow_float_names`,
  `param_slow_bool_names`, `param_fast_float_names`, `overlays`, `received`.
- **`descriptor_receiver_process()`** — eigener `multiprocessing`-Prozess
  (Kopie des Musters von `udp_receiver_process` in `network_worker.py`), setzt
  Chunks pro Node wieder zu vollständigem JSON zusammen.
- **`send_descriptor_request()`** — 4-Byte-Request-Paket senden (Button
  "🏷 Kanalnamen" im Header bzw. "Kanalnamen anfordern" in der Toolbar).
- **`apply_overlay_defaults()`** — befüllt `visuals_overlays.json`-Gruppen,
  deren `overlays`/`graphics` noch leer sind, aus `registry.overlays`.
  **Bereits lokal editierte Gruppen werden nie überschrieben.**

### 5.1 Wo die Namen ankommen

| GUI-Bereich | Datei | Mechanismus |
|---|---|---|
| Live-Tabelle (Kanalnamen) | `gui/tab_table.py`, `bridge/telemetry_bridge.py` | `TelemetryTableModel.set_names()` — granulares `dataChanged`, kein Neuaufbau |
| Param-Tab (Namen der Slow-/Fast-Einträge) | `gui/tab_params.py` | Jede Widget-Factory hängt einen `_name_setter`-Callback an ihr Wurzel-Widget; `ParamEditorWidget.apply_names()` ruft ihn gezielt pro Index auf — **Werte/Zustand bleiben unangetastet** |
| Param-Tab (QML) | `bridge/param_bridge.py` | Baut `groups` neu auf (QML kennt keine granulare Property-Aktualisierung), gibt dabei aber die **aktuellen Live-Werte** aus `ParamStore` statt der JSON-Defaults mit — sonst würde der Repeater-Neuaufbau jeden verstellten Regler zurücksetzen |
| Systemansicht (Overlay-Defaults) | `gui/tab_visuals.py`, `bridge/visuals_bridge.py` | `apply_overlay_defaults_from_registry()` — nur leere Gruppen werden befüllt; Widgets-GUI hat zusätzlich einen "⟲ Auf Teensy-Standard zurücksetzen"-Button für die aktuell sichtbare Gruppe |
| Systemansicht (Tabellen-Kanalnamen) | `qml/components/MiniTable.qml` | Bekommt `channelNames` (aufgelöst in `visuals_bridge.py` via `VARIABLE_NAMES`) statt clientseitig `"Var_" + index` zu bilden |

`VARIABLE_NAMES` (in `config.py`) wird beim Empfang **in-place mutiert**
(`.update(...)`, nicht neu zugewiesen), damit bereits importierte Referenzen
überall im Code automatisch die neuen Namen sehen.

### 5.2 Bewusste Einschränkung: kein Overlay-Editor in QML

Nur die PyQt6-Widgets-GUI (`gui/tab_visuals.py::OverlayConfigTable`) kann
Overlays interaktiv bearbeiten und speichern — das war schon vor dieser
Änderung so (QML zeigt Overlays nur an, siehe `README_QML.md`). Die neue
Teensy-Namensfunktion ändert daran nichts: QML zeigt die vom Teensy gelieferten
bzw. lokal editierten Overlays an, die Bearbeitung bleibt Widgets-exklusiv.

---

## 6. Verifikation

- **Automatisiert geprüft** (Standalone-Testskript, ohne echten Teensy/PyQt):
  Chunking/Reassemblierung (`ChunkFrameAssembler`, inkl. eingestreutem Rauschen),
  `ChannelRegistry.from_json_dict`, `apply_overlay_defaults` (inkl. Schutz vor
  Überschreiben bereits konfigurierter Gruppen, `bodies`-`extra`-Parsing), sowie
  ein **End-to-End-Loopback** über echte UDP-Sockets + `multiprocessing.Process`
  (`descriptor_receiver_process`) — 16/16 Checks bestanden.
- **Nicht geprüft:** Firmware-Kompilierung. Zwei Gründe, beide unabhängig von
  dieser Änderung:
  1. Die ARM-Toolchain (`arm-none-eabi-g++`) wird auf dieser Maschine von einer
     Device-Guard-Richtlinie blockiert.
  2. `teensy_firmware/` enthält aktuell **kein `main.cpp`/`.ino`** (Einstiegspunkt
     fehlt) und `PDS.h` inkludiert bereits vor dieser Änderung ein nicht
     vorhandenes `"enum.h"` — das Projekt baut im aktuellen Repo-Stand nicht
     eigenständig.

  → Vor dem ersten echten Flash: `PDS.cpp`/`channel_config.h` mit dem
  vollständigen Projekt (inkl. `main.cpp`/`enum.h`) auf einem Rechner ohne
  diese Einschränkungen kompilieren.
