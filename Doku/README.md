# Dokumentation

## Zum Nachschlagen (aktueller Stand)

| Dokument | Wofür |
|---|---|
| [Setup_und_Update.md](Setup_und_Update.md) | Haupt-Pi und Nodes einrichten, aktualisieren, zurückrollen, Fehlersuche |
| [Architektur.md](Architektur.md) | Wie Teensy, Node und GUI miteinander reden: Ports, Pakete, Wire-Format |
| [../FEATURES.md](../FEATURES.md) | Vollständige Funktionsübersicht |
| [../teensy_firmware/README.md](../teensy_firmware/README.md) | Teensy-Bibliothek: API, Build-Flags, Diagnose |
| [../rpi5_monitor/64Bit_Version/README_QML.md](../rpi5_monitor/64Bit_Version/README_QML.md) | Die Oberfläche: Dateien, Tabs, Editor, `settings.json`, Plotter-Betriebsarten |
| [../pc_flash_tool/README.md](../pc_flash_tool/README.md) | Firmware per Bluetooth vom PC flashen |
| [Teensy_Einstellungen.md](Teensy_Einstellungen.md) | Die Oberfläche aus der Firmware heraus einstellen |
| [PS4_Controller_Implementierung.md](PS4_Controller_Implementierung.md) | Controller-Belegung, Kalibrierung, `controller_config.json` |
| [Blockierfreiheit.md](Blockierfreiheit.md) | Warum `PDS.update()` den Roboter nie aufhält |
| [Latenz_Fernsteuerung.md](Latenz_Fernsteuerung.md) | Woraus die Reaktionszeit der Fernsteuerung besteht, wie man sie misst |

## Entwurfs- und Planungsdokumente

Sie halten fest, **warum** etwas so gebaut wurde. Einzelheiten können sich
seither geändert haben — maßgeblich ist der Code und die Liste oben.

| Dokument | Thema |
|---|---|
| [Param_Implementierung.md](Param_Implementierung.md) | Parameter-Downlink (Slow/Fast-Kanal) |
| [Kanalnamen_Implementierung.md](Kanalnamen_Implementierung.md) | Namens-/Overlay-Deskriptor vom Teensy |
| [Flash_Implementierung.md](Flash_Implementierung.md) | Firmware per Bluetooth |
| [Plotter_Ressourcen_Plan.md](Plotter_Ressourcen_Plan.md) | Rechenlast des Plotters: Messungen, Maßnahmen, Ergebnis |
| [reviews/](reviews/) | Protokolle früherer Code-Durchsichten |

Gemeldete und behobene Fehler: [../BUG.md](../BUG.md).
Änderungsverlauf: [../CHANGELOG.md](../CHANGELOG.md).
