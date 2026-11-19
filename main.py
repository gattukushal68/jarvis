"""AETHER desktop assistant. Responsive Tkinter UI; works on desktop Windows/Linux."""
from __future__ import annotations
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk

from security_firewall import SelfHealingShield
from jarvis_core import JarvisEngine, CREATIONS_DIR


class AetherApp:
    BG = "#f4f6fa"
    PANEL = "#ffffff"
    TEXT = "#172033"
    MUTED = "#65718a"
    ACCENT = "#2563eb"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AETHER — Personal Assistant")
        self.root.geometry("760x720")
        self.root.minsize(360, 560)
        self.root.configure(bg=self.BG)
        self.shield = SelfHealingShield()
        self.engine = JarvisEngine(
            firewall=self.shield,
            output_cb=self.thread_safe_log,
            state_cb=self.thread_safe_state,
        )
        self._build_ui()
        self.log_message("AETHER", "Ready. Ask a question or try: time, open chrome, screenshot.")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=self.PANEL, padx=16, pady=12)
        header.pack(fill=tk.X)
        tk.Label(header, text="AETHER", bg=self.PANEL, fg=self.TEXT,
                 font=("Segoe UI", 17, "bold")).pack(side=tk.LEFT)
        self.status = tk.Label(header, text="● Ready", bg=self.PANEL, fg="#15803d",
                               font=("Segoe UI", 9))
        self.status.pack(side=tk.RIGHT)

        body = tk.Frame(self.root, bg=self.BG, padx=12, pady=12)
        body.pack(fill=tk.BOTH, expand=True)
        self.console = scrolledtext.ScrolledText(
            body, wrap=tk.WORD, bg=self.PANEL, fg=self.TEXT,
            insertbackground=self.TEXT, relief=tk.FLAT, borderwidth=0,
            font=("Segoe UI", 10), padx=12, pady=12, state=tk.DISABLED
        )
        self.console.pack(fill=tk.BOTH, expand=True)
        self.console.tag_config("speaker", foreground=self.ACCENT, font=("Segoe UI", 9, "bold"))
        self.console.tag_config("body", foreground=self.TEXT, font=("Segoe UI", 10))

        actions = tk.Frame(self.root, bg=self.BG, padx=12)
        actions.pack(fill=tk.X)
        tk.Button(actions, text="Attach file", command=self.pick_file, relief=tk.FLAT,
                  bg="#e8edf7", fg=self.TEXT, padx=12, pady=8).pack(side=tk.LEFT)
        self.file_label = tk.Label(actions, text="No file attached", bg=self.BG,
                                   fg=self.MUTED, font=("Segoe UI", 9))
        self.file_label.pack(side=tk.LEFT, padx=8)

        composer = tk.Frame(self.root, bg=self.PANEL, padx=10, pady=10)
        composer.pack(fill=tk.X, padx=12, pady=12)
        self.entry = tk.Entry(composer, font=("Segoe UI", 11), relief=tk.FLAT,
                              bg=self.PANEL, fg=self.TEXT)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(2, 8))
        self.entry.bind("<Return>", self.send_cmd)
        tk.Button(composer, text="Send", command=self.send_cmd, bg=self.ACCENT,
                  fg="white", activebackground="#1d4ed8", relief=tk.FLAT,
                  padx=18, pady=9).pack(side=tk.RIGHT)
        self.entry.focus_set()

        footer = tk.Label(self.root, text=f"Files are saved in: {CREATIONS_DIR}",
                          bg=self.BG, fg=self.MUTED, font=("Segoe UI", 8), anchor="w")
        footer.pack(fill=tk.X, padx=14, pady=(0, 8))

    def pick_file(self):
        path = filedialog.askopenfilename(title="Choose a file")
        if path:
            self.engine.attached_file_path = path
            self.file_label.config(text=os.path.basename(path))
            self.log_message("FILE", f"Attached {path}")

    def send_cmd(self, event=None):
        command = self.entry.get().strip()
        if not command:
            return
        self.entry.delete(0, tk.END)
        self.status.config(text="● Working…", fg="#b45309")
        threading.Thread(target=self._run_command, args=(command,), daemon=True).start()

    def _run_command(self, command):
        try:
            self.engine.process_command(command)
        except Exception as exc:
            self.thread_safe_log("ERROR", str(exc))
        finally:
            self.thread_safe_state("Ready")

    def log_message(self, speaker, message):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, f"{speaker}\n", "speaker")
        self.console.insert(tk.END, f"{message}\n\n", "body")
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

    def thread_safe_log(self, speaker, message):
        self.root.after(0, lambda: self.log_message(speaker, message))

    def thread_safe_state(self, state):
        self.root.after(0, lambda: self.status.config(text=f"● {state}", fg="#15803d"))

    def close(self):
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AetherApp(root)
    root.mainloop()
