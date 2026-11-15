"""Native Tkinter desktop dashboard and controls for Jarvis."""

import json
import math
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import psutil
import speech_recognition as sr

import jarvis_brain
import jarvis_market
import jarvis_voice


THEMES = {
    "Cyan": {"accent": "#36e8ff", "glow": "#0d7184"},
    "Green": {"accent": "#49ffab", "glow": "#16764e"},
    "Violet": {"accent": "#c084ff", "glow": "#633897"},
    "Amber": {"accent": "#ffc857", "glow": "#806324"},
}
STATE_COLORS = {
    "LISTENING": "#36e8ff",
    "RECOGNIZING": "#ffc857",
    "PROCESSING": "#c084ff",
    "SPEAKING": "#49ffab",
    "READY": "#36e8ff",
    "SYSTEM READY": "#36e8ff",
}
BG = "#050b12"
PANEL = "#0a1420"
TEXT = "#e8faff"
MUTED = "#7995a6"


def _settings_path():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(root, "OpenJarvis", "settings.json")


def _load_settings():
    settings = {
        "theme": "Cyan",
        "speech_enabled": True,
        "speech_rate": 0,
        "autostart_listening": True,
    }
    try:
        with open(_settings_path(), encoding="utf-8") as settings_file:
            saved = json.load(settings_file)
        if isinstance(saved, dict):
            settings.update(saved)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Settings error] Could not load settings: {exc}")

    if settings.get("theme") not in THEMES:
        settings["theme"] = "Cyan"
    settings["speech_enabled"] = bool(settings.get("speech_enabled", True))
    settings["autostart_listening"] = bool(settings.get("autostart_listening", True))
    try:
        settings["speech_rate"] = max(-10, min(10, int(settings["speech_rate"])))
    except (TypeError, ValueError):
        settings["speech_rate"] = 0
    return settings


class JarvisDesktop:
    def __init__(self, root):
        self.root = root
        self._closed = False
        self._after_ids = set()
        self.root.title("J.A.R.V.I.S. | Executive Assistant")
        self.root.geometry("1360x860")
        self.root.minsize(1120, 720)
        self.root.configure(bg=BG)
        self.settings = _load_settings()
        self.events = queue.Queue()
        self.stop_event = None
        self.voice_thread = None
        self.command_lock = threading.Lock()
        self.speech_lock = threading.Lock()
        self.chat_count = 0
        self.started_at = time.monotonic()
        self._holo_items = {}
        self._holo_styles = {}
        self._holo_frame = 0
        self.globe_paths = []
        for latitude in (-60, -30, 0, 30, 60):
            lat = math.radians(latitude)
            self.globe_paths.append([
                (math.cos(lat) * math.cos(step / 52 * math.tau),
                 math.sin(lat),
                 math.cos(lat) * math.sin(step / 52 * math.tau))
                for step in range(53)
            ])
        for meridian in range(12):
            lon = meridian / 12 * math.pi
            self.globe_paths.append([
                (math.cos(-math.pi / 2 + step / 52 * math.pi) * math.cos(lon),
                 math.sin(-math.pi / 2 + step / 52 * math.pi),
                 math.cos(-math.pi / 2 + step / 52 * math.pi) * math.sin(lon))
                for step in range(53)
            ])
        self.particles = [
            [random.random(), random.random(), random.uniform(0.002, 0.009), random.uniform(1, 2)]
            for _ in range(48)
        ]
        self.theme = THEMES[self.settings["theme"]]
        self.status_var = tk.StringVar(value="SYSTEM READY")
        self.note_var = tk.StringVar(value="Awaiting voice input")
        self.time_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.current_state = "IDLE"
        self.visual_accent = self.theme["accent"]
        self.wave_items = {}
        self.settings_window = None
        self.panel_frames = []
        self.panel_titles = []
        self._build_ui()
        self._apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._after(50, self._drain_events)
        self._after(1000, self._update_telemetry)
        self._after(25, self._animate)
        self._after(1800, self.refresh_market)
        self._after(90000, self._schedule_market_refresh)
        self.add_message("SYS", "Native Jarvis interface online.")
        if self.settings["autostart_listening"]:
            self._after(500, self.start_assistant)

    def _after(self, delay_ms, callback):
        callback_id = None

        def run_callback():
            self._after_ids.discard(callback_id)
            if not self._closed:
                callback()

        callback_id = self.root.after(delay_ms, run_callback)
        self._after_ids.add(callback_id)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=BG, padx=20, pady=14)
        header.pack(fill="x")
        tk.Label(
            header, text="◉", font=("Segoe UI", 26, "bold"),
            fg=self.theme["accent"], bg=BG,
        ).pack(side="left", padx=(0, 12))
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left")
        tk.Label(
            title_box, text="J.A.R.V.I.S", font=("Segoe UI", 22, "bold"),
            fg=TEXT, bg=BG,
        ).pack(anchor="w")
        tk.Label(
            title_box, text="MARK VII  /  EXECUTIVE ASSISTANT",
            font=("Consolas", 9), fg=MUTED, bg=BG,
        ).pack(anchor="w")
        tk.Label(
            header, textvariable=self.status_var, font=("Consolas", 11, "bold"),
            fg=self.theme["accent"], bg=BG,
        ).pack(side="right", padx=8)
        tk.Label(
            header, textvariable=self.date_var, font=("Consolas", 8),
            fg=MUTED, bg=BG,
        ).pack(side="right", padx=(8, 14))
        tk.Label(
            header, textvariable=self.time_var, font=("Consolas", 18, "bold"),
            fg=TEXT, bg=BG,
        ).pack(side="right", padx=8)
        tk.Button(
            header, text="SETTINGS", command=self.open_settings,
            relief="flat", bg=PANEL, fg=self.theme["accent"],
            activebackground=self.theme["glow"], font=("Consolas", 9, "bold"),
        ).pack(side="right", padx=12)
        tk.Frame(self.root, bg=self.theme["accent"], height=1).pack(fill="x", padx=18)

        body = tk.Frame(self.root, bg=BG, padx=14, pady=14)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, minsize=310, weight=3, uniform="dashboard")
        body.grid_columnconfigure(1, minsize=430, weight=5, uniform="dashboard")
        body.grid_columnconfigure(2, minsize=330, weight=3, uniform="dashboard")
        body.grid_rowconfigure(0, weight=1)

        self.left = tk.Frame(body, bg=BG)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.center = tk.Frame(body, bg=BG)
        self.center.grid(row=0, column=1, sticky="nsew", padx=6)
        self.right = tk.Frame(body, bg=BG)
        self.right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        self._build_telemetry()
        self._build_hologram()
        self._build_right()

        footer = tk.Frame(self.root, bg=BG, padx=18, pady=10)
        footer.pack(fill="x")
        self.start_button = tk.Button(
            footer, text="START LISTENING", command=self.start_assistant,
            font=("Consolas", 10, "bold"), relief="flat", padx=14, pady=8,
            bg=self.theme["glow"], fg=TEXT, activebackground=self.theme["accent"],
        )
        self.start_button.pack(side="left")
        self.stop_button = tk.Button(
            footer, text="STOP", command=self.stop_assistant,
            font=("Consolas", 10, "bold"), relief="flat", padx=14, pady=8,
            bg=PANEL, fg=TEXT, activebackground=self.theme["glow"],
        )
        self.stop_button.pack(side="left", padx=8)
        tk.Label(
            footer, textvariable=self.note_var, font=("Consolas", 9),
            fg=MUTED, bg=BG,
        ).pack(side="right")

    def _panel(self, parent, title):
        frame = tk.Frame(
            parent, bg=PANEL, highlightthickness=1,
            highlightbackground=self.theme["glow"], padx=12, pady=10,
        )
        title_label = tk.Label(
            frame, text=title.upper(), font=("Consolas", 10, "bold"),
            fg=self.theme["accent"], bg=PANEL,
        )
        title_label.pack(anchor="w", pady=(0, 8))
        self.panel_frames.append(frame)
        self.panel_titles.append(title_label)
        return frame

    def _build_telemetry(self):
        voice = self._panel(self.left, "Voice Frequency Oscilloscope")
        voice.pack(fill="x", pady=(0, 10))
        self.wave = tk.Canvas(
            voice, height=76, bg="#07101a", highlightthickness=0,
        )
        self.wave.pack(fill="x")
        voice_status = tk.Frame(voice, bg=PANEL)
        voice_status.pack(fill="x", pady=(6, 0))
        tk.Label(
            voice_status, textvariable=self.status_var, font=("Consolas", 8, "bold"),
            fg=self.theme["accent"], bg=PANEL,
        ).pack(side="left")
        tk.Label(
            voice_status, text="MIC READY", font=("Consolas", 8),
            fg=MUTED, bg=PANEL,
        ).pack(side="right")

        pipeline = self._panel(self.left, "Neural Pipeline")
        pipeline.pack(fill="x", pady=(0, 10))
        self.pipeline_vars = {}
        self.pipeline_labels = {}
        for step in ("MIC", "EAR", "MIND", "HANDS", "VOICE"):
            value = tk.StringVar(value=step)
            self.pipeline_vars[step] = value
            label = tk.Label(
                pipeline, textvariable=value, anchor="center",
                font=("Consolas", 8, "bold"), fg=MUTED, bg="#08121c",
                padx=3, pady=7,
            )
            label.pack(side="left", fill="x", expand=True, padx=2, pady=2)
            self.pipeline_labels[step] = label

        chat = self._panel(self.left, "Telemetry Logs & Chat")
        chat.pack(fill="both", expand=True)
        self._build_chat(chat)

    def _build_hologram(self):
        self.holo = tk.Canvas(
            self.center, bg="#02070d", highlightthickness=1,
            highlightbackground=self.theme["glow"],
        )
        self.holo.pack(fill="both", expand=True)
        self.holo.bind("<Configure>", self._on_hologram_resize)
        self.center_note = tk.Label(
            self.center, text="SYSTEM CORE  //  HOLOGRAPHIC INTERFACE",
            font=("Consolas", 10, "bold"), fg=self.theme["accent"], bg=BG,
        )
        self.center_note.pack(fill="x", pady=(10, 0))

    def _build_right(self):
        style = ttk.Style()
        style.configure(
            "Treeview", background="#07101a", fieldbackground="#07101a",
            foreground=TEXT, rowheight=27, borderwidth=0,
        )
        style.configure(
            "Treeview.Heading", background=PANEL, foreground=self.theme["accent"],
            font=("Consolas", 8, "bold"),
        )
        self._build_market()
        briefs = self._panel(self.right, "Executive Briefings & Inbox")
        briefs.pack(fill="both", expand=True, pady=10)
        self.brief_text = tk.Text(
            briefs, bg="#07101a", fg=TEXT, relief="flat", wrap="word",
            font=("Segoe UI", 9), padx=8, pady=8,
        )
        self.brief_text.pack(fill="both", expand=True)
        self.brief_text.insert(
            "end", "Say “check my unread emails” to hear your inbox briefing.\n\n"
                   "Market signals and assistant updates will appear here.",
        )
        self.brief_text.configure(state="disabled")
        telemetry = self._panel(self.right, "Hardware Vitals")
        telemetry.pack(fill="x")
        self.vital_vars = {}
        for label in ("CPU", "MEMORY", "DISK", "UPTIME"):
            row = tk.Frame(telemetry, bg=PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(
                row, text=label, width=9, anchor="w", font=("Consolas", 8),
                fg=MUTED, bg=PANEL,
            ).pack(side="left")
            value = tk.StringVar(value="--")
            self.vital_vars[label] = value
            tk.Label(
                row, textvariable=value, font=("Consolas", 8, "bold"),
                fg=TEXT, bg=PANEL,
            ).pack(side="right")

    def _build_chat(self, parent):
        self.chat_log = tk.Text(
            parent, bg="#07101a", fg=TEXT, insertbackground=TEXT,
            relief="flat", wrap="word", font=("Segoe UI", 10), padx=8, pady=8,
            state="disabled",
        )
        self.chat_log.pack(fill="both", expand=True)
        self.chat_log.tag_configure("you", foreground=self.theme["accent"])
        self.chat_log.tag_configure("jarvis", foreground="#75ffbd")
        self.chat_log.tag_configure("sys", foreground=MUTED)
        entry_row = tk.Frame(parent, bg=PANEL)
        entry_row.pack(fill="x", pady=(8, 0))
        self.command_entry = tk.Entry(
            entry_row, bg="#07101a", fg=TEXT, insertbackground=TEXT,
            relief="flat", font=("Segoe UI", 10),
        )
        self.command_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.command_entry.bind("<Return>", self._submit_command)
        tk.Button(
            entry_row, text="SEND", command=self.send_command, relief="flat",
            bg=self.theme["glow"], fg=TEXT, font=("Consolas", 9, "bold"),
        ).pack(side="right", padx=(6, 0), ipady=6)

    def _build_market(self):
        self.market_panel = self._panel(self.right, "Live Market Intelligence")
        self.market_panel.pack(fill="both", expand=True)
        row = tk.Frame(self.market_panel, bg=PANEL)
        row.pack(fill="x")
        tk.Label(
            row, text="WATCHLIST", fg=MUTED, bg=PANEL,
            font=("Consolas", 8, "bold"),
        ).pack(side="left")
        tk.Button(
            row, text="REFRESH", command=self.refresh_market, relief="flat",
            bg=self.theme["glow"], fg=TEXT, font=("Consolas", 8, "bold"),
        ).pack(side="right")
        columns = ("symbol", "price", "change", "signal")
        self.market_tree = ttk.Treeview(
            self.market_panel, columns=columns, show="headings", height=11,
        )
        for column, title, width in (
            ("symbol", "ASSET", 95), ("price", "PRICE", 75),
            ("change", "CHANGE", 65), ("signal", "SIGNAL", 95),
        ):
            self.market_tree.heading(column, text=title)
            self.market_tree.column(column, width=width, anchor="w")
        self.market_tree.pack(fill="both", expand=True, pady=(10, 0))
        self.market_tree.insert(
            "", "end", values=("—", "Press REFRESH", "", "—"),
        )

    def _build_settings(self, parent):
        tk.Label(
            parent, text="PERSONALIZE JARVIS",
            font=("Consolas", 10, "bold"), fg=self.theme["accent"], bg=PANEL,
        ).pack(anchor="w", pady=(0, 12))

        self.theme_var = tk.StringVar(value=self.settings["theme"])
        self.speech_var = tk.BooleanVar(value=self.settings["speech_enabled"])
        self.autostart_var = tk.BooleanVar(value=self.settings["autostart_listening"])
        self.rate_var = tk.IntVar(value=self.settings["speech_rate"])
        self._setting_label(parent, "Hologram color")
        ttk.Combobox(
            parent, textvariable=self.theme_var,
            values=list(THEMES), state="readonly",
        ).pack(fill="x", pady=(0, 10))
        self.theme_var.trace_add("write", self._theme_changed)
        tk.Checkbutton(
            parent, text="Speak answers aloud",
            variable=self.speech_var, bg=PANEL, fg=TEXT,
            activebackground=PANEL, activeforeground=TEXT, selectcolor=BG,
        ).pack(anchor="w", pady=4)
        tk.Checkbutton(
            parent, text="Start listening on launch",
            variable=self.autostart_var, bg=PANEL, fg=TEXT,
            activebackground=PANEL, activeforeground=TEXT, selectcolor=BG,
        ).pack(anchor="w", pady=4)
        self._setting_label(parent, "Speech rate")
        tk.Scale(
            parent, from_=-10, to=10, orient="horizontal",
            variable=self.rate_var, bg=PANEL, fg=TEXT, troughcolor=BG,
            highlightthickness=0, activebackground=self.theme["accent"],
            showvalue=True,
        ).pack(fill="x", pady=(0, 10))

        self._setting_label(parent, "Groq API key (optional)")
        self.key_entry = tk.Entry(
            parent, show="*", bg="#07101a", fg=TEXT,
            insertbackground=TEXT, relief="flat",
        )
        self.key_entry.pack(fill="x", ipady=7, pady=(0, 5))
        self.key_status = tk.StringVar(
            value="Key configured" if jarvis_brain._get_api_key() else "No key configured"
        )
        tk.Label(
            parent, textvariable=self.key_status,
            fg=MUTED, bg=PANEL, font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 8))
        tk.Button(
            parent, text="SAVE API KEY", command=self.save_key,
            relief="flat", bg=self.theme["glow"], fg=TEXT,
            font=("Consolas", 9, "bold"),
        ).pack(fill="x", pady=(0, 12))
        tk.Button(
            parent, text="SAVE SETTINGS", command=self.save_settings,
            relief="flat", bg=self.theme["glow"], fg=TEXT,
            font=("Consolas", 9, "bold"),
        ).pack(fill="x")
        tk.Label(
            parent,
            text="The key is stored locally in your user profile.",
            wraplength=300, justify="left", fg=MUTED, bg=PANEL,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(8, 0))

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            return
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Jarvis Settings")
        self.settings_window.configure(bg=PANEL)
        self.settings_window.geometry("390x470")
        self.settings_window.resizable(False, False)
        self.settings_window.transient(self.root)
        self._build_settings(self.settings_window)

    def _submit_command(self, event):
        if event is None:
            return None
        self.send_command()
        return "break"

    def _theme_changed(self, *args):
        if args:
            self._apply_theme()

    def _setting_label(self, parent, text):
        tk.Label(
            parent, text=text, fg=MUTED, bg=PANEL,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 5))

    def _apply_theme(self):
        self.theme = (
            THEMES.get(self.theme_var.get(), THEMES["Cyan"])
            if hasattr(self, "theme_var")
            else THEMES[self.settings["theme"]]
        )
        for frame in getattr(self, "panel_frames", []):
            frame.configure(highlightbackground=self.theme["glow"])
        for title in getattr(self, "panel_titles", []):
            title.configure(fg=self.theme["accent"])
        if hasattr(self, "holo"):
            self.holo.configure(highlightbackground=self.theme["glow"])
            self.center_note.configure(fg=self.theme["accent"])
            self.start_button.configure(bg=self.theme["glow"])
            self.wave.configure(highlightbackground=self.theme["glow"])
            for step, label in getattr(self, "pipeline_labels", {}).items():
                label.configure(fg=self.theme["accent"] if self.pipeline_vars[step].get().startswith("●") else MUTED)
            self.chat_log.tag_configure("you", foreground=self.theme["accent"])
            if hasattr(self, "market_tree"):
                style = ttk.Style()
                style.configure(
                    "Treeview.Heading", background=PANEL,
                    foreground=self.theme["accent"],
                )
            self._draw_hologram()

    def save_settings(self):
        self.settings.update({
            "theme": self.theme_var.get(),
            "speech_enabled": self.speech_var.get(),
            "speech_rate": self.rate_var.get(),
            "autostart_listening": self.autostart_var.get(),
        })
        try:
            path = _settings_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as settings_file:
                json.dump(self.settings, settings_file, indent=2)
        except OSError as exc:
            messagebox.showerror("Settings", f"Could not save settings:\n{exc}")
            return
        self.note_var.set("Settings saved")

    def save_key(self):
        key = self.key_entry.get().strip()
        if not key:
            messagebox.showinfo("API key", "Enter a key first. Your existing key is unchanged.")
            return
        try:
            jarvis_brain.save_api_key(key)
        except OSError as exc:
            messagebox.showerror("API key", f"Could not save the key:\n{exc}")
            return
        self.key_entry.delete(0, "end")
        self.key_status.set("Key configured")
        self.note_var.set("API key saved")

    def add_message(self, speaker, message):
        self.chat_count += 1
        tag = "you" if speaker == "YOU" else "jarvis" if speaker == "JARVIS" else "sys"
        self.chat_log.configure(state="normal")
        self.chat_log.insert("end", f"{speaker}  ", tag)
        self.chat_log.insert("end", message + "\n\n")
        self.chat_log.see("end")
        self.chat_log.configure(state="disabled")

    def send_command(self):
        query = self.command_entry.get().strip()
        if not query:
            return
        self.command_entry.delete(0, "end")
        self.add_message("YOU", query)
        threading.Thread(
            target=self._answer_query, args=(query,), daemon=True,
        ).start()

    def _answer_query(self, query):
        with self.command_lock:
            self.events.put(("state", "PROCESSING", "Thinking"))
            try:
                response = jarvis_brain.think(query)
            except Exception as exc:
                self.events.put(("message", "SYS", f"Request failed: {exc}"))
                self.events.put(("state", "READY", "Request failed"))
                return
            self.events.put(("message", "JARVIS", response))
            self._speak(response)
            self.events.put(("state", "READY", "Ready"))

    def _speak(self, text):
        self.events.put(("state", "SPEAKING", "Speaking"))
        with self.speech_lock:
            jarvis_voice.speak(
                text,
                enabled=self.settings["speech_enabled"],
                rate=self.settings["speech_rate"],
                print_output=False,
            )

    def start_assistant(self):
        if self.voice_thread and self.voice_thread.is_alive():
            return
        self.stop_event = threading.Event()
        self.voice_thread = threading.Thread(
            target=self._voice_worker, args=(self.stop_event,), daemon=True,
        )
        self.voice_thread.start()
        self.note_var.set("Starting microphone")

    def stop_assistant(self):
        if self.stop_event:
            self.stop_event.set()
        self.status_var.set("STOPPING")
        self.note_var.set("Stopping microphone")

    def _voice_worker(self, stop_event):
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        try:
            mic = jarvis_voice._create_microphone()
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.6)
            self.events.put(("state", "LISTENING", "Microphone ready"))
        except Exception as exc:
            self.events.put(("message", "SYS", f"Microphone unavailable: {exc}"))
            self.events.put(("state", "READY", "Check microphone permissions"))
            return

        while not stop_event.is_set():
            self.events.put(("state", "LISTENING", "Listening for a command"))
            try:
                with mic as source:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=8)
            except sr.WaitTimeoutError:
                continue
            except Exception as exc:
                if not stop_event.is_set():
                    self.events.put(("message", "SYS", f"Microphone error: {exc}"))
                    self.events.put(("state", "READY", "Microphone error"))
                break

            if stop_event.is_set():
                break
            self.events.put(("state", "RECOGNIZING", "Recognizing speech"))
            try:
                query = recognizer.recognize_google(audio).strip()
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                self.events.put(("message", "SYS", f"Speech recognition failed: {exc}"))
                continue
            if not query:
                continue
            self.events.put(("message", "YOU", query))
            cleaned = query.lower().replace("jarvis", "").strip(" ,.!?")
            if jarvis_voice._is_shutdown_command(cleaned):
                self.events.put(("voice_shutdown",))
                stop_event.set()
                break

            with self.command_lock:
                self.events.put(("state", "PROCESSING", "Thinking"))
                try:
                    response = jarvis_brain.think(cleaned)
                except Exception as exc:
                    self.events.put(("message", "SYS", f"Request failed: {exc}"))
                    continue
                self.events.put(("message", "JARVIS", response))
                self._speak(response)

        self.events.put(("state", "READY", "Assistant stopped"))

    def refresh_market(self):
        self.note_var.set("Refreshing market data")
        threading.Thread(target=self._market_worker, daemon=True).start()

    def _market_worker(self):
        try:
            results = jarvis_market.get_market_watchlist()
            self.events.put(("market", results))
        except Exception as exc:
            self.events.put(("message", "SYS", f"Market refresh failed: {exc}"))
        finally:
            self.events.put(("note", "Market refresh complete"))

    def _drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "message":
                    self.add_message(event[1], event[2])
                elif kind == "state":
                    self.status_var.set(event[1])
                    self.note_var.set(event[2])
                    self.current_state = event[1]
                    self._set_pipeline(event[1])
                elif kind == "market":
                    self._show_market(event[1])
                elif kind == "note":
                    self.note_var.set(event[1])
                elif kind == "voice_shutdown":
                    self._after(0, self.close)
        except queue.Empty:
            pass
        if not self._closed and self.root.winfo_exists():
            self._after(50, self._drain_events)

    def _set_pipeline(self, state):
        active = {
            "LISTENING": "MIC", "RECOGNIZING": "EAR",
            "PROCESSING": "MIND", "SPEAKING": "VOICE",
        }.get(state)
        for step, variable in self.pipeline_vars.items():
            marker = "●" if step == active else "○"
            variable.set(f"{marker}  {step}")
            self.pipeline_labels[step].configure(
                fg=self.theme["accent"] if step == active else MUTED,
            )

    def _show_market(self, results):
        for item in self.market_tree.get_children():
            self.market_tree.delete(item)
        for item in results:
            change = f"{item['pct_change']:+.2f}%"
            self.market_tree.insert(
                "", "end",
                values=(
                    item["name"], f"{item['currency']}{item['price']:,.2f}",
                    change, item["signal"],
                ),
            )
        if not results:
            self.market_tree.insert(
                "", "end", values=("—", "No market data available", "", "—"),
            )

    def _update_telemetry(self):
        if not self.root.winfo_exists():
            return
        now = time.localtime()
        self.time_var.set(time.strftime("%H:%M:%S", now))
        self.date_var.set(time.strftime("%A, %d %B %Y", now).upper())
        self.vital_vars["CPU"].set(f"{psutil.cpu_percent():.0f}%")
        self.vital_vars["MEMORY"].set(f"{psutil.virtual_memory().percent:.0f}%")
        self.vital_vars["DISK"].set(f"{psutil.disk_usage(os.path.abspath(os.sep)).percent:.0f}%")
        elapsed = int(time.monotonic() - self.started_at)
        self.vital_vars["UPTIME"].set(f"{elapsed // 60}m {elapsed % 60}s")
        self._after(1000, self._update_telemetry)

    def _schedule_market_refresh(self):
        if self.root.winfo_exists():
            self.refresh_market()
            self._after(90000, self._schedule_market_refresh)

    def _on_hologram_resize(self, event):
        self._draw_hologram(event.width, event.height)

    def _draw_wave(self):
        width = max(1, self.wave.winfo_width())
        height = max(1, self.wave.winfo_height())
        mid = height / 2
        baseline = self.wave_items.get("baseline")
        if baseline is None:
            baseline = self.wave.create_line(0, mid, width, mid, fill=self.theme["glow"])
            self.wave_items["baseline"] = baseline
        else:
            self.wave.coords(baseline, 0, mid, width, mid)
            self.wave.itemconfigure(baseline, fill=self.theme["glow"])
        phase = time.monotonic() * (2.4 if self.current_state == "SPEAKING" else 1)
        amplitude = 0.9 if self.current_state in ("LISTENING", "SPEAKING") else 0.28
        for level in range(4):
            coords = []
            for step in range(61):
                x = step / 60 * width
                envelope = math.sin(step / 60 * math.pi)
                wave = (
                    math.sin(step / 60 * (12 + level * 8) + phase * (2.2 + level))
                    * height * 0.38 * amplitude * envelope * (1 - level * 0.2)
                    + math.sin(step / 60 * 48 + phase * 3) * height * 0.05 * amplitude
                )
                coords.extend((x, mid + wave))
            item = self.wave_items.get(f"wave-{level}")
            options = {
                "fill": self.visual_accent if level == 0 else self.theme["glow"],
                "width": 2 if level == 0 else 1,
                "smooth": True,
            }
            if item is None:
                self.wave_items[f"wave-{level}"] = self.wave.create_line(coords, **options)
            else:
                self.wave.coords(item, *coords)
                self.wave.itemconfigure(item, **options)

    def _draw_hologram(self, canvas_width=None, canvas_height=None):
        if not hasattr(self, "holo"):
            return
        width = max(1, canvas_width or self.holo.winfo_width())
        height = max(1, canvas_height or self.holo.winfo_height())
        cx, cy = width / 2, height / 2
        radius = min(width, height) * 0.31
        target_accent = STATE_COLORS.get(self.current_state, self.theme["accent"])
        self.visual_accent = self._blend_color(self.visual_accent, target_accent, 0.18)
        accent = self.visual_accent
        phase = time.monotonic()
        items = self._holo_items

        def draw(key, kind, coords, **options):
            item = items.get(key)
            if item is None:
                item = getattr(self.holo, f"create_{kind}")(*coords, **options)
                items[key] = item
                self._holo_styles[key] = options.copy()
            else:
                self.holo.coords(item, *coords)
                if self._holo_styles[key] != options:
                    self.holo.itemconfigure(item, **options)
                    self._holo_styles[key] = options.copy()

        # Soft layered light, cyber horizon, and moving particles.
        for index in range(7):
            r = radius * (1.7 - index * 0.17)
            color = ("#061722", "#061a24", "#071d28", "#08212c",
                     "#092630", "#0a2933", "#0b2d36")[index]
            draw(
                ("ambient", index), "oval",
                (cx-r, cy-r, cx+r, cy+r), fill=color, outline="",
            )
        horizon = height * 0.68
        for index in range(14):
            fraction = (index + (phase * 0.35 % 1)) / 14
            y = horizon + fraction * fraction * (height - horizon)
            draw(
                ("grid-h", index), "line", (0, y, width, y),
                fill=self.theme["glow"], width=1,
            )
        for index in range(-10, 11):
            draw(
                ("grid-v", index), "line",
                (cx + index * width * 0.012, horizon,
                 cx + index * width * 0.12, height),
                fill=self.theme["glow"], width=1,
            )
        for index, particle in enumerate(self.particles):
            particle[1] -= particle[2]
            if particle[1] < 0:
                particle[0] = random.random()
                particle[1] = 1
            px, py = particle[0] * width, particle[1] * height
            size = particle[3]
            draw(
                ("particle", index), "oval",
                (px-size, py-size, px+size, py+size),
                fill=accent, outline="",
            )

        # Reactor tick marks and counter-rotating segmented rings.
        for i, fraction in enumerate((1.0, 0.92, 0.82, 0.72, 0.6, 0.46)):
            r = radius * fraction
            rotation = phase * (18 + i * 11) * (1 if i % 2 else -1)
            draw(
                ("ring", i), "oval", (cx-r, cy-r, cx+r, cy+r),
                outline=self.theme["glow"], width=1,
            )
            for segment, (offset, extent) in enumerate(((0, 70), (145, 55), (265, 50))):
                draw(
                    ("arc", i, segment), "arc", (cx-r, cy-r, cx+r, cy+r),
                    start=rotation + offset, extent=extent, style="arc",
                    outline=accent, width=3 if i in (0, 2) else 1,
                )

        for tick in range(100):
            angle = tick / 100 * math.tau + phase * 0.06
            length = 12 if tick % 10 == 0 else 8 if tick % 5 == 0 else 4
            draw(
                ("tick", tick), "line",
                (cx + math.cos(angle) * radius,
                 cy + math.sin(angle) * radius,
                 cx + math.cos(angle) * (radius - length),
                 cy + math.sin(angle) * (radius - length)),
                fill=accent, width=2 if tick % 10 == 0 else 1,
            )

        # Rotating wireframe globe, split into brighter front and dim rear lines.
        rot = phase * 0.65
        globe_r = radius * 0.38
        tilt = 0.42
        for path_index, path in enumerate(self.globe_paths):
            coordinates = []
            depth = 0
            for x, y, z in path:
                xr = x * math.cos(rot) + z * math.sin(rot)
                zr = -x * math.sin(rot) + z * math.cos(rot)
                y2 = y * math.cos(tilt) - zr * math.sin(tilt)
                depth += y * math.sin(tilt) + zr * math.cos(tilt)
                coordinates.extend((cx + xr * globe_r, cy + y2 * globe_r))
            line_color = accent if depth >= 0 else self.theme["glow"]
            draw(
                ("globe", path_index), "line", coordinates,
                fill=line_color, width=1, smooth=True,
            )

        # Plasma core and rotating aperture.
        pulse = 1 + 0.05 * math.sin(phase * 3.5) + 0.02 * math.sin(phase * 7)
        core = radius * 0.16 * pulse
        for i, scale in enumerate((2.3, 1.65, 1.1, 0.62, 0.24)):
            r = core * scale
            fill = ("#082b36", "#0b6270", "#19b5c3", accent, "#ffffff")[i]
            draw(
                ("core", i), "oval", (cx-r, cy-r, cx+r, cy+r),
                fill=fill, outline=accent,
            )
        for blade in range(12):
            angle = phase * 0.5 + blade * math.tau / 12
            outer = radius * 0.34
            draw(
                ("blade", blade), "arc",
                (cx-outer, cy-outer, cx+outer, cy+outer),
                start=math.degrees(angle), extent=14, style="arc",
                outline=TEXT, width=3,
            )
        for index in range(12):
            angle = phase * (0.8 + (index % 4) * 0.1) + index * math.tau / 12
            x = cx + math.cos(angle) * radius * (0.85 + (index % 3) * 0.12)
            y = cy + math.sin(angle) * radius * 0.65
            draw(
                ("node", index), "oval", (x-3, y-3, x+3, y+3),
                fill="#ffffff", outline=accent,
            )
        for index in range(4):
            r = radius * (0.52 + index * 0.08)
            draw(
                ("radar", index), "arc", (cx-r, cy-r, cx+r, cy+r),
                start=(phase * 80 + index * 90) % 360, extent=28,
                style="arc", outline=accent, width=2,
            )
        draw(
            "title", "text", (cx, cy-radius*1.28),
            text="QUANTUM REACTOR", fill=TEXT,
            font=("Consolas", 12, "bold"),
        )
        draw(
            "footer", "text", (cx, cy+radius*1.8),
            text="J.A.R.V.I.S  //  CORE ONLINE", fill=accent,
            font=("Consolas", 10, "bold"),
        )
        self._holo_frame += 1

    @staticmethod
    def _blend_color(current, target, amount):
        current_rgb = tuple(int(current[index:index + 2], 16) for index in (1, 3, 5))
        target_rgb = tuple(int(target[index:index + 2], 16) for index in (1, 3, 5))
        blended = tuple(
            round(start + (end - start) * amount)
            for start, end in zip(current_rgb, target_rgb)
        )
        return "#" + "".join(f"{channel:02x}" for channel in blended)

    def _animate(self):
        if not self.root.winfo_exists():
            return
        if self.root.state() != "iconic":
            self._draw_hologram()
            self._draw_wave()
        self._after(25, self._animate)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.stop_event:
            self.stop_event.set()
        for callback_id in self._after_ids:
            try:
                self.root.after_cancel(callback_id)
            except tk.TclError:
                pass
        self._after_ids.clear()
        self.root.destroy()


def main():
    log_path = os.path.join(os.path.dirname(_settings_path()), "jarvis.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_file:
        sys.stdout = log_file
        sys.stderr = log_file
        root = tk.Tk()
        if sys.platform == "win32":
            root.state("zoomed")
        JarvisDesktop(root)
        root.mainloop()


if __name__ == "__main__":
    main()
