"""Desktop UI for managing multiple SQL Server-to-MySQL sync scripts."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from manager.history import append_history, get_logger, LOG_DIR, LOG_FILE, HISTORY_FILE
from manager.runner import run_script
from manager.settings import load_settings, save_settings

APP_TITLE = "MSSQL → MySQL Sync Center"
BG = "#0B1120"
PANEL = "#111B2E"
PANEL_ALT = "#162238"
TEXT = "#E5EDF9"
MUTED = "#93A4BD"
ACCENT = "#38BDF8"
GREEN = "#34D399"
RED = "#FB7185"
AMBER = "#FBBF24"


class SyncManagerApp:
    """Tkinter application that runs sync scripts one by one."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1420x920")
        self.root.minsize(1100, 720)
        self.root.configure(bg=BG)

        self.settings = load_settings()
        self.logger = get_logger()
        self.events: queue.Queue[tuple] = queue.Queue()
        self.scripts: list[Path] = []
        self.is_running = False
        self.stop_event: threading.Event | None = None
        self.worker_thread: threading.Thread | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self.process_lock = threading.Lock()
        self.auto_enabled = False
        self.next_auto_run: float | None = None
        self.latest_successes = 0
        self.latest_failures = 0
        self.latest_no_new = 0

        self.script_dir_var = tk.StringVar(value=str(self.settings["scripts_directory"]))
        self.working_dir_var = tk.StringVar(value=str(self.settings["working_directory"]))
        self.python_var = tk.StringVar(value=str(self.settings["python_executable"]))
        self.interval_var = tk.StringVar(value=str(self.settings["interval_minutes"]))
        self.timeout_var = tk.StringVar(value=str(self.settings["script_timeout_minutes"]))
        self.patterns_var = tk.StringVar(
            value=", ".join(self.settings.get("include_patterns", ["transfer_*.py"]))
        )
        self.auto_status_var = tk.StringVar(value="Auto sync is off")
        self.next_run_var = tk.StringVar(value="Next run: —")
        self.footer_status_var = tk.StringVar(value="Ready to scan for scripts")

        self._setup_styles()
        self._build_ui()
        self.refresh_scripts()
        self._log(f"Application started. Log file: {LOG_FILE}")
        self.root.after(100, self._process_events)
        self.root.after(1000, self._tick)

        if self.settings.get("auto_start"):
            self.root.after(800, self.start_auto_sync)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Alt.TFrame", background=PANEL_ALT)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("CardTitle.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("CardValue.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 20, "bold"))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 22, "bold"))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        style.configure("TButton", padding=(12, 8), font=("Segoe UI Semibold", 9))
        style.configure("Accent.TButton", background="#0284C7", foreground="white", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#0369A1"), ("disabled", "#334155")])
        style.configure("Success.TButton", background="#047857", foreground="white", borderwidth=0)
        style.map("Success.TButton", background=[("active", "#065F46")])
        style.configure("Danger.TButton", background="#BE123C", foreground="white", borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#9F1239")])
        style.configure("Secondary.TButton", background="#23334D", foreground=TEXT, borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#344966")])
        style.configure("TEntry", fieldbackground="#0F1A2D", foreground=TEXT, insertcolor=TEXT, padding=6)
        style.configure("TCombobox", fieldbackground="#0F1A2D", foreground=TEXT, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#0F1A2D")], foreground=[("readonly", TEXT)])
        style.configure(
            "Treeview",
            background="#0F1A2D",
            fieldbackground="#0F1A2D",
            foreground=TEXT,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#1E2D45",
            foreground=TEXT,
            font=("Segoe UI Semibold", 9, "bold"),
            padding=(8, 8),
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#075985")])
        style.configure("TSeparator", background="#27364D")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(20, 16, 20, 12))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 14))
        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Run existing Python sync scripts • monitor records • schedule recurring syncs",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        self.header_pill = tk.Label(
            header,
            text="● IDLE",
            bg="#064E3B",
            fg="#A7F3D0",
            font=("Segoe UI Semibold", 9),
            padx=14,
            pady=8,
        )
        self.header_pill.pack(side="right", anchor="n")

        # Folder and runtime settings.
        paths_panel = ttk.Frame(outer, style="Panel.TFrame", padding=14)
        paths_panel.pack(fill="x", pady=(0, 12))
        ttk.Label(paths_panel, text="SYNC CONFIGURATION", style="Panel.TLabel", font=("Segoe UI Semibold", 10, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )

        ttk.Label(paths_panel, text="Scripts folder", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.script_entry = ttk.Entry(paths_panel, textvariable=self.script_dir_var)
        self.script_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        ttk.Button(paths_panel, text="Browse…", style="Secondary.TButton", command=self.browse_script_dir).grid(row=1, column=2, sticky="ew", padx=(0, 14), pady=4)

        ttk.Label(paths_panel, text="Working directory (.env base)", style="Panel.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.working_entry = ttk.Entry(paths_panel, textvariable=self.working_dir_var)
        self.working_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=4)
        ttk.Button(paths_panel, text="Browse…", style="Secondary.TButton", command=self.browse_working_dir).grid(row=2, column=2, sticky="ew", padx=(0, 14), pady=4)

        ttk.Label(paths_panel, text="Python executable", style="Panel.TLabel").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.python_entry = ttk.Entry(paths_panel, textvariable=self.python_var)
        self.python_entry.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=4)
        ttk.Button(paths_panel, text="Browse…", style="Secondary.TButton", command=self.browse_python).grid(row=3, column=2, sticky="ew", padx=(0, 14), pady=4)

        ttk.Label(paths_panel, text="Script patterns", style="Panel.TLabel").grid(row=1, column=3, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(paths_panel, textvariable=self.patterns_var, width=30).grid(row=1, column=4, sticky="ew", pady=4)
        ttk.Label(paths_panel, text="Interval (min)", style="Panel.TLabel").grid(row=2, column=3, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(
            paths_panel,
            textvariable=self.interval_var,
            values=("5", "10", "15", "30", "60", "120"),
            state="readonly",
            width=9,
        ).grid(row=2, column=4, sticky="w", pady=4)
        ttk.Label(paths_panel, text="Script timeout (min)", style="Panel.TLabel").grid(row=3, column=3, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(paths_panel, textvariable=self.timeout_var, width=10).grid(row=3, column=4, sticky="w", pady=4)

        for col in (1, 4):
            paths_panel.columnconfigure(col, weight=1)

        config_actions = ttk.Frame(paths_panel, style="Panel.TFrame")
        config_actions.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        ttk.Button(config_actions, text="Save Settings", style="Secondary.TButton", command=self.save_current_settings).pack(side="left")
        ttk.Button(config_actions, text="Scan Scripts", style="Secondary.TButton", command=self.refresh_scripts).pack(side="left", padx=(8, 0))
        ttk.Label(
            config_actions,
            text="Tip: use transfer_*.py, sync_*.py, update_*.py to avoid running unrelated Python files.",
            style="Muted.TLabel",
        ).pack(side="left", padx=(14, 0))

        # Summary cards.
        cards = ttk.Frame(outer)
        cards.pack(fill="x", pady=(0, 12))
        self.card_scripts = self._make_card(cards, "SCRIPTS FOUND", "0", 0)
        self.card_success = self._make_card(cards, "SUCCESS", "0", 1)
        self.card_no_new = self._make_card(cards, "NO NEW RECORDS", "0", 2)
        self.card_failed = self._make_card(cards, "FAILED / TIMEOUT", "0", 3)

        # Run and scheduler controls.
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Button(controls, text="▶  Run All", style="Accent.TButton", command=self.run_all).pack(side="left")
        ttk.Button(controls, text="Run Selected", style="Secondary.TButton", command=self.run_selected).pack(side="left", padx=(8, 0))
        self.stop_button = ttk.Button(controls, text="■  Stop Run", style="Danger.TButton", command=self.stop_run, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 14))
        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=(0, 14), pady=3)
        self.auto_start_button = ttk.Button(controls, text="Start Auto Sync", style="Success.TButton", command=self.start_auto_sync)
        self.auto_start_button.pack(side="left")
        self.auto_stop_button = ttk.Button(controls, text="Stop Auto Sync", style="Secondary.TButton", command=self.stop_auto_sync, state="disabled")
        self.auto_stop_button.pack(side="left", padx=(8, 0))
        ttk.Label(controls, textvariable=self.auto_status_var, style="Muted.TLabel").pack(side="left", padx=(14, 8))
        ttk.Label(controls, textvariable=self.next_run_var, style="Muted.TLabel").pack(side="right")

        # Script results table.
        table_panel = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        table_panel.pack(fill="both", expand=True, pady=(0, 12))
        table_header = ttk.Frame(table_panel, style="Panel.TFrame")
        table_header.pack(fill="x", pady=(0, 8))
        ttk.Label(table_header, text="SYNC JOBS", style="Panel.TLabel", font=("Segoe UI Semibold", 10, "bold")).pack(side="left")
        ttk.Label(table_header, text="Select a row to run one script", style="Panel.TLabel", foreground=MUTED).pack(side="right")

        columns = ("script", "status", "new_records", "duration", "result")
        self.tree = ttk.Treeview(table_panel, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("script", text="PYTHON FILE")
        self.tree.heading("status", text="STATUS")
        self.tree.heading("new_records", text="NEW RECORDS")
        self.tree.heading("duration", text="DURATION")
        self.tree.heading("result", text="RESULT / MESSAGE")
        self.tree.column("script", width=300, minwidth=180, anchor="w")
        self.tree.column("status", width=150, minwidth=120, anchor="center")
        self.tree.column("new_records", width=120, minwidth=100, anchor="center")
        self.tree.column("duration", width=100, minwidth=80, anchor="center")
        self.tree.column("result", width=650, minwidth=240, anchor="w")
        self.tree.tag_configure("SUCCESS", foreground="#6EE7B7")
        self.tree.tag_configure("NO NEW RECORDS", foreground="#93C5FD")
        self.tree.tag_configure("FAILED", foreground="#FDA4AF")
        self.tree.tag_configure("TIMEOUT", foreground="#FCD34D")
        self.tree.tag_configure("STOPPED", foreground="#FCD34D")
        self.tree.tag_configure("RUNNING", foreground="#7DD3FC")
        self.tree.tag_configure("PENDING", foreground=MUTED)
        self.tree.tag_configure("SKIPPED", foreground=MUTED)

        table_scroll = ttk.Scrollbar(table_panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=table_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        table_scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.run_selected())

        # Live output log.
        log_panel = ttk.Frame(outer, style="Panel.TFrame", padding=10)
        log_panel.pack(fill="both", expand=False)
        log_header = ttk.Frame(log_panel, style="Panel.TFrame")
        log_header.pack(fill="x", pady=(0, 7))
        ttk.Label(log_header, text="LIVE OUTPUT", style="Panel.TLabel", font=("Segoe UI Semibold", 10, "bold")).pack(side="left")
        ttk.Button(log_header, text="Clear View", style="Secondary.TButton", command=self.clear_log_view).pack(side="right")
        ttk.Button(log_header, text="Open Logs Folder", style="Secondary.TButton", command=self.open_logs_folder).pack(side="right", padx=(0, 8))

        self.log_text = tk.Text(
            log_panel,
            height=8,
            bg="#07101D",
            fg="#C7D6EA",
            insertbackground=TEXT,
            relief="flat",
            wrap="word",
            font=("Consolas", 9),
            padx=9,
            pady=8,
        )
        log_scroll = ttk.Scrollbar(log_panel, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, textvariable=self.footer_status_var, style="Muted.TLabel").pack(side="left")
        ttk.Label(footer, text=f"History: {HISTORY_FILE}", style="Muted.TLabel").pack(side="right")

    def _make_card(self, parent: ttk.Frame, label: str, value: str, column: int) -> ttk.Label:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 10))
        card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 8, 0))
        parent.columnconfigure(column, weight=1)
        ttk.Label(card, text=label, style="CardTitle.TLabel").pack(anchor="w")
        value_label = ttk.Label(card, text=value, style="CardValue.TLabel")
        value_label.pack(anchor="w", pady=(5, 0))
        return value_label

    # ------------------------------------------------------------------
    # Settings and script discovery
    # ------------------------------------------------------------------

    def _read_form_settings(self) -> dict[str, Any]:
        try:
            interval = int(self.interval_var.get().strip())
            timeout = int(self.timeout_var.get().strip())
        except ValueError as error:
            raise ValueError("Interval and timeout must be whole numbers.") from error

        if interval < 1:
            raise ValueError("Auto-sync interval must be at least 1 minute.")
        if timeout < 1:
            raise ValueError("Script timeout must be at least 1 minute.")

        patterns = [item.strip() for item in self.patterns_var.get().split(",") if item.strip()]
        if not patterns:
            raise ValueError("Enter at least one script pattern, for example transfer_*.py.")

        return {
            **self.settings,
            "scripts_directory": self.script_dir_var.get().strip(),
            "working_directory": self.working_dir_var.get().strip(),
            "python_executable": self.python_var.get().strip(),
            "interval_minutes": interval,
            "script_timeout_minutes": timeout,
            "include_patterns": patterns,
        }

    def save_current_settings(self, show_message: bool = True) -> bool:
        try:
            settings = self._read_form_settings()
        except ValueError as error:
            messagebox.showerror("Invalid settings", str(error), parent=self.root)
            return False

        if not settings["scripts_directory"]:
            messagebox.showerror("Missing folder", "Select the folder containing sync scripts.", parent=self.root)
            return False
        if not settings["working_directory"]:
            messagebox.showerror("Missing working directory", "Select the directory used by your scripts for relative paths and .env files.", parent=self.root)
            return False
        if not settings["python_executable"]:
            messagebox.showerror("Missing Python", "Select the Python executable used to run your sync scripts.", parent=self.root)
            return False

        self.settings = settings
        try:
            save_settings(self.settings)
        except OSError as error:
            messagebox.showerror("Settings could not be saved", str(error), parent=self.root)
            return False

        if show_message:
            self._log("Settings saved.")
            self.footer_status_var.set("Settings saved")
        return True

    def browse_script_dir(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose folder containing SQL Server → MySQL scripts",
            initialdir=self.script_dir_var.get() or str(Path.home()),
        )
        if selected:
            self.script_dir_var.set(selected)
            self.refresh_scripts()

    def browse_working_dir(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose script working directory (relative .env path base)",
            initialdir=self.working_dir_var.get() or str(Path.home()),
        )
        if selected:
            self.working_dir_var.set(selected)

    def browse_python(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Python executable",
            filetypes=[("Python executable", "python.exe"), ("All files", "*.*")],
            initialdir=str(Path(self.python_var.get()).parent) if self.python_var.get() else str(Path.home()),
        )
        if selected:
            self.python_var.set(selected)

    def refresh_scripts(self) -> None:
        raw_directory = self.script_dir_var.get().strip()
        directory = Path(raw_directory).expanduser() if raw_directory else Path()
        self.scripts = []

        for item in self.tree.get_children():
            self.tree.delete(item)

        if not raw_directory or not directory.is_dir():
            self.card_scripts.configure(text="0")
            message = f"Scripts folder does not exist: {directory}" if raw_directory else "Select a scripts folder."
            self.footer_status_var.set(message)
            self._log(message)
            self._update_metrics()
            return

        try:
            settings = self._read_form_settings()
            patterns = settings["include_patterns"]
        except ValueError as error:
            self._log(f"Cannot scan scripts: {error}")
            patterns = ["transfer_*.py", "sync_*.py", "update_*.py"]

        excluded = {name.lower() for name in self.settings.get("exclude_files", [])}
        found: dict[str, Path] = {}
        for pattern in patterns:
            for path in directory.glob(pattern):
                if not path.is_file() or path.suffix.lower() != ".py":
                    continue
                if path.name.lower() in excluded or path.name.startswith("."):
                    continue
                found[str(path.resolve()).lower()] = path.resolve()

        self.scripts = sorted(found.values(), key=lambda item: item.name.lower())
        for path in self.scripts:
            iid = str(path)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(path.name, "READY", "—", "—", "Not run yet"),
                tags=("PENDING",),
            )

        self.card_scripts.configure(text=str(len(self.scripts)))
        self.footer_status_var.set(f"Found {len(self.scripts)} sync script(s) in {directory}")
        self._log(f"Script scan completed: {len(self.scripts)} file(s) found in {directory}")
        if not self.scripts:
            self._log("No matching files. Check the folder and script patterns.")
        self._update_metrics()

    # ------------------------------------------------------------------
    # Run management
    # ------------------------------------------------------------------

    def run_all(self) -> None:
        self._start_run(self.scripts.copy(), source="manual")

    def run_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Select a script", "Select a script row first, then click Run Selected.", parent=self.root)
            return
        selected_path = Path(selection[0])
        self._start_run([selected_path], source="manual-selected")

    def _start_run(self, scripts: list[Path], source: str) -> None:
        if self.is_running:
            messagebox.showinfo("Sync is running", "A sync batch is already running. Wait for it to finish or stop it first.", parent=self.root)
            return
        if not scripts:
            messagebox.showwarning("No scripts", "No sync scripts were found. Check the scripts folder and patterns.", parent=self.root)
            return
        if not self.save_current_settings(show_message=False):
            return

        working_directory = Path(self.working_dir_var.get().strip()).expanduser()
        python_executable = self.python_var.get().strip()
        if not working_directory.is_dir():
            messagebox.showerror("Invalid working directory", f"Directory does not exist:\n{working_directory}", parent=self.root)
            return
        if not Path(python_executable).exists() and not (os.name == "nt" and python_executable.lower() == "python"):
            messagebox.showerror("Python not found", f"Python executable does not exist:\n{python_executable}", parent=self.root)
            return

        self.is_running = True
        self.stop_event = threading.Event()
        self.latest_successes = 0
        self.latest_failures = 0
        self.latest_no_new = 0
        self.stop_button.configure(state="normal")
        self.header_pill.configure(text="● RUNNING", bg="#164E63", fg="#A5F3FC")
        self.footer_status_var.set(f"Running {len(scripts)} script(s) ({source})…")

        for path in scripts:
            if self.tree.exists(str(path)):
                self.tree.item(str(path), values=(path.name, "QUEUED", "—", "—", "Waiting to run"), tags=("PENDING",))

        self._log(f"Started {len(scripts)} script(s); execution is sequential ({source}).")
        timeout_seconds = int(self.timeout_var.get().strip()) * 60
        stop_event = self.stop_event

        self.worker_thread = threading.Thread(
            target=self._run_batch_worker,
            args=(scripts, python_executable, working_directory, timeout_seconds, stop_event),
            name="sync-batch-worker",
            daemon=True,
        )
        self.worker_thread.start()

    def _run_batch_worker(
        self,
        scripts: list[Path],
        python_executable: str,
        working_directory: Path,
        timeout_seconds: int,
        stop_event: threading.Event,
    ) -> None:
        batch_started = datetime.now()
        results: list[dict[str, Any]] = []

        for position, script_path in enumerate(scripts, start=1):
            if stop_event.is_set():
                for skipped_path in scripts[position - 1 :]:
                    result = {
                        "started_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
                        "script": skipped_path.name,
                        "status": "SKIPPED",
                        "new_records": None,
                        "count_source": "unknown",
                        "duration_seconds": 0,
                        "return_code": None,
                        "message": "Skipped because the run was stopped",
                        "output": [],
                    }
                    results.append(result)
                    self.events.put(("script_done", result))
                break

            self.events.put(("script_start", script_path.name, position, len(scripts)))
            self.logger.info("Starting script: %s", script_path)

            def on_output(line: str, name: str = script_path.name) -> None:
                self.events.put(("output", name, line))

            def on_process(process: subprocess.Popen[str] | None) -> None:
                with self.process_lock:
                    self.current_process = process

            result = run_script(
                script_path=script_path,
                python_executable=python_executable,
                working_directory=working_directory,
                timeout_seconds=timeout_seconds,
                stop_event=stop_event,
                output_callback=on_output,
                process_callback=on_process,
            )
            results.append(result)
            append_history(result)
            self.logger.info(
                "Finished script=%s status=%s new_records=%s duration=%s message=%s",
                result["script"],
                result["status"],
                result["new_records"],
                result["duration_seconds"],
                result["message"],
            )
            self.events.put(("script_done", result))

        self.events.put(("run_finished", {
            "results": results,
            "started_at": batch_started.isoformat(sep=" ", timespec="seconds"),
            "source": "batch",
            "stopped": stop_event.is_set(),
        }))

    def stop_run(self) -> None:
        if not self.is_running or self.stop_event is None:
            return
        self.stop_event.set()
        with self.process_lock:
            process = self.current_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as error:
                self._log(f"Could not terminate current process: {error}")
        self.footer_status_var.set("Stop requested; waiting for current script to exit…")
        self._log("Stop requested by user.")

    # ------------------------------------------------------------------
    # Auto scheduler
    # ------------------------------------------------------------------

    def start_auto_sync(self) -> None:
        if self.auto_enabled:
            return
        if not self.save_current_settings(show_message=False):
            return
        self.auto_enabled = True
        self.next_auto_run = time.monotonic() + int(self.interval_var.get()) * 60
        self.auto_status_var.set("Auto sync is on")
        self.auto_start_button.configure(state="disabled")
        self.auto_stop_button.configure(state="normal")
        self.settings["auto_start"] = True
        save_settings(self.settings)
        self._log(f"Auto sync enabled. Interval: {self.interval_var.get()} minute(s).")
        self.footer_status_var.set("Auto sync enabled; the first automatic run will start after the selected interval.")

    def stop_auto_sync(self) -> None:
        self.auto_enabled = False
        self.next_auto_run = None
        self.auto_status_var.set("Auto sync is off")
        self.next_run_var.set("Next run: —")
        self.auto_start_button.configure(state="normal")
        self.auto_stop_button.configure(state="disabled")
        self.settings["auto_start"] = False
        save_settings(self.settings)
        self._log("Auto sync disabled. A currently running batch is not stopped by this action.")

    def _tick(self) -> None:
        if self.auto_enabled and self.next_auto_run is not None:
            remaining = max(0, int(self.next_auto_run - time.monotonic()))
            minutes, seconds = divmod(remaining, 60)
            self.next_run_var.set(f"Next run in: {minutes:02d}:{seconds:02d}")
            if remaining <= 0 and not self.is_running:
                self._log("Scheduled auto sync started.")
                self._start_run(self.scripts.copy(), source="auto")
                self.next_auto_run = None
        self.root.after(1000, self._tick)

    # ------------------------------------------------------------------
    # Event processing and display updates
    # ------------------------------------------------------------------

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                event_type = event[0]

                if event_type == "script_start":
                    _, name, position, total = event
                    path = next((item for item in self.scripts if item.name == name), None)
                    if path and self.tree.exists(str(path)):
                        self.tree.item(str(path), values=(name, "RUNNING", "—", "—", f"Running {position} of {total}"), tags=("RUNNING",))
                    self.footer_status_var.set(f"Running {name} ({position}/{total})")
                    self._log(f"Starting {name} ({position}/{total})")

                elif event_type == "output":
                    _, name, line = event
                    if line:
                        # Store child-script output in the log file as well as the UI.
                        self.logger.info("[%s] %s", name, line)
                        self._append_log_line(f"[{name}] {line}")

                elif event_type == "script_done":
                    _, result = event
                    path = next((item for item in self.scripts if item.name == result["script"]), None)
                    new_count = result.get("new_records")
                    count_display = "—" if new_count is None else f"{new_count:,}"
                    duration_display = f"{result.get('duration_seconds', 0):.1f}s"
                    if path and self.tree.exists(str(path)):
                        status = result["status"]
                        tag = status if status in {"SUCCESS", "NO NEW RECORDS", "FAILED", "TIMEOUT", "STOPPED", "SKIPPED"} else "PENDING"
                        self.tree.item(
                            str(path),
                            values=(result["script"], status, count_display, duration_display, result["message"]),
                            tags=(tag,),
                        )
                    if result["status"] == "SUCCESS":
                        self.latest_successes += 1
                    elif result["status"] == "NO NEW RECORDS":
                        self.latest_no_new += 1
                    elif result["status"] in {"FAILED", "TIMEOUT"}:
                        self.latest_failures += 1
                    self._log(f"Result: {result['script']} | {result['status']} | {result['message']}")
                    self._update_metrics()

                elif event_type == "run_finished":
                    _, info = event
                    self.is_running = False
                    self.current_process = None
                    self.stop_button.configure(state="disabled")
                    if self.auto_enabled:
                        self.next_auto_run = time.monotonic() + int(self.interval_var.get()) * 60
                    else:
                        self.next_auto_run = None
                        self.next_run_var.set("Next run: —")
                    if info["stopped"]:
                        self.header_pill.configure(text="● STOPPED", bg="#78350F", fg="#FDE68A")
                        self.footer_status_var.set("Batch stopped")
                    elif self.latest_failures:
                        self.header_pill.configure(text="● COMPLETED WITH ERRORS", bg="#881337", fg="#FECDD3")
                        self.footer_status_var.set("Batch finished; one or more scripts failed or timed out")
                    else:
                        self.header_pill.configure(text="● IDLE", bg="#064E3B", fg="#A7F3D0")
                        self.footer_status_var.set("Batch completed")
                    self._log(
                        f"Batch finished. Success={self.latest_successes}, "
                        f"No new records={self.latest_no_new}, Failed/timeout={self.latest_failures}."
                    )
                    self._update_metrics()

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_events)

    def _update_metrics(self) -> None:
        self.card_scripts.configure(text=str(len(self.scripts)))
        self.card_success.configure(text=str(self.latest_successes))
        self.card_no_new.configure(text=str(self.latest_no_new))
        self.card_failed.configure(text=str(self.latest_failures))

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"{timestamp}  {message}"
        self.logger.info(message)
        self._append_log_line(line)

    def _append_log_line(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log_view(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def open_logs_folder(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(LOG_DIR))  # type: ignore[attr-defined]
            else:
                import webbrowser
                webbrowser.open(LOG_DIR.as_uri())
        except Exception as error:
            messagebox.showerror("Could not open logs folder", str(error), parent=self.root)

    def on_close(self) -> None:
        if self.is_running:
            should_close = messagebox.askyesno(
                "Sync is running",
                "A sync script is currently running. Stop it and close the manager?",
                parent=self.root,
            )
            if not should_close:
                return
            self.stop_run()
            # Keep the UI alive briefly to process the stop and avoid closing mid-write.
            self.root.after(800, self._finish_close)
            return
        self._finish_close()

    def _finish_close(self) -> None:
        self.root.destroy()


def main() -> None:
    """Application entry point."""
    root = tk.Tk()
    app = SyncManagerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
