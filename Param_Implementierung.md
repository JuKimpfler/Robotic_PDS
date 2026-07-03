# Implementierungsplan v2: Param-Funktionalität (RPi 5 → RPi Zero 2 W → Teensy 4.0)

**Projekt:** Robotic_PDS (RoboCup Junior Soccer 2vs2)
**Basis:** `PDS.h` / `PDS.cpp` (PowerDebugger-Klasse), `params.h`, aktueller Stand `Robotic_PDS-julius.zip`
**Entscheidungen aus Rückfrage (unverändert gültig):** RAM-only auf dem Teensy · Senden nur an den in der GUI aktuell gewählten Node · Fire-and-Forget ohne ACK

---

## 0. Was sich gegenüber Plan v1 geändert hat

| Punkt | v1 (Annahme) | v2 (Ist-Zustand / neue Anforderung) |
|---|---|---|
| Firmware-Struktur | `main.cpp` direkt, SPI→UART-Portierung als Voraussetzung nötig | **Bereits erledigt.** UART-Empfang/-Versand ist sauber in die `PowerDebugger`-Klasse (`PDS.h`/`PDS.cpp`) gekapselt. Phase 0 aus v1 entfällt komplett. |
| Baudrate | Widerspruch 1 MBaud (deine Angabe) vs. 4 MBaud (Doku) | **Geklärt:** `params.h` definiert `UART_DBG_BAUD = 1'000'000UL`. Kein offener Punkt mehr. |
| UART-Instanz | vermutet `Serial1` | Code verwendet durchgängig das Makro `UART_DBG` (in `main.cpp` bisher `Serial3`). Ich übernehme `UART_DBG`, ohne die dahinterliegende Instanz zu erraten (siehe Abschnitt 13, offener Punkt). |
| Parameteranzahl | 50 Floats + 50 Bools @ 2 Hz | **Zusätzlich:** 5 eigenständige Floats @ **100 Hz** für Echtzeit-Joystick-Steuerung — eigener, schnellerer Kanal, separat von den 50+50. |
| Persistenz | „RAM-only, keine Persistenz" | **Präzisiert, kein Widerspruch:** weiterhin kein Flash/EEPROM auf dem Teensy. Aber: neuer **Save-Button in der GUI**, der den aktuellen Parametersatz als Text in eine `.h`-Datei schreibt; diese Datei wird beim nächsten **GUI-Start** wieder eingelesen und als Default gesetzt. Das ist GUI-seitige Persistenz, keine Teensy-seitige — passt zur ursprünglichen Entscheidung. |
| Node-IP | statisch `192.168.42.11` / `.12` | Node-IPs kommen jetzt per **DHCP** vom RPi-5-Hotspot und werden von der GUI **dynamisch aus dem Absender der Telemetrie-Broadcasts** gelernt (`MainWindow._node_ips`). Der Param-Downlink muss diese dynamische IP verwenden, nicht die statischen Konstanten. |

---

## 1. Zielarchitektur (aktualisiert)

```
┌───────────────────────────┐  UDP unicast, 2 Hz (Slow)   ┌──────────────────────┐  UART_DBG RX  ┌─────────────────────┐
│  RPi 5 — GUI (PyQt6)       │ ───────────────────────────▶│  RPi Zero 2 W (Node)  │──────────────▶│  Teensy 4.0          │
│  tab_params.py             │  Port 7001 / 7002            │  uart_receiver.py     │  1 MBaud       │  PowerDebugger        │
│  ParamStore (slow + fast)  │                              │  (aus spi_receiver.py)│               │  (PDS.h / PDS.cpp)    │
│                             │  UDP unicast, 100 Hz (Fast) │                       │               │                       │
│                             │ ───────────────────────────▶│  + 2 UDP-Listener-    │──────────────▶│  g_paramFloats[50]    │
│                             │  Port 7011 / 7012            │    Threads → UART_DBG │               │  g_paramBools[50]     │
└───────────────────────────┘                              └──────────────────────┘               │  g_fastFloats[5]      │
         ▲                                                          │                                └─────────┬────────────┘
         │ IP wird dynamisch aus eingehender Telemetrie gelernt     │ UART_DBG RX (Telemetrie, bestehend, 100 Hz)  │
         └──────────────────────────────────────────────────────────┴───────────────────────────────────────────┘
                     (Broadcast 255.255.255.255:5001/5002, unverändert)
```

**Wichtig, bewusst anders als bei der Telemetrie:** Die Telemetrie (Teensy → RPi 5) läuft per **Broadcast** (`255.255.255.255`) — das ist praktisch, weil die GUI die Node-IP daraus lernt. Der Param-Downlink (RPi 5 → Node) bleibt **Unicast an die aktuell gewählte Node-IP**. Broadcast wäre hier falsch: Bei einem 2-gegen-2-Setup mit zwei unabhängigen Robotern würden sonst **beide** RPi-Zero-Knoten dieselben Steuerbefehle an ihre Teensys weiterreichen, obwohl nur ein Roboter angesteuert werden soll. Das ist keine Kleinigkeit — bitte im Hinterkopf behalten, falls später mal jemand aus Konsistenzgründen versucht ist, auch hier auf Broadcast umzustellen.

---

## 2. Protokoll-Spezifikation: zwei Pakettypen

### 2.1 Slow-Kanal — 50 Floats + 50 Bools, 2 Hz

Unverändert zu Plan v1:

| Offset | Bytes | Feld | Beschreibung |
|---|---|---|---|
| 0 | 4 | `magic` | `0xCAFEFEED` |
| 4 | 4 | `seq` | Laufender Zähler / `millis()`, nur fürs Debugging |
| 8 | 200 | `floats[50]` | `float32`, Little-Endian |
| 208 | 50 | `bools[50]` | 1 Byte/Bool (0x00/0x01) |
| **Σ** | **258 Bytes** | | |

### 2.2 Fast-Kanal — 5 Floats, 100 Hz (neu)

Eigener, bewusst minimaler Pakettyp für niedrige Latenz (Joystick-Steuerung):

| Offset | Bytes | Feld | Beschreibung |
|---|---|---|---|
| 0 | 4 | `magic` | `0xFA57DA7A` ("FAST DATA") — unterscheidbar von Slow-Magic und Telemetrie-Magic `0xDEADBEEF` |
| 4 | 4 | `seq` | wie oben |
| 8 | 20 | `floats[5]` | `float32`, Little-Endian |
| **Σ** | **28 Bytes** | | |

**Warum ein komplett eigener Pakettyp statt einfach 5 der 50 Floats öfter zu senden:** Wenn man alle 258 Byte des Slow-Pakets mit 100 Hz senden würde, käme man auf 25,8 kB/s allein für den Downlink — unnötig, wenn nur 5 Werte wirklich Echtzeit brauchen. Der Fast-Kanal mit 28 Byte @ 100 Hz sind nur 2,8 kB/s. Beide Kanäle zusammen (2,8 + 0,5 kB/s) sind gegenüber der Baudrate (1 MBaud ≈ 100 kB/s brutto) und gegenüber der bestehenden Telemetrie (100 Hz × 1608 Byte ≈ 160 kB/s — läuft aber auf der TX-Leitung, physisch getrennt von RX) verschwindend gering.

### 2.3 Byte-Synchronisation bei zwei Magic-Werten (Teensy-seitig)

Da beide Pakettypen über denselben `UART_DBG`-RX-Stream hereinkommen, muss der Parser beim Erkennen des Magic-Werts zwischen den beiden Paketlängen unterscheiden. Details in Abschnitt 4.

---

## 3. Wie das in die `PowerDebugger`-Klasse passt

Ausgangslage (`PDS.h`):

```cpp
class PowerDebugger{
    private:
        void buildPacket();

    public:
        void init();
        void update();
        void Channel(u_int8_t chn , float val);
};
```

Erweiterung (neue private Member + neue öffentliche Methoden, bestehende bleiben unverändert):

```cpp
class PowerDebugger{
    private:
        void buildPacket();
        void pollParamUart();          // NEU — liest UART_DBG.available(), Zwei-Magic-Sync

        // NEU — Slow-Kanal (50 Floats + 50 Bools, 2 Hz)
        float    g_paramFloats[PARAM_SLOW_FLOAT_COUNT];
        bool     g_paramBools[PARAM_SLOW_BOOL_COUNT];
        uint32_t g_lastSlowRxMs = 0;

        // NEU — Fast-Kanal (5 Floats, 100 Hz, Joystick)
        float    g_fastFloats[PARAM_FAST_FLOAT_COUNT];
        uint32_t g_lastFastRxMs = 0;

    public:
        void init();
        void update();                 // ruft am Ende zusätzlich pollParamUart() auf
        void Channel(u_int8_t chn, float val);

        // NEU — Öffentliche Zugriffs-API für den Roboter-Code
        float getParam(uint8_t index) const;        // Slow-Float, 0–49
        bool  getParamBool(uint8_t index) const;     // Slow-Bool,  0–49
        float getFastParam(uint8_t index) const;     // Fast-Float, 0–4
        bool  paramsAreFresh() const;                // Slow-Kanal-Watchdog
        bool  fastParamsAreFresh() const;             // Fast-Kanal-Watchdog (enger)
};
```

**Warum als Methoden der bestehenden Klasse und nicht als globale Arrays wie in meinem v1-Entwurf:** Ihr habt mit `PDS.h`/`PDS.cpp` bereits den Schritt weg von globalem Zustand in `main.cpp` hin zu einer gekapselten Klasse gemacht. Diesen Stil ziehe ich hier konsequent weiter — der Roboter-Code in `main.cpp` bekommt so eine saubere, konsistente API (`debugger.getParam(3)`, `debugger.getFastParam(0)`), statt zwei verschiedene Zugriffsmuster (Klasse für Telemetrie, globale Arrays für Parameter) nebeneinander pflegen zu müssen.

---

## 4. Phase 1 — Firmware: `PDS.h` / `PDS.cpp` erweitern

### 4.1 Konstanten (in `params.h`, damit sie wie `UART_DBG_BAUD` zentral an einer Stelle stehen)

```cpp
// ── Param-Downlink (RPi 5 → Teensy, über UART_DBG) ──────────────────────────
static constexpr uint32_t PARAM_SLOW_MAGIC        = 0xCAFEFEEDUL;
static constexpr int      PARAM_SLOW_FLOAT_COUNT  = 50;
static constexpr int      PARAM_SLOW_BOOL_COUNT   = 50;
static constexpr int      PARAM_HEADER_BYTES      = 8;   // magic + seq, für beide Pakettypen gleich
static constexpr int      PARAM_SLOW_PACKET_BYTES =
    PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + PARAM_SLOW_BOOL_COUNT;      // 258

static constexpr uint32_t PARAM_FAST_MAGIC        = 0xFA57DA7AUL;
static constexpr int      PARAM_FAST_FLOAT_COUNT  = 5;
static constexpr int      PARAM_FAST_PACKET_BYTES =
    PARAM_HEADER_BYTES + PARAM_FAST_FLOAT_COUNT * 4;                             // 28

static constexpr uint32_t PARAM_SLOW_TIMEOUT_MS = 1000;  // 2 verpasste Zyklen (500 ms) → stale
static constexpr uint32_t PARAM_FAST_TIMEOUT_MS = 150;   // ~15 verpasste Zyklen (10 ms) → stale
```

`PARAM_FAST_TIMEOUT_MS` bewusst großzügiger als "2 verpasste Zyklen" (das wären nur 20 ms) gewählt, weil WLAN-Jitter bei 100 Hz sonst ständig Fehlalarm auslösen würde. 150 ms ist ein Startwert — feinjustieren, sobald ihr reale WLAN-Latenz zwischen RPi 5 und Node gemessen habt.

### 4.2 `pollParamUart()` — Zwei-Magic-Parser

```cpp
void PowerDebugger::pollParamUart() {
    static uint8_t buf[PARAM_SLOW_PACKET_BYTES];   // größerer der beiden Pakettypen, wiederverwendet
    static int     fill = 0;
    static int     expectedLen = 0;                // 0 = suche noch nach einem gültigen Magic

    while (UART_DBG.available()) {
        uint8_t b = UART_DBG.read();

        if (expectedLen == 0) {
            // Schiebefenster über die letzten 4 Bytes für die Magic-Suche
            buf[0] = buf[1]; buf[1] = buf[2]; buf[2] = buf[3]; buf[3] = b;
            if (fill < 4) { fill++; continue; }

            uint32_t magic;
            memcpy(&magic, buf, 4);

            if (magic == PARAM_SLOW_MAGIC) {
                expectedLen = PARAM_SLOW_PACKET_BYTES;
                fill = 4;
            } else if (magic == PARAM_FAST_MAGIC) {
                expectedLen = PARAM_FAST_PACKET_BYTES;
                fill = 4;
            }
            // Sonst: kein bekannter Magic — Fenster bleibt, nächstes Byte prüfen
        } else {
            buf[fill++] = b;

            if (fill == expectedLen) {
                if (expectedLen == PARAM_SLOW_PACKET_BYTES) {
                    memcpy(g_paramFloats, buf + PARAM_HEADER_BYTES,
                           PARAM_SLOW_FLOAT_COUNT * 4);
                    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT; i++) {
                        g_paramBools[i] =
                            buf[PARAM_HEADER_BYTES + PARAM_SLOW_FLOAT_COUNT * 4 + i] != 0;
                    }
                    g_lastSlowRxMs = millis();
                } else {
                    memcpy(g_fastFloats, buf + PARAM_HEADER_BYTES,
                           PARAM_FAST_FLOAT_COUNT * 4);
                    g_lastFastRxMs = millis();
                }
                expectedLen = 0;
                fill = 0;   // bereit für das nächste Paket
            }
        }
    }
}
```

`loop()` ist bei euch einzelsträngig (keine ISRs, die auf dieselben Arrays zugreifen) — deshalb bewusst **ohne** `noInterrupts()/interrupts()`-Klammerung, das wäre hier unnötiger Overhead.

### 4.3 `init()` / `update()` erweitern

```cpp
void PowerDebugger::init(){
    for (int i = 0; i < MAX_FLOATS; i++) debugData[i] = 0;

    UART_DBG.addMemoryForWrite(_serial1_tx_buf, sizeof(_serial1_tx_buf));
    UART_DBG.begin(UART_DBG_BAUD, SERIAL_8N1);

    // NEU — Param-Defaults auf 0 / false initialisieren (RAM-only, kein Flash-Restore)
    for (int i = 0; i < PARAM_SLOW_FLOAT_COUNT; i++) g_paramFloats[i] = 0.0f;
    for (int i = 0; i < PARAM_SLOW_BOOL_COUNT;  i++) g_paramBools[i]  = false;
    for (int i = 0; i < PARAM_FAST_FLOAT_COUNT; i++) g_fastFloats[i]  = 0.0f;

    pinMode(10, INPUT);
}

void PowerDebugger::update(){
    if (DBGTimer >= SAMPLE_PERIOD_US) {
        buildPacket();
        DBGTimer = 0;
        UART_DBG.write(_pkt_buf, PACKET_BYTES);
    }

    pollParamUart();   // NEU — jede update()-Iteration, nicht-blockierend
}
```

### 4.4 Getter + Watchdogs

```cpp
float PowerDebugger::getParam(uint8_t index) const {
    return (index < PARAM_SLOW_FLOAT_COUNT) ? g_paramFloats[index] : 0.0f;
}

bool PowerDebugger::getParamBool(uint8_t index) const {
    return (index < PARAM_SLOW_BOOL_COUNT) ? g_paramBools[index] : false;
}

float PowerDebugger::getFastParam(uint8_t index) const {
    return (index < PARAM_FAST_FLOAT_COUNT) ? g_fastFloats[index] : 0.0f;
}

bool PowerDebugger::paramsAreFresh() const {
    return (g_lastSlowRxMs != 0) && (millis() - g_lastSlowRxMs < PARAM_SLOW_TIMEOUT_MS);
}

bool PowerDebugger::fastParamsAreFresh() const {
    return (g_lastFastRxMs != 0) && (millis() - g_lastFastRxMs < PARAM_FAST_TIMEOUT_MS);
}
```

**Empfehlung (optional, unverändert zu v1):** Vor allem für den Fast-Kanal (Joystick-Fahrsteuerung!) unbedingt `fastParamsAreFresh()` prüfen, bevor die Werte auf Motoren gegeben werden, und bei `false` auf Stillstand statt auf den letzten (u. U. veralteten) Joystick-Wert zurückfallen. Das ist Teensy-intern, verletzt eure Fire-and-Forget-Entscheidung nicht.

---

## 5. Phase 2 — RPi Zero 2 W: `spi_receiver.py` (installiert als `uart_receiver.py`)

Das Umbenennungs-Problem aus Plan v1 ist bei euch bereits gelöst — `setup_node.sh` kopiert `spi_receiver.py` beim Setup automatisch nach `uart_receiver.py`. Die neuen Threads werden direkt in `spi_receiver.py` ergänzt.

### 5.1 Konstanten

```python
# ── Param-Downlink: UDP (von RPi 5) → UART_DBG TX (an Teensy) ──────────────
PARAM_SLOW_MAGIC        = 0xCAFEFEED
PARAM_SLOW_MAGIC_BYTES  = struct.pack("<I", PARAM_SLOW_MAGIC)
PARAM_SLOW_PACKET_BYTES = 8 + 50 * 4 + 50               # 258
UDP_PARAM_SLOW_PORT     = 7000 + NODE_ID                # 7001 / 7002

PARAM_FAST_MAGIC        = 0xFA57DA7A
PARAM_FAST_MAGIC_BYTES  = struct.pack("<I", PARAM_FAST_MAGIC)
PARAM_FAST_PACKET_BYTES = 8 + 5 * 4                      # 28
UDP_PARAM_FAST_PORT     = 7010 + NODE_ID                # 7011 / 7012
```

### 5.2 Gemeinsamer Schreib-Lock

Zwei neue Threads (Slow- und Fast-Downlink) schreiben potenziell **gleichzeitig** auf dasselbe `serial.Serial`-Objekt. Anders als beim bestehenden Lesen (ein einzelner Reader-Thread) braucht das **Schreiben** hier einen Lock, sonst könnten sich zwei `ser.write()`-Aufrufe mitten im Paket überlappen und der Teensy bekäme einen unbrauchbaren Byte-Mix:

```python
_uart_write_lock = threading.Lock()
```

### 5.3 Generischer Downlink-Thread (einmal parametrisiert für Slow und Fast)

```python
def _param_downlink_thread(
    ser: serial.Serial,
    udp_port: int,
    magic_bytes: bytes,
    packet_bytes: int,
    write_lock: threading.Lock,
    stop_event: threading.Event,
    label: str,
) -> None:
    """
    Lauscht auf UDP-Pakete vom RPi 5 und reicht sie unverändert
    (Magic- und Längen-geprüft) über UART_DBG-TX an den Teensy weiter.
    Reiner Relay — keine Interpretation der Werte, kein Rückkanal.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", udp_port))
    sock.settimeout(0.5)
    log.info(f"Param-Downlink[{label}] lauscht auf :{udp_port}")

    fwd_ok, fwd_bad = 0, 0
    t_stat = time.monotonic()

    while not stop_event.is_set():
        try:
            data, _addr = sock.recvfrom(packet_bytes + 64)
        except socket.timeout:
            continue
        except OSError:
            break

        if len(data) != packet_bytes or data[:4] != magic_bytes:
            fwd_bad += 1
            continue

        try:
            with write_lock:
                ser.write(data)
            fwd_ok += 1
        except serial.SerialException as exc:
            log.warning(f"[{label}] UART-Schreibfehler: {exc}")
            fwd_bad += 1

        if time.monotonic() - t_stat >= 10.0:
            log.info(f"[{label}] weitergeleitet={fwd_ok} verworfen={fwd_bad}")
            fwd_ok = fwd_bad = 0
            t_stat = time.monotonic()

    sock.close()


def start_param_downlink_threads(ser, stop_event) -> list[threading.Thread]:
    threads = [
        threading.Thread(
            target=_param_downlink_thread,
            args=(ser, UDP_PARAM_SLOW_PORT, PARAM_SLOW_MAGIC_BYTES,
                  PARAM_SLOW_PACKET_BYTES, _uart_write_lock, stop_event, "Slow"),
            daemon=True, name="ParamDownlinkSlow",
        ),
        threading.Thread(
            target=_param_downlink_thread,
            args=(ser, UDP_PARAM_FAST_PORT, PARAM_FAST_MAGIC_BYTES,
                  PARAM_FAST_PACKET_BYTES, _uart_write_lock, stop_event, "Fast"),
            daemon=True, name="ParamDownlinkFast",
        ),
    ]
    for t in threads:
        t.start()
    return threads
```

In `main()`, direkt nach dem Start des UART-Reader-Threads (bzw. `net_thread`) aufrufen: `param_threads = start_param_downlink_threads(ser, stop_event)`, und im `finally`-Block `for t in param_threads: t.join(timeout=1)` ergänzen.

### 5.4 Kleine Randnotiz (kein Blocker, aber beim ohnehin fälligen Editieren dieser Datei leicht mitzunehmen)

In `_network_monitor_thread` wird der Thread aktuell so gestartet:

```python
net_thread = threading.Thread(
    target=_network_monitor_thread,
    args=(stop_event),      # ← fehlendes Komma: das ist KEIN Tuple, sondern nur `stop_event` in Klammern
    ...
)
```

`args=(stop_event)` ist kein Tupel (dafür bräuchte es `(stop_event,)` mit Komma). Da `Event`-Objekte nicht iterierbar sind, wirft der Thread beim Start intern eine `TypeError` und stirbt lautlos (Daemon-Thread, kein Crash des Hauptprogramms — daher fällt es im Betrieb vermutlich nicht auf, der Netzwerk-Monitor läuft aber schlicht nie). Würde ich beim Einbauen der neuen Threads gleich mitkorrigieren: `args=(stop_event,)`.

---

## 6. Phase 3 — RPi 5: `config.py` erweitern

```python
# ── Slow-Param-Kanal (50 Floats + 50 Bools, 2 Hz) ───────────────────────────
PARAM_SLOW_MAGIC        = 0xCAFE_FEED
PARAM_SLOW_FLOAT_COUNT  = 50
PARAM_SLOW_BOOL_COUNT   = 50
PARAM_HEADER_SIZE       = 8
PARAM_SLOW_PACKET_BYTES = PARAM_HEADER_SIZE + PARAM_SLOW_FLOAT_COUNT * 4 + PARAM_SLOW_BOOL_COUNT  # 258

UDP_PARAM_SLOW_PORT_NODE1 = 7001
UDP_PARAM_SLOW_PORT_NODE2 = 7002

PARAM_SLOW_SEND_HZ          = 2.0
PARAM_SLOW_SEND_INTERVAL_MS = int(1000 / PARAM_SLOW_SEND_HZ)   # 500

# ── Fast-Param-Kanal (5 Floats, 100 Hz, Joystick-Echtzeitsteuerung) ─────────
PARAM_FAST_MAGIC        = 0xFA57_DA7A
PARAM_FAST_FLOAT_COUNT  = 5
PARAM_FAST_PACKET_BYTES = PARAM_HEADER_SIZE + PARAM_FAST_FLOAT_COUNT * 4    # 28

UDP_PARAM_FAST_PORT_NODE1 = 7011
UDP_PARAM_FAST_PORT_NODE2 = 7012

PARAM_FAST_SEND_HZ          = 100.0
PARAM_FAST_SEND_INTERVAL_MS = int(1000 / PARAM_FAST_SEND_HZ)   # 10

# ── Konfigurations- & Persistenzdateien ──────────────────────────────────────
from pathlib import Path
PARAM_CONFIG_PATH      = Path(__file__).parent / "param_config.json"
PARAM_DEFAULTS_H_PATH  = Path(__file__).parent / "param_defaults.h"
```

`TCP_PARAM_PORT = 7001   # Zukunft: Parameter-Übertragung` entfernen bzw. durch Kommentar `# ersetzt durch PARAM_SLOW/FAST-Konstanten, siehe Param-Feature-Plan v2` ersetzen (Port-Nummer 7001 bleibt zufällig gleich, Protokoll ist jetzt UDP statt TCP — siehe Begründung in Plan v1, Abschnitt 2.1, weiterhin gültig).

### 6.1 Dynamische Node-IP nutzen statt `NODE1_IP`/`NODE2_IP`

Da die Node-IPs jetzt per DHCP vergeben werden und `MainWindow._node_ips` sie bereits laufend aus der eingehenden Telemetrie lernt, darf `tab_params.py` **nicht** einfach `NODE1_IP`/`NODE2_IP` aus `config.py` als Sendeziel verwenden — das wären nur die Fallback-Werte für den Fall, dass noch gar keine Telemetrie empfangen wurde. Details der Anbindung in Abschnitt 9.

---

## 7. Phase 4 — `param_config.json`: Schema (aktualisiert um `fast_floats`)

**Ort:** `rpi5_monitor/param_config.json` (GUI-seitig, siehe Begründung Plan v1 Abschnitt 7 — RPi Zero bleibt dummer Relay).

```json
{
  "version": 2,
  "floats": [
    { "index": 0, "name": "Kp_Motor_L", "widget": "slider", "min": 0.0, "max": 10.0, "step": 0.01, "default": 1.0 },
    { "index": 1, "name": "Zielgeschwindigkeit", "widget": "number", "min": -100.0, "max": 100.0, "step": 0.5, "default": 0.0 }
  ],
  "bools": [
    { "index": 0, "name": "Motor_Enable", "widget": "toggle", "default": false },
    { "index": 1, "name": "Kick_Trigger", "widget": "button", "momentary": true, "default": false }
  ],
  "fast_floats": [
    { "index": 0, "name": "Joystick_X",  "widget": "joystick_axis" },
    { "index": 1, "name": "Joystick_Y",  "widget": "joystick_axis" },
    { "index": 2, "name": "Rotation",    "widget": "slider" },
    { "index": 3, "name": "Speed_Scale", "widget": "slider" },
    { "index": 4, "name": "Reserve",     "widget": "text", "min": -10.0, "max": 10.0, "default": 0.0 }
  ],
  "joysticks": [
    {
      "name": "Fahr-Joystick",
      "source": "fast",
      "x_index": 0,
      "y_index": 1,
      "return_to_center": true
    }
  ]
}
```

**Neu gegenüber Plan v1:**
- Eigener Abschnitt `"fast_floats"` mit **genau 5 Einträgen** (Index 0–4) — analog zu `"floats"`/`"bools"`, aber diese Werte gehen über den 100-Hz-Kanal statt über den 2-Hz-Kanal.
- `"joysticks"` bekommt ein Feld `"source"` (`"slow"` oder `"fast"`), damit ein Joystick-Widget wahlweise zwei Indizes aus `"floats"` **oder** aus `"fast_floats"` zusammenfassen kann. Für die klassische Fahrsteuerung (niedrige Latenz nötig) wird hier `"fast"` erwartet.
- `"min"`/`"max"`/`"x_range"`/`"y_range"` sind bei `"slider"`- und `"joystick_axis"`-Einträgen jetzt **optional** — ohne explizite Angabe gilt automatisch ±100 (Konvention, siehe Abschnitt 9.3.0). Nur wenn ihr bewusst davon abweichen wollt (wie bei `"Reserve"` oben, als `"text"`-Eingabe mit ±10), gebt ihr `"min"`/`"max"` explizit an.
- Neuer Widget-Typ `"text"` für direkte Tastatur-Zahleneingabe (siehe Abschnitt 9.3.3).
- Fallback-Mechanismus für nicht konfigurierte Indizes (Plan v1, Abschnitt 7.2) gilt unverändert auch für `"fast_floats"` — allerdings sind es hier nur 5 Einträge, insofern eher unwahrscheinlich, dass ihr die nicht von Anfang an alle benennt.
- Validierungsregeln aus Plan v1 (doppelte Indizes, Bereichsprüfung, unbekannter Widget-Typ) gelten unverändert, ergänzt um: `fast_floats`-Indizes müssen 0–4 sein, `joysticks[].source` muss `"slow"` oder `"fast"` sein.

---

## 8. Phase 5 — Persistenz: Save-Button → `param_defaults.h`

### 8.1 Anforderung, wie ich sie verstehe

- Ein **Save-Button** in der GUI schreibt die *aktuell eingestellten* Werte (Slow-Floats, Slow-Bools, **und** Fast-Floats) in eine feste `.h`-Datei — aktuell bewusst simpel als **reiner Text**, kein echtes C-Parsing nötig.
- **Bei jedem GUI-Start** wird diese Datei gelesen und die enthaltenen Werte werden als Startwerte (statt der statischen `"default"`-Werte aus `param_config.json`) übernommen.

> **Meine Annahme zum Ort des "Programmstarts":** Ich beziehe das auf den Start der **RPi-5-GUI** (`main.py`), nicht auf einen Neustart/Neu-Flash des Teensy — Letzteres würde ein `#include` in der Firmware und einen Kompilier-/Flash-Vorgang bei jeder Wertänderung erfordern, was dem Wunsch nach "aktuell einfach reines Abspeichern" widerspräche. Die GUI-seitige Lösung gibt euch den eigentlich gewollten Workflow: Werte live einstellen, **Speichern** klicken, GUI zu einem späteren Zeitpunkt neu starten → Regler stehen wieder dort, wo ihr sie verlassen habt. Falls ihr zusätzlich *auch* haben wollt, dass der Teensy diese Datei als kompilierte Defaults nutzt (z. B. `#include "param_defaults.h"` in `PDS.cpp`, damit der Roboter auch ganz ohne GUI-Verbindung sinnvolle Startwerte hat), ist das dieselbe Datei — nur müsstet ihr sie dafür manuell in den Firmware-Ordner kopieren und neu flashen. Das nehme ich als optionalen Bonus mit auf, aber nicht als automatisierten Schritt (das wäre deutlich mehr Komplexität — zwei physisch getrennte Rechner, die sich einen Dateipfad teilen müssten).

### 8.2 Dateiformat (reiner Text, aber gültige C-Array-Syntax)

```cpp
// ============================================================
//  param_defaults.h — Auto-generated by Power Debug Monitor
//  Gespeichert am: 2026-07-03T15:42:10
//  NICHT MANUELL BEARBEITEN (wird von der GUI ueberschrieben)
// ============================================================
#pragma once

static const float PARAM_FLOAT_DEFAULTS[50] = {
    1.000000f, 0.000000f, 3.500000f, /* ... 47 weitere ... */
};

static const bool PARAM_BOOL_DEFAULTS[50] = {
    false, true, false, /* ... 47 weitere ... */
};

static const float PARAM_FAST_FLOAT_DEFAULTS[5] = {
    0.000000f, 0.000000f, 0.000000f, 1.000000f, 0.000000f
};
```

### 8.3 Neues Modul `rpi5_monitor/param_io.py`

Bewusst als eigenes, kleines Modul statt alles in `tab_params.py` zu packen — hält die GUI-Datei fokussiert auf Widgets/Layout:

```python
"""param_io.py — Laden/Speichern der Param-Konfiguration und -Defaults."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════
#  param_config.json  →  Widget-Spezifikation (Struktur, Namen, Grenzen)
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ParamEntry:
    index: int
    name: str
    widget: str
    default: float | bool = 0.0
    min: float = 0.0
    max: float = 1.0
    step: float = 0.01
    momentary: bool = False


@dataclass
class JoystickEntry:
    name: str
    source: str        # "slow" oder "fast"
    x_index: int
    y_index: int
    x_range: tuple[float, float] = (-1.0, 1.0)
    y_range: tuple[float, float] = (-1.0, 1.0)
    return_to_center: bool = True


@dataclass
class ParamConfig:
    floats: list[ParamEntry]
    bools: list[ParamEntry]
    fast_floats: list[ParamEntry]
    joysticks: list[JoystickEntry] = field(default_factory=list)


_VALID_WIDGETS = {"number", "slider", "toggle", "button", "joystick_axis"}


def load_param_config(path: Path,
                       float_count: int = 50,
                       bool_count: int = 50,
                       fast_float_count: int = 5) -> ParamConfig:
    """
    Lädt und validiert param_config.json.
    Nicht definierte Indizes werden mit generischen Fallback-Einträgen
    aufgefüllt (analog zu VARIABLE_NAMES in config.py).
    Wirft ValueError mit klarer Meldung bei Widersprüchen.
    """
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    floats      = _resolve_entries(raw.get("floats", []),      float_count,      "number", 0.0)
    bools       = _resolve_entries(raw.get("bools", []),       bool_count,       "toggle", False)
    fast_floats = _resolve_entries(raw.get("fast_floats", []), fast_float_count, "number", 0.0)

    joysticks = []
    for j in raw.get("joysticks", []):
        if j.get("source") not in ("slow", "fast"):
            raise ValueError(f"Joystick '{j.get('name')}': 'source' muss 'slow' oder 'fast' sein")
        joysticks.append(JoystickEntry(
            name=j["name"], source=j["source"],
            x_index=j["x_index"], y_index=j["y_index"],
            x_range=tuple(j.get("x_range", (-1.0, 1.0))),
            y_range=tuple(j.get("y_range", (-1.0, 1.0))),
            return_to_center=j.get("return_to_center", True),
        ))

    return ParamConfig(floats=floats, bools=bools, fast_floats=fast_floats, joysticks=joysticks)


def _resolve_entries(raw_list, count, fallback_widget, fallback_default) -> list[ParamEntry]:
    by_index: dict[int, ParamEntry] = {}
    for e in raw_list:
        idx = e["index"]
        if not (0 <= idx < count):
            raise ValueError(f"Index {idx} außerhalb 0..{count - 1}")
        if idx in by_index:
            raise ValueError(f"Index {idx} doppelt vergeben ('{by_index[idx].name}' vs. '{e['name']}')")
        if e["widget"] not in _VALID_WIDGETS:
            raise ValueError(f"Ungültiger widget-Typ '{e['widget']}' bei Index {idx}")
        by_index[idx] = ParamEntry(
            index=idx, name=e["name"], widget=e["widget"],
            default=e.get("default", fallback_default),
            min=e.get("min", 0.0), max=e.get("max", 1.0),
            step=e.get("step", 0.01), momentary=e.get("momentary", False),
        )

    # Fallback-Einträge für nicht konfigurierte Indizes
    prefix = "Float" if fallback_widget != "toggle" else "Bool"
    for idx in range(count):
        if idx not in by_index:
            by_index[idx] = ParamEntry(
                index=idx, name=f"{prefix}_{idx:02d}",
                widget=fallback_widget, default=fallback_default,
            )
    return [by_index[i] for i in range(count)]


# ══════════════════════════════════════════════════════════════════════════
#  param_defaults.h  ↔  aktuelle Werte (reiner Text, kein echtes C-Parsing)
# ══════════════════════════════════════════════════════════════════════════

_FLOAT_ARR_RE = re.compile(r"PARAM_FLOAT_DEFAULTS\s*\[\d+\]\s*=\s*\{([^}]*)\}")
_BOOL_ARR_RE  = re.compile(r"PARAM_BOOL_DEFAULTS\s*\[\d+\]\s*=\s*\{([^}]*)\}")
_FAST_ARR_RE  = re.compile(r"PARAM_FAST_FLOAT_DEFAULTS\s*\[\d+\]\s*=\s*\{([^}]*)\}")


def write_param_defaults_h(path: Path, floats, bools, fast_floats) -> None:
    def _fmt_floats(values):
        return ", ".join(f"{v:.6f}f" for v in values)

    def _fmt_bools(values):
        return ", ".join("true" if b else "false" for b in values)

    text = (
        "// ============================================================\n"
        "//  param_defaults.h — Auto-generated by Power Debug Monitor\n"
        f"//  Gespeichert am: {datetime.now().isoformat(timespec='seconds')}\n"
        "//  NICHT MANUELL BEARBEITEN (wird von der GUI ueberschrieben)\n"
        "// ============================================================\n"
        "#pragma once\n\n"
        f"static const float PARAM_FLOAT_DEFAULTS[{len(floats)}] = {{\n"
        f"    {_fmt_floats(floats)}\n}};\n\n"
        f"static const bool PARAM_BOOL_DEFAULTS[{len(bools)}] = {{\n"
        f"    {_fmt_bools(bools)}\n}};\n\n"
        f"static const float PARAM_FAST_FLOAT_DEFAULTS[{len(fast_floats)}] = {{\n"
        f"    {_fmt_floats(fast_floats)}\n}};\n"
    )
    path.write_text(text, encoding="utf-8")


def read_param_defaults_h(path: Path) -> dict | None:
    """Gibt None zurück, wenn die Datei fehlt oder nicht parsebar ist —
    der Aufrufer fällt dann auf die JSON-Defaults zurück."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")

    def _parse_floats(body: str) -> list[float]:
        return [float(x.strip().rstrip("fF")) for x in body.split(",") if x.strip()]

    def _parse_bools(body: str) -> list[bool]:
        return [x.strip().lower() == "true" for x in body.split(",") if x.strip()]

    m_f, m_b, m_ff = (_FLOAT_ARR_RE.search(text), _BOOL_ARR_RE.search(text), _FAST_ARR_RE.search(text))
    if not (m_f and m_b):
        return None

    try:
        return {
            "floats": _parse_floats(m_f.group(1)),
            "bools": _parse_bools(m_b.group(1)),
            "fast_floats": _parse_floats(m_ff.group(1)) if m_ff else None,
        }
    except ValueError:
        return None   # Datei beschädigt/unvollständig — GUI fällt auf JSON-Defaults zurück
```

**Robustheit bewusst eingebaut:** `read_param_defaults_h()` gibt `None` zurück statt zu werfen, wenn die Datei fehlt, beschädigt ist oder eine falsche Länge hat — die GUI darf beim Start nicht abstürzen, nur weil z. B. mal jemand die Datei von Hand angefasst hat. Der Aufrufer (Abschnitt 9) muss zusätzlich prüfen, ob `len(floats) == 50` etc. stimmt, bevor er die Werte übernimmt.

---

## 9. Phase 6 — GUI: `tab_params.py`

### 9.1 `ParamStore` (erweitert um Fast-Kanal)

```python
import struct
import numpy as np
from config import PARAM_SLOW_MAGIC, PARAM_FAST_MAGIC


class ParamStore:
    def __init__(self, config: "ParamConfig") -> None:
        self.floats      = np.array([e.default for e in config.floats],      dtype=np.float32)
        self.bools       = np.array([e.default for e in config.bools],       dtype=bool)
        self.fast_floats = np.array([e.default for e in config.fast_floats], dtype=np.float32)
        self._slow_seq = 0
        self._fast_seq = 0

    def set_float(self, i: int, v: float) -> None:      self.floats[i] = v
    def set_bool(self, i: int, v: bool) -> None:         self.bools[i] = v
    def set_fast_float(self, i: int, v: float) -> None:  self.fast_floats[i] = v

    def pack_slow(self) -> bytes:
        self._slow_seq = (self._slow_seq + 1) & 0xFFFFFFFF
        header = struct.pack("<II", PARAM_SLOW_MAGIC, self._slow_seq)
        return header + self.floats.astype("<f4").tobytes() \
                       + bytes(1 if b else 0 for b in self.bools)

    def pack_fast(self) -> bytes:
        self._fast_seq = (self._fast_seq + 1) & 0xFFFFFFFF
        header = struct.pack("<II", PARAM_FAST_MAGIC, self._fast_seq)
        return header + self.fast_floats.astype("<f4").tobytes()

    def apply_defaults_h(self, defaults: dict) -> None:
        """Überschreibt die aktuellen Werte mit denen aus param_defaults.h,
        nur wenn Länge exakt passt (Robustheit gegen alte/kaputte Dateien)."""
        if defaults.get("floats") and len(defaults["floats"]) == len(self.floats):
            self.floats[:] = defaults["floats"]
        if defaults.get("bools") and len(defaults["bools"]) == len(self.bools):
            self.bools[:] = defaults["bools"]
        ff = defaults.get("fast_floats")
        if ff and len(ff) == len(self.fast_floats):
            self.fast_floats[:] = ff
```

### 9.2 Aufbau von `ParamEditorWidget` (Konstruktor, Kernstruktur)

```python
class ParamEditorWidget(QWidget):

    def __init__(self, get_node_ip, parent=None) -> None:
        """
        get_node_ip: Callable[[int], str] — liefert die AKTUELL bekannte
                     IP des angegebenen Node (dynamisch gelernt, siehe
                     MainWindow._node_ips). Wird von MainWindow injiziert.
        """
        super().__init__(parent)
        self._get_node_ip = get_node_ip
        self._active_node = 1
        self._enabled = True

        self._config = load_param_config(PARAM_CONFIG_PATH)
        self._store  = ParamStore(self._config)

        # Defaults aus param_defaults.h überlagern, falls vorhanden & gültig
        defaults = read_param_defaults_h(PARAM_DEFAULTS_H_PATH)
        if defaults:
            self._store.apply_defaults_h(defaults)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._pkt_sent_slow = 0
        self._pkt_sent_fast = 0

        self._build_ui()          # Widgets AUS den (ggf. überschriebenen) Store-Werten aufbauen

        self._slow_timer = QTimer(self)
        self._slow_timer.setInterval(PARAM_SLOW_SEND_INTERVAL_MS)   # 500 ms
        self._slow_timer.timeout.connect(self._send_slow_tick)
        self._slow_timer.start()

        self._fast_timer = QTimer(self)
        self._fast_timer.setInterval(PARAM_FAST_SEND_INTERVAL_MS)   # 10 ms
        self._fast_timer.timeout.connect(self._send_fast_tick)
        self._fast_timer.start()

    # ── Senden ────────────────────────────────────────────────────────────
    def _send_slow_tick(self) -> None:
        if not self._enabled:
            return
        ip   = self._get_node_ip(self._active_node)
        port = UDP_PARAM_SLOW_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_SLOW_PORT_NODE2
        try:
            self._sock.sendto(self._store.pack_slow(), (ip, port))
            self._pkt_sent_slow += 1
        except OSError as exc:
            log.warning(f"Slow-Param-Sendefehler: {exc}")

    def _send_fast_tick(self) -> None:
        if not self._enabled:
            return
        ip   = self._get_node_ip(self._active_node)
        port = UDP_PARAM_FAST_PORT_NODE1 if self._active_node == 1 else UDP_PARAM_FAST_PORT_NODE2
        try:
            self._sock.sendto(self._store.pack_fast(), (ip, port))
            self._pkt_sent_fast += 1
        except OSError as exc:
            log.warning(f"Fast-Param-Sendefehler: {exc}")

    # ── Von MainWindow aufgerufen ────────────────────────────────────────
    def set_active_node(self, node_id: int) -> None:
        self._active_node = node_id

    # ── Save-Button ───────────────────────────────────────────────────────
    def _on_save_clicked(self) -> None:
        write_param_defaults_h(
            PARAM_DEFAULTS_H_PATH,
            self._store.floats, self._store.bools, self._store.fast_floats,
        )
        self._status_label.setText(f"💾 Gespeichert: {PARAM_DEFAULTS_H_PATH.name}")
```

**Hinweis zur 100-Hz-Genauigkeit von `QTimer`:** Ein `QTimer` mit 10 ms Intervall läuft im GUI-Thread und ist nicht hart echtzeitfähig — unter Last (z. B. wenn gleichzeitig der Plotter viele Punkte zeichnet) können einzelne Ticks um ein paar Millisekunden verspätet oder sogar zusammengefasst auftreten. Für eine Joystick-Steuerung ist das in der Praxis unkritisch, weil `fastParamsAreFresh()` auf dem Teensy ohnehin mit 150 ms Toleranz arbeitet (Abschnitt 4.1) — kleinere Jitter fallen darunter. Falls ihr am Feld feststellt, dass es doch spürbar ruckelt, wäre der nächste Schritt, den Fast-Sender in einen eigenen `QThread` mit `time.sleep`-basiertem Takt auszulagern statt einen GUI-Qt-Timer zu nutzen — das hebe ich hier nur als bekannten Kompromiss hervor, baue es aber nicht vorsorglich ein (unnötige Komplexität, solange ihr nicht gemessen habt, dass es ein echtes Problem ist).

### 9.3 Widget-Factory — konkrete Implementierung

Gegenüber Plan v1 (dort nur skizziert) hier die vollständige, lauffähige Umsetzung der vier gewünschten Widget-Typen: **Schieberegler** (Bereich immer ±100), **2-Achsen-Analog-Joystick**, **Buttons/Switches** (groß, gut bedienbar) und **Texteingabe**. Die Widget-Factory läuft über **drei** Listen (`config.floats`, `config.bools`, `config.fast_floats`), Fast-Float-Widgets schreiben über `store.set_fast_float(i, v)` statt `store.set_float(i, v)`.

Benötigte zusätzliche Imports in `tab_params.py`:

```python
import math
from PyQt6.QtWidgets import (
    QSlider, QLineEdit, QGroupBox, QSizePolicy, QDoubleSpinBox,
)
from PyQt6.QtGui import QPainter, QPen, QColor, QDoubleValidator
from PyQt6.QtCore import QPointF
```

#### 9.3.0 Konvention: ±100 als Standardbereich

Damit Slider und Joystick-Achsen projektweit einheitlich sind, gilt: **wenn in `param_config.json` für einen `"slider"`- oder `"joystick_axis"`-Eintrag kein `"min"`/`"max"` gesetzt ist, ist der Bereich immer −100…+100** (statt der generischen 0.0/1.0-Vorbelegung aus Plan v1). Das ist eine kleine, aber wichtige Ergänzung in `param_io.py` (Abschnitt 8.3):

```python
def _default_range_for(widget: str) -> tuple[float, float]:
    if widget in ("slider", "joystick_axis"):
        return -100.0, 100.0
    return 0.0, 1.0

# in _resolve_entries(): ersetzt die bisherige feste Zeile
#   min=e.get("min", 0.0), max=e.get("max", 1.0),
min_default, max_default = _default_range_for(e["widget"])
# ...
min=e.get("min", min_default), max=e.get("max", max_default),
```

Zusätzlich `_VALID_WIDGETS` um den neuen Typ `"text"` erweitern:

```python
_VALID_WIDGETS = {"number", "slider", "toggle", "button", "joystick_axis", "text"}
```

Die physikalische Umrechnung (z. B. ±100 → tatsächliche Motor-PWM) passiert bewusst **im Roboter-Code auf dem Teensy**, nicht in der GUI — die GUI bleibt so ein reiner, generischer Eingabe-Layer.

#### 9.3.1 Schieberegler (Slider)

`QSlider` arbeitet intern nur mit `int` — daher eine kleine Skalierung für Nachkommastellen. Bewusst mit `setMinimumHeight(32)`, damit der Griff auch auf einem Touchscreen gut zu treffen ist:

```python
def make_slider_widget(entry: ParamEntry, on_change) -> QWidget:
    SCALE = 10   # 1 Nachkommastelle Auflösung

    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(4, 2, 4, 2)

    name_lbl = QLabel(entry.name)
    name_lbl.setMinimumWidth(160)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setMinimumHeight(32)                       # dickerer Griff, besser bedienbar
    slider.setMinimum(int(entry.min * SCALE))          # z. B. -1000 bei ±100
    slider.setMaximum(int(entry.max * SCALE))
    slider.setValue(int(entry.default * SCALE))

    value_lbl = QLabel(f"{entry.default:+.1f}")
    value_lbl.setMinimumWidth(56)
    value_lbl.setStyleSheet("font-family: monospace;")

    def _on_changed(raw_int: int) -> None:
        val = raw_int / SCALE
        value_lbl.setText(f"{val:+.1f}")
        on_change(val)

    slider.valueChanged.connect(_on_changed)

    layout.addWidget(name_lbl)
    layout.addWidget(slider, stretch=1)
    layout.addWidget(value_lbl)
    return box
```

#### 9.3.2 Buttons & Switches (groß, gut bedienbar)

Zwei getrennte Stile: ein **Switch** (Toggle, bleibt AN/AUS bis erneuter Klick — grün wenn aktiv) und ein **Button** (momentan, nur aktiv solange gedrückt gehalten — rot, klassischer "Kick-Trigger"). Beide mit `min-width`/`min-height` bewusst großzügig dimensioniert:

```python
_SWITCH_STYLE = """
QPushButton {
    min-width: 140px; min-height: 56px;
    font-size: 13pt; font-weight: 600;
    border-radius: 10px; border: 2px solid #444;
    background: #3a3a3a; color: #ccc;
}
QPushButton:checked {
    background: #2ecc71; color: #10331d; border-color: #2ecc71;
}
QPushButton:!checked:hover { background: #4a4a4a; }
"""

def make_toggle_widget(entry: ParamEntry, on_change) -> QWidget:
    btn = QPushButton()
    btn.setCheckable(True)
    btn.setChecked(entry.default)
    btn.setStyleSheet(_SWITCH_STYLE)
    btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _refresh_text(checked: bool) -> None:
        btn.setText(f"{entry.name}\n{'● AN' if checked else '○ AUS'}")

    btn.toggled.connect(lambda checked: (_refresh_text(checked), on_change(checked)))
    _refresh_text(entry.default)
    return btn


_MOMENTARY_STYLE = """
QPushButton {
    min-width: 140px; min-height: 56px;
    font-size: 13pt; font-weight: 700;
    border-radius: 10px; border: 2px solid #7a2e2e;
    background: #a33; color: white;
}
QPushButton:pressed { background: #ff4444; border-color: #ff4444; }
QPushButton:checked  { background: #2ecc71; border-color: #2ecc71; }
"""

def make_button_widget(entry: ParamEntry, on_change) -> QWidget:
    btn = QPushButton(entry.name)
    btn.setStyleSheet(_MOMENTARY_STYLE)
    btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    if entry.momentary:
        # Bool ist true NUR solange die Taste gedrückt gehalten wird
        btn.pressed.connect(lambda: on_change(True))
        btn.released.connect(lambda: on_change(False))
    else:
        # Klick schaltet um, bleibt bis zum nächsten Klick — als Button gerendert
        btn.setCheckable(True)
        btn.setChecked(entry.default)
        btn.toggled.connect(on_change)

    return btn
```

`entry.momentary` steuert also, ob `"widget": "button"` sich wie ein Taster oder wie ein Schalter verhält (Schema siehe Abschnitt 7) — `"widget": "toggle"` ist dagegen immer ein Schalter.

#### 9.3.3 Texteingabe (neu)

Für Werte, die man exakt eintippen statt ziehen/klicken will (z. B. über eine angeschlossene Tastatur oder die On-Screen-Tastatur des RPi 5). Der Wert wird erst bei **Enter** oder **Fokusverlust** übernommen, nicht bei jedem Tastendruck, damit ein halb eingetippter Wert nicht sofort losgesendet wird:

```python
def make_text_widget(entry: ParamEntry, on_change) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(4, 2, 4, 2)

    name_lbl = QLabel(entry.name)
    name_lbl.setMinimumWidth(160)

    edit = QLineEdit(f"{entry.default:.3f}")
    edit.setMinimumHeight(32)
    edit.setMaximumWidth(100)
    validator = QDoubleValidator(entry.min, entry.max, 4)
    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    edit.setValidator(validator)   # verhindert bereits beim Tippen ungültige Zeichen

    def _commit() -> None:
        try:
            val = float(edit.text().replace(",", "."))   # Komma als Dezimaltrennzeichen zulassen
        except ValueError:
            edit.setText(f"{entry.default:.3f}")          # ungültig → letzter bekannter Wert
            return
        val = max(entry.min, min(entry.max, val))          # hart auf Grenzen klemmen
        edit.setText(f"{val:.3f}")
        on_change(val)

    edit.editingFinished.connect(_commit)

    layout.addWidget(name_lbl)
    layout.addWidget(edit)
    return box
```

#### 9.3.4 2-Achsen-Analog-Joystick (Custom-Widget)

Kein fertiges Qt-Widget dafür vorhanden — eigene Klasse mit `paintEvent` (Kreis + Fadenkreuz + Griff-Punkt) und Maus-Events. Bewusst mit `setMinimumSize(200, 200)`, damit er auf einem Touchscreen gut zu treffen ist, und großem Griff-Punkt (16 px Radius):

```python
class JoystickWidget(QWidget):
    """
    Digitaler 2-Achsen-Joystick. Gibt Werte im konfigurierten Bereich
    zurück (Standard ±100, siehe Abschnitt 9.3.0).
    """

    def __init__(self, x_range=(-100.0, 100.0), y_range=(-100.0, 100.0),
                 return_to_center: bool = True, size_px: int = 200, parent=None) -> None:
        super().__init__(parent)
        self._x_range = x_range
        self._y_range = y_range
        self._return_to_center = return_to_center
        self._knob = QPointF(0.0, 0.0)     # normiert -1..1, unabhängig vom Zielbereich
        self._dragging = False
        self.setMinimumSize(size_px, size_px)
        self.on_change: "Callable[[float, float], None] | None" = None

    # ── Geometrie ─────────────────────────────────────────────────────────
    def _center_radius(self):
        r = min(self.width(), self.height()) / 2 - 14
        return QPointF(self.width() / 2, self.height() / 2), r

    def _pos_to_norm(self, pos: QPointF) -> QPointF:
        center, r = self._center_radius()
        dx = (pos.x() - center.x()) / r
        dy = (pos.y() - center.y()) / r
        mag = math.hypot(dx, dy)
        if mag > 1.0:              # auf den Kreisrand klemmen
            dx, dy = dx / mag, dy / mag
        return QPointF(dx, dy)

    # ── Maus-/Touch-Events ────────────────────────────────────────────────
    def mousePressEvent(self, ev) -> None:
        self._dragging = True
        self._update_from(ev.position())

    def mouseMoveEvent(self, ev) -> None:
        if self._dragging:
            self._update_from(ev.position())

    def mouseReleaseEvent(self, ev) -> None:
        self._dragging = False
        if self._return_to_center:
            self._knob = QPointF(0.0, 0.0)
            self._emit()
            self.update()

    def _update_from(self, pos: QPointF) -> None:
        self._knob = self._pos_to_norm(pos)
        self._emit()
        self.update()

    def _emit(self) -> None:
        if self.on_change is None:
            return
        x = self._knob.x() * (self._x_range[1] if self._knob.x() >= 0 else -self._x_range[0])
        # Bildschirm-Y zeigt nach unten -> Vorzeichen umdrehen, damit "nach oben
        # ziehen" intuitiv einem positiven Y entspricht (wie bei Fahr-Joysticks üblich)
        y = -self._knob.y() * (self._y_range[1] if -self._knob.y() >= 0 else -self._y_range[0])
        self.on_change(x, y)

    # ── Zeichnen ──────────────────────────────────────────────────────────
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center, r = self._center_radius()

        p.setPen(QPen(QColor("#555"), 2))
        p.setBrush(QColor("#2a2a2a"))
        p.drawEllipse(center, r, r)

        p.setPen(QPen(QColor("#444"), 1))
        p.drawLine(QPointF(center.x() - r, center.y()), QPointF(center.x() + r, center.y()))
        p.drawLine(QPointF(center.x(), center.y() - r), QPointF(center.x(), center.y() + r))

        knob_pos = QPointF(center.x() + self._knob.x() * r, center.y() + self._knob.y() * r)
        p.setPen(QPen(QColor("#2ecc71"), 2))
        p.setBrush(QColor("#2ecc71") if self._dragging else QColor("#3a9c63"))
        p.drawEllipse(knob_pos, 16, 16)   # großer Griff-Punkt, gut mit dem Finger zu treffen
```

Einbettung über eine kleine Factory-Funktion, die die zwei referenzierten Float-Indizes (`x_index`/`y_index` aus dem `"joysticks"`-Abschnitt, siehe Abschnitt 7) an den jeweils passenden Store-Setter koppelt:

```python
def make_joystick_widget(js: JoystickEntry, on_change_x, on_change_y) -> QWidget:
    box = QGroupBox(js.name)
    layout = QVBoxLayout(box)
    jw = JoystickWidget(
        x_range=js.x_range, y_range=js.y_range,
        return_to_center=js.return_to_center, size_px=200,
    )
    jw.on_change = lambda x, y: (on_change_x(x), on_change_y(y))
    layout.addWidget(jw, alignment=Qt.AlignmentFlag.AlignCenter)
    return box
```

#### 9.3.5 Zusammenbau: Dispatch-Tabelle + Skip-Logik für Joystick-Indizes

Wichtig: Die beiden Float-Indizes, die ein Joystick zusammenfasst (`x_index`/`y_index`), tauchen **auch einzeln** in `config.floats`/`config.fast_floats` auf (nötig, damit die 50/50/5-Zählung vollständig bleibt, siehe Abschnitt 7). Diese Einzel-Einträge dürfen aber **nicht zusätzlich** als Slider/Number gerendert werden — der Bau-Loop muss sie überspringen, weil sie bereits über das Joystick-Widget abgedeckt sind:

```python
_WIDGET_FACTORIES = {
    "slider": make_slider_widget,
    "toggle": make_toggle_widget,
    "button": make_button_widget,
    "text":   make_text_widget,
    "number": make_number_widget,   # QDoubleSpinBox, Plan v1 Abschnitt 8.2 — unverändert
}

def _build_group(entries: list[ParamEntry], joysticks: list["JoystickEntry"],
                  source: str, on_change_float, on_change_bool) -> QWidget:
    joystick_indices = {
        idx for js in joysticks if js.source == source
        for idx in (js.x_index, js.y_index)
    }

    box = QWidget()
    layout = QVBoxLayout(box)

    # Joysticks zuerst rendern (oben in der Gruppe)
    for js in joysticks:
        if js.source != source:
            continue
        layout.addWidget(make_joystick_widget(
            js,
            on_change_x=lambda v, i=js.x_index: on_change_float(i, v),
            on_change_y=lambda v, i=js.y_index: on_change_float(i, v),
        ))

    # Restliche Einträge — Joystick-Indizes werden übersprungen (s.o.)
    for e in entries:
        if e.index in joystick_indices:
            continue
        is_bool = e.widget in ("toggle", "button")
        factory = _WIDGET_FACTORIES[e.widget]
        cb = (lambda v, i=e.index: on_change_bool(i, v)) if is_bool \
             else (lambda v, i=e.index: on_change_float(i, v))
        layout.addWidget(factory(e, cb))

    return box
```

Aufruf in `_build_ui()`:

```python
def _build_ui(self) -> None:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)

    content = QWidget()
    root = QVBoxLayout(content)

    fast_box = _build_group(self._config.fast_floats, self._config.joysticks,
                             "fast", self._store.set_fast_float, None)
    fast_group = QGroupBox("⚡ Echtzeit-Steuerung (100 Hz)")
    QVBoxLayout(fast_group).addWidget(fast_box)
    root.addWidget(fast_group)

    slow_floats = _build_group(self._config.floats, self._config.joysticks,
                                "slow", self._store.set_float, None)
    root.addWidget(_titled(slow_floats, "Parameter (Floats, 2 Hz)"))

    slow_bools = _build_group(self._config.bools, [], "slow",
                               None, self._store.set_bool)
    root.addWidget(_titled(slow_bools, "Schalter (Bools, 2 Hz)"))

    scroll.setWidget(content)
    QVBoxLayout(self).addWidget(scroll)
```

(`_titled()` eine kleine Hilfsfunktion, die ein Widget in eine `QGroupBox` mit Titel packt — trivial, hier ausgelassen. Der `QScrollArea`-Wrapper ist bei bis zu 105 Einträgen Pflicht, siehe Plan v1 Abschnitt 8.2.)

### 9.4 Toolbar-Zeile (Status, Pause, Save)

```
[ ⚡ → Node 1 (192.168.42.11) · Slow: 2.0 Hz (1234 Pkt) · Fast: 100 Hz (61200 Pkt) ]
[ ☑ Übertragung aktiv ]   [ 💾 Speichern als Default (.h) ]
```

Wie in Plan v1: kein ACK, also zeigt die Zeile nur den eigenen Sendezustand, nicht ob der Teensy tatsächlich empfängt.

---

## 10. Phase 7 — `main_window.py`: Anbindung

### 10.1 `get_node_ip()` bereitstellen

`main_window.py` trackt bereits `self._node_ips` (aus der Telemetrie gelernt). Diese Methode neu ergänzen:

```python
def get_node_ip(self, node_id: int) -> str:
    """Liefert die aktuell bekannte IP eines Node — dynamisch gelernt aus
    dem Absender der Telemetrie-Broadcasts, mit statischem Fallback,
    solange von diesem Node noch kein Paket empfangen wurde."""
    if not hasattr(self, "_node_ips"):
        self._node_ips = {1: NODE1_IP, 2: NODE2_IP}
    default_ip = NODE1_IP if node_id == 1 else NODE2_IP
    return self._node_ips.get(node_id, default_ip)
```

(Der bestehende `hasattr`-Guard in `_poll_data()`/`_on_flash_clicked()` bleibt bestehen — hier nur zusätzlich zentral als Methode gekapselt, damit `tab_params.py` nicht auf `MainWindow`-interne Attribute direkt zugreifen muss.)

### 10.2 `ParamEditorWidget` mit der Callback-Funktion konstruieren

```python
self._tab_params = ParamEditorWidget(get_node_ip=self.get_active_node_ip)
```

### 10.3 `_on_node_toggled()` erweitern (wie in Plan v1, unverändert wichtig)

```python
def _on_node_toggled(self, btn_id: int, checked: bool) -> None:
    if not checked:
        return
    self._active_node = btn_id
    self._tab_table.clear_stats()
    self._tab_plotter.clear_buffer()
    self._tab_params.set_active_node(btn_id)     # ← neu
    self._sb.showMessage(f"Node {btn_id} aktiviert.", 2000)
```

---

## 11. Phase 8 — Tests

Erweitert gegenüber Plan v1 um den Fast-Kanal:

1. **Ohne Hardware:** `tools/param_udp_listener_sim.py` erweitern, um auf **beiden** Ports (Slow 7001/7002, Fast 7011/7012) parallel zu lauschen und Rate + letzte Werte separat auszugeben.
2. **Mit RPi Zero, ohne Teensy:** `screen /dev/ttyAMA0 1000000` (oder Logic Analyzer) — prüfen, dass 258-Byte-Slow-Pakete etwa alle 500 ms UND 28-Byte-Fast-Pakete etwa alle 10 ms auf der Leitung erscheinen, **ohne dass sich Slow- und Fast-Bytes ineinander verschachteln** (das wäre ein Hinweis, dass der Schreib-Lock aus Abschnitt 5.2 fehlt oder nicht greift).
3. **End-to-End:** Joystick in der GUI bewegen → auf dem Teensy per `Serial.printf` (USB, nicht `UART_DBG`) `debugger.getFastParam(0)`/`getFastParam(1)` alle 200 ms ausgeben → Latenz optisch/mit Stoppuhr abschätzen (Zielgröße: deutlich unter 100 ms Round-Trip-Gefühl).
4. **Save/Load:** Werte verändern → Speichern-Button → GUI komplett schließen und neu starten → prüfen, dass alle Regler/Schalter exakt wieder dort stehen, wo sie beim Speichern waren.
5. **Persistenz-Robustheit:** `param_defaults.h` von Hand mit falscher Array-Länge oder kaputtem Inhalt befüllen → GUI darf nicht abstürzen, muss auf JSON-Defaults zurückfallen (stiller Fallback ist hier bewusst gewählt, ggf. zusätzlich eine Statuszeile "⚠ param_defaults.h ungültig, JSON-Defaults verwendet" ergänzen).
6. **Watchdog:** GUI schließen bzw. "Übertragung aktiv" deaktivieren → `fastParamsAreFresh()` soll nach `PARAM_FAST_TIMEOUT_MS` (150 ms) auf `false` wechseln, `paramsAreFresh()` nach `PARAM_SLOW_TIMEOUT_MS` (1000 ms).

---

## 12. Reihenfolge der Umsetzung (aktualisiert, Phase 0 aus v1 entfällt)

1. **Phase 1** — `params.h`: neue Konstanten. `PDS.h`/`PDS.cpp`: `pollParamUart()`, Getter, Watchdogs
2. **Phase 2** — `spi_receiver.py`: zwei Downlink-Threads + Schreib-Lock, `args=(stop_event,)`-Fix
3. **Phase 3** — `config.py`: neue Konstanten (Ports, Paketgrößen, Dateipfade)
4. **Phase 4** — `param_config.json` anlegen, `param_io.py`: `load_param_config()` + Dataclasses
5. **Phase 5** — `param_io.py`: `write_param_defaults_h()` / `read_param_defaults_h()`
6. **Phase 6** — `tab_params.py` komplett neu: `ParamStore`, Widget-Factory (inkl. Fast-Gruppe), zwei Timer, Save-Button
7. **Phase 7** — `main_window.py`: `get_node_ip()`, `ParamEditorWidget`-Konstruktion, `_on_node_toggled()`-Erweiterung
8. **Phase 8** — Tests gemäß Abschnitt 11, von Simulation bis End-to-End inkl. Save/Load-Zyklus

---

## 13. Offene Punkte / Annahmen — bitte kurz gegenchecken

1. **`UART_DBG`:** In `params.h` ist nur `UART_DBG_BAUD` definiert, nicht `UART_DBG` selbst. Ich gehe davon aus, dass es ein `#define UART_DBG Serial3` (oder ähnlich) an anderer Stelle gibt, analog zum bisherigen `main.cpp`, das direkt `Serial3` verwendet hat — für den hier skizzierten Code ist das aber irrelevant, da ich durchgängig das Makro `UART_DBG` verwende, nicht die konkrete Instanz.
2. **Momentary-Button-Semantik:** Ich gehe davon aus, dass "Button" in der GUI bedeutet: Bool ist `true`, solange die Maustaste gedrückt gehalten wird, und `false` sobald losgelassen (klassisches "Kick-Trigger"-Verhalten). Falls stattdessen ein einmaliger Klick reichen soll, der bis zum nächsten Klick "hält", wäre das eher `"widget": "toggle"` — beide Varianten sind im Schema bereits vorgesehen.
3. **Ort von `param_defaults.h`:** Ich platziere sie GUI-seitig unter `rpi5_monitor/param_defaults.h`, nicht im Firmware-Ordner — Begründung in Abschnitt 8.1. Sag Bescheid, falls ihr sie stattdessen (auch) direkt im PlatformIO-`include/`-Pfad haben wollt, damit sie ohne manuelles Kopieren von der Firmware inkludierbar ist.
4. **`enum.h`:** laut dir aktuell ohne relevanten Inhalt — falls sich das ändert (z. B. benannte Kanal-Indizes für die Telemetrie), lohnt es sich, `param_config.json`-Namen später an dasselbe Schema anzulehnen, damit ihr nicht zwei Namenskonventionen parallel pflegt.
