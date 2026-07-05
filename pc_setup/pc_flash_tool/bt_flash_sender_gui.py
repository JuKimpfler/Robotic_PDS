#!/usr/bin/env python3
"""
bt_flash_sender_gui.py
========================
Einfache grafische Oberfläche für bt_flash_sender.py (siehe
Flash_Implementierung.md, Abschnitt 5.1: "optional später eine minimale
Tkinter-GUI").

Bietet:
  - Dateiauswahl (.hex) per Dialog
  - Empfänger-Auswahl (Node 1 / Node 2, je per Checkbox, auch beide zusammen)
  - Log-Fenster mit Live-Ausgabe
  - Fortschrittsbalken je Node
  - Flashen läuft in einem Hintergrund-Thread, GUI bleibt bedienbar

Nur Python-Standardbibliothek (tkinter ist bei Standard-Python unter Windows
immer mit dabei) — kein zusätzliches pip-Paket nötig.

Start:
    python bt_flash_sender_gui.py
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bt_flash_sender import TARGETS_FILE_DEFAULT, flash_one, load_targets

APP_TITLE = "PDS — Wireless Flash (Bluetooth)"


class FlashApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(False, False)
        self.minsize(560, 420)

        self.hex_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Bereit.")
        self.targets_file = TARGETS_FILE_DEFAULT
        self.node_vars: dict[str, tk.BooleanVar] = {}
        self.progress_bars: dict[str, ttk.Progressbar] = {}
        self.progress_labels: dict[str, tk.StringVar] = {}
        self._worker: threading.Thread | None = None
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._flashing = False

        self._build_ui()
        self._load_targets_into_ui()
        self.after(100, self._drain_log_queue)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}

        # --- Dateiauswahl ------------------------------------------------
        file_frame = ttk.LabelFrame(self, text="1. Firmware-Datei (.hex)")
        file_frame.pack(fill="x", **pad)

        entry = ttk.Entry(file_frame, textvariable=self.hex_path_var, width=52)
        entry.pack(side="left", padx=(10, 5), pady=10, fill="x", expand=True)
        ttk.Button(file_frame, text="Durchsuchen ...", command=self._browse_file).pack(
            side="left", padx=(0, 10), pady=10
        )

        # --- Empfänger-Auswahl --------------------------------------------
        self.target_frame = ttk.LabelFrame(self, text="2. Empfänger auswählen")
        self.target_frame.pack(fill="x", **pad)

        # --- Aktion --------------------------------------------------------
        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)
        self.flash_button = ttk.Button(action_frame, text="Flashen", command=self._on_flash_clicked)
        self.flash_button.pack(side="left")
        ttk.Label(action_frame, textvariable=self.status_var).pack(side="left", padx=12)

        # --- Fortschritt (wird pro Node dynamisch befüllt) -----------------
        self.progress_frame = ttk.LabelFrame(self, text="3. Fortschritt")
        self.progress_frame.pack(fill="x", **pad)

        # --- Log -------------------------------------------------------------
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=12, width=68, state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _load_targets_into_ui(self) -> None:
        """Lädt bt_targets.json und legt für jeden Node eine Checkbox + Fortschrittsbalken an."""
        try:
            targets = load_targets(self.targets_file)
        except SystemExit:
            targets = {}
            messagebox.showwarning(
                APP_TITLE,
                f"{self.targets_file} existierte nicht — eine Vorlage wurde angelegt.\n"
                "Bitte MAC-Adresse, Kanal und Token eintragen (siehe setup_node.sh-Ausgabe "
                "auf dem jeweiligen Pi) und die GUI neu starten.",
            )

        real_targets = {
            name: cfg for name, cfg in targets.items()
            if not name.startswith("_") and isinstance(cfg, dict)
        }
        if not real_targets:
            ttk.Label(self.target_frame, text="Keine Ziele in bt_targets.json gefunden.").pack(
                padx=10, pady=10
            )
            return

        for name, cfg in real_targets.items():
            var = tk.BooleanVar(value=True)
            self.node_vars[name] = var
            mac = cfg.get("mac", "?")
            ttk.Checkbutton(
                self.target_frame, text=f"{name}  ({mac})", variable=var
            ).pack(anchor="w", padx=10, pady=(6, 0))

            row = ttk.Frame(self.progress_frame)
            row.pack(fill="x", padx=10, pady=4)
            ttk.Label(row, text=name, width=8).pack(side="left")
            bar = ttk.Progressbar(row, length=300, mode="determinate", maximum=100)
            bar.pack(side="left", padx=6)
            label_var = tk.StringVar(value="wartet ...")
            ttk.Label(row, textvariable=label_var, width=26).pack(side="left")
            self.progress_bars[name] = bar
            self.progress_labels[name] = label_var
        # letzte Zeile im target_frame etwas Luft geben
        ttk.Label(self.target_frame, text="").pack(pady=(0, 4))

    # -------------------------------------------------------------- Aktionen
    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Firmware-Datei auswählen",
            filetypes=[("Teensy HEX-Datei", "*.hex"), ("Alle Dateien", "*.*")],
        )
        if path:
            self.hex_path_var.set(path)

    def _on_flash_clicked(self) -> None:
        if self._flashing:
            return

        hex_path = Path(self.hex_path_var.get().strip())
        if not hex_path.exists():
            messagebox.showerror(APP_TITLE, f"Datei nicht gefunden:\n{hex_path}")
            return

        selected = [name for name, var in self.node_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning(APP_TITLE, "Bitte mindestens einen Empfänger auswählen.")
            return

        self._clear_log()
        for name in self.progress_bars:
            self.progress_bars[name]["value"] = 0
            self.progress_labels[name].set("wartet ...")

        self._flashing = True
        self.flash_button.configure(state="disabled")
        self.status_var.set("Flashe ...")

        self._worker = threading.Thread(
            target=self._flash_worker, args=(selected, hex_path), daemon=True
        )
        self._worker.start()

    # ---------------------------------------------------------- Worker-Thread
    def _flash_worker(self, selected: list[str], hex_path: Path) -> None:
        targets = load_targets(self.targets_file)
        results: dict[str, bool] = {}

        for name in selected:
            if name not in targets:
                self._log_queue.put(f"[FEHLER] '{name}' fehlt in {self.targets_file}")
                results[name] = False
                continue

            def log_cb(msg: str, _name=name) -> None:
                self._log_queue.put(f"[{_name}] {msg}")

            def progress_cb(pct: int, sent: int, size: int, kbs: float, _name=name) -> None:
                self.after(0, self._update_progress, _name, pct, sent, size, kbs)

            results[name] = flash_one(name, targets[name], hex_path, log_cb=log_cb, progress_cb=progress_cb)
            self.after(0, self._mark_done, name, results[name])

        ok_all = all(results.values()) if results else False
        self.after(0, self._flash_finished, results, ok_all)

    def _update_progress(self, name: str, pct: int, sent: int, size: int, kbs: float) -> None:
        self.progress_bars[name]["value"] = pct
        self.progress_labels[name].set(f"{pct:3d}%  ({kbs:.0f} KB/s)")

    def _mark_done(self, name: str, ok: bool) -> None:
        self.progress_labels[name].set("OK ✓" if ok else "FEHLGESCHLAGEN ✗")
        if ok:
            self.progress_bars[name]["value"] = 100

    def _flash_finished(self, results: dict[str, bool], ok_all: bool) -> None:
        self._flashing = False
        self.flash_button.configure(state="normal")
        self.status_var.set("Fertig — alle erfolgreich." if ok_all else "Fertig — mindestens ein Fehler.")
        summary = "\n".join(f"  {name}: {'OK' if ok else 'FEHLGESCHLAGEN'}" for name, ok in results.items())
        self._log_queue.put("\n=== Zusammenfassung ===\n" + summary)
        if ok_all:
            messagebox.showinfo(APP_TITLE, "Alle gewählten Nodes wurden erfolgreich geflasht.")
        else:
            messagebox.showerror(APP_TITLE, "Mindestens ein Node konnte nicht geflasht werden.\nDetails im Log.")

    # -------------------------------------------------------------------- Log
    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._drain_log_queue)


def main() -> None:
    app = FlashApp()
    app.mainloop()


if __name__ == "__main__":
    main()