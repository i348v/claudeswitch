"""
ClaudeSwitch — main chat window.
Run:  python client_app.py
"""
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from artifacts import create_artifact
from claude_backend import chat
from config_manager import (
    load as load_cfg, save as save_cfg,
    get_active, get_active_id, set_active,
    list_accounts, update_account,
    get_pref, set_pref,
)
from store import (
    add_message,
    create_conversation,
    create_project,
    delete_conversation,
    delete_empty_conversations,
    delete_project,
    get_conversations, search_conversations,
    get_messages,
    get_project,
    init_db,
    list_projects,
    truncate_messages,
    update_project,
    update_title,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":        "#0d1117",
    "sidebar":   "#161b22",
    "border":    "#21262d",
    "user_bg":   "#1c2128",
    "user_fg":   "#e6edf3",
    "user_acc":  "#388bfd",
    "asst_fg":   "#c9d1d9",
    "asst_acc":  "#3fb950",
    "api_acc":   "#d29922",
    "meta":      "#8b949e",
    "select":    "#264f78",
    "error":     "#f85149",
    "thinking":  "#484f58",
    "code_bg":   "#010409",
    "code_hdr":  "#161b22",
}

MONO = ("Consolas", 12) if sys.platform == "win32" else \
       ("Menlo", 12)    if sys.platform == "darwin" else \
       ("Monospace", 11)

MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-8",
    "claude-haiku-4-5-20251001",
]

# $/million tokens  {model: (input, output)}
PRICING = {
    "claude-sonnet-4-6":         (3.0,   15.0),
    "claude-opus-4-8":           (15.0,  75.0),
    "claude-haiku-4-5-20251001": (0.80,   4.0),
}

def _calc_cost(model: str, inp: int, out: int) -> float:
    p = PRICING.get(model, (3.0, 15.0))
    return (inp * p[0] + out * p[1]) / 1_000_000

def _fmt_tokens(inp: int, out: int, model: str) -> str:
    cost = _calc_cost(model, inp, out)
    total = inp + out
    if total == 0:
        return ""
    tk = f"{total/1000:.1f}k" if total >= 1000 else str(total)
    return f"↑{inp/1000:.1f}k ↓{out/1000:.1f}k · ${cost:.4f}"


# ── Tooltip ───────────────────────────────────────────────────────────────────

class Tooltip:
    """Hover tooltip for any tkinter / CTk widget."""
    _DELAY = 500  # ms before appearing

    def __init__(self, widget, text: str):
        self._w    = widget
        self._text = text
        self._tip  = None
        self._job  = None
        widget.bind("<Enter>",       self._schedule, add="+")
        widget.bind("<Leave>",       self._cancel,   add="+")
        widget.bind("<ButtonPress>", self._cancel,   add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._job = self._w.after(self._DELAY, self._show)

    def _cancel(self, _=None):
        if self._job:
            self._w.after_cancel(self._job)
            self._job = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        x = self._w.winfo_rootx() + 4
        y = self._w.winfo_rooty() + self._w.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self._w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.wm_attributes("-topmost", True)
        tk.Label(
            tw, text=self._text,
            background="#1c2128", foreground="#e6edf3",
            relief="flat", borderwidth=0,
            padx=8, pady=5,
            font=("sans-serif", 10),
        ).pack()


# ── Markdown renderer ──────────────────────────────────────────────────────────

class MarkdownRenderer:
    """Renders Claude markdown into a tk.Text widget."""

    def __init__(self, widget: tk.Text):
        self.w = widget
        self._configure_tags()

    def _configure_tags(self):
        w = self.w
        base_font = MONO[0]
        base_size = MONO[1]

        w.tag_configure("asst_body",     foreground=C["asst_fg"],  font=(base_font, base_size))
        w.tag_configure("user_acc",      foreground=C["user_acc"],  font=(base_font, base_size, "bold"))
        w.tag_configure("user_body",     foreground=C["user_fg"],   background=C["user_bg"],
                        font=(base_font, base_size), lmargin1=8, lmargin2=8, rmargin=8)
        w.tag_configure("asst_label",    foreground=C["asst_acc"],  font=(base_font, base_size, "bold"))
        w.tag_configure("api_label",     foreground=C["api_acc"],   font=(base_font, base_size, "bold"))
        w.tag_configure("meta",          foreground=C["meta"],      font=(base_font, 10))
        w.tag_configure("error_msg",     foreground=C["error"],     font=(base_font, base_size))
        w.tag_configure("switch_banner", foreground=C["meta"],      font=(base_font, 10, "italic"),
                        lmargin1=8, spacing1=4, spacing3=4)
        w.tag_configure("thinking_txt",  foreground=C["thinking"],  font=(base_font, base_size, "italic"))
        w.tag_configure("streaming",     foreground="#79c0ff",      font=(base_font, base_size))

        # Markdown
        w.tag_configure("h1",          foreground="#e6edf3", font=(base_font, base_size + 6, "bold"),
                        spacing1=10, spacing3=4)
        w.tag_configure("h2",          foreground="#e6edf3", font=(base_font, base_size + 3, "bold"),
                        spacing1=8, spacing3=3)
        w.tag_configure("h3",          foreground="#e6edf3", font=(base_font, base_size + 1, "bold"),
                        spacing1=6, spacing3=2)
        w.tag_configure("bold",        font=(base_font, base_size, "bold"))
        w.tag_configure("italic",      font=(base_font, base_size, "italic"))
        w.tag_configure("bold_italic", font=(base_font, base_size, "bold italic"))
        w.tag_configure("inline_code", foreground="#e6edf3", background="#1c2128",
                        font=(base_font, base_size - 1))
        w.tag_configure("code_block",  foreground="#e6edf3", background=C["code_bg"],
                        font=(base_font, base_size - 1), lmargin1=16, lmargin2=16,
                        rmargin=16, spacing1=1, spacing3=1)
        w.tag_configure("code_lang",   foreground=C["meta"], background=C["code_hdr"],
                        font=(base_font, 10), lmargin1=16)
        w.tag_configure("blockquote",  foreground=C["meta"],
                        lmargin1=24, lmargin2=24)
        w.tag_configure("bullet",      foreground=C["asst_fg"],
                        lmargin1=20, lmargin2=36, font=(base_font, base_size))
        w.tag_configure("hr",          foreground=C["border"])

    def render(self, text: str):
        """Parse and insert markdown. Widget must NOT be disabled when called."""
        w = self.w
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # Fenced code block
            if line.startswith("```"):
                lang = line[3:].strip() or "code"
                code_lines = []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                self._code_block("\n".join(code_lines), lang)
                i += 1
                continue

            if line.startswith("### "):
                self._inline(line[4:], "h3"); w.insert(tk.END, "\n")
            elif line.startswith("## "):
                self._inline(line[3:], "h2"); w.insert(tk.END, "\n")
            elif line.startswith("# "):
                self._inline(line[2:], "h1"); w.insert(tk.END, "\n")
            elif line.strip() in ("---", "***", "___") and len(line.strip()) == 3:
                w.insert(tk.END, "  " + "─" * 54 + "\n", "hr")
            elif line.startswith("> "):
                self._inline("▎  " + line[2:], "blockquote"); w.insert(tk.END, "\n")
            elif re.match(r"^[ \t]*[-*+] ", line):
                depth = (len(line) - len(line.lstrip())) // 2
                content = re.sub(r"^[ \t]*[-*+] ", "", line)
                self._inline("  " * depth + "  • " + content, "bullet")
                w.insert(tk.END, "\n")
            elif re.match(r"^\d+\. ", line):
                num = re.match(r"^(\d+)\. ", line).group(1)
                content = re.sub(r"^\d+\. ", "", line)
                self._inline(f"  {num}.  " + content, "bullet")
                w.insert(tk.END, "\n")
            elif line.strip() == "":
                w.insert(tk.END, "\n")
            else:
                self._inline(line, "asst_body")
                w.insert(tk.END, "\n")

            i += 1

    def _inline(self, text: str, base: str):
        """Insert text with inline bold/italic/code markup applied."""
        w = self.w
        pattern = r"(\*\*\*(?:[^*]|\*(?!\*\*))+\*\*\*|\*\*(?:[^*]|\*(?!\*))+\*\*|\*(?:[^*])+\*|`[^`\n]+`)"
        for part in re.split(pattern, text):
            if not part:
                continue
            if part.startswith("***") and part.endswith("***") and len(part) > 6:
                w.insert(tk.END, part[3:-3], (base, "bold_italic"))
            elif part.startswith("**") and part.endswith("**") and len(part) > 4:
                w.insert(tk.END, part[2:-2], (base, "bold"))
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                w.insert(tk.END, part[1:-1], (base, "italic"))
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                w.insert(tk.END, part[1:-1], "inline_code")
            else:
                w.insert(tk.END, part, base)

    def _code_block(self, code: str, lang: str):
        w = self.w
        w.insert(tk.END, f"  {lang}\n", "code_lang")
        w.insert(tk.END, code, "code_block")

        captured = code
        def _copy():
            w.clipboard_clear()
            w.clipboard_append(captured)
            btn.configure(text="✓ Copied!", fg="#3fb950")
            w.after(1500, lambda: btn.configure(text="⎘ Copy", fg=C["meta"]))

        btn = tk.Button(
            w, text="⎘ Copy", command=_copy,
            bg=C["code_hdr"], fg=C["meta"],
            activebackground="#21262d", activeforeground="#c9d1d9",
            relief=tk.FLAT, padx=10, pady=3,
            font=(MONO[0], 10), cursor="hand2", bd=0,
        )
        w.insert(tk.END, "\n")
        w.window_create(tk.END, window=btn, padx=16, pady=6)
        w.insert(tk.END, "\n\n")


# ── Live sync dialog ──────────────────────────────────────────────────────────

class LiveSyncDialog(ctk.CTkToplevel):
    """Pull conversation history directly from claude.ai via stored session cookies."""

    def __init__(self, parent, on_import_done=None):
        super().__init__(parent)
        self.title("Sync Conversations from Claude.ai")
        self.geometry("440x340")
        self.minsize(380, 280)
        self.resizable(True, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])

        self._on_import_done = on_import_done
        self._cancel_flag    = threading.Event()

        F_BOLD = ctk.CTkFont(size=13, weight="bold")
        F_UI   = ctk.CTkFont(size=13)
        F_SM   = ctk.CTkFont(size=11)

        # ── Account picker ──
        ctk.CTkLabel(self, text="Sync Conversations from Claude.ai",
                     font=F_BOLD, text_color="#e6edf3").pack(padx=20, pady=(18, 4), anchor="w")
        ctk.CTkLabel(
            self,
            text="Imports your existing Claude.ai conversation history\n"
                 "directly — no data export or email required.",
            font=F_SM, text_color=C["meta"], justify="left",
        ).pack(padx=20, pady=(0, 12), anchor="w")

        acc_row = ctk.CTkFrame(self, fg_color="transparent")
        acc_row.pack(fill="x", padx=20, pady=(0, 6))
        acc_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(acc_row, text="Account:", font=F_SM,
                     text_color=C["meta"]).grid(row=0, column=0, padx=(0, 8))

        # Only show subscription accounts that have a valid sessionKey
        from config_manager import list_accounts as _list
        self._sub_accounts = [
            (aid, acc) for aid, acc in _list()
            if acc.get("mode") == "subscription" and acc.get("cookies", {}).get("sessionKey")
        ]

        if not self._sub_accounts:
            ctk.CTkLabel(
                self,
                text="No signed-in Claude.ai accounts found.\n"
                     "Open Account Manager (⚙) and add one first.",
                font=F_SM, text_color=C["error"], justify="left",
            ).pack(padx=20, pady=8, anchor="w")
            ctk.CTkButton(self, text="Close", height=34, font=F_UI,
                          command=self.destroy).pack(padx=20, pady=8, fill="x")
            return

        self._acc_var = tk.StringVar()
        labels = [acc["label"] for _, acc in self._sub_accounts]
        acc_menu = ctk.CTkOptionMenu(
            acc_row, variable=self._acc_var, values=labels,
            height=30, font=F_SM,
            fg_color="#21262d", button_color="#30363d",
            dropdown_fg_color=C["sidebar"],
        )
        acc_menu.set(labels[0])
        acc_menu.grid(row=0, column=1, sticky="ew")

        # ── Progress ──
        self._status_var = tk.StringVar(value="Ready — click Sync to begin.")
        self._status_lbl = ctk.CTkLabel(self, textvariable=self._status_var,
                     font=F_SM, text_color=C["meta"],
                     wraplength=390, justify="left")
        self._status_lbl.pack(padx=20, pady=(8, 4), anchor="w")

        self._progress = ctk.CTkProgressBar(self, height=8)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=20, pady=(0, 12))

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 12))
        btn_row.grid_columnconfigure(0, weight=1)

        self._sync_btn = ctk.CTkButton(
            btn_row, text="⬇  Sync Now", height=36, font=F_UI,
            command=self._start_sync,
        )
        self._sync_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self._cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", height=36, font=F_UI,
            fg_color="#21262d", hover_color="#30363d",
            command=self._close,
        )
        self._cancel_btn.grid(row=0, column=1, padx=(6, 0))

        ctk.CTkButton(
            self,
            text="Import from file instead (IMAP / data export)…",
            height=26, font=F_SM,
            fg_color="transparent", hover_color=C["border"],
            text_color=C["meta"],
            command=self._open_wizard,
        ).pack(pady=(0, 8))

        # ── Done banner — lives in the empty space at the bottom, revealed on finish ──
        self._done_frame = ctk.CTkFrame(
            self, fg_color="transparent", corner_radius=10,
            border_width=0,
        )
        self._done_frame.pack(fill="x", padx=20, pady=(0, 16), expand=True)

        self._done_inner_lbl = ctk.CTkLabel(
            self._done_frame,
            text="",
            font=F_SM, text_color="#3fb950",
        )
        self._done_inner_btn = ctk.CTkButton(
            self._done_frame,
            text="✓  Close this window",
            height=38, font=F_UI,
            fg_color="#2ea043", hover_color="#3fb950",
            text_color="#0d1117",
            command=self._close,
        )

        self.protocol("WM_DELETE_WINDOW", self._close)

    def _selected_acc(self):
        label = self._acc_var.get()
        for aid, acc in self._sub_accounts:
            if acc["label"] == label:
                return aid, acc
        return (None, self._sub_accounts[0][1]) if self._sub_accounts else (None, None)

    def _set_status(self, msg, color=None):
        self._status_var.set(msg)

    def _start_sync(self):
        acc_id, acc = self._selected_acc()
        if not acc:
            return
        self._sync_btn.configure(state="disabled", text="Syncing…")
        self._cancel_flag.clear()
        self._progress.set(0)
        self._set_status("Connecting to Claude.ai…")
        threading.Thread(target=self._worker, args=(acc_id, acc), daemon=True).start()

    def _worker(self, acc_id, acc):
        from claude_backend import fetch_conversations
        import json, tempfile

        try:
            def on_progress(fetched, total, title):
                if total > 0:
                    self.after(0, lambda f=fetched, t=total, n=title: (
                        self._progress.set(f / t),
                        self._set_status(f"Fetching {f}/{t}: {n[:40]}…"),
                    ))

            conversations = fetch_conversations(acc, on_progress=on_progress)

            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            json.dump(conversations, tmp, ensure_ascii=False)
            tmp.close()

            self.after(0, lambda p=tmp.name, aid=acc_id: self._finish(p, aid))

        except Exception as exc:
            self.after(0, lambda e=str(exc): self._on_error(e))

    def _finish(self, tmp_path, acc_id=""):
        from store import import_from_claudeai
        import os
        try:
            convs, msgs = import_from_claudeai(tmp_path, account_id=acc_id)
        except Exception as exc:
            self._on_error(str(exc))
            return
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        self._progress.set(1.0)
        self._progress.configure(progress_color="#2ea043")
        self._set_status(f"✓  {convs} new conversations, {msgs} messages imported.")
        self._status_lbl.configure(text_color="#3fb950")
        self._sync_btn.configure(state="normal", text="⬇  Sync Again")
        self._cancel_btn.configure(state="disabled")

        # Reveal the done banner in the empty space at the bottom
        self._done_frame.configure(fg_color="#0f2a1a", border_width=1, border_color="#2ea043")
        self._done_inner_lbl.configure(
            text="🎉  All done! Your conversations are in the sidebar.",
        )
        self._done_inner_lbl.pack(padx=16, pady=(12, 6))
        self._done_inner_btn.pack(fill="x", padx=16, pady=(0, 14))

        if self._on_import_done:
            self._on_import_done(convs, msgs)

    def _on_error(self, msg):
        self._set_status(f"⚠ {msg}")
        self._sync_btn.configure(state="normal", text="⬇  Sync Now")

    def _close(self):
        self._cancel_flag.set()
        self.destroy()

    def _open_wizard(self):
        self.destroy()
        ImportWizard(self.master, on_import_done=self._on_import_done)


# ── Import wizard ──────────────────────────────────────────────────────────────

class ImportWizard(ctk.CTkToplevel):
    """
    Step-by-step guide that:
    1. Opens Claude.ai export page in browser
    2. Collects email + password, connects via IMAP
    3. Watches inbox for the Anthropic export email
    4. Downloads the file and imports automatically
    """

    def __init__(self, parent, on_import_done=None):
        super().__init__(parent)
        self.title("Import from Claude.ai")
        self.geometry("440x480")
        self.resizable(False, True)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._on_import_done = on_import_done
        self._stop_event     = threading.Event()
        self._status_var     = tk.StringVar(value="")

        F_BOLD = ctk.CTkFont(size=13, weight="bold")
        F_UI   = ctk.CTkFont(size=13)
        F_SM   = ctk.CTkFont(size=11)

        # ── Step 1 banner ──
        step1 = ctk.CTkFrame(self, fg_color="#1c2128", corner_radius=10)
        step1.pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(step1, text="Step 1 — Request your data from Claude.ai",
                     font=F_BOLD, text_color="#e6edf3", anchor="w").pack(
                         padx=14, pady=(12, 2), anchor="w")
        ctk.CTkLabel(
            step1,
            text="Click the button below. On Claude.ai go to:\n"
                 "Settings › Privacy › Export Data  →  click 'Export'\n"
                 "Anthropic will email you a download link.",
            font=F_SM, text_color=C["meta"], justify="left", anchor="w",
            wraplength=370,
        ).pack(padx=14, pady=(0, 8), anchor="w")
        ctk.CTkButton(step1, text="Open Claude.ai Export Page →",
                      height=32, font=F_UI,
                      command=lambda: __import__("webbrowser").open(
                          "https://claude.ai/settings/privacy")
                      ).pack(padx=14, pady=(0, 12), fill="x")

        # ── Step 2 banner ──
        step2 = ctk.CTkFrame(self, fg_color="#1c2128", corner_radius=10)
        step2.pack(fill="x", padx=20, pady=6)
        ctk.CTkLabel(step2, text="Step 2 — Let ClaudeSwitch fetch it from your inbox",
                     font=F_BOLD, text_color="#e6edf3", anchor="w").pack(
                         padx=14, pady=(12, 2), anchor="w")
        ctk.CTkLabel(
            step2,
            text="Enter the email tied to your Claude.ai account.",
            font=F_SM, text_color=C["meta"], justify="left", anchor="w",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        self._email_entry = ctk.CTkEntry(step2, placeholder_text="you@gmail.com",
                                          height=34, font=F_UI)
        self._email_entry.pack(fill="x", padx=14, pady=(0, 4))
        self._email_entry.bind("<KeyRelease>", self._on_email_key)

        # Dynamic setup card — shown/hidden based on email domain
        self._setup_card = ctk.CTkFrame(step2, fg_color="#0d1117", corner_radius=8)
        self._setup_card.pack(fill="x", padx=14, pady=(0, 4))
        self._setup_inner = ctk.CTkFrame(self._setup_card, fg_color="transparent")
        self._setup_inner.pack(fill="x", padx=10, pady=8)
        # (contents built dynamically in _on_email_key)

        pw_row = ctk.CTkFrame(step2, fg_color="transparent")
        pw_row.pack(fill="x", padx=14, pady=(0, 12))
        pw_row.grid_columnconfigure(0, weight=1)
        self._pw_label = ctk.CTkLabel(pw_row, text="Password / App Password",
                                       font=F_SM, text_color=C["meta"])
        self._pw_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self._pw_entry = ctk.CTkEntry(pw_row, placeholder_text="Enter password",
                                       show="•", height=34, font=F_UI)
        self._pw_entry.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(pw_row, text="👁", width=34, height=34,
                       fg_color="#21262d", hover_color="#30363d",
                       command=self._toggle_pw).grid(row=1, column=1)

        # Trigger setup card for any pre-filled value
        self._last_domain = ""
        self._use_oauth   = False
        self._on_email_key()

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(10, 4))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        self._watch_btn = ctk.CTkButton(
            btn_row, text="▶  Watch My Inbox", height=36, font=F_UI,
            command=self._start_watch,
        )
        self._watch_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        ctk.CTkButton(
            btn_row, text="📂  Choose File Manually", height=36, font=F_UI,
            fg_color="#21262d", hover_color="#30363d",
            command=self._manual,
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # ── Status ──
        self._status_lbl = ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=F_SM, text_color=C["meta"], wraplength=400,
        )
        self._status_lbl.pack(padx=20, pady=(4, 16))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _toggle_pw(self):
        self._pw_entry.configure(
            show="" if self._pw_entry.cget("show") == "•" else "•"
        )

    def _on_email_key(self, event=None):
        import webbrowser
        email = self._email_entry.get().strip().lower()
        domain = email.split("@")[-1] if "@" in email else ""
        if domain == self._last_domain:
            return
        self._last_domain = domain

        # Clear old setup card contents
        for w in self._setup_inner.winfo_children():
            w.destroy()

        self._use_oauth = False
        self._pw_entry.configure(state="normal")

        F_SM   = ctk.CTkFont(size=11)
        F_UI   = ctk.CTkFont(size=12)

        def open_url(url):
            webbrowser.open(url)

        if domain in ("gmail.com", "googlemail.com"):
            # ── Google OAuth path (primary) ──────────────────────────────
            self._use_oauth = True
            self._pw_label.configure(text="Password  (not needed for Sign in with Google)")
            self._pw_entry.configure(state="disabled")

            ctk.CTkLabel(self._setup_inner,
                         text="Easiest — Sign in with Google",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="#e6edf3").pack(anchor="w", pady=(0, 4))
            ctk.CTkButton(
                self._setup_inner,
                text="🔵  Sign in with Google",
                height=36, font=F_UI,
                fg_color="#1f6feb", hover_color="#1a5cb0", text_color="#fff",
                command=self._start_google_watch,
            ).pack(fill="x", pady=(0, 8))

            # Divider with "or use App Password"
            ctk.CTkFrame(self._setup_inner, height=1,
                         fg_color=C["border"]).pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(self._setup_inner,
                         text="Or use an App Password instead (advanced)",
                         font=ctk.CTkFont(size=10), text_color=C["meta"],
                         anchor="w").pack(anchor="w", pady=(0, 6))

            self._pw_entry.configure(state="normal")
            self._pw_label.configure(text="App Password  (16-digit code — not your Gmail password)")

            # Step 1
            ctk.CTkLabel(self._setup_inner,
                         text="Step 1 of 2 — Enable IMAP inside Gmail",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="#e6edf3").pack(anchor="w", pady=(0, 2))
            ctk.CTkLabel(
                self._setup_inner,
                text="On the page that opens, scroll to 'IMAP access':\n"
                     "  • If you see Auto-Expunge / folder options → IMAP is\n"
                     "    already ON. Skip this step, go to Step 2 below.\n"
                     "  • If you see 'Enable IMAP' radio button → select it\n"
                     "    and click 'Save Changes' at the bottom.",
                font=F_SM, text_color=C["meta"], justify="left",
                anchor="w", wraplength=360,
            ).pack(anchor="w", pady=(0, 4))
            ctk.CTkButton(
                self._setup_inner,
                text="Open Gmail IMAP Settings →",
                height=30, font=F_UI, anchor="w",
                fg_color="#1f6feb", hover_color="#1a5cb0", text_color="#fff",
                command=lambda: open_url(
                    "https://mail.google.com/mail/u/0/#settings/fwdandpop"
                ),
            ).pack(fill="x", pady=(0, 8))

            # Divider
            ctk.CTkFrame(self._setup_inner, height=1,
                         fg_color=C["border"]).pack(fill="x", pady=(0, 8))

            # Step 2
            ctk.CTkLabel(self._setup_inner,
                         text="Step 2 of 2 — Create an App Password",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="#e6edf3").pack(anchor="w", pady=(0, 2))
            ctk.CTkLabel(
                self._setup_inner,
                text="App Passwords require 2-Step Verification to be on.\n"
                     "If you see 'App not available' — do this first:",
                font=F_SM, text_color=C["meta"], justify="left",
                anchor="w", wraplength=360,
            ).pack(anchor="w", pady=(0, 4))
            ctk.CTkButton(
                self._setup_inner,
                text="① Enable 2-Step Verification →",
                height=30, font=F_UI, anchor="w",
                fg_color="#21262d", hover_color="#30363d", text_color="#d29922",
                command=lambda: open_url(
                    "https://myaccount.google.com/signinoptions/two-step-verification"
                ),
            ).pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(
                self._setup_inner,
                text="Once 2-Step Verification is on, come back here and:",
                font=F_SM, text_color=C["meta"], justify="left", anchor="w",
            ).pack(anchor="w", pady=(0, 2))
            ctk.CTkLabel(
                self._setup_inner,
                text="  • Search for 'App Passwords' in Google Account search\n"
                     "  • App: Mail  →  Device: Other  →  type ClaudeSwitch\n"
                     "  • Click Generate  →  copy the 16-character code\n"
                     "  • Paste it in the password field below",
                font=F_SM, text_color=C["meta"], justify="left",
                anchor="w", wraplength=360,
            ).pack(anchor="w", pady=(0, 4))
            ctk.CTkButton(
                self._setup_inner,
                text="② Open Google App Passwords →",
                height=30, font=F_UI, anchor="w",
                fg_color="#1f6feb", hover_color="#1a5cb0", text_color="#fff",
                command=lambda: open_url("https://myaccount.google.com/apppasswords"),
            ).pack(fill="x")

        elif domain in ("outlook.com", "hotmail.com", "live.com", "msn.com"):
            self._pw_label.configure(text="Password  (your regular Outlook password)")
            ctk.CTkLabel(self._setup_inner,
                         text="Outlook IMAP is on by default — no setup needed.",
                         font=F_SM, text_color=C["meta"]).pack(anchor="w")

        elif domain in ("yahoo.com", "ymail.com"):
            self._pw_label.configure(text="App Password  (required for Yahoo)")
            ctk.CTkButton(
                self._setup_inner,
                text="Generate Yahoo App Password →",
                height=28, font=F_UI, anchor="w",
                fg_color="#21262d", hover_color="#30363d", text_color="#79c0ff",
                command=lambda: open_url(
                    "https://login.yahoo.com/account/security/app-passwords/list"
                ),
            ).pack(fill="x", pady=2)

        elif domain in ("icloud.com", "me.com", "mac.com"):
            self._pw_label.configure(text="App-Specific Password  (not your Apple ID password)")
            ctk.CTkLabel(self._setup_inner,
                         text="iCloud requires an App-Specific Password:",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color="#e6edf3").pack(anchor="w", pady=(0, 4))
            ctk.CTkLabel(
                self._setup_inner,
                text="  1.  Click the button below to open Apple ID\n"
                     "  2.  Sign in with your Apple ID\n"
                     "  3.  Go to  Sign-In and Security  →  App-Specific Passwords\n"
                     "  4.  Click  ＋  and name it  ClaudeSwitch\n"
                     "  5.  Copy the generated password and paste it below",
                font=F_SM, text_color=C["meta"], justify="left",
                anchor="w", wraplength=360,
            ).pack(anchor="w", pady=(0, 6))
            ctk.CTkButton(
                self._setup_inner,
                text="  Open Apple ID → App-Specific Passwords",
                height=32, font=F_UI, anchor="w",
                fg_color="#21262d", hover_color="#30363d", text_color="#e6edf3",
                command=lambda: open_url(
                    "https://appleid.apple.com/account/manage/section/security"
                ),
            ).pack(fill="x")

        elif domain in ("protonmail.com", "proton.me"):
            self._pw_label.configure(text="IMAP Bridge Password")
            ctk.CTkLabel(
                self._setup_inner,
                text="ProtonMail requires the Proton Mail Bridge app to be running.",
                font=F_SM, text_color=C["meta"], wraplength=360,
            ).pack(anchor="w")
            ctk.CTkButton(
                self._setup_inner,
                text="Download Proton Mail Bridge →",
                height=28, font=F_UI, anchor="w",
                fg_color="#21262d", hover_color="#30363d", text_color="#79c0ff",
                command=lambda: open_url("https://proton.me/mail/bridge"),
            ).pack(fill="x", pady=2)

        elif domain:
            self._pw_label.configure(text="Password")
            ctk.CTkLabel(
                self._setup_inner,
                text=f"Using IMAP on {domain}. Enter your regular email password.",
                font=F_SM, text_color=C["meta"],
            ).pack(anchor="w")

        else:
            ctk.CTkLabel(self._setup_inner,
                         text="Type your email above to see setup instructions.",
                         font=F_SM, text_color=C["thinking"]).pack(anchor="w")

    def _set_status(self, msg: str, color: str = C["meta"]):
        self._status_var.set(msg)
        self._status_lbl.configure(text_color=color)

    def _start_google_watch(self):
        from gmail_oauth import watch as google_watch
        self._stop_event.clear()
        self._set_status("Opening browser for Google Sign-In…", C["meta"])
        threading.Thread(
            target=google_watch,
            kwargs=dict(
                on_status=lambda m: self.after(0, lambda msg=m: self._set_status(msg)),
                on_found=self._on_found,
                on_error=lambda m: self.after(0, lambda msg=m: self._on_error(msg)),
                stop_event=self._stop_event,
            ),
            daemon=True,
        ).start()

    def _start_watch(self):
        from email_watcher import watch

        addr = self._email_entry.get().strip()
        pw   = self._pw_entry.get().strip()
        if not addr or not pw:
            self._set_status("⚠  Enter your email and password first.", C["error"])
            return

        self._stop_event.clear()
        self._watch_btn.configure(text="■  Stop Watching", fg_color="#b91c1c",
                                   command=self._stop_watch)
        self._set_status("Connecting…", C["meta"])

        threading.Thread(
            target=watch,
            kwargs=dict(
                email_addr=addr,
                password=pw,
                on_status=lambda m: self.after(0, lambda: self._set_status(m)),
                on_found=self._on_found,
                on_error=lambda m: self.after(0, lambda: self._on_error(m)),
                stop_event=self._stop_event,
            ),
            daemon=True,
        ).start()

    def _stop_watch(self):
        self._stop_event.set()
        self._watch_btn.configure(text="▶  Watch My Inbox", fg_color=["#1f538d","#1f538d"],
                                   command=self._start_watch)
        self._set_status("Stopped.")

    def _on_found(self, path: str):
        from store import import_from_claudeai
        self.after(0, lambda: self._set_status("Importing conversations…", C["asst_acc"]))
        try:
            convs, msgs = import_from_claudeai(path)
            self.after(0, lambda: self._finish(convs, msgs))
        except Exception as exc:
            self.after(0, lambda: self._on_error(str(exc)))

    def _finish(self, convs: int, msgs: int):
        self._set_status(
            f"✓  Done — {convs} conversations, {msgs} messages imported.", C["asst_acc"]
        )
        self._watch_btn.configure(state="disabled")
        if self._on_import_done:
            self._on_import_done(convs, msgs)
        self.after(2500, self.destroy)

    def _on_error(self, msg: str):
        self._set_status(f"⚠  {msg}", C["error"])
        self._watch_btn.configure(text="▶  Watch My Inbox", fg_color=["#1f538d","#1f538d"],
                                   command=self._start_watch)

    def _manual(self):
        from tkinter import filedialog
        from store import import_from_claudeai
        path = filedialog.askopenfilename(
            title="Select Claude.ai export",
            filetypes=[("Claude.ai export", "*.json *.zip"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            convs, msgs = import_from_claudeai(path)
            self._finish(convs, msgs)
        except Exception as exc:
            self._on_error(str(exc))

    def _on_close(self):
        self._stop_event.set()
        self.destroy()


# ── Project dialog ─────────────────────────────────────────────────────────────

class ProjectDialog(ctk.CTkToplevel):
    def __init__(self, parent, proj=None, on_save=None, on_delete=None):
        super().__init__(parent)
        self.title("Edit Project" if proj else "New Project")
        self.geometry("420x340")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._proj    = proj
        self._on_save = on_save
        self._on_delete = on_delete

        F_UI = ctk.CTkFont(size=13)
        F_SM = ctk.CTkFont(size=11)
        pad  = {"padx": 20, "pady": 5}

        ctk.CTkLabel(self, text="Project Name", font=F_SM,
                     text_color=C["meta"], anchor="w").pack(fill="x", padx=20, pady=(18, 0))
        self._name = ctk.CTkEntry(self, placeholder_text="e.g. Work, Research, Creative",
                                   height=34, font=F_UI)
        self._name.pack(fill="x", **pad)

        ctk.CTkLabel(self, text="System Prompt  (optional — sets Claude's persona for this project)",
                     font=F_SM, text_color=C["meta"], anchor="w",
                     wraplength=380).pack(fill="x", padx=20, pady=(10, 0))
        self._sysprompt = ctk.CTkTextbox(self, height=100, font=F_SM, wrap="word")
        self._sysprompt.pack(fill="x", **pad)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(14, 16))
        btn_row.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(btn_row, text="Save", height=36, font=F_UI,
                       command=self._save).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", height=36, font=F_UI,
                       fg_color="#21262d", hover_color="#30363d",
                       command=self.destroy).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        if proj:
            self._name.insert(0, proj.get("name", ""))
            self._sysprompt.insert("1.0", proj.get("system_prompt", ""))
            ctk.CTkButton(btn_row, text="🗑  Delete", height=36, font=F_UI,
                           fg_color="#21262d", hover_color="#6e1313",
                           text_color=C["error"],
                           command=self._delete).grid(row=1, column=0, columnspan=2,
                                                      sticky="ew", pady=(8, 0))

    def _save(self):
        name = self._name.get().strip()
        if not name:
            return
        sp = self._sysprompt.get("1.0", "end").strip()
        if self._proj:
            update_project(self._proj["id"], name, sp)
        else:
            create_project(name, sp)
        self.destroy()
        if self._on_save:
            self._on_save()

    def _delete(self):
        if not self._proj:
            return
        from tkinter import messagebox
        if not messagebox.askyesno("Delete project",
                                   f"Delete '{self._proj['name']}'? Conversations are kept.",
                                   parent=self):
            return
        pid = self._proj["id"]
        delete_project(pid)
        self.destroy()
        if self._on_delete:
            self._on_delete(pid)


# ── Help content ──────────────────────────────────────────────────────────────

def _load_doc(filename: str) -> str:
    p = Path(__file__).parent / filename
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"(File not found: {filename})"

_HELP_GETTING_STARTED = """\
GETTING STARTED WITH CLAUDESWITCH
══════════════════════════════════

ClaudeSwitch is a multi-account Claude desktop client. All your
conversations are stored locally — nothing is shared between sessions
except the actual messages you send to Claude.

────────────────────────────────────
STEP 1 — Add your first account
────────────────────────────────────
Click ⚙ (top-left of the sidebar) to open the Account Manager.

  • Subscription account  — Signs you into claude.ai via an embedded
    browser. Works with Google, Apple, or email login. No API key needed.
    Billed to your existing claude.ai subscription.

  • API Credits account  — Paste your Anthropic API key (sk-ant-...).
    Billed per-token to your Anthropic account.

Give the account a label (e.g. "Personal" or "Work") and click Add.

────────────────────────────────────
STEP 2 — Start chatting
────────────────────────────────────
Click "+ New Chat" in the sidebar, type your message, and press Enter.
Your active account is shown in the dropdown at the top of the window.

To switch accounts, select a different one from that dropdown — or
open the Account Manager and set a different account as active.

────────────────────────────────────
STEP 3 — Organise with Projects
────────────────────────────────────
Click ＋ next to PROJECTS to create a project folder.
Projects let you set a system prompt that applies to every conversation
inside that project — useful for giving Claude a persona or context.

────────────────────────────────────
TIPS
────────────────────────────────────
• Conversations are grouped by account in the sidebar.
  Click an account header to collapse or expand its list.

• Use the search box to filter conversations by keyword.

• Click ✏ on any message to edit and resubmit from that point.
  Everything after the edited message is replaced.

• Attach files with 📎 Attach — images, PDFs, and text files supported.

• Export any conversation to a styled HTML file with 🖼 Artifact.

• Adjust how many conversations show per account under ≡ Preferences.
"""

_HELP_SHORTCUTS = """\
KEYBOARD SHORTCUTS
══════════════════

CHAT
  Enter          Send message
  Shift+Enter    New line without sending
  Ctrl+Z         Undo (in input box)

TEXT
  Ctrl+C         Copy selected text
  Ctrl+V         Paste
  Ctrl+A         Select all (in input box)
  Ctrl+Shift+A   Select all text in chat

WINDOW
  Ctrl+N         New conversation (if configured)

RIGHT-CLICK MENUS
  Chat area      Copy, Select All
  Input box      Cut, Copy, Paste, Select All
  Conversation   Rename, Delete, Move to account
"""

_HELP_FEATURES = """\
FEATURES
════════

MULTI-ACCOUNT SWITCHING
  Add unlimited Claude.ai subscription accounts or Anthropic API
  keys. Switch between them at any time — conversation history stays
  in the sidebar, and Claude keeps its context when you switch.

PROJECTS
  Folder-style organisation with a custom system prompt per project.
  Every conversation started inside a project uses that prompt.

FILE ATTACHMENTS
  Attach images (JPEG, PNG, GIF, WebP), PDFs, and plain text or
  code files to any message.

MESSAGE EDITING
  Click ✏ on any past message to edit it and resubmit.
  The conversation is rolled back to that point.

CONVERSATION SEARCH
  The search box in the sidebar filters across all conversation titles
  and message content in real time.

CLAUDE.AI IMPORT
  Bring in your existing Claude.ai conversation history via Gmail
  OAuth or IMAP. Click "📥 Get Claude.ai Chats" to start.

ARTIFACT EXPORT
  Export any conversation to a self-contained, styled HTML file
  you can open in any browser or share with others.

TOKEN USAGE (API MODE)
  When using an API key account, each response shows the input and
  output token count and estimated cost. Session totals appear in
  the sidebar footer.

NO CLI DEPENDENCY
  Subscription mode communicates directly with claude.ai via your
  session cookies. The Claude Code CLI is not required.
"""

# ── Main app ───────────────────────────────────────────────────────────────────

class ChatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ClaudeSwitch")
        self.geometry("1160x760")
        self.minsize(820, 560)
        self.configure(fg_color=C["bg"])

        self.current_conv_id: str | None = None
        self.messages: list[dict] = []
        self.rq: queue.Queue = queue.Queue()
        self.is_loading = False
        self._stop_event = threading.Event()
        self._stream_idx = "1.0"
        self._conv_buttons: dict[str, ctk.CTkButton] = {}
        self._last_account_id: str = get_active_id()
        self._inject_handoff: bool = False
        self._active_project_id: str | None = None
        self._session_in: int = 0
        self._session_out: int = 0
        self._collapsed_accounts: set[str] = set()
        self._expanded_accounts: set[str] = set()  # accounts showing full list

        # Fonts (must come after super().__init__)
        self.F_UI   = ctk.CTkFont(size=13)
        self.F_BOLD = ctk.CTkFont(size=13, weight="bold")
        self.F_SM   = ctk.CTkFont(size=11)
        self.F_MONO = ctk.CTkFont(family=MONO[0], size=MONO[1])

        init_db()
        delete_empty_conversations()
        self._build_ui()
        self._refresh_projects()
        self._refresh_sidebar()
        self._new_conv()
        self._poll_config()
        self._poll_response()

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._bind_scroll()

    def _bind_scroll(self):
        """Wire touchpad / mouse-wheel scroll for Linux (Button-4/5) and macOS/Windows."""
        sidebar_canvas = self.conv_scroll._parent_canvas

        def _route(e):
            # Determine scroll direction
            up = (e.num == 4) or (getattr(e, "delta", 0) > 0)
            amt = -2 if up else 2

            # Walk widget ancestry to decide which scrollable gets the event
            w = e.widget
            while w:
                if w is self.chat:
                    self.chat.yview_scroll(amt, "units")
                    return
                if w is self.conv_scroll or w is sidebar_canvas:
                    sidebar_canvas.yview_scroll(amt, "units")
                    return
                try:
                    w = self.nametowidget(w.winfo_parent())
                except Exception:
                    break

        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.bind_all(seq, _route, add=True)

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=C["sidebar"])
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(4, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(sb, fg_color="transparent", height=54)
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(14, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="ClaudeSwitch", font=self.F_BOLD,
                     text_color="#e6edf3").grid(row=0, column=0, sticky="w")
        _gear = ctk.CTkButton(
            hdr, text="⚙", width=30, height=30, fg_color="transparent",
            hover_color=C["border"], font=ctk.CTkFont(size=16),
            command=self._open_switcher,
        )
        _gear.grid(row=0, column=1)
        Tooltip(_gear, "Account Manager")
        _prefs = ctk.CTkButton(
            hdr, text="≡", width=30, height=30, fg_color="transparent",
            hover_color=C["border"], font=ctk.CTkFont(size=16),
            command=self._open_preferences,
        )
        _prefs.grid(row=0, column=2)
        Tooltip(_prefs, "Preferences")

        _help_btn = ctk.CTkButton(
            hdr, text="?", width=26, height=26, fg_color="transparent",
            hover_color=C["border"], font=ctk.CTkFont(size=12),
            text_color=C["meta"], command=self._open_help,
        )
        _help_btn.grid(row=0, column=3)
        Tooltip(_help_btn, "Help & documentation")

        # ── Projects section ──
        proj_hdr = ctk.CTkFrame(sb, fg_color="transparent")
        proj_hdr.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        proj_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(proj_hdr, text="PROJECTS", font=ctk.CTkFont(size=10),
                     text_color=C["meta"]).grid(row=0, column=0, sticky="w")
        _new_proj = ctk.CTkButton(proj_hdr, text="＋", width=22, height=22,
                      fg_color="transparent", hover_color=C["border"],
                      font=self.F_SM, text_color=C["meta"],
                      command=self._new_project)
        _new_proj.grid(row=0, column=1)
        Tooltip(_new_proj, "New Project")

        self._proj_frame = ctk.CTkFrame(sb, fg_color="transparent")
        self._proj_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 4))
        self._proj_frame.grid_columnconfigure(0, weight=1)

        # ── Search box ──
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)
        search_row = ctk.CTkFrame(sb, fg_color="transparent")
        search_row.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 4))
        search_row.grid_columnconfigure(0, weight=1)
        self._search_entry = ctk.CTkEntry(
            search_row, textvariable=self._search_var,
            placeholder_text="🔍  Search conversations…",
            height=30, font=self.F_SM,
            fg_color=C["border"], border_color=C["border"],
        )
        self._search_entry.grid(row=0, column=0, sticky="ew")
        self._clear_search_btn = ctk.CTkButton(
            search_row, text="✕", width=28, height=30,
            fg_color="transparent", hover_color=C["border"],
            font=self.F_SM, text_color=C["meta"],
            command=self._clear_search,
        )
        self._clear_search_btn.grid(row=0, column=1, padx=(2, 0))
        self._clear_search_btn.grid_remove()  # hidden until user types
        Tooltip(self._clear_search_btn, "Clear search")

        self.conv_scroll = ctk.CTkScrollableFrame(sb, fg_color="transparent", corner_radius=0)
        self.conv_scroll.grid(row=4, column=0, sticky="nsew", padx=4)
        self.conv_scroll.grid_columnconfigure(0, weight=1)

        bot = ctk.CTkFrame(sb, fg_color="transparent")
        bot.grid(row=5, column=0, sticky="ew", padx=10, pady=10)
        bot.grid_columnconfigure(0, weight=1)
        _new_chat = ctk.CTkButton(bot, text="＋  New Chat", height=34,
                      font=self.F_UI, command=self._new_conv)
        _new_chat.grid(row=0, column=0, sticky="ew")
        Tooltip(_new_chat, "Start a new conversation  (Ctrl+N)")
        _import = ctk.CTkButton(bot, text="📥  Get Claude.ai Chats", height=28,
                      font=self.F_SM, fg_color="#21262d", hover_color="#30363d",
                      text_color="#adbac7", command=self._start_claudeai_import)
        _import.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        Tooltip(_import, "Import your Claude.ai conversation history")

        self._usage_var = tk.StringVar(value="")
        ctk.CTkLabel(bot, textvariable=self._usage_var,
                     font=ctk.CTkFont(size=10), text_color=C["meta"],
                     anchor="center").grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color=C["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # ── Header ──
        hdr = ctk.CTkFrame(main, height=54, corner_radius=0, fg_color=C["sidebar"])
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        self.title_lbl = ctk.CTkLabel(
            hdr, text="New Conversation", font=self.F_BOLD, text_color="#e6edf3"
        )
        self.title_lbl.grid(row=0, column=0, padx=(18, 8), pady=14, sticky="w")

        # Account dropdown
        self.account_var = tk.StringVar()
        self.account_menu = ctk.CTkOptionMenu(
            hdr, variable=self.account_var,
            values=[""], width=180, height=28, font=self.F_SM,
            command=self._on_account_change,
            fg_color="#21262d", button_color="#30363d",
            dropdown_fg_color=C["sidebar"],
        )
        self.account_menu.grid(row=0, column=1, padx=6, pady=14)
        self._rebuild_account_menu()
        Tooltip(self.account_menu, "Switch active account")

        # Model selector
        acc = get_active()
        self.model_var = tk.StringVar(value=acc.get("model", MODELS[0]))
        self.model_menu = ctk.CTkOptionMenu(
            hdr, values=MODELS, variable=self.model_var,
            width=190, height=28, font=self.F_SM,
            command=self._on_model_change,
            fg_color="#21262d", button_color="#30363d",
            dropdown_fg_color=C["sidebar"],
        )
        self.model_menu.grid(row=0, column=2, padx=6, pady=14)
        Tooltip(self.model_menu, "Select Claude model")

        self.mode_pill = ctk.CTkLabel(
            hdr, text="● Subscription", font=self.F_SM, text_color=C["asst_acc"]
        )
        self.mode_pill.grid(row=0, column=3, padx=(0, 4), pady=14)

        _del = ctk.CTkButton(
            hdr, text="🗑", width=30, height=30, fg_color="transparent",
            hover_color="#21262d", font=ctk.CTkFont(size=15),
            command=self._delete_conv,
        )
        _del.grid(row=0, column=4, padx=(0, 10), pady=14)
        Tooltip(_del, "Delete this conversation")

        # ── Chat area ──
        chat_wrap = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
        chat_wrap.grid(row=1, column=0, sticky="nsew")
        chat_wrap.grid_rowconfigure(0, weight=1)
        chat_wrap.grid_columnconfigure(0, weight=1)

        self.chat = tk.Text(
            chat_wrap,
            bg=C["bg"], fg=C["asst_fg"],
            font=MONO,
            wrap=tk.WORD,
            state=tk.NORMAL,
            relief=tk.FLAT,
            padx=28, pady=18,
            selectbackground=C["select"],
            insertbackground="#e6edf3",
            spacing1=2, spacing3=6,
            cursor="xterm",
        )
        vsb = ctk.CTkScrollbar(chat_wrap, command=self.chat.yview)
        self.chat.configure(yscrollcommand=vsb.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.md = MarkdownRenderer(self.chat)

        # ── Read-only chat: selection and standard shortcuts ──
        # Widget stays NORMAL so mouse and keyboard selection work natively.

        def _select_all(event=None):
            self.chat.tag_add(tk.SEL, "1.0", tk.END)
            self.chat.mark_set(tk.INSERT, tk.END)
            return "break"

        def _copy_sel(event=None):
            try:
                sel = self.chat.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.clipboard_clear(); self.clipboard_append(sel)
            except tk.TclError:
                pass
            return "break"

        def _copy_all(event=None):
            self.clipboard_clear()
            self.clipboard_append(self.chat.get("1.0", tk.END).strip())
            return "break"

        def _block_chat_edit(event):
            ctrl  = (event.state & 0x4) != 0
            shift = (event.state & 0x1) != 0
            # Allow all navigation (with or without Shift for extend-selection)
            if event.keysym in ('Up', 'Down', 'Left', 'Right',
                                 'Home', 'End', 'Prior', 'Next',
                                 'Escape', 'Tab'):
                return
            # Allow Ctrl+C/X (copy), Ctrl+A (select-all handled below)
            if ctrl and event.keysym.lower() in ('c', 'x', 'a'):
                return
            return "break"

        # Explicit bindings so Linux Emacs-style defaults don't interfere
        self.chat.bind("<Key>",           _block_chat_edit)
        self.chat.bind("<Control-a>",     _select_all)
        self.chat.bind("<Control-A>",     _select_all)
        self.chat.bind("<Control-c>",     _copy_sel)
        self.chat.bind("<Control-C>",     _copy_sel)
        self.chat.bind("<Control-Home>",  lambda e: (self.chat.see("1.0"), "break"))
        self.chat.bind("<Control-End>",   lambda e: (self.chat.see(tk.END), "break"))

        def _make_menu(parent):
            return tk.Menu(parent, tearoff=0,
                           bg=C["sidebar"], fg=C["asst_fg"],
                           activebackground=C["select"], activeforeground="#e6edf3",
                           bd=1, relief=tk.FLAT)

        def _chat_context_menu(event):
            try:
                sel = self.chat.get(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                sel = None
            menu = _make_menu(self.chat)
            if sel:
                menu.add_command(label="Copy",     command=lambda s=sel: (
                    self.clipboard_clear(), self.clipboard_append(s)))
            else:
                menu.add_command(label="Copy",     state="disabled")
            menu.add_command(label="Select All",   command=_select_all)
            menu.add_separator()
            menu.add_command(label="Copy All",     command=_copy_all)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        self.chat.bind("<Button-3>", _chat_context_menu)

        # ── Input bar ──
        inp_bar = ctk.CTkFrame(main, corner_radius=0, fg_color=C["sidebar"])
        inp_bar.grid(row=2, column=0, sticky="ew")
        inp_bar.grid_columnconfigure(0, weight=1)

        # Attachment tray (hidden until files are added)
        self._attach_tray = ctk.CTkFrame(inp_bar, fg_color="transparent")
        self._attach_tray.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(8, 0))
        self._attach_tray.grid_remove()

        # Text input row
        self.inp = ctk.CTkTextbox(inp_bar, height=62, font=self.F_UI, wrap="word")
        self.inp.grid(row=1, column=0, padx=(14, 6), pady=10, sticky="ew")
        self.inp.bind("<Return>",       self._on_enter)
        self.inp.bind("<Shift-Return>", lambda e: None)

        def _inp_context_menu(event):
            w = self.inp._textbox
            try:
                sel = w.get(tk.SEL_FIRST, tk.SEL_LAST)
            except tk.TclError:
                sel = None
            has_sel = sel is not None
            menu = _make_menu(w)
            menu.add_command(label="Cut",        state="normal" if has_sel else "disabled",
                             command=lambda: (w.event_generate("<<Cut>>"),))
            menu.add_command(label="Copy",       state="normal" if has_sel else "disabled",
                             command=lambda: (w.event_generate("<<Copy>>"),))
            menu.add_command(label="Paste",
                             command=lambda: (w.event_generate("<<Paste>>"),))
            menu.add_separator()
            menu.add_command(label="Select All",
                             command=lambda: (w.tag_add(tk.SEL, "1.0", tk.END),
                                              w.mark_set(tk.INSERT, tk.END)))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        self.inp._textbox.bind("<Button-3>", _inp_context_menu)

        btn_box = ctk.CTkFrame(inp_bar, fg_color="transparent")
        btn_box.grid(row=1, column=1, padx=(0, 14), pady=10, sticky="ns")

        self.send_btn = ctk.CTkButton(
            btn_box, text="Send", width=90, height=28,
            font=self.F_UI, command=self._send,
        )
        self.send_btn.pack(pady=(2, 3))
        Tooltip(self.send_btn, "Send message  (Enter)")

        _attach = ctk.CTkButton(
            btn_box, text="📎  Attach", width=90, height=28,
            font=self.F_SM, fg_color="#21262d", hover_color="#30363d",
            text_color="#adbac7", command=self._pick_attachment,
        )
        _attach.pack(pady=(0, 3))
        Tooltip(_attach, "Attach a file — image, PDF, or text")

        _artifact = ctk.CTkButton(
            btn_box, text="🖼  Artifact", width=90, height=28,
            font=self.F_SM, fg_color="#21262d", hover_color="#30363d",
            text_color="#adbac7", command=self._export_artifact,
        )
        _artifact.pack()
        Tooltip(_artifact, "Export conversation to HTML")

        self._attachments: list[dict] = []  # [{name, kind, data, media_type}]

    # ── Account menu ───────────────────────────────────────────────────────────

    def _rebuild_account_menu(self):
        accounts = list_accounts()
        active_id = get_active_id()
        labels = [f"{acc['label']} ({'api' if acc['mode'] == 'api' else 'sub'})"
                  for _, acc in accounts]
        self._account_ids = [acc_id for acc_id, _ in accounts]
        self.account_menu.configure(values=labels if labels else [""])
        try:
            idx = self._account_ids.index(active_id)
            self.account_var.set(labels[idx])
        except (ValueError, IndexError):
            if labels:
                self.account_var.set(labels[0])
                set_active(self._account_ids[0])

    def _on_account_change(self, choice: str):
        labels = self.account_menu.cget("values")
        try:
            idx = list(labels).index(choice)
            new_id = self._account_ids[idx]
        except (ValueError, IndexError):
            return
        if new_id == get_active_id():
            return
        set_active(new_id)
        self._handle_account_switch(new_id)

    def _handle_account_switch(self, new_id: str):
        acc = get_active()
        self.model_var.set(acc.get("model", MODELS[0]))
        self._update_mode_pill(acc)
        self._last_account_id = new_id

        if self.messages:
            self._inject_handoff = True
            mode_label = "API Credits" if acc["mode"] == "api" else "Subscription"
            self._write_switch_banner(
                f"↔  Switched to {acc['label']}  ({mode_label})  —  "
                f"full conversation history shared"
            )
        else:
            self._inject_handoff = False

    def _write_switch_banner(self, text: str):
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, f"\n  {text}\n", "switch_banner")
        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)

    def _write_system_notice(self, text: str):
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, f"\n  {text}\n", "switch_banner")
        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)

    # ── Config polling ─────────────────────────────────────────────────────────

    def _poll_config(self):
        acc = get_active()
        self._update_mode_pill(acc)

        # Detect external account switch (from account manager window)
        current_id = get_active_id()
        if current_id != self._last_account_id:
            self._last_account_id = current_id
            self._rebuild_account_menu()
            self.model_var.set(acc.get("model", MODELS[0]))

        # Rebuild dropdown if accounts changed
        self._rebuild_account_menu()

        self.after(1500, self._poll_config)

    def _update_mode_pill(self, acc: dict):
        if acc["mode"] == "api":
            self.mode_pill.configure(text="● API Credits", text_color=C["api_acc"])
        else:
            self.mode_pill.configure(text="● Subscription", text_color=C["asst_acc"])

    def _on_model_change(self, model: str):
        update_account(get_active_id(), model=model)

    # ── Response queue polling ─────────────────────────────────────────────────

    def _poll_response(self):
        try:
            while True:
                item = self.rq.get_nowait()
                if item["type"] == "chunk":
                    self._update_stream(item["accumulated"])
                elif item["type"] == "done":
                    self._finish(item["text"], item.get("usage", {}))
                elif item["type"] == "error":
                    self._show_error(item["text"])
                elif item["type"] == "import_done":
                    self._refresh_sidebar()
                    self._write_system_notice(
                        f"✓ Auto-imported {item['convs']} conversations "
                        f"({item['msgs']} messages) from Claude.ai."
                    )
        except queue.Empty:
            pass
        self.after(40, self._poll_response)

    # ── Sidebar ────────────────────────────────────────────────────────────────

    # ── Projects ───────────────────────────────────────────────────────────────

    def _refresh_projects(self):
        for w in self._proj_frame.winfo_children():
            w.destroy()

        projects = list_projects()
        # "All" pill
        all_active = self._active_project_id is None
        ctk.CTkButton(
            self._proj_frame,
            text="All chats",
            height=26, anchor="w", font=self.F_SM,
            fg_color=C["user_bg"] if all_active else "transparent",
            hover_color=C["user_bg"], text_color="#e6edf3" if all_active else C["meta"],
            command=self._deselect_project,
        ).grid(sticky="ew", pady=1)

        for p in projects:
            is_active = self._active_project_id == p["id"]
            row = ctk.CTkFrame(self._proj_frame, fg_color="transparent")
            row.grid(sticky="ew", pady=1)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(
                row, text=f"📁  {p['name']}", height=26, anchor="w", font=self.F_SM,
                fg_color=C["user_bg"] if is_active else "transparent",
                hover_color=C["user_bg"],
                text_color="#e6edf3" if is_active else C["meta"],
                command=lambda pid=p["id"]: self._select_project(pid),
            ).grid(row=0, column=0, sticky="ew")
            ctk.CTkButton(
                row, text="…", width=24, height=26, font=self.F_SM,
                fg_color="transparent", hover_color=C["border"], text_color=C["meta"],
                command=lambda proj=p: self._edit_project(proj),
            ).grid(row=0, column=1)

    def _select_project(self, project_id: str):
        self._active_project_id = project_id
        p = get_project(project_id)
        self.title_lbl.configure(text=f"📁 {p['name']}" if p else "Project")
        self._refresh_projects()
        self._refresh_sidebar()

    def _deselect_project(self):
        self._active_project_id = None
        self.title_lbl.configure(text="All Chats")
        self._refresh_projects()
        self._refresh_sidebar()

    def _new_project(self):
        ProjectDialog(self, on_save=self._refresh_projects)

    def _edit_project(self, proj: dict):
        ProjectDialog(self, proj=proj, on_save=self._refresh_projects,
                      on_delete=self._on_project_deleted)

    def _on_project_deleted(self, project_id: str):
        if self._active_project_id == project_id:
            self._active_project_id = None
        self._refresh_projects()
        self._refresh_sidebar()

    def _on_search(self, *_):
        q = self._search_var.get().strip()
        if q:
            self._clear_search_btn.grid()
        else:
            self._clear_search_btn.grid_remove()
        self._refresh_sidebar()

    def _clear_search(self):
        self._search_var.set("")
        self._search_entry.focus()

    _ACC_PALETTE = [
        "#388bfd",  # blue
        "#3fb950",  # green
        "#d29922",  # amber
        "#f78166",  # coral
        "#79c0ff",  # sky
        "#d2a8ff",  # lavender
    ]

    def _account_color(self, acc_id: str) -> str:
        ids = [aid for aid, _ in list_accounts()]
        try:
            idx = ids.index(acc_id)
        except ValueError:
            idx = 0
        return self._ACC_PALETTE[idx % len(self._ACC_PALETTE)]

    _SIDEBAR_PAGE_DEFAULT = 15

    def _refresh_sidebar(self):
        for w in self.conv_scroll.winfo_children():
            w.destroy()
        self._conv_buttons.clear()

        q = self._search_var.get().strip() if hasattr(self, "_search_var") else ""
        pid = self._active_project_id
        convs = search_conversations(q, pid) if q else get_conversations(pid)

        if q and not convs:
            ctk.CTkLabel(
                self.conv_scroll, text="No results.",
                font=self.F_SM, text_color=C["meta"],
            ).grid(pady=20)
            return

        # During search, show a flat list (no grouping, capped at 100)
        if q:
            for conv in convs[:100]:
                self._sidebar_conv_row(self.conv_scroll, conv, indent=False)
            return

        # Group conversations by account_id
        accounts = list_accounts()
        acc_map  = {aid: acc for aid, acc in accounts}
        acc_order = [aid for aid, _ in accounts]

        grouped: dict[str, list] = {aid: [] for aid in acc_order}
        grouped["__none__"] = []
        for conv in convs:
            aid = conv.get("account_id", "") or "__none__"
            if aid not in grouped:
                grouped[aid] = []
            grouped[aid].append(conv)

        row_idx = 0
        for aid in acc_order + ["__none__"]:
            bucket = grouped.get(aid, [])
            if not bucket:
                continue

            if aid == "__none__":
                label = "Other"
                color = C["meta"]
            else:
                label = acc_map[aid]["label"]
                color = self._account_color(aid)

            # ── Section header (collapsible) ──
            is_open = aid not in self._collapsed_accounts

            hdr = ctk.CTkFrame(self.conv_scroll, fg_color=C["border"], corner_radius=6)
            hdr.grid(row=row_idx, column=0, sticky="ew", padx=4, pady=(6, 1))
            hdr.grid_columnconfigure(1, weight=1)
            row_idx += 1

            ctk.CTkFrame(hdr, width=3, height=20, corner_radius=2,
                         fg_color=color).grid(row=0, column=0, padx=(6, 0), pady=6)

            chevron = "▼" if is_open else "▶"
            count   = len(bucket)
            hdr_btn = ctk.CTkButton(
                hdr,
                text=f"{chevron}  {label}  ({count})",
                anchor="w", height=28, font=self.F_SM,
                fg_color="transparent", hover_color=C["user_bg"],
                text_color="#e6edf3",
                command=lambda a=aid: self._toggle_account_section(a),
            )
            hdr_btn.grid(row=0, column=1, sticky="ew", padx=(4, 4))

            if not is_open:
                continue

            # ── Conversations under this account (capped) ──
            page = get_pref("sidebar_limit", self._SIDEBAR_PAGE_DEFAULT)
            limit = len(bucket) if aid in self._expanded_accounts else page
            visible = bucket[:limit]
            for conv in visible:
                self._sidebar_conv_row(self.conv_scroll, conv, indent=True,
                                       grid_row=row_idx)
                row_idx += 1

            remaining = len(bucket) - len(visible)
            if remaining > 0:
                show_more = ctk.CTkButton(
                    self.conv_scroll,
                    text=f"⋯  show {remaining} more",
                    anchor="w", height=24, font=self.F_SM,
                    fg_color="transparent", hover_color=C["border"],
                    text_color=C["meta"],
                    command=lambda a=aid: self._expand_account_section(a),
                )
                show_more.grid(row=row_idx, column=0, sticky="ew",
                               padx=(18, 4), pady=(0, 2))
                row_idx += 1

    def _expand_account_section(self, acc_id: str):
        self._expanded_accounts.add(acc_id)
        self._refresh_sidebar()

    def _sidebar_conv_row(self, parent, conv: dict, indent: bool = True,
                          grid_row: int | None = None):
        title     = conv["title"][:26] + ("…" if len(conv["title"]) > 26 else "")
        is_active = conv["id"] == self.current_conv_id

        btn = ctk.CTkButton(
            parent,
            text=title, anchor="w", height=28, font=self.F_SM,
            fg_color=C["user_bg"] if is_active else "transparent",
            hover_color=C["user_bg"],
            text_color="#e6edf3" if is_active else "#adbac7",
            command=lambda cid=conv["id"]: self._load_conv(cid),
        )
        pad_left = 14 if indent else 4
        if grid_row is not None:
            btn.grid(row=grid_row, column=0, sticky="ew",
                     padx=(pad_left, 4), pady=1)
        else:
            btn.grid(sticky="ew", padx=(pad_left, 4), pady=1)

        btn.bind("<Button-3>", lambda e, cid=conv["id"]: self._conv_context_menu(e, cid))
        self._conv_buttons[conv["id"]] = btn

    def _toggle_account_section(self, acc_id: str):
        if acc_id in self._collapsed_accounts:
            self._collapsed_accounts.discard(acc_id)
        else:
            self._collapsed_accounts.add(acc_id)
            self._expanded_accounts.discard(acc_id)
        self._refresh_sidebar()

    def _conv_context_menu(self, event, conv_id: str):
        accounts  = list_accounts()
        active_id = get_active_id()

        menu = tk.Menu(self, tearoff=0,
                       bg=C["sidebar"], fg=C["asst_fg"],
                       activebackground=C["select"], activeforeground="#e6edf3",
                       bd=0, relief=tk.FLAT)

        menu.add_command(
            label="Continue with…",
            state="disabled",
            font=("", 10),
        )
        menu.add_separator()

        for acc_id, acc in accounts:
            tag  = "api" if acc["mode"] == "api" else "sub"
            tick = "✦  " if acc_id == active_id else "     "
            menu.add_command(
                label=f"{tick}{acc['label']}  [{tag}]",
                command=lambda aid=acc_id, cid=conv_id: self._continue_with(aid, cid),
            )

        menu.add_separator()
        menu.add_command(
            label="🗑  Delete",
            command=lambda cid=conv_id: self._delete_conv_by_id(cid),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _continue_with(self, acc_id: str, conv_id: str):
        old_id = get_active_id()
        switched = acc_id != old_id
        if switched:
            set_active(acc_id)
            self._rebuild_account_menu()
            acc = get_active()
            self._update_mode_pill(acc)
            self.model_var.set(acc.get("model", MODELS[0]))
            self._last_account_id = acc_id

        self._inject_handoff = False  # history is already in the loaded conv
        self._load_conv(conv_id)

        if switched:
            acc = get_active()
            mode_label = "API Credits" if acc["mode"] == "api" else "Subscription"
            self._write_switch_banner(
                f"↔  Continuing with {acc['label']}  ({mode_label})  —  "
                f"full history shared"
            )

    def _delete_conv_by_id(self, conv_id: str):
        if not messagebox.askyesno("Delete", "Delete this conversation? This cannot be undone."):
            return
        delete_conversation(conv_id)
        if conv_id == self.current_conv_id:
            self._new_conv()
        else:
            self._refresh_sidebar()

    # ── Conversation ops ───────────────────────────────────────────────────────

    def _new_conv(self):
        self.current_conv_id = None  # created lazily on first send
        self.messages = []
        self._clear_chat()
        self.title_lbl.configure(text="New Conversation")
        self._refresh_sidebar()

    def _load_conv(self, conv_id: str):
        if self.is_loading:
            return
        self.current_conv_id = conv_id
        self.messages = get_messages(conv_id)
        self._clear_chat()
        cfg = load_cfg()

        self.chat.configure(state=tk.NORMAL)
        for i, m in enumerate(self.messages):
            if m["role"] == "user":
                self._write_user_msg(m["content"], i, m.get("account_label", ""))
            elif m["role"] == "switch":
                self.chat.insert(tk.END, f"\n  {m['content']}\n", "switch_banner")
            else:
                mode = m.get("mode", "subscription")
                self._write_asst_header(mode)
                self.md.render(m["content"])
        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)

        title = self.messages[0]["content"][:50] if self.messages else "New Conversation"
        self.title_lbl.configure(text=title)
        self._refresh_sidebar()

    def _delete_conv(self):
        if not self.current_conv_id or not self.messages:
            return
        if not messagebox.askyesno("Delete", "Delete this conversation? This cannot be undone."):
            return
        delete_conversation(self.current_conv_id)
        self._new_conv()

    # ── Chat display helpers ───────────────────────────────────────────────────

    def _clear_chat(self):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state=tk.NORMAL)

    def _write_user_header(self, account_label=""):
        self.chat.insert(tk.END, "\n")
        suffix = f"  ·  {account_label}" if account_label else ""
        self.chat.insert(tk.END, f"  You{suffix}\n", "user_acc")

    def _write_user_msg(self, text: str, msg_idx: int, account_label: str = ""):
        """Write a user bubble with an embedded ✏ edit button."""
        self._write_user_header(account_label)
        self.chat.insert(tk.END, f"  {text}\n", "user_body")
        btn = tk.Button(
            self.chat,
            text="  ✏ edit",
            bg=C["bg"], fg=C["meta"],
            activebackground=C["bg"], activeforeground="#e6edf3",
            relief=tk.FLAT, padx=4, pady=1,
            font=(MONO[0], 9), cursor="hand2", bd=0,
            command=lambda idx=msg_idx: self._edit_message(idx),
        )
        self.chat.window_create(tk.END, window=btn)
        self.chat.insert(tk.END, "\n")

    def _edit_message(self, msg_idx: int):
        """Reload a past user message into the input and truncate history after it."""
        if self.is_loading or msg_idx >= len(self.messages):
            return
        content = self.messages[msg_idx]["content"]
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        self.inp.delete("1.0", tk.END)
        self.inp.insert("1.0", content)

        self.messages = self.messages[:msg_idx]
        truncate_messages(self.current_conv_id, msg_idx)

        cfg = load_cfg()
        self._clear_chat()
        self.chat.configure(state=tk.NORMAL)
        for i, m in enumerate(self.messages):
            if m["role"] == "user":
                disp = m["content"] if isinstance(m["content"], str) else \
                       "\n".join(b.get("text","") for b in m["content"]
                                 if isinstance(b, dict) and b.get("type") == "text")
                self._write_user_msg(disp, i)
            else:
                self._write_asst_header(m.get("mode", "subscription"))
                self.md.render(m["content"])
        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)
        self.inp.focus()

    def _write_asst_header(self, mode: str):
        tag = "api_label" if mode == "api" else "asst_label"
        label = "api" if mode == "api" else "sub"
        self.chat.insert(tk.END, "\n")
        self.chat.insert(tk.END, "  Claude", tag)
        self.chat.insert(tk.END, f"  [{label}]\n", "meta")
        self.chat.insert(tk.END, "  ")  # left padding before content

    def _begin_stream(self):
        """Mark where streaming text will be inserted."""
        self._stream_idx = self.chat.index(f"{tk.END}-1c")
        self.chat.insert(tk.END, "thinking…", "thinking_txt")
        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)

    def _update_stream(self, accumulated: str):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete(self._stream_idx, tk.END)
        self.chat.insert(self._stream_idx, accumulated, "streaming")
        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)

    def _finish(self, full_text: str, usage: dict = {}):
        acc  = get_active()
        inp  = usage.get("input_tokens", 0)
        out  = usage.get("output_tokens", 0)
        model = usage.get("model", acc.get("model", "claude-sonnet-4-6"))

        # Remove raw streaming text, render with markdown
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete(self._stream_idx, tk.END)
        self.md.render(full_text)

        # Token pill below assistant response (API mode only)
        if inp or out:
            label = _fmt_tokens(inp, out, model)
            self.chat.insert(tk.END, f"\n  {label}\n", "meta")

        self.chat.configure(state=tk.NORMAL)
        self.chat.see(tk.END)

        add_message(self.current_conv_id, "assistant", full_text, acc["mode"],
                    acc.get("model", ""), input_tokens=inp, output_tokens=out)
        self.messages.append({"role": "assistant", "content": full_text, "mode": acc["mode"]})

        # Update session totals
        if inp or out:
            self._session_in  += inp
            self._session_out += out
            self._usage_var.set(_fmt_tokens(self._session_in, self._session_out, model))

        if len(self.messages) <= 2:
            title = self.messages[0]["content"][:50]
            update_title(self.current_conv_id, title)
            self.title_lbl.configure(text=title)
            self._refresh_sidebar()

        self._set_loading(False)

    def _show_error(self, msg: str):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete(self._stream_idx, tk.END)
        self.chat.insert(self._stream_idx, f"⚠  {msg}\n", "error_msg")
        self.chat.configure(state=tk.NORMAL)
        self._set_loading(False)

    # ── File attachments ───────────────────────────────────────────────────────

    def _pick_attachment(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Attach a file",
            filetypes=[
                ("Supported files", "*.png *.jpg *.jpeg *.gif *.webp *.pdf *.txt *.md *.py *.js *.ts *.json *.csv *.html *.css *.xml"),
                ("Images",          "*.png *.jpg *.jpeg *.gif *.webp"),
                ("Documents",       "*.pdf *.txt *.md"),
                ("Code",            "*.py *.js *.ts *.json *.csv *.html *.css *.xml"),
                ("All files",       "*.*"),
            ],
        )
        if path:
            self._add_attachment(path)

    def _add_attachment(self, path: str):
        import base64, mimetypes
        from pathlib import Path
        p = Path(path)
        ext = p.suffix.lower()
        name = p.name

        IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg",
                      ".jpeg": "image/jpeg", ".gif": "image/gif",
                      ".webp": "image/webp"}

        if ext in IMAGE_EXTS:
            data = base64.standard_b64encode(p.read_bytes()).decode()
            att = {"name": name, "kind": "image", "data": data,
                   "media_type": IMAGE_EXTS[ext]}
        elif ext == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(p))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception:
                text = f"[Could not extract text from {name}]"
            att = {"name": name, "kind": "text", "data": text, "media_type": "text/plain"}
        else:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = f"[Could not read {name}]"
            att = {"name": name, "kind": "text", "data": text, "media_type": "text/plain"}

        self._attachments.append(att)
        self._rebuild_attach_tray()

    def _rebuild_attach_tray(self):
        for w in self._attach_tray.winfo_children():
            w.destroy()

        if not self._attachments:
            self._attach_tray.grid_remove()
            return

        self._attach_tray.grid()
        for i, att in enumerate(self._attachments):
            icon = "🖼" if att["kind"] == "image" else "📄"
            chip = ctk.CTkFrame(self._attach_tray, fg_color=C["border"], corner_radius=6)
            chip.pack(side="left", padx=(0, 4), pady=2)
            ctk.CTkLabel(chip, text=f"{icon} {att['name'][:24]}",
                         font=self.F_SM, text_color="#e6edf3").pack(side="left", padx=(8, 2), pady=4)
            ctk.CTkButton(chip, text="✕", width=20, height=20,
                          fg_color="transparent", hover_color="#6e1313",
                          font=self.F_SM, text_color=C["meta"],
                          command=lambda idx=i: self._remove_attachment(idx),
                          ).pack(side="left", padx=(0, 4))

    def _remove_attachment(self, idx: int):
        if 0 <= idx < len(self._attachments):
            self._attachments.pop(idx)
        self._rebuild_attach_tray()

    def _clear_attachments(self):
        self._attachments.clear()
        self._rebuild_attach_tray()

    # ── Send / stop ────────────────────────────────────────────────────────────

    def _on_enter(self, event):
        if event.state & 0x1:
            return
        self._send()
        return "break"

    def _send(self):
        if self.is_loading:
            return
        text = self.inp.get("1.0", tk.END).strip()
        attachments = list(self._attachments)
        if not text and not attachments:
            return

        self.inp.delete("1.0", tk.END)
        self._clear_attachments()
        acc = get_active()
        cfg = load_cfg()

        # Handoff: prepend context summary so the new account is caught up
        if self._inject_handoff and self.messages:
            history = "\n".join(
                f"{'Human' if m['role'] == 'user' else 'Assistant'}: {m['content'][:300]}"
                for m in self.messages[-6:]
            )
            text = f"[Account switch. Conversation so far:\n{history}\n]\n\n{text}"
            self._inject_handoff = False

        # Build display text and API content
        display_text = text
        if attachments:
            names = ", ".join(a["name"] for a in attachments)
            display_text = f"[{names}]\n{text}" if text else f"[{names}]"

        # Build content for API (multimodal if images, text-prepend otherwise)
        if attachments and acc["mode"] == "api":
            content: list | str = []
            for att in attachments:
                if att["kind"] == "image":
                    content.append({"type": "image", "source": {
                        "type": "base64",
                        "media_type": att["media_type"],
                        "data": att["data"],
                    }})
                else:
                    content.append({"type": "text",
                                    "text": f"[File: {att['name']}]\n{att['data']}"})
            if text:
                content.append({"type": "text", "text": text})
        elif attachments:
            # Subscription mode: prepend text content (images described)
            parts = []
            for att in attachments:
                if att["kind"] == "image":
                    parts.append(f"[Image attached: {att['name']} — image data not available in CLI mode]")
                else:
                    parts.append(f"[File: {att['name']}]\n{att['data']}")
            content = "\n\n".join(parts) + (f"\n\n{text}" if text else "")
        else:
            content = text

        if self.current_conv_id is None:
            self.current_conv_id = create_conversation(
                project_id=self._active_project_id,
                account_id=get_active_id(),
            )

        stored_text = display_text if isinstance(content, list) else content
        add_message(self.current_conv_id, "user", stored_text, acc["mode"],
                    account_label=acc.get("label", ""))
        self.messages.append({"role": "user", "content": content,
                              "account_label": acc.get("label", "")})
        msg_idx = len(self.messages) - 1

        self.chat.configure(state=tk.NORMAL)
        self._write_user_msg(display_text, msg_idx, acc.get("label", ""))
        self._write_asst_header(acc["mode"])
        self._begin_stream()

        self._set_loading(True)
        self._stop_event.clear()

        api_msgs = [{"role": m["role"], "content": m["content"]} for m in self.messages]
        sys_prompt = ""
        if self._active_project_id:
            p = get_project(self._active_project_id)
            sys_prompt = p.get("system_prompt", "") if p else ""
        threading.Thread(target=self._worker, args=(api_msgs, sys_prompt), daemon=True).start()

    def _stop(self):
        self._stop_event.set()

    def _worker(self, msgs: list[dict], system_prompt: str = ""):
        try:
            accumulated = ""
            stop = self._stop_event
            usage_data = {}

            def on_chunk(chunk: str):
                nonlocal accumulated
                if stop.is_set():
                    return
                accumulated += chunk
                self.rq.put({"type": "chunk", "accumulated": accumulated})

            def on_usage(u: dict):
                usage_data.update(u)

            result = chat(msgs, on_chunk=on_chunk, stop_event=stop,
                          system_prompt=system_prompt, on_usage=on_usage)
            if not stop.is_set():
                self.rq.put({"type": "done", "text": result, "usage": usage_data})
            else:
                self.rq.put({"type": "done", "text": accumulated or result, "usage": usage_data})
        except Exception as exc:
            self.rq.put({"type": "error", "text": str(exc)})

    def _set_loading(self, state: bool):
        self.is_loading = state
        if state:
            self.send_btn.configure(
                text="■ Stop", fg_color="#b91c1c", hover_color="#991b1b",
                command=self._stop,
            )
        else:
            self.send_btn.configure(
                text="Send", fg_color=["#1f538d", "#1f538d"],
                hover_color=["#14375e", "#14375e"],
                command=self._send,
            )

    # ── Artifact export ────────────────────────────────────────────────────────

    def _export_artifact(self):
        if not self.messages:
            messagebox.showinfo("Nothing to export", "Start a conversation first.")
            return
        path = create_artifact(self.messages, self.title_lbl.cget("text"))
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, f"\n  📎 Artifact → {path}\n", "meta")
        self.chat.configure(state=tk.NORMAL)

    # ── Open switcher ──────────────────────────────────────────────────────────

    def _open_switcher(self):
        switcher = Path(__file__).parent / "switcher_app.py"
        subprocess.Popen([sys.executable, str(switcher)], close_fds=True)

    def _open_help(self):
        win = ctk.CTkToplevel(self)
        win.title("ClaudeSwitch — Help")
        win.geometry("720x560")
        win.configure(fg_color=C["bg"])

        # Load file-backed docs lazily so the main thread isn't blocked at open time
        _doc_cache: dict[str, str] = {}
        SECTION_KEYS = [
            ("Getting Started", lambda: _HELP_GETTING_STARTED),
            ("Keyboard Shortcuts", lambda: _HELP_SHORTCUTS),
            ("Features", lambda: _HELP_FEATURES),
            ("Changelog", lambda: _load_doc("CHANGELOG.md")),
            ("README", lambda: _load_doc("README.md")),
            ("License", lambda: _load_doc("LICENSE")),
        ]

        win.grid_columnconfigure(1, weight=1)
        win.grid_rowconfigure(0, weight=1)

        # Left nav
        nav = ctk.CTkFrame(win, width=160, fg_color=C["sidebar"], corner_radius=0)
        nav.grid(row=0, column=0, sticky="nsew")
        nav.grid_propagate(False)

        ctk.CTkLabel(nav, text="Help", font=self.F_BOLD,
                     text_color="#e6edf3").pack(pady=(18, 12), padx=14, anchor="w")

        # Content area
        content_frame = ctk.CTkFrame(win, fg_color=C["bg"], corner_radius=0)
        content_frame.grid(row=0, column=1, sticky="nsew")
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)

        txt = tk.Text(content_frame, bg=C["bg"], fg="#e6edf3",
                      font=("monospace", 11), wrap=tk.WORD,
                      relief=tk.FLAT, padx=22, pady=18,
                      selectbackground=C["select"])
        txt.grid(row=0, column=0, sticky="nsew")
        sb = ctk.CTkScrollbar(content_frame, command=txt.yview)
        sb.grid(row=0, column=1, sticky="ns")
        txt.configure(yscrollcommand=sb.set)
        # Block editing without disabling the widget (disabled + CTkScrollbar deadlocks on Linux)
        txt.bind("<Key>", lambda e: "break")

        def _show(name):
            if name not in _doc_cache:
                _doc_cache[name] = next(fn for k, fn in SECTION_KEYS if k == name)()
            txt.delete("1.0", tk.END)
            txt.insert(tk.END, _doc_cache[name])
            txt.yview_moveto(0)
            for b in nav_btns:
                b.configure(fg_color=C["user_bg"] if b._text == name else "transparent")

        nav_btns = []
        for name, _ in SECTION_KEYS:
            b = ctk.CTkButton(nav, text=name, anchor="w", height=30,
                              font=self.F_SM, fg_color="transparent",
                              hover_color=C["border"], text_color="#adbac7",
                              command=lambda n=name: _show(n))
            b._text = name
            b.pack(fill="x", padx=8, pady=1)
            nav_btns.append(b)

        win.after(50, lambda: _show("Getting Started"))

    def _open_preferences(self):
        win = ctk.CTkToplevel(self)
        win.title("Preferences")
        win.resizable(False, False)
        win.configure(fg_color=C["bg"])

        pad = {"padx": 20, "pady": 10}

        # ── Sidebar section ──
        ctk.CTkLabel(win, text="SIDEBAR", font=ctk.CTkFont(size=10),
                     text_color=C["meta"]).grid(row=0, column=0, columnspan=2,
                     sticky="w", padx=20, pady=(16, 2))

        ctk.CTkLabel(win, text="Conversations shown per account:",
                     font=self.F_UI, text_color="#e6edf3").grid(
                     row=1, column=0, sticky="w", **pad)

        current = get_pref("sidebar_limit", self._SIDEBAR_PAGE_DEFAULT)
        limit_var = tk.IntVar(value=current)
        val_lbl = ctk.CTkLabel(win, textvariable=limit_var,
                               font=self.F_BOLD, text_color="#e6edf3", width=30)
        val_lbl.grid(row=1, column=1, padx=(0, 20))

        slider = ctk.CTkSlider(win, from_=5, to=100, number_of_steps=19,
                               variable=limit_var, width=260,
                               command=lambda v: limit_var.set(int(v)))
        slider.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 6))

        ctk.CTkLabel(win, text="5", font=self.F_SM, text_color=C["meta"]).grid(
            row=3, column=0, sticky="w", padx=22)
        ctk.CTkLabel(win, text="100", font=self.F_SM, text_color=C["meta"]).grid(
            row=3, column=1, sticky="e", padx=22)

        ctk.CTkFrame(win, height=1, fg_color=C["border"]).grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=20, pady=12)

        def _save():
            set_pref("sidebar_limit", limit_var.get())
            self._expanded_accounts.clear()
            self._refresh_sidebar()
            win.destroy()

        ctk.CTkButton(win, text="Save", width=100, command=_save).grid(
            row=5, column=0, columnspan=2, pady=(0, 16))

    def _start_claudeai_import(self):
        LiveSyncDialog(self, on_import_done=self._on_import_done)

    def _on_import_done(self, convs: int, msgs: int):
        self._refresh_sidebar()
        self._write_system_notice(
            f"✓ Imported {convs} conversation{'s' if convs != 1 else ''} "
            f"and {msgs} message{'s' if msgs != 1 else ''} from Claude.ai."
        )


if __name__ == "__main__":
    ChatApp().mainloop()
