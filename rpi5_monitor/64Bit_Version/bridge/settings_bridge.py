"""
bridge/settings_bridge.py — Oberflächen-Einstellungen (dauerhaft gespeichert)
==============================================================================
Alles, was der BEDIENER einstellt und was einen Neustart überleben soll:
Farbschema, Schriftgröße, Kiosk-Modus, Tastatursteuerung, Akku-Warnung —
und seit der Umstellung auf settings.json auch die Dinge, die vorher fest in
QML standen: alle Farben und Maße des Themes, die Fenstergröße und vor allem
die GRENZEN der Schieberegler und Drehfelder (`ranges`).

Diese Brücke ist nur noch das Fenster nach QML; wo die Werte herkommen, wie
sie geprüft und gespeichert werden und was ein Profil ist, steht in
app_settings.py.

Bewusst getrennt von der Konfiguration, die der Teensy liefert (siehe
runtime_config.py): das eine gehört zum Roboter, das andere zum Gerät, auf
dem die Oberfläche läuft. Wer sein Tablet auf große Schrift stellt, will das
nicht beim nächsten Firmware-Update wieder verlieren.

Geschrieben wird verzögert (siehe _SAVE_DELAY_MS): ein Schieberegler für die
Schriftgröße löst sonst bei jedem Pixel einen Dateizugriff aus.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtProperty, pyqtSlot

import app_settings
from bridge.utils import safe_slot

log = logging.getLogger("bridge.settings")

_SAVE_DELAY_MS = 800


class SettingsBridge(QObject):
    themeChanged    = pyqtSignal()
    kioskChanged    = pyqtSignal()
    settingsChanged = pyqtSignal()
    profilesChanged = pyqtSignal()
    # Ein KOMPLETTER Einstellungssatz wurde uebernommen (Profil geladen,
    # zurueckgesetzt). Eigenes Signal statt settingsChanged, damit AppBridge
    # die Akku-Warnung genau dann neu einliest — und nicht bei jedem
    # Schalterklick, was ein Hin und Her mit DiagBridge waere.
    settingsReplaced = pyqtSignal()
    # Meldung für die Fußzeile ("Profil 'Spiel' geladen", ...). AppBridge
    # hängt sich daran (siehe dort), damit Profilwechsel dieselbe Statuszeile
    # benutzen wie alles andere.
    notice          = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # DASSELBE dict wie app_settings.SETTINGS, nicht eine Kopie: config.py
        # und die anderen Module lesen dort weiter mit.
        self._data = app_settings.SETTINGS

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save)

    # ── Speichern ─────────────────────────────────────────────────────────
    @safe_slot
    def _save(self) -> None:
        app_settings.save(self._data)

    def _touch(self) -> None:
        self._save_timer.start()
        self.settingsChanged.emit()

    def flush(self) -> None:
        """Beim Beenden sofort schreiben, statt auf den Timer zu warten."""
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save()

    def _clamp(self, range_name: str, value: float) -> float:
        rng = self._data["ranges"][range_name]
        return min(rng["max"], max(rng["min"], value))

    # ══════════════════════════════════════════════════════════════════════
    #  Was der Bediener umschaltet
    # ══════════════════════════════════════════════════════════════════════

    # ── Farbschema / Schriftgröße (F7) ────────────────────────────────────
    @pyqtProperty(bool, notify=themeChanged)
    def dark(self):
        return self._data["ui"]["dark"]

    @pyqtSlot(bool)
    def setDark(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["ui"]["dark"]:
            self._data["ui"]["dark"] = value
            self.themeChanged.emit()
            self._touch()

    @pyqtSlot()
    def toggleTheme(self) -> None:
        self.setDark(not self._data["ui"]["dark"])

    @pyqtProperty(float, notify=themeChanged)
    def fontScale(self):
        return self._data["ui"]["fontScale"]

    @pyqtSlot(float)
    def setFontScale(self, value: float) -> None:
        # Grenzen aus settings.json ("ranges.fontScale"): unter 0.8 wird es
        # auf dem 13"-Touchscreen untreffbar, über 1.6 passen die
        # Tabellenspalten nicht mehr nebeneinander — wer es trotzdem anders
        # braucht, ändert dort eine Zahl statt einer .qml-Datei.
        value = round(self._clamp("fontScale", float(value)), 2)
        if value != self._data["ui"]["fontScale"]:
            self._data["ui"]["fontScale"] = value
            self.themeChanged.emit()
            self._touch()

    # ── Kiosk-/Sperrmodus ─────────────────────────────────────────────────
    @pyqtProperty(bool, notify=kioskChanged)
    def kiosk(self):
        return self._data["ui"]["kiosk"]

    @pyqtSlot(bool)
    def setKiosk(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["ui"]["kiosk"]:
            self._data["ui"]["kiosk"] = value
            self.kioskChanged.emit()
            self._touch()

    # ── Tastatursteuerung (B4) ────────────────────────────────────────────
    @pyqtProperty(bool, notify=settingsChanged)
    def keyboardControl(self):
        return self._data["ui"]["keyboardControl"]

    @pyqtSlot(bool)
    def setKeyboardControl(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["ui"]["keyboardControl"]:
            self._data["ui"]["keyboardControl"] = value
            self._touch()

    # ── Teensy-Konfiguration automatisch übernehmen ───────────────────────
    @pyqtProperty(bool, notify=settingsChanged)
    def autoApplyTeensyConfig(self):
        return self._data["ui"]["autoApplyTeensyConfig"]

    @pyqtSlot(bool)
    def setAutoApplyTeensyConfig(self, value: bool) -> None:
        value = bool(value)
        if value != self._data["ui"]["autoApplyTeensyConfig"]:
            self._data["ui"]["autoApplyTeensyConfig"] = value
            self._touch()

    # ── Tab, mit dem die Oberfläche startet ───────────────────────────────
    @pyqtProperty(int, notify=settingsChanged)
    def startTab(self):
        return self._data["ui"]["startTab"]

    @pyqtSlot(int)
    def setStartTab(self, value: int) -> None:
        value = int(value)
        if value != self._data["ui"]["startTab"]:
            self._data["ui"]["startTab"] = value
            self._touch()

    # ══════════════════════════════════════════════════════════════════════
    #  Was früher fest in QML stand
    # ══════════════════════════════════════════════════════════════════════
    #  Als ganzer Abschnitt statt als Einzel-Property: eine Property je Farbe
    #  wären dreißig fast identische Methoden, und QML kommt mit dem
    #  verschachtelten Objekt genauso gut zurecht
    #  (`Theme.pal.bg`, `settings.ranges.fontScale.max`).
    #
    #  notify=themeChanged bei allen dreien, damit ein Profilwechsel die
    #  komplette Oberfläche neu auswertet — ohne Neustart.

    @pyqtProperty("QVariantMap", notify=themeChanged)
    def theme(self):
        return self._data["theme"]

    @pyqtProperty("QVariantMap", notify=themeChanged)
    def ranges(self):
        return self._data["ranges"]

    @pyqtProperty("QVariantMap", notify=themeChanged)
    def window(self):
        return self._data["window"]

    # Heisst bewusst NICHT `params`: `appBridge.params` ist die
    # Parameter-Bruecke des Roboters, und zwei Namensvettern in derselben
    # Datei sind genau die Sorte Verwechslung, die man erst am Spielfeldrand
    # bemerkt.
    @pyqtProperty("QVariantMap", notify=themeChanged)
    def paramUi(self):
        return self._data["params"]

    # ── Akku-Warnung (C3) — hier nur die Persistenz ───────────────────────
    def battery(self) -> dict:
        return dict(self._data["battery"])

    def store_battery(self, cfg: dict) -> None:
        if cfg != self._data["battery"]:
            self._data["battery"] = dict(cfg)
            self._touch()

    # ══════════════════════════════════════════════════════════════════════
    #  Profile: mehrere Einstellungssätze speichern und laden
    # ══════════════════════════════════════════════════════════════════════

    @pyqtProperty(str, constant=True)
    def settingsPath(self):
        """Damit die Oberfläche sagen kann, WO die Datei liegt — sonst sucht
        man sie am Spielfeldrand im Home-Verzeichnis."""
        return str(app_settings.SETTINGS_PATH)

    @pyqtProperty("QStringList", notify=profilesChanged)
    def profiles(self):
        return app_settings.list_profiles()

    @pyqtSlot(str)
    def saveProfile(self, name: str) -> None:
        """Den aktuellen Stand als settings.<name>.json ablegen."""
        # Vorher den aktiven Stand festschreiben: sonst fehlt im Profil
        # ausgerechnet die Änderung, wegen der man gerade speichert (der
        # verzögerte Schreibtimer läuft ja noch).
        self.flush()
        if app_settings.save_profile(name, self._data):
            self.profilesChanged.emit()
            self.notice.emit(f"Einstellungen als Profil „{name}“ gespeichert.")
        else:
            self.notice.emit(
                f"Profil „{name}“ konnte nicht gespeichert werden — erlaubt "
                "sind Buchstaben, Ziffern, Leerzeichen, - und _.")

    @pyqtSlot(str)
    def loadProfile(self, name: str) -> None:
        """Ein Profil zum aktiven Stand machen."""
        data = app_settings.load_profile(name)
        if data is None:
            self.notice.emit(f"Profil „{name}“ ist nicht lesbar.")
            return
        self._apply(data)
        self.notice.emit(f"Profil „{name}“ geladen.")

    @pyqtSlot(str)
    def deleteProfile(self, name: str) -> None:
        if app_settings.delete_profile(name):
            self.profilesChanged.emit()
            self.notice.emit(f"Profil „{name}“ gelöscht.")
        else:
            self.notice.emit(f"Profil „{name}“ konnte nicht gelöscht werden.")

    @pyqtSlot()
    def resetToDefaults(self) -> None:
        self._apply(app_settings.defaults())
        self.notice.emit("Einstellungen auf Standardwerte zurückgesetzt.")

    def _apply(self, data: dict) -> None:
        """Einen kompletten Einstellungssatz übernehmen.

        app_settings.replace() ändert das dict AN ORT UND STELLE — self._data
        und app_settings.SETTINGS sind dasselbe Objekt und bleiben es auch
        nach einem Profilwechsel.

        Danach ALLE Signale feuern, ohne auf Änderungen zu prüfen: nach einem
        Profilwechsel kann sich jede einzelne Property geändert haben, und
        eine vergessene Benachrichtigung sieht in QML aus wie eine Farbe, die
        sich nicht umstellen lässt.

        Nicht neu eingelesen werden die Werte, die beim START gebraucht
        wurden (Fenstergröße, Ports, Puffergrößen, Controller-Belegung) —
        die stehen längst in config.py-Konstanten. Deshalb der Hinweis in der
        Oberfläche, dass manches erst nach einem Neustart gilt.
        """
        app_settings.replace(data)
        self.settingsReplaced.emit()
        self.themeChanged.emit()
        self.kioskChanged.emit()
        self.settingsChanged.emit()
        self.profilesChanged.emit()
        self.flush()
