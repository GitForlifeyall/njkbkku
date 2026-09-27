"""
YouTube Shorts Uploader GUI
===========================
Modern desktop interface for automating YouTube Shorts uploads to Redroid containers.
Features real-time colored logging, instant pause/resume, account switching, and screen mirroring.
"""

import sys
import os
import time
import queue
import threading
import importlib
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

# Import uploader backend logic
import upload_short as backend

DARK_BG = "#121318"
DARK_CARD = "#1c1e26"
DARK_INPUT = "#262936"
ACCENT_PRIMARY = "#ff0033"      # YouTube Red
ACCENT_BLUE = "#3b82f6"         # Action Blue
ACCENT_GREEN = "#10b981"        # Success Green
ACCENT_YELLOW = "#f59e0b"       # Warning / Pause
ACCENT_PURPLE = "#8b5cf6"
TEXT_COLOR = "#f3f4f6"
TEXT_MUTED = "#9ca3af"
BORDER_COLOR = "#2d3243"


class YouTubeUploaderGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Shorts Studio - Redroid Automation")
        self.geometry("960x780")
        self.minsize(840, 680)
        self.configure(bg=DARK_BG)

        # Threading & Control Flags
        self.log_queue = queue.Queue()
        self.pause_event = threading.Event()
        self.pause_event.set()  # set = running / not paused
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.is_running = False

        self._setup_styles()
        self._build_ui()
        self._check_log_queue()

    def _setup_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(".", background=DARK_BG, foreground=TEXT_COLOR)
        self.style.configure("TFrame", background=DARK_BG)
        self.style.configure("Card.TFrame", background=DARK_CARD, relief="flat")
        self.style.configure("TLabel", background=DARK_BG, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        self.style.configure("Card.TLabel", background=DARK_CARD, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background=DARK_BG, foreground="#ffffff", font=("Segoe UI", 16, "bold"))
        self.style.configure("SubHeader.TLabel", background=DARK_BG, foreground=TEXT_MUTED, font=("Segoe UI", 9))
        self.style.configure("CardTitle.TLabel", background=DARK_CARD, foreground="#ffffff", font=("Segoe UI", 11, "bold"))

        # Button Styles
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background=ACCENT_PRIMARY, foreground="#ffffff", borderwidth=0, padding=8)
        self.style.map("Primary.TButton", background=[("active", "#d9002c"), ("disabled", "#552026")])

        self.style.configure("Pause.TButton", font=("Segoe UI", 10, "bold"), background=ACCENT_YELLOW, foreground="#111111", borderwidth=0, padding=8)
        self.style.map("Pause.TButton", background=[("active", "#d98200"), ("disabled", "#443a20")])

        self.style.configure("Action.TButton", font=("Segoe UI", 10), background=DARK_INPUT, foreground=TEXT_COLOR, borderwidth=0, padding=6)
        self.style.map("Action.TButton", background=[("active", BORDER_COLOR)])

        self.style.configure("Mirror.TButton", font=("Segoe UI", 10), background=ACCENT_BLUE, foreground="#ffffff", borderwidth=0, padding=6)
        self.style.map("Mirror.TButton", background=[("active", "#2563eb")])

        self.style.configure("Stop.TButton", font=("Segoe UI", 10), background="#ef4444", foreground="#ffffff", borderwidth=0, padding=8)
        self.style.map("Stop.TButton", background=[("active", "#dc2626"), ("disabled", "#4b2222")])

        # Entry & Combobox
        self.style.configure("TEntry", fieldbackground=DARK_INPUT, foreground=TEXT_COLOR, borderwidth=1, insertcolor=TEXT_COLOR)
        self.style.configure("TCombobox", fieldbackground=DARK_INPUT, background=DARK_INPUT, foreground=TEXT_COLOR)
        self.style.map("TCombobox", fieldbackground=[("readonly", DARK_INPUT)], selectbackground=[("readonly", DARK_INPUT)])

    def _build_ui(self):
        # Top Bar (Header & Screen Mirror button)
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", padx=20, pady=(16, 12))

        title_box = ttk.Frame(header_frame)
        title_box.pack(side="left")
        ttk.Label(title_box, text="▶ YouTube Shorts Studio", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Automated Redroid multi-instance short publisher", style="SubHeader.TLabel").pack(anchor="w")

        # Top Right Actions
        top_actions = ttk.Frame(header_frame)
        top_actions.pack(side="right")

        self.btn_scrcpy = ttk.Button(top_actions, text="📱 Open Screen Mirror", style="Mirror.TButton", command=self._launch_scrcpy)
        self.btn_scrcpy.pack(side="right", padx=4)

        # Main Layout (Left: Settings / Controls, Right: Live Logs)
        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=20, pady=8)

        # Left Column: Configuration Card
        left_pane = ttk.Frame(content, style="Card.TFrame", padding=16)
        left_pane.pack(side="left", fill="y", padx=(0, 10))
        left_pane.config(width=340)
        left_pane.pack_propagate(False)

        ttk.Label(left_pane, text="Upload Configuration", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 12))

        # Target Account
        ttk.Label(left_pane, text="Redroid Account Container:", style="Card.TLabel").pack(anchor="w", pady=(4, 2))
        self.account_var = tk.StringVar(value="01")
        acc_combo = ttk.Combobox(left_pane, textvariable=self.account_var, values=["01", "02", "03", "04", "05"], state="readonly")
        acc_combo.pack(fill="x", pady=(0, 10))

        # Video File Selection
        ttk.Label(left_pane, text="Video File (.mp4):", style="Card.TLabel").pack(anchor="w", pady=(4, 2))
        file_box = ttk.Frame(left_pane, style="Card.TFrame")
        file_box.pack(fill="x", pady=(0, 10))

        self.video_path_var = tk.StringVar()
        self.video_entry = tk.Entry(file_box, textvariable=self.video_path_var, bg=DARK_INPUT, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, relief="flat", highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.video_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

        btn_browse = ttk.Button(file_box, text="Browse...", style="Action.TButton", command=self._browse_video)
        btn_browse.pack(side="right")

        # Video Title
        ttk.Label(left_pane, text="Short Title (with #shorts):", style="Card.TLabel").pack(anchor="w", pady=(4, 2))
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(left_pane, textvariable=self.title_var, bg=DARK_INPUT, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, relief="flat", highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.title_entry.pack(fill="x", ipady=4, pady=(0, 10))

        # Sound Search & Timestamp (Optional)
        ttk.Label(left_pane, text="Add Music Track (Optional Search):", style="Card.TLabel").pack(anchor="w", pady=(4, 2))
        self.sound_var = tk.StringVar()
        self.sound_entry = tk.Entry(left_pane, textvariable=self.sound_var, bg=DARK_INPUT, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, relief="flat", highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.sound_entry.pack(fill="x", ipady=4, pady=(0, 10))

        ttk.Label(left_pane, text="Audio Timestamp (e.g. '0:30', 'random', or empty):", style="Card.TLabel").pack(anchor="w", pady=(4, 2))
        self.timestamp_var = tk.StringVar()
        self.timestamp_entry = tk.Entry(left_pane, textvariable=self.timestamp_var, bg=DARK_INPUT, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, relief="flat", highlightthickness=1, highlightbackground=BORDER_COLOR)
        self.timestamp_entry.pack(fill="x", ipady=4, pady=(0, 16))

        # Separator
        ttk.Separator(left_pane, orient="horizontal").pack(fill="x", pady=8)

        # Status Badge Indicator
        self.status_frame = tk.Frame(left_pane, bg=DARK_CARD)
        self.status_frame.pack(fill="x", pady=(4, 16))
        ttk.Label(self.status_frame, text="Status:", style="Card.TLabel").pack(side="left")
        self.status_label = tk.Label(self.status_frame, text="IDLE", bg=DARK_INPUT, fg=TEXT_MUTED, font=("Segoe UI", 9, "bold"), padx=10, pady=3)
        self.status_label.pack(side="right")

        # Control Action Buttons
        self.btn_start = ttk.Button(left_pane, text="🚀 START UPLOAD", style="Primary.TButton", command=self._start_upload)
        self.btn_start.pack(fill="x", pady=(0, 8))

        ctrl_row = ttk.Frame(left_pane, style="Card.TFrame")
        ctrl_row.pack(fill="x", pady=(0, 8))

        self.btn_pause = ttk.Button(ctrl_row, text="⏸ Pause", style="Pause.TButton", command=self._toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_stop = ttk.Button(ctrl_row, text="⏹ Stop", style="Stop.TButton", command=self._stop_upload, state="disabled")
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Right Column: Live Terminal Logs
        right_pane = ttk.Frame(content, style="Card.TFrame", padding=14)
        right_pane.pack(side="right", fill="both", expand=True)

        log_top = ttk.Frame(right_pane, style="Card.TFrame")
        log_top.pack(fill="x", pady=(0, 8))
        ttk.Label(log_top, text="Real-Time Automation Logs", style="CardTitle.TLabel").pack(side="left")

        btn_clear = ttk.Button(log_top, text="Clear Log", style="Action.TButton", command=self._clear_logs)
        btn_clear.pack(side="right")

        # Styled ScrolledText for colored logs
        self.log_text = ScrolledText(
            right_pane,
            wrap="word",
            bg="#0d0e12",
            fg="#e5e7eb",
            insertbackground="#ffffff",
            font=("Consolas", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR
        )
        self.log_text.pack(fill="both", expand=True)

        # Setup Log Color Tags
        self.log_text.tag_config("time", foreground="#6b7280")
        self.log_text.tag_config("info", foreground="#60a5fa")
        self.log_text.tag_config("success", foreground="#34d399", font=("Consolas", 10, "bold"))
        self.log_text.tag_config("warn", foreground="#fbbf24")
        self.log_text.tag_config("error", foreground="#f87171", font=("Consolas", 10, "bold"))
        self.log_text.tag_config("header", foreground="#c084fc", font=("Consolas", 10, "bold"))
        self.log_text.tag_config("normal", foreground="#e5e7eb")

        # Initial greeting log
        self._append_log_message("[*] YouTube Shorts Studio ready.", "info")
        self._append_log_message("[*] Select your video and click 'START UPLOAD' to begin.", "normal")

        # Pre-fill sample if available
        sample_path = Path(r"c:\Users\khann\OneDrive\Documents\Projects\insta uploader\ytuploader\upload files\sample_short.mp4")
        if sample_path.exists():
            self.video_path_var.set(str(sample_path))
            self.title_var.set(sample_path.stem + " #shorts")

    def _browse_video(self):
        f = filedialog.askopenfilename(
            title="Select Video File",
            filetypes=[("MP4 Videos", "*.mp4"), ("All Videos", "*.mp4;*.mov;*.mkv;*.webm"), ("All Files", "*.*")]
        )
        if f:
            self.video_path_var.set(f)
            stem = Path(f).stem
            if not self.title_var.get() or self.title_var.get() == "sample_short #shorts":
                self.title_var.set(f"{stem} #shorts")

    def _set_status(self, text: str, bg_color: str, fg_color: str = "#ffffff"):
        self.status_label.config(text=text, bg=bg_color, fg=fg_color)

    def _append_log_message(self, text: str, level: str = "normal"):
        now_str = time.strftime("[%H:%M:%S] ")
        self.log_text.insert("end", now_str, "time")
        self.log_text.insert("end", text + "\n", level)
        self.log_text.see("end")

    def _log_callback(self, msg: str):
        # Classify message style
        lvl = "normal"
        s = msg.strip()
        if s.startswith("[+]") or "SUCCESS" in s:
            lvl = "success"
        elif s.startswith("[*]"):
            lvl = "info"
        elif s.startswith("[!]"):
            lvl = "warn"
        elif "Error" in s or "failed" in s.lower() or "exception" in s.lower():
            lvl = "error"
        elif s.startswith("===") or s.startswith("---"):
            lvl = "header"

        self.log_queue.put((msg, lvl))

    def _check_log_queue(self):
        while not self.log_queue.empty():
            try:
                msg, lvl = self.log_queue.get_nowait()
                self._append_log_message(msg, lvl)
            except queue.Empty:
                break
        self.after(100, self._check_log_queue)

    def _clear_logs(self):
        self.log_text.delete("1.0", "end")

    def _launch_scrcpy(self):
        acc = self.account_var.get().strip() or "01"
        port = 5800 + int(acc)
        target = f"127.0.0.1:{port}"
        scrcpy_exe = backend.find_tool("scrcpy", backend.DEFAULT_SCRCPY)
        self._append_log_message(f"[*] Launching scrcpy for container {acc} ({target})...", "info")
        backend.launch_scrcpy(scrcpy_exe, target, log_fn=self._log_callback)

    def _start_upload(self):
        video_path = self.video_path_var.get().strip()
        if not video_path or not Path(video_path).exists():
            messagebox.showerror("Invalid File", "Please select a valid video file (.mp4) first.")
            return

        # Hot-reload backend module to always use the freshest script edits
        global backend
        try:
            backend = importlib.reload(backend)
            self._append_log_message("[+] Loaded latest upload_short.py script fresh.", "info")
        except Exception as e:
            self._append_log_message(f"[!] Warning: Could not reload backend module: {e}", "warn")

        title = self.title_var.get().strip() or Path(video_path).stem
        sound_query = self.sound_var.get().strip() or None
        timestamp_query = self.timestamp_var.get().strip() or None
        acc = self.account_var.get().strip() or "01"
        port = 5800 + int(acc)
        target = f"127.0.0.1:{port}"

        self.is_running = True
        self.pause_event.set()
        self.stop_event.clear()

        # Update Buttons & Status
        self.btn_start.config(state="disabled")
        self.btn_pause.config(state="normal", text="⏸ Pause", style="Pause.TButton")
        self.btn_stop.config(state="normal")
        self._set_status("UPLOADING", ACCENT_PRIMARY)

        # Run upload worker thread
        self.worker_thread = threading.Thread(
            target=self._upload_worker,
            args=(target, video_path, title, sound_query, timestamp_query),
            daemon=True
        )
        self.worker_thread.start()

    def _upload_worker(self, target: str, video_path: str, title: str, sound: Optional[str], timestamp: Optional[str]):
        adb_exe = backend.find_tool("adb", backend.DEFAULT_ADB)
        try:
            self._log_callback(f"[*] Initializing connection to {target}...")
            live_target = backend.connect_adb(adb_exe, target, log_fn=self._log_callback)

            # Check stopped before starting
            if self.stop_event.is_set():
                raise backend.UploadCancelledException("Upload cancelled by user.")

            backend.upload_short_to_youtube(
                adb_exe=adb_exe,
                target=live_target,
                video_path=video_path,
                title=title,
                sound=sound,
                timestamp=timestamp,
                log_fn=self._log_callback,
                pause_event=self.pause_event,
                stop_event=self.stop_event
            )
            self._log_callback(f"[SUCCESS] YouTube Short '{title}' published successfully!")
            self.after(0, lambda: self._on_finish("COMPLETED", ACCENT_GREEN))

        except backend.UploadCancelledException:
            self._log_callback("[!] Upload process stopped by user.")
            self.after(0, lambda: self._on_finish("STOPPED", ACCENT_YELLOW))
        except Exception as e:
            self._log_callback(f"[!] Upload Error: {str(e)}")
            self.after(0, lambda: self._on_finish("ERROR", ACCENT_PRIMARY))

    def _toggle_pause(self):
        if not self.is_running:
            return

        if self.pause_event.is_set():
            # Trigger Instant Pause
            self.pause_event.clear()
            self.btn_pause.config(text="▶ Resume", style="Primary.TButton")
            self._set_status("PAUSED", ACCENT_YELLOW, "#111111")
            self._log_callback("[!] Automation PAUSED immediately. Click Resume to continue.")
        else:
            # Resume
            self.pause_event.set()
            self.btn_pause.config(text="⏸ Pause", style="Pause.TButton")
            self._set_status("UPLOADING", ACCENT_PRIMARY)
            self._log_callback("[+] Automation RESUMED.")

    def _stop_upload(self):
        if not self.is_running:
            return

        if messagebox.askyesno("Stop Upload", "Are you sure you want to stop the current upload?"):
            self._log_callback("[*] Stopping upload process...")
            self.stop_event.set()
            self.pause_event.set()  # Unblock pause if paused so thread can exit immediately
            self.btn_stop.config(state="disabled")
            self.btn_pause.config(state="disabled")

    def _on_finish(self, status_text: str, status_color: str):
        self.is_running = False
        self.btn_start.config(state="normal")
        self.btn_pause.config(state="disabled", text="⏸ Pause", style="Pause.TButton")
        self.btn_stop.config(state="disabled")
        self._set_status(status_text, status_color)


def main():
    app = YouTubeUploaderGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
