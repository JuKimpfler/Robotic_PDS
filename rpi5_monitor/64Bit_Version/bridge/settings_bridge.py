"""
bridge/settings_bridge.py — Oberflächen-Einstellungen (dauerhaft gespeichert)
==============================================================================
Alles, was der BEDIENER einstellt und was einen Neustart überleben soll:
Farbschema, Schriftgröße, Kiosk-Modus, Tastatursteuerung, Akku-Warnung.

Bewusst getrennt von der Konfiguration, die der Teensy liefert (siehe
runtime_config.py): das eine gehört zum Roboter, das andere zum Gerät, auf
dem die Oberfläche läuft. Wer sein Tablet auf große Schrift stellt, will das
nicht beim nächsten Firmware-Update wieder verlieren.

Geschrieben wird verzögert (siehe _SAVE_DELAY_MS): ein Schieberegler für die
Schriftgröße löst sonst bei jedem Pixel einen Dateizugriff aus.
"""
from __future__ import annotations

import json
import logging
import os

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtProperty, pyqtSlot

from config import UI_SETTINGS_PATH, BATTERY_ALARM_DEFAULTS
from bridge.utils import safe_slot

log = logging.getLogger("bridge.settings")

_SAVE_DELAY_MS = 800

_DEFAULTS = {
    "dark": True,
    "fontScale": 1.0,
    "kiosk": False,
    "keyboardControl": True,
    "startTab": 0,
    "autoApplyTeensyConfig": True,
    "battery": dict(BATTERY_ALARM_DEFAULTS),
}


class SettingsBridge(QObject):
    themeChanged    = pyqtSignal()
    kioskChanged    = pyqtSignal()
    settingsChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data = dict(_DEFAULTS)
        self._data["battery"] = dict(BATTERY_ALARM_DEFAULTS)
        self._load()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save)

    # ── Laden / Speichern ─────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            raw = json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return                      # normaler Zustand beim ersten Start
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar (%s) — Standardwerte aktiv.", UI_SETTINGS_PATH, exc)
            return
        if not isinstance(raw, dict):
            return
        for key, default in _DEFAULTS.items():
            if key not in raw:
                continue
            value = raw[key]
            if isinstance(default, bool):
                self._data[key] = bool(value)
            elif isinstance(default, float):
                try:
                    self._data[key] = float(value)
                except (TypeError, ValueError):
                    pass
            elif isinstance(default, int):
                try:
                    self._data[key] = int(value)
                except (TypeError, ValueError):
                    pass
            elif isinstance(default, dict) and isinstance(value, dict):
                merged = dict(default)
                merged.update(value)
                self._data[key] = merged
        log.info("Oberflächen-Einstellungen aus %s geladen.", UI_SETTINGS_PATH)

    @safe_slot
    def _save(self) -> None:
        tmp = UI_SETTINGS_PATH.with_suffix(".json.tmp")
        try:
            UI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False),
                            encoding="utf-8")
            os.replace(tmp, UI_SETTINGS_PATH)
        except OSError as exc:
            log.error("Einstellungen konnten nicht gespeichert werden: %s", exc)

    def _touch(self) -> None:
        self._save_timer.start()
        self.settingsChanged.emit()

    def flush(self) -> None:
        """Beim Beenden sofort schreiben, statt auf den Timer zu warten."""
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save()

    # ── Farbschema / Schriftgröße (F7) ────────────────────────────────────
    @pyqtProperty(bool, notify=themeChanged)
    def dark(self):
        return self._data["dark"]

    @pyqtSlot(bool)
    def setDark(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["dark"]:
            self._data["dark"] = value
            self.themeChanged.emit()
            self._touch()

    @pyqtSlot()
    def toggleTheme(self) -> None:
        self.setDark(not self._data["dark"])

    @pyqtProperty(float, notify=themeChanged)
    def fontScale(self):
        return self._data["fontScale"]

    @pyqtSlot(float)
    def setFontScale(self, value: float) -> None:
        # Unter 0.8 wird es auf dem 13"-Touchscreen untreffbar, über 1.6
        # passen die Tabellenspalten nicht mehr nebeneinander.
        value = round(min(1.6, max(0.8, float(value))), 2)
        if value != self._data["fontScale"]:
            self._data["fontScale"] = value
            self.themeChanged.emit()
            self._touch()

    # ── Kiosk-/Sperrmodus ─────────────────────────────────────────────────
    @pyqtProperty(bool, notify=kioskChanged)
    def kiosk(self):
        return self._data["kiosk"]

    @pyqtSlot(bool)
    def setKiosk(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["kiosk"]:
            self._data["kiosk"] = value
            self.kioskChanged.emit()
            self._touch()

    # ── Tastatursteuerung (B4) ────────────────────────────────────────────
    @pyqtProperty(bool, notify=settingsChanged)
    def keyboardControl(self):
        return self._data["keyboardControl"]

    @pyqtSlot(bool)
    def setKeyboardControl(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["keyboardControl"]:
            self._data["keyboardControl"] = value
            self._touch()

    # ── Teensy-Konfiguration automatisch übernehmen ───────────────────────
    @pyqtProperty(bool, notify=settingsChanged)
    def autoApplyTeensyConfig(self):
        return self._data["autoApplyTeensyConfig"]

    @pyqtSlot(bool)
    def setAutoApplyTeensyConfig(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["autoApplyTeensyConfig"]:
            self._data["autoApplyTeensyConfig"] = value
            self._touch()

    # ── Akku-Warnung (C3) — hier nur die Persistenz ───────────────────────
    def battery(self) -> dict:
        return dict(self._data["battery"])

    def store_battery(self, cfg: dict) -> None:
        if cfg != self._data["battery"]:
            self._data["battery"] = dict(cfg)
            self._touch()
