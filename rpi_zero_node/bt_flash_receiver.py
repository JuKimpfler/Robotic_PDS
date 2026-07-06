#!/usr/bin/env python3
"""
bt_flash_receiver.py
======================
RPi-Zero-2-W-Seite des Wireless-Flash-Features (siehe Flash_Implementierung.md).

Nimmt ein .hex-Firmware-Image per Bluetooth Classic (RFCOMM/SPP) entgegen und
flasht es über den vorhandenen USB-Anschluss mit `teensy_loader_cli` auf den
angeschlossenen Teensy 4.0. Läuft als eigener systemd-Dienst
`bt-flash-receiver.service`, unabhängig vom bestehenden `uart-receiver.service`.

────────────────────────────────────────────────────────────────────────────
ABWEICHUNG VOM URSPRÜNGLICHEN PLAN (Abschnitt 5.2/5.4 in Flash_Implementierung.md)
────────────────────────────────────────────────────────────────────────────
Der Plan schlägt als einfachsten Weg vor: eigenes rohes AF_BLUETOOTH-Server-
Socket + `sdptool add --channel=4 SP` zur SDP-Registrierung.

Auf dem Ziel-Image hier — **Raspberry Pi OS Lite (Legacy, 64-bit, Bullseye-
Basis)** — ist NICHT zuverlässig garantiert, dass `sdptool` im mitgelieferten
`bluez`-Paket noch als (deprecated) Zusatztool gebaut wurde; das hängt vom
genauen Bullseye-Repo-Snapshot ab und wurde in neueren BlueZ-Versionen
zunehmend entfernt. Ein Setup-Skript, das sich darauf verlässt, würde auf
manchen Legacy-Images einfach mit "command not found" scheitern.

Deshalb wird hier direkt der "saubere" BlueZ-5-Weg aus Abschnitt 5.4
(Ansatz 2) verwendet: Registrierung als **D-Bus-Profil**
(`org.bluez.ProfileManager1.RegisterProfile`). Das hat zwei Vorteile:
  1. Hängt nur von `python3-dbus` + `python3-gi` ab — beide Pakete sind auf
     Bullseye UND Bookworm identisch verfügbar (kein sdptool-Risiko).
  2. BlueZ übernimmt SDP-Registrierung UND Verbindungsannahme komplett
     selbst und übergibt uns nur noch das fertige Socket-Filedescriptor
     (`NewConnection`). Kein eigenes `bind()`/`listen()` auf einem
     AF_BLUETOOTH-Socket nötig.

Zusätzlich wird auf `bluez-tools`/`bt-agent` verzichtet (dessen Verfügbarkeit
auf Legacy-Images ebenfalls nicht sicher ist) — stattdessen registriert dieses
Skript einen winzigen eigenen Pairing-Agent direkt über D-Bus
(`AutoAcceptAgent`), der Kopplungsanfragen automatisch bestätigt.

Kompatibilitätshinweis Python 3.9 (Standard auf Bullseye): dieses Modul nutzt
`from __future__ import annotations`, damit die modernen Typ-Hints
(z. B. `tuple[bool, str]`) nicht zur Laufzeit ausgewertet werden — das ist
auf 3.9 sonst ein `TypeError` (PEP 604 `X | Y` gibt es erst ab 3.10).
────────────────────────────────────────────────────────────────────────────

SOFTWARE-BOOTLOADER-TRIGGER (kein manueller Knopfdruck mehr nötig)
────────────────────────────────────────────────────────────────────────────
Vorher musste vor jedem Flash-Vorgang der physische Bootloader-Taster am
Teensy 4.0 gedrückt werden, weil `check_teensy_present()` nur per `lsusb`
prüfte, ob der Teensy *bereits* im HalfKay-Bootloader (16c0:0478) oder im
USB-CDC-Serial-Modus (16c0:0483) sichtbar ist — ohne aktiv etwas zu
unternehmen, wenn das nicht der Fall war.

Der Teensy 4.0 unterstützt (wie Teensy 3.x) einen Software-Reboot in den
Bootloader: Öffnet man den USB-CDC-Serial-Port, den der laufende Sketch
über den Teensyduino-USB-Typ "Serial" bereitstellt, mit der "magischen"
Baudrate 134, interpretiert die Teensyduino-USB-Stack-Firmware das als
SET_LINE_CODING-Request mit dwDTERate=134 und löst daraufhin selbst einen
Sprung in den HalfKay-Bootloader aus. Das ist exakt dieselbe Technik, die
`teensy_loader_cli -s` (soft_reboot(), siehe dessen Quellcode) und die
Arduino-IDE/Teensyduino beim automatischen Hochladen ohne Knopfdruck
verwenden — hier wird sie eigenständig vor dem eigentlichen Aufruf von
`teensy_loader_cli` durchgeführt (`trigger_bootloader_mode()`), damit
`check_teensy_present()` den Teensy zuverlässig findet, *bevor* überhaupt
FLASH_START bestätigt wird.

Voraussetzungen auf dem Pi:
  - Paket `pyserial` (z. B. `pip3 install pyserial` oder
    `apt install python3-serial`) — wird nur für den Öffnen-mit-Baudrate-134-
    Trick gebraucht, ist aber kein Hard-Requirement: ist es nicht
    installiert, fällt der Code auf das alte Verhalten (nur lsusb-Check,
    ggf. manueller Knopfdruck nötig) zurück.
  - Der Systembenutzer, unter dem `bt-flash-receiver.service` läuft, muss
    Lese-/Schreibzugriff auf `/dev/ttyACM*` haben (i. d. R. Mitgliedschaft
    in der Gruppe `dialout`: `sudo usermod -aG dialout <user>`).
  - Funktioniert nur, wenn die *aktuell auf dem Teensy laufende* Firmware
    den USB-Typ "Serial" (oder eine Kombination mit Serial, z. B.
    "Serial + MIDI") verwendet und dadurch einen CDC-ACM-Port (16c0:0483)
    öffnet. Nutzt der Sketch einen anderen USB-Typ (z. B. reines
    "Keyboard+Mouse+Joystick" ohne Serial) oder ist der Teensy abgestürzt/
    hängt, kann der Software-Trigger den Port nicht finden — dann bleibt
    der manuelle Knopfdruck als Fallback nötig, was `check_teensy_present()`
    in der Fehlermeldung entsprechend kommuniziert.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

try:
    import serial  # pyserial - fuer Software-Bootloader-Trigger (siehe Docstring oben)
    import serial.tools.list_ports as serial_list_ports
except ImportError:  # pragma: no cover - pyserial optional, siehe Docstring
    serial = None
    serial_list_ports = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
try:
    from bt_flash_protocol import Cmd, ProtocolError, recv_frame, send_frame
except ImportError:
    # Fallback: auf dem Node liegt shared/ ggf. direkt neben diesem Skript
    # (siehe setup_node.sh, kopiert beides nach /opt/power_debug_node/)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bt_flash_protocol import Cmd, ProtocolError, recv_frame, send_frame

# ─────────────────────────────────────────────────────────────── Konfiguration
NODE_ID = os.environ.get("NODE_ID", "1")
INSTALL_DIR = Path(os.environ.get("INSTALL_DIR", "/opt/power_debug_node"))
SECRET_FILE = Path(os.environ.get("BT_FLASH_SECRET_FILE", str(INSTALL_DIR / "bt_flash_secret")))
INCOMING_DIR = INSTALL_DIR / "flash_incoming"
TEENSY_LOADER = "teensy_loader_cli"
RFCOMM_CHANNEL = int(os.environ.get("BT_FLASH_CHANNEL", "4"))
SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_DBUS_PATH = "/pds/bt_flash_profile"
AGENT_DBUS_PATH = "/pds/bt_flash_agent"
TEENSY_USB_IDS = ("16c0:0483", "16c0:0478")  # HalfKay-Bootloader / Teensy CDC-Serial
TEENSY_VID = 0x16C0
TEENSY_SERIAL_PID = 0x0483    # normaler Betrieb: USB-CDC-Serial (Teensyduino USB-Typ "Serial")
TEENSY_BOOTLOADER_PID = 0x0478  # HalfKay-Bootloader
TEENSY_BOOTLOADER_USB_ID = f"{TEENSY_VID:04x}:{TEENSY_BOOTLOADER_PID:04x}"
REBOOT_MAGIC_BAUDRATE = 134   # von Teensyduino als "SET_LINE_CODING -> Reboot in Bootloader" erkannt
BOOTLOADER_WAIT_TIMEOUT_S = 6.0
BOOTLOADER_POLL_INTERVAL_S = 0.25
FLASH_TIMEOUT_S = 20
KEEP_OLD_HEX_FILES = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bt-flash-receiver")


def load_secret() -> str:
    if not SECRET_FILE.exists():
        log.error("Auth-Token-Datei fehlt: %s (wird von setup_node.sh angelegt)", SECRET_FILE)
        raise SystemExit(1)
    return SECRET_FILE.read_text(encoding="utf-8").strip()


# ───────────────────────────────────────────────────────────────── Pairing-Agent
class AutoAcceptAgent(dbus.service.Object):
    """Minimaler BlueZ-Agent (Interface org.bluez.Agent1): bestätigt Pairing-
    Anfragen automatisch, damit auf dem headless laufenden Node kein
    interaktiver Prompt nötig ist. Die eigentliche PIN-Eingabe erfolgt auf
    PC-Seite über die Windows-Bluetooth-Einstellungen."""

    AGENT_INTERFACE = "org.bluez.Agent1"

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        log.info("[Agent] Release")

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        log.info("[Agent] AuthorizeService %s %s -> OK", device, uuid)

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        log.info("[Agent] RequestPinCode %s -> 0000", device)
        return "0000"

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        log.info("[Agent] RequestPasskey %s -> 0", device)
        return dbus.UInt32(0)

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        pass

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        pass

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        log.info("[Agent] RequestConfirmation %s (%06d) -> auto-bestätigt", device, passkey)

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        log.info("[Agent] RequestAuthorization %s -> auto-bestätigt", device)

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        log.info("[Agent] Cancel")


def register_agent(bus: dbus.SystemBus) -> None:
    AutoAcceptAgent(bus, AGENT_DBUS_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
    manager.RegisterAgent(AGENT_DBUS_PATH, "NoInputNoOutput")
    manager.RequestDefaultAgent(AGENT_DBUS_PATH)
    log.info("Pairing-Agent registriert (NoInputNoOutput, Auto-Accept)")


def configure_adapter(bus: dbus.SystemBus) -> None:
    """Setzt Alias, Powered/Discoverable/Pairable über die hci0-Adapter-Properties."""
    props = dbus.Interface(
        bus.get_object("org.bluez", "/org/bluez/hci0"), "org.freedesktop.DBus.Properties"
    )
    alias = f"PDS-Node{NODE_ID}-BT"
    for prop, value in (
        ("Powered", True),
        ("Pairable", True),
        ("Discoverable", True),
        ("Alias", alias),
    ):
        try:
            props.Set("org.bluez.Adapter1", prop, value)
        except dbus.exceptions.DBusException as exc:
            log.warning("Konnte Adapter-Property %s nicht setzen: %s", prop, exc)
    log.info("Bluetooth-Adapter konfiguriert (Alias=%s, discoverable/pairable=on)", alias)


# ───────────────────────────────────────────────────────────────────── SPP-Profil
class FlashProfile(dbus.service.Object):
    PROFILE_INTERFACE = "org.bluez.Profile1"

    @dbus.service.method(PROFILE_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        log.info("[Profile] Release")

    @dbus.service.method(PROFILE_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        log.info("[Profile] Cancel")

    @dbus.service.method(PROFILE_INTERFACE, in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        raw_fd = fd.take()
        log.info("[Profile] Neue Verbindung: %s (fd=%d)", path, raw_fd)
        threading.Thread(
            target=_handle_client_safe, args=(raw_fd, str(path)), daemon=True, name="bt-flash-client"
        ).start()


def register_profile(bus: dbus.SystemBus) -> None:
    FlashProfile(bus, PROFILE_DBUS_PATH)
    opts = {
        "Name": "PDS Flash Channel",
        "Role": "server",
        "Channel": dbus.UInt16(RFCOMM_CHANNEL),
        "RequireAuthentication": dbus.Boolean(False),
        "RequireAuthorization": dbus.Boolean(False),
        "AutoConnect": dbus.Boolean(True),
    }
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
    manager.RegisterProfile(PROFILE_DBUS_PATH, SPP_UUID, opts)
    log.info("SPP-Profil registriert (Kanal %d, UUID %s)", RFCOMM_CHANNEL, SPP_UUID)


# ──────────────────────────────────────────────────────────────── Verbindungslogik
def _handle_client_safe(raw_fd: int, peer_path: str) -> None:
    try:
        handle_client(raw_fd, peer_path)
    except Exception:  # noqa: BLE001 - Verbindung darf den Dienst nie crashen
        log.exception("Unerwarteter Fehler bei Verbindung %s", peer_path)


def handle_client(raw_fd: int, peer_path: str) -> None:
    sock = socket.fromfd(raw_fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    os.close(raw_fd)  # fromfd() dupliziert den fd, Original schließen
    secret = load_secret()

    try:
        sock.settimeout(10.0)

        # --- HELLO / Auth ----------------------------------------------------
        cmd, payload = recv_frame(sock)
        token_ok = cmd == Cmd.HELLO and payload.decode("utf-8", "replace") == secret
        send_frame(sock, Cmd.HELLO_ACK, json.dumps(
            {"ok": token_ok, "node_id": NODE_ID, "msg": "" if token_ok else "Auth fehlgeschlagen"}
        ).encode("utf-8"))
        if not token_ok:
            log.warning("Auth fehlgeschlagen von %s", peer_path)
            return
        log.info("Auth erfolgreich von %s", peer_path)

        # --- FLASH_START -------------------------------------------------------
        cmd, payload = recv_frame(sock)
        if cmd != Cmd.FLASH_START:
            log.warning("Unerwartetes Kommando statt FLASH_START: %s", cmd)
            return
        meta = json.loads(payload.decode("utf-8"))
        filename = meta["filename"]
        size = int(meta["size"])
        sha256_expected = meta["sha256"]

        teensy_ok, teensy_msg = check_teensy_present()
        send_frame(sock, Cmd.FLASH_START_ACK, json.dumps({"ok": teensy_ok, "msg": teensy_msg}).encode("utf-8"))
        if not teensy_ok:
            log.warning("FLASH_START abgelehnt: %s", teensy_msg)
            return

        # --- Datei-Empfang -------------------------------------------------------
        INCOMING_DIR.mkdir(parents=True, exist_ok=True)
        target_path = INCOMING_DIR / f"{int(time.time())}_{Path(filename).name}"
        hasher = hashlib.sha256()
        received = 0
        sock.settimeout(20.0)

        with open(target_path, "wb") as f:
            while received < size:
                cmd, payload = recv_frame(sock)
                if cmd == Cmd.FLASH_END:
                    break
                if cmd != Cmd.DATA_CHUNK:
                    continue
                f.write(payload)
                hasher.update(payload)
                received += len(payload)
                send_frame(sock, Cmd.DATA_CHUNK_ACK,
                           json.dumps({"ok": True, "received": received}).encode("utf-8"))

        if received >= size:
            try:
                sock.settimeout(5.0)
                recv_frame(sock)  # abschließendes FLASH_END, falls noch ausstehend
            except (ProtocolError, socket.timeout, OSError):
                pass

        if hasher.hexdigest() != sha256_expected:
            msg = "SHA-256 stimmt nicht überein — Datei verworfen"
            log.error("%s (%s)", msg, target_path)
            send_frame(sock, Cmd.FLASH_RESULT,
                       json.dumps({"ok": False, "returncode": -1, "output": msg}).encode("utf-8"))
            target_path.unlink(missing_ok=True)
            return

        log.info("Datei vollständig empfangen und verifiziert: %s (%d Bytes)", target_path, received)

        # --- Flashen ---------------------------------------------------------------
        ok, returncode, output = flash_teensy(target_path)
        send_frame(sock, Cmd.FLASH_RESULT, json.dumps(
            {"ok": ok, "returncode": returncode, "output": output[-2000:]}
        ).encode("utf-8"))
        if ok:
            log.info("Flash erfolgreich: %s", target_path)
        else:
            log.error("Flash fehlgeschlagen (Code %s): %s", returncode, output[-500:])
        cleanup_old_files()

    except (ProtocolError, OSError, socket.timeout) as exc:
        log.error("Verbindungsfehler mit %s: %s", peer_path, exc)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _lsusb_output() -> str | None:
    try:
        return subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("lsusb fehlgeschlagen: %s", exc)
        return None


def _usb_id_present(vid_pid: str) -> bool:
    out = _lsusb_output()
    return bool(out) and vid_pid in out


def _find_teensy_serial_port() -> str | None:
    """Sucht den /dev/ttyACM*-Port des Teensy im normalen CDC-Serial-Betrieb
    (VID/PID 16c0:0483) über pyserial. Liefert None, wenn pyserial fehlt oder
    kein passender Port gefunden wurde."""
    if serial_list_ports is None:
        return None
    try:
        for port in serial_list_ports.comports():
            if port.vid == TEENSY_VID and port.pid == TEENSY_SERIAL_PID:
                return port.device
    except OSError as exc:
        log.warning("Fehler beim Auflisten der seriellen Ports: %s", exc)
    return None


def trigger_bootloader_mode() -> tuple[bool, str]:
    """Versetzt den Teensy 4.0 per Software in den HalfKay-Bootloader, ohne
    dass der Bootloader-Taster gedrückt werden muss.

    Technik: Der laufende Sketch stellt (sofern er den Teensyduino-USB-Typ
    "Serial" nutzt) einen USB-CDC-ACM-Port bereit (VID:PID 16c0:0483). Öffnet
    man diesen Port mit der "magischen" Baudrate 134, interpretiert die
    Teensyduino-USB-Stack-Firmware das SET_LINE_CODING-Kommando als Befehl,
    in den Bootloader zu springen — dieselbe Technik, die intern auch
    `teensy_loader_cli -s` (soft_reboot()) und die Arduino-IDE beim
    automatischen Hochladen verwenden.

    Rückgabe: (ok, meldung). ok=True bedeutet, der Teensy ist (jetzt) im
    Bootloader-Modus (16c0:0478) und `teensy_loader_cli` kann ihn ansprechen.
    """
    if _usb_id_present(TEENSY_BOOTLOADER_USB_ID):
        return True, "Teensy ist bereits im Bootloader-Modus"

    if serial is None:
        return False, (
            "pyserial nicht installiert - Software-Reboot in den Bootloader "
            "nicht möglich (Abhilfe: 'pip3 install pyserial' auf dem Node, "
            "siehe README)"
        )

    port = _find_teensy_serial_port()
    if not port:
        return False, (
            "Kein Teensy-CDC-Serial-Port gefunden - entweder ist der Teensy "
            "nicht angeschlossen, oder die aktuell laufende Firmware nutzt "
            "keinen USB-Typ mit 'Serial'"
        )

    try:
        log.info("Löse Software-Reboot in Bootloader über %s aus (Baudrate=%d) ...",
                  port, REBOOT_MAGIC_BAUDRATE)
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = REBOOT_MAGIC_BAUDRATE
        ser.open()
        time.sleep(0.1)
        ser.close()
    except (OSError, serial.SerialException) as exc:
        return False, f"Fehler beim Software-Reboot über {port}: {exc}"

    deadline = time.monotonic() + BOOTLOADER_WAIT_TIMEOUT_S
    while time.monotonic() < deadline:
        if _usb_id_present(TEENSY_BOOTLOADER_USB_ID):
            log.info("Teensy erfolgreich per Software in den Bootloader versetzt")
            return True, "Teensy per Software erfolgreich in Bootloader-Modus versetzt"
        time.sleep(BOOTLOADER_POLL_INTERVAL_S)

    return False, (
        f"Software-Reboot über {port} ausgelöst, aber Bootloader-Modus "
        f"({TEENSY_BOOTLOADER_USB_ID}) nicht innerhalb von "
        f"{BOOTLOADER_WAIT_TIMEOUT_S:.0f}s erkannt"
    )


def check_teensy_present() -> tuple[bool, str]:
    ok, msg = trigger_bootloader_mode()
    if ok:
        return True, msg

    # Fallback: falls trigger_bootloader_mode() aus anderen Gründen (z. B.
    # pyserial fehlt) nichts tun konnte, aber der Bootloader-Taster bereits
    # manuell gedrückt wurde, ist der Teensy evtl. trotzdem schon bereit.
    out = _lsusb_output()
    if out is None:
        return False, f"lsusb fehlgeschlagen ({msg})"
    if any(vid_pid in out for vid_pid in TEENSY_USB_IDS):
        return True, "Teensy per USB gefunden"
    return False, f"Kein Teensy per USB gefunden ({msg})"


def flash_teensy(hex_path: Path) -> tuple[bool, int, str]:
    cmd = [TEENSY_LOADER, "--mcu=TEENSY40", "-w", "-v", "-s", str(hex_path)]
    log.info("Flash-Befehl: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=FLASH_TIMEOUT_S)
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, proc.returncode, output
    except subprocess.TimeoutExpired as exc:
        return False, -1, f"Timeout beim Flashen nach {FLASH_TIMEOUT_S}s: {exc}"
    except OSError as exc:
        return False, -1, f"{TEENSY_LOADER} konnte nicht gestartet werden: {exc}"


def cleanup_old_files(keep: int = KEEP_OLD_HEX_FILES) -> None:
    files = sorted(INCOMING_DIR.glob("*.hex"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────────────────── Main
def main() -> None:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    configure_adapter(bus)
    register_agent(bus)
    register_profile(bus)
    log.info("bt-flash-receiver bereit (Node %s, RFCOMM-Kanal %d)", NODE_ID, RFCOMM_CHANNEL)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()