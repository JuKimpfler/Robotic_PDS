#!/usr/bin/env python3
"""
tools/desc_json_check.py — den Deskriptor des Teensy WIRKLICH ausfuehren
==========================================================================
Uebersetzt teensy_firmware/src/PDS.cpp mit einer minimalen Arduino-Attrappe
(tools/hostsim/) fuer den PC, laesst die Bibliothek ihren Namens-/Overlay-
Deskriptor senden und prueft das Ergebnis mit einem echten JSON-Parser.

WARUM: Der Deskriptor wird von Hand in einen Zeichenpuffer geschrieben — mit
Ueberlaufreserve, abgeschnittenen Listen und escapten Zeichenketten. Ein
Komma zu viel oder eine fehlende Klammer macht ihn unlesbar, und in der GUI
sieht man davon nur "die Kanalnamen kommen nicht an". Genau dieser Fehler ist
in diesem Projekt schon einmal aufgetreten. Ein Uebersetzungslauf allein
findet ihn nicht — er muss ausgefuehrt werden.

Ohne C++-Compiler beendet sich das Skript mit Exit-Code 0 und einem Hinweis
(SKIP), damit es auf einem Entwicklungsrechner ohne Compiler nicht stoert.
In der CI ist g++ vorhanden, dort laeuft die Pruefung wirklich.

Auf einem Rechner ohne Compiler (typisch: Windows) genuegt:
    pip install ziglang
    CXX="python -m ziglang c++" python tools/desc_json_check.py

Aufruf:
    python tools/desc_json_check.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTSIM = ROOT / "tools" / "hostsim"
SRC = ROOT / "teensy_firmware" / "src"

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [ ok ] {name}")
    else:
        print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")
        _failures.append(name)


def _find_compiler() -> list[str] | None:
    """Womit wird uebersetzt? Gibt den Aufruf als Argumentliste zurueck.

    CXX hat Vorrang. Ohne diese Moeglichkeit liess sich der Test auf einem
    Rechner ohne g++ gar nicht ausfuehren — und genau dort ist er am
    wertvollsten, weil er sonst erst in der CI zum ersten Mal laeuft.
    Der Wert darf mehrere Woerter haben, damit auch Aufrufe wie
    `python -m ziglang c++` oder `zig c++` funktionieren.
    """
    env = os.environ.get("CXX", "").strip()
    if env:
        return env.split()
    found = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
    return [found] if found else None


def build_and_run() -> str | None:
    cxx = _find_compiler()
    if cxx is None:
        print("SKIP: kein C++-Compiler gefunden — Deskriptor-Test uebersprungen.")
        print("      Ohne g++/clang++ im Pfad hilft z. B.:")
        print('        pip install ziglang')
        print('        CXX="python -m ziglang c++" python tools/desc_json_check.py')
        return None

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # ── Alle Quellen in EIN Verzeichnis kopieren ──────────────────────
        #  Frueher stand hier -I hostsim -I src mit dem Kommentar "hostsim MUSS
        #  vor src stehen". Das war falsch: bei einem Include in
        #  Anfuehrungszeichen sucht der Praeprozessor ZUERST im Verzeichnis der
        #  einbindenden Datei. PDS.cpp liegt in src/, also gewann immer
        #  src/channel_config.h -- und das ist die ausgelieferte Vorlage, in der
        #  alles auskommentiert ist. Der Test lief damit gegen eine LEERE
        #  Konfiguration und pruefte faktisch nichts von dem, was er zu pruefen
        #  vorgibt. Mit allen Dateien im selben Verzeichnis greift die
        #  Testkonfiguration, ohne dass PDS.cpp etwas davon wissen muss.
        for name in ("PDS.cpp", "PDS.h", "params.h"):
            shutil.copy2(SRC / name, work / name)
        for name in ("channel_config.h", "Arduino.h", "elapsedMillis.h",
                     "desc_dump.cpp"):
            shutil.copy2(HOSTSIM / name, work / name)

        exe = work / ("desc_dump.exe" if sys.platform == "win32" else "desc_dump")
        cmd = [
            *cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter",
            # __DATE__/__TIME__ stehen absichtlich in der Firmware: sie sind
            # der Build-Stempel, den der Deskriptor als "build" meldet. Zig
            # macht daraus per Default einen FEHLER (-Wdate-time), womit der
            # im Kopf dieser Datei empfohlene Ersatz-Compiler gar nicht erst
            # uebersetzt hat. g++/clang++ ignorieren die Option.
            "-Wno-date-time",
            f"-I{work}",
            str(work / "desc_dump.cpp"), str(work / "PDS.cpp"),
            "-o", str(exe),
        ]
        # encoding ausdruecklich: der Deskriptor ist UTF-8, und mit
        # text=True wuerde subprocess die Locale-Kodierung nehmen --
        # auf Windows cp1252. Aus "Groesse_Oe" wurde damit Zeichensalat,
        # und der Test meldete einen Fehler im Escaping, den es nicht gab.
        proc = subprocess.run(cmd, capture_output=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            print("  [FAIL] Uebersetzung fehlgeschlagen:")
            print(proc.stderr[:4000])
            _failures.append("Uebersetzung")
            return None
        if proc.stderr.strip():
            # -Wall/-Wextra-Warnungen sind hier ein echtes Signal: derselbe
            # Code laeuft auf dem Roboter.
            print("  [FAIL] Compiler-Warnungen:")
            print(proc.stderr[:4000])
            _failures.append("Compiler-Warnungen")

        run = subprocess.run([str(exe)], capture_output=True,
                             encoding="utf-8", errors="replace",
                             timeout=60)
        if run.returncode != 0:
            print("  [FAIL] Ausfuehrung fehlgeschlagen:")
            print(run.stderr[:2000])
            _failures.append("Ausfuehrung")
            return None
        return run.stdout


def main() -> int:
    print("Deskriptor-Test (PDS.cpp auf dem Host ausgefuehrt)")
    out = build_and_run()
    if out is None:
        return 1 if _failures else 0

    fields: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        fields[key] = value

    for key in ("CHUNKS", "DESCRIPTORS", "JSONLEN", "OVERFLOW", "EVENTS",
                "ACKS", "TELEMETRY", "USED", "JSON"):
        if key not in fields:
            check(f"Ausgabefeld {key} vorhanden", False, out[:300])
            return 1

    raw = fields["JSON"]
    check("Deskriptor wurde vollstaendig gesendet", int(fields["CHUNKS"]) > 0)
    check("Deskriptor passt in den Puffer (kein Ueberlauf)",
          fields["OVERFLOW"] == "0",
          "PDS_DESC_BUF_BYTES erhoehen oder channel_config.h kuerzen")
    check("JSON-Laenge stimmt mit den Chunks ueberein",
          int(fields["JSONLEN"]) == len(raw.encode("utf-8")),
          f'{fields["JSONLEN"]} vs. {len(raw.encode("utf-8"))}')
    check("Deskriptor wird in Ruhe automatisch wiederholt",
          int(fields["DESCRIPTORS"]) >= 2, fields["DESCRIPTORS"])
    check("Ereignisse und Logzeilen wurden gesendet",
          int(fields["EVENTS"]) == 4, fields["EVENTS"])
    check("Parameter-Rueckmeldung laeuft mit 2 Hz",
          20 <= int(fields["ACKS"]) <= 28, fields["ACKS"])
    check("Telemetrie laeuft mit 100 Hz weiter",
          1100 <= int(fields["TELEMETRY"]) <= 1200, fields["TELEMETRY"])

    # ── Der eigentliche Punkt: ist es gueltiges JSON? ─────────────────────
    try:
        data = json.loads(raw)
        check("Deskriptor ist gueltiges JSON", True)
    except ValueError as exc:
        check("Deskriptor ist gueltiges JSON", False, str(exc))
        print("\n--- Anfang des JSON ---")
        print(raw[:600])
        print("--- Ende ---")
        print(raw[-400:])
        return 1

    check("oberste Ebene ist ein Objekt", isinstance(data, dict))

    # Lief der Test ueberhaupt gegen die Testkonfiguration? Ohne diese Frage
    # sah ein Lauf gegen die leere Vorlage aus wie ein Haufen einzelner
    # Fehlschlaege statt wie das eine Problem, das es ist.
    used_testcfg = bool(data.get("param_slow_floats")) and bool(data.get("overlays"))
    check("tools/hostsim/channel_config.h wurde benutzt", used_testcfg,
          "der Deskriptor ist leer — vermutlich wurde "
          "teensy_firmware/src/channel_config.h eingebunden (die Vorlage)")
    if not used_testcfg:
        return 1
    for key in ("meta", "channels", "units", "param_slow_floats",
                "param_slow_bools", "param_fast_floats", "param_cfg", "overlays"):
        check(f"Abschnitt '{key}' vorhanden", key in data)

    meta = data.get("meta", {})
    check("meta traegt die Firmware-Version",
          meta.get("fw") == 'Test "1.2"', repr(meta.get("fw")))
    check("meta traegt Wire-Version und Kanalzahl",
          meta.get("wire") == 2 and meta.get("channels") == 200, str(meta))

    channels = data.get("channels", {})
    check("im Sketch benannte Kanaele sind enthalten",
          "Akku_Live" in channels.values() and "Ball_X_Live" in channels.values())
    check("Kanal aus channel_config.h ist enthalten",
          channels.get("10") == "Akku_Spannung", str(channels.get("10")))
    check("fester Kanal aus bind(name, ptr, 30) sitzt auf 30",
          channels.get("30") == "Ball_X_Live", str(channels.get("30")))

    units = data.get("units", {})
    check("Einheiten kommen mit", units.get("10") == "V" and units.get("30") == "cm",
          str(units))

    # Sonderzeichen: genau hier ist das Escaping entscheidend.
    slow = data.get("param_slow_floats", {})
    check("Anfuehrungszeichen im Namen ueberleben das Escaping",
          slow.get("2") == 'Kd "quoted"', repr(slow.get("2")))
    check("Backslash im Namen ueberlebt das Escaping",
          slow.get("3") == "Pfad\\Test", repr(slow.get("3")))
    check("Umlaute ueberleben (UTF-8 unveraendert durchgereicht)",
          slow.get("4") == "Größe_Ö", repr(slow.get("4")))
    check("Steuerzeichen wird als \\u00xx kodiert",
          channels.get("12") == "Steuer\x01Zeichen", repr(channels.get("12")))

    cfg = data.get("param_cfg", {})
    for key in ("slow_floats", "slow_bools", "fast_floats", "joysticks"):
        check(f"param_cfg.{key} ist eine Liste", isinstance(cfg.get(key), list))
    sf = cfg.get("slow_floats", [])
    check("param_cfg enthaelt alle Slow-Floats", len(sf) == 5, str(len(sf)))
    if sf:
        first = sf[0]
        check("param_cfg: Bereich und Gruppe kommen mit",
              first.get("min") == 0 and first.get("max") == 10
              and first.get("g") == "Regler", str(first))
    sb = cfg.get("slow_bools", [])
    check("param_cfg: momentary wird gemeldet",
          any(e.get("m") for e in sb), str(sb))
    js = cfg.get("joysticks", [])
    check("param_cfg: Joystick kommt mit",
          len(js) == 1 and js[0].get("s") == "fast", str(js))

    overlays = data.get("overlays", [])
    types = [o.get("type") for o in overlays]
    check("Overlays: leerer Typ wird uebersprungen", "" not in types, str(types))
    check("Overlays: textgrid und bodies sind dabei",
          "textgrid" in types and "bodies" in types, str(types))
    grid = next((o for o in overlays if o.get("type") == "textgrid"), None)
    check("Overlays: extra-Text kommt unveraendert an",
          grid is not None and grid.get("extra") == "channels=0-11,20;cols=2;dx=24;dy=5",
          str(grid))

    # ── Die GUI muss daraus wirklich ihre Konfiguration bauen koennen ─────
    sys.path.insert(0, str(ROOT / "rpi5_monitor" / "64Bit_Version"))
    from channel_registry import ChannelRegistry
    import runtime_config
    import param_io

    reg = ChannelRegistry.from_json_dict(data)
    check("ChannelRegistry liest den Deskriptor", not reg.is_empty())
    check("ChannelRegistry: Einheiten", reg.channel_units.get(10) == "V")
    check("ChannelRegistry: Firmware-Text", "Test" in reg.firmware_label(),
          reg.firmware_label())

    pcfg = runtime_config.param_config_from_descriptor(reg.param_cfg)
    check("param_config wird daraus erzeugt", pcfg is not None)
    if pcfg:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "param_config.json"
            path.write_text(json.dumps(pcfg), encoding="utf-8")
            loaded = param_io.load_param_config(path)
            check("param_io akzeptiert die erzeugte Konfiguration",
                  loaded.floats[0].name == "Kp_Heading"
                  and loaded.joysticks[0].source == "fast")

    print()
    if _failures:
        print(f"{len(_failures)} Pruefung(en) FEHLGESCHLAGEN:")
        for f in _failures:
            print(f"  * {f}")
        return 1
    print("OK — der Deskriptor des Teensy ist gueltiges JSON und die GUI kann ihn lesen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
