# Wireless Flashing — PC-Seite (`bt_flash_sender.py`)

Sendet ein kompiliertes Teensy-4.0-Firmware-Image (`.hex`) per Bluetooth Classic
(RFCOMM/SPP) an einen oder beide RPi Zero 2 W Nodes. Der Node flasht die Datei
dann selbstständig über USB auf den angeschlossenen Teensy 4.0
(`teensy_loader_cli`). Details/Architektur: siehe `Flash_Implementierung.md`
im Projekt-Root.

## Voraussetzungen

- Windows 10/11, Python 3.9 oder neuer (`python --version`).
- Kein zusätzliches Paket nötig — nur die Python-Standardbibliothek
  (`socket.AF_BLUETOOTH` / `BTPROTO_RFCOMM` ist seit Python 3.9 nativ unter
  Windows verfügbar).
- Die Datei `../../shared/bt_flash_protocol.py` muss vorhanden bleiben
  (relativer Import, zwei Ordner über diesem Skript).
- Ein oder beide RPi Zero 2 W Nodes wurden bereits mit dem aktualisierten
  `setup_node.sh` eingerichtet (dabei wird BT aktiviert und der Auth-Token
  ausgegeben).

## Einmaliges Koppeln (Pairing) mit Windows

Bluetooth-Klassik verlangt unter Windows, dass das Zielgerät **vor** der
Verbindungsaufnahme per Code bereits über die Windows-Bluetooth-Einstellungen
gekoppelt wurde:

1. **Einstellungen → Bluetooth & Geräte → Gerät hinzufügen → Bluetooth.**
2. Windows zeigt `PDS-Node1-BT` bzw. `PDS-Node2-BT` in der Liste
   (der Node muss dafür eingeschaltet sein und discoverable — das ist nach
   `setup_node.sh` + Reboot automatisch der Fall).
3. Gerät auswählen, PIN eingeben (wird von `setup_node.sh` auf dem Pi
   ausgegeben, Standard-Fallback ist `0000`).
4. Nach erfolgreichem Pairing: **Einstellungen → Bluetooth & Geräte → Geräte
   → PDS-Node1-BT → Eigenschaften** öffnen, dort die Bluetooth-**MAC-Adresse**
   ablesen (Format `AA:BB:CC:DD:EE:FF`).
5. MAC-Adresse, den vom Setup-Skript ausgegebenen **Auth-Token** und die
   Kanalnummer (Standard: `4`) in `bt_targets.json` eintragen.

Das Pairing muss nur einmal pro PC/Node-Paar durchgeführt werden — danach
verbindet sich `bt_flash_sender.py` per bekannter MAC-Adresse jederzeit neu.

## Benutzung

### Option A: Grafische Oberfläche (empfohlen für den schnellen Einsatz)

```cmd
python bt_flash_sender_gui.py
```

- **1. Firmware-Datei (.hex)**: über "Durchsuchen ..." auswählen.
- **2. Empfänger auswählen**: Checkboxen für `node1` / `node2` (Namen und
  MAC-Adressen werden automatisch aus `bt_targets.json` geladen) — beliebig
  einzeln oder zusammen anhaken.
- **Flashen**-Button startet den Vorgang im Hintergrund; Fortschrittsbalken
  je Node und ein Log-Fenster zeigen den Verlauf live an.
- Existiert `bt_targets.json` noch nicht, legt die GUI beim ersten Start
  automatisch eine Vorlage an und weist darauf hin, die Werte einzutragen.

### Option B: Kommandozeile

```cmd
:: Beide Nodes nacheinander flashen
python bt_flash_sender.py C:\Pfad\zu\firmware.hex --target both

:: Nur Node 1
python bt_flash_sender.py firmware.hex --target node1

:: Andere Konfigurationsdatei verwenden
python bt_flash_sender.py firmware.hex --target both --targets-file meine_targets.json
```

Die `.hex`-Datei entsteht z. B. über PlatformIO aus `teensy_firmware/`
(`pio run` erzeugt sie unter `.pio/build/teensy40/firmware.hex`).

Ausgabe zeigt Fortschritt in Prozent je Node und am Ende eine Zusammenfassung.
**Exit-Code** `0` = alle gewählten Ziele erfolgreich, `1` = mindestens ein
Ziel fehlgeschlagen, `2` = Konfigurationsfehler (z. B. `bt_targets.json`
fehlt/unvollständig) — nützlich, um das Tool aus einem Build-Skript heraus
aufzurufen.

## Fehlerbehebung

| Symptom | Wahrscheinliche Ursache |
|---|---|
| `[FEHLER] Verbindung zu nodeX (...) fehlgeschlagen` | Node nicht gepaart, ausgeschaltet, außer Reichweite, oder Bluetooth-Dienst auf dem Pi nicht aktiv |
| `Auth/Handshake fehlgeschlagen` | Falscher Token in `bt_targets.json` (mit dem Wert aus `setup_node.sh`-Ausgabe abgleichen) |
| `FLASH_START wurde abgelehnt` — "Kein Teensy gefunden" | Teensy 4.0 nicht per USB am Node angeschlossen |
| Übertragung bricht mitten in einem Chunk ab | Bluetooth-Reichweite verlassen — Vorgang einfach erneut starten |
| `CRC32 ... stimmt nicht überein` (auf Pi-Seite in `journalctl`) | Störung während Übertragung — erneut versuchen, ggf. näher an den Node |
