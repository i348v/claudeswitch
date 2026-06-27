"""
ClaudeSwitch — Account Manager
Manage multiple accounts and switch between them seamlessly.
Launched via the ⚙ button in the main client, or: python switcher_app.py
"""
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import customtkinter as ctk

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\r')
_URL_RE   = re.compile(r'https?://\S+')

# Each profile gets its own isolated Claude config directory
_PROFILES_DIR = Path.home() / ".claude_client" / "profiles"


def _run_claude_login(parent, profile: str = ""):
    """Run claude auth login with an embedded webview — no browser, no code pasting."""
    claude = shutil.which("claude")
    if not claude:
        messagebox.showerror(
            "Claude CLI not found",
            "The 'claude' command was not found in your PATH.\n\n"
            "Install Claude Code first:\n  npm install -g @anthropic-ai/claude-code",
        )
        return

    cmd = [claude, "auth", "login"]
    env = dict(os.environ)
    env["BROWSER"] = "/bin/true"          # stop claude from opening its own browser
    if profile:
        profile_dir = _PROFILES_DIR / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(profile_dir)

    # ── Simple status dialog (no code field — webview handles everything) ─────
    dlg = ctk.CTkToplevel(parent)
    dlg.title("Sign in to Claude")
    dlg.geometry("400x340")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(fg_color="#0d1117")
    dlg.grab_set()

    F_TITLE = ctk.CTkFont(size=14, weight="bold")
    F_BODY  = ctk.CTkFont(size=12)
    F_SM    = ctk.CTkFont(size=11)

    ctk.CTkLabel(dlg, text="Sign in to Claude", font=F_TITLE,
                 text_color="#e6edf3").pack(pady=(18, 4))
    status_var = tk.StringVar(value="Opening private browser window…")
    ctk.CTkLabel(dlg, textvariable=status_var, font=F_BODY,
                 text_color="#8b949e", wraplength=340,
                 justify="left").pack(pady=(0, 6), padx=20, anchor="w")

    # Code paste area — shown once the private browser is open
    code_frame = ctk.CTkFrame(dlg, fg_color="transparent")
    code_entry = ctk.CTkEntry(code_frame, height=34, font=F_BODY,
                               placeholder_text="Paste code here…")
    code_entry.pack(fill="x", padx=0, pady=(0, 4))

    code_ready = threading.Event()
    cancel_ev  = threading.Event()
    procs      = []

    def _submit():
        code_ready.set()

    ctk.CTkButton(code_frame, text="Submit Code", height=30, font=F_BODY,
                  command=_submit).pack(fill="x")
    code_entry.bind("<Return>", lambda _: _submit())

    def _cancel():
        cancel_ev.set()
        code_ready.set()
        for p in procs:
            try: p.terminate()
            except Exception: pass
        try: dlg.destroy()
        except Exception: pass

    ctk.CTkButton(dlg, text="Cancel", height=28, font=F_SM,
                  fg_color="#21262d", hover_color="#30363d",
                  command=_cancel).pack(pady=(8, 12))

    def _bg():
        import time

        # ── Step 1: start claude auth login, capture the OAuth URL ────────────
        master_fd, slave_fd = pty.openpty()
        try:
            auth_proc = subprocess.Popen(
                cmd,
                stdout=slave_fd, stderr=slave_fd,
                stdin=subprocess.PIPE,
                env=env, close_fds=True,
            )
            procs.append(auth_proc)
            os.close(slave_fd)
        except Exception as e:
            try: os.close(slave_fd)
            except OSError: pass
            try: os.close(master_fd)
            except OSError: pass
            parent.after(0, lambda: status_var.set(f"Error: {e}"))
            return

        buf = ""
        auth_url = None
        t0 = time.time()
        while not cancel_ev.is_set() and time.time() - t0 < 15:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.1)
            except (ValueError, OSError):
                break
            if r:
                try:
                    buf += _ANSI_RE.sub(
                        "", os.read(master_fd, 512).decode("utf-8", errors="replace"))
                    m = _URL_RE.search(buf)
                    if m:
                        auth_url = m.group(0).rstrip(".,;)")
                        break
                except OSError:
                    break
            if auth_proc.poll() is not None:
                break

        if cancel_ev.is_set() or not auth_url:
            try: os.close(master_fd)
            except OSError: pass
            if not cancel_ev.is_set():
                parent.after(0, lambda: status_var.set(
                    "Could not start sign-in. Close this and try again."))
            else:
                auth_proc.terminate()
            return

        # ── Step 2: try embedded WebKit browser first ─────────────────────────
        webview_script = Path(__file__).parent / "webview_login.py"
        use_webview    = webview_script.exists()
        auth_code      = None

        if use_webview and not cancel_ev.is_set():
            parent.after(0, lambda: status_var.set(
                "Sign in in the window that just opened…\n"
                "(Close the sign-in window to cancel)"
            ))
            try:
                wv_proc = subprocess.Popen(
                    [sys.executable, str(webview_script), auth_url],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                procs.append(wv_proc)
                code_line = wv_proc.stdout.readline()
                wv_proc.wait()
                auth_code = code_line.decode("utf-8", errors="replace").strip() or None
            except Exception:
                auth_code    = None
                use_webview  = False  # WebKit unavailable — fall through to Firefox

            if use_webview and not auth_code and not cancel_ev.is_set():
                # User closed the webview without completing sign-in
                try: os.close(master_fd)
                except OSError: pass
                auth_proc.terminate()
                parent.after(0, lambda: status_var.set("Sign-in cancelled."))
                return

        # ── Fallback: Firefox private window + manual code paste ──────────────
        if not auth_code and not cancel_ev.is_set():
            firefox = shutil.which("firefox") or shutil.which("firefox-esr")
            if firefox:
                subprocess.Popen([firefox, "--private-window", auth_url])
            else:
                subprocess.Popen(["xdg-open", auth_url])

            parent.after(0, lambda: (
                status_var.set(
                    "1. Sign in with Google or Apple in the\n"
                    "   private Firefox window that just opened.\n\n"
                    "2. After signing in, copy the code shown\n"
                    "   and paste it below, then click Submit."
                ),
                code_frame.pack(fill="x", padx=20, pady=(4, 0)),
                code_entry.focus_set(),
            ))

            code_ready.wait()
            if cancel_ev.is_set():
                try: os.close(master_fd)
                except OSError: pass
                auth_proc.terminate()
                return

            auth_code = code_entry.get().strip()
            if not auth_code:
                try: os.close(master_fd)
                except OSError: pass
                parent.after(0, lambda: status_var.set("No code entered. Close this and try again."))
                return

        if not auth_code or cancel_ev.is_set():
            try: os.close(master_fd)
            except OSError: pass
            auth_proc.terminate()
            return

        # ── Step 4: send code to claude auth login ────────────────────────────
        parent.after(0, lambda: (
            status_var.set("Verifying…"),
            code_frame.pack_forget(),
        ))
        try:
            auth_proc.stdin.write((auth_code + "\n").encode())
            auth_proc.stdin.flush()
        except Exception:
            pass

        while not cancel_ev.is_set():
            try:
                r, _, _ = select.select([master_fd], [], [], 0.1)
            except (ValueError, OSError):
                break
            if r:
                try: os.read(master_fd, 512)
                except OSError: break
            elif auth_proc.poll() is not None:
                break

        try: os.close(master_fd)
        except OSError: pass

        if cancel_ev.is_set():
            auth_proc.terminate()
            return

        if auth_proc.wait() == 0:
            def _done():
                status_var.set("✓ Signed in! Click Save Account to finish.")
                dlg.after(2500, dlg.destroy)
            parent.after(0, _done)
        else:
            parent.after(0, lambda: status_var.set(
                "Sign-in failed — wrong code or timed out.\nClose this and try again."))

    threading.Thread(target=_bg, daemon=True).start()

from config_manager import (
    load,
    get_active_id, set_active,
    list_accounts, add_account,
    update_account, remove_account,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":     "#0d1117",
    "card":   "#161b22",
    "border": "#21262d",
    "hover":  "#1c2128",
    "sub":    "#3fb950",
    "api":    "#d29922",
    "text":   "#e6edf3",
    "meta":   "#8b949e",
    "error":  "#f85149",
    "active": "#1f6feb",
}

MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-8",
    "claude-haiku-4-5-20251001",
]


# ── Add / Edit dialog (separate toplevel so it never overflows the list) ───────

class AccountDialog(ctk.CTkToplevel):
    def __init__(self, parent, acc_id=None, acc=None, on_save=None):
        super().__init__(parent)
        self.title("Edit Account" if acc_id else "Add Account")
        self.geometry("440x560")
        self.minsize(380, 420)
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._acc_id  = acc_id
        self._on_save = on_save

        F_UI = ctk.CTkFont(size=13)
        F_SM = ctk.CTkFont(size=11)

        # Scrollable body so nothing ever gets cut off
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        pad = {"padx": 20, "pady": 5}

        # Label
        ctk.CTkLabel(scroll, text="Label", font=F_SM, text_color=C["meta"],
                     anchor="w").pack(fill="x", padx=20, pady=(14, 0))
        self.lbl_entry = ctk.CTkEntry(scroll, placeholder_text="e.g. Personal Sub, Work API",
                                      height=34, font=F_UI)
        self.lbl_entry.pack(fill="x", **pad)

        # Mode toggle
        ctk.CTkLabel(scroll, text="Auth Mode", font=F_SM, text_color=C["meta"],
                     anchor="w").pack(fill="x", padx=20, pady=(8, 0))
        mode_row = ctk.CTkFrame(scroll, fg_color="transparent")
        mode_row.pack(fill="x", **pad)
        mode_row.grid_columnconfigure((0, 1), weight=1)

        self._mode = tk.StringVar(value="subscription")
        self.sub_btn = ctk.CTkButton(mode_row, text="● Subscription", height=34,
                                      font=F_SM, fg_color=C["sub"], text_color=C["bg"],
                                      command=lambda: self._set_mode("subscription"))
        self.sub_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.api_btn = ctk.CTkButton(mode_row, text="● API Credits", height=34,
                                      font=F_SM, fg_color="#21262d", text_color=C["meta"],
                                      command=lambda: self._set_mode("api"))
        self.api_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Subscription sign-in box
        self._sub_info = ctk.CTkFrame(scroll, fg_color="#1c2128", corner_radius=8)
        ctk.CTkLabel(self._sub_info,
                     text="Sign in with your Claude.ai account.\nSupports Google, Apple ID, and email.",
                     font=F_SM, text_color=C["meta"], justify="left", anchor="w",
                     wraplength=360).pack(padx=14, pady=(12, 8))
        btn_row_sub = ctk.CTkFrame(self._sub_info, fg_color="transparent")
        btn_row_sub.pack(fill="x", padx=14, pady=(0, 12))
        btn_row_sub.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btn_row_sub, text="🔵  Sign in with Google", height=32, font=F_SM,
                       fg_color="#1f6feb", hover_color="#1a5cb0", text_color="#fff",
                       command=lambda: _run_claude_login(self, self.profile_entry.get().strip())
                       ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(btn_row_sub, text="  Sign in with Apple", height=32, font=F_SM,
                       fg_color="#21262d", hover_color="#30363d", text_color="#e6edf3",
                       command=lambda: _run_claude_login(self, self.profile_entry.get().strip())
                       ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Profile name — optional, used to keep multiple accounts separate
        self._profile_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        ctk.CTkLabel(self._profile_frame, text="Account nickname  (optional — for multiple accounts)",
                     font=F_SM, text_color=C["meta"], anchor="w").pack(fill="x")
        self.profile_entry = ctk.CTkEntry(
            self._profile_frame,
            placeholder_text="e.g. work, personal  — leave blank for your main account",
            height=34, font=F_UI)
        self.profile_entry.pack(fill="x", pady=(4, 0))

        # API key (api mode only)
        self._key_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        self._key_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._key_frame, text="Anthropic API Key",
                     font=F_SM, text_color=C["meta"], anchor="w").grid(
                         row=0, column=0, columnspan=2, sticky="w")
        self.key_entry = ctk.CTkEntry(self._key_frame, placeholder_text="sk-ant-...",
                                       show="•", height=34, font=F_UI)
        self.key_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0), padx=(0, 4))
        ctk.CTkButton(self._key_frame, text="👁", width=34, height=34,
                       fg_color="#21262d", hover_color="#30363d",
                       command=self._toggle_vis).grid(row=1, column=1, pady=(4, 0))

        # Model
        ctk.CTkLabel(scroll, text="Model", font=F_SM, text_color=C["meta"],
                     anchor="w").pack(fill="x", padx=20, pady=(10, 0))
        self.model_menu = ctk.CTkOptionMenu(scroll, values=MODELS, height=32, font=F_SM,
                                             fg_color="#21262d", button_color="#30363d",
                                             dropdown_fg_color=C["card"])
        self.model_menu.set(MODELS[0])
        self.model_menu.pack(fill="x", **pad)

        # Save / Cancel — fixed at bottom of window, outside scroll
        btn_row = ctk.CTkFrame(self, fg_color=C["bg"])
        btn_row.grid(row=1, column=0, sticky="ew", padx=20, pady=(6, 14))
        btn_row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(btn_row, text="Save Account", height=36, font=F_UI,
                       command=self._save).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", height=36, font=F_UI,
                       fg_color="#21262d", hover_color="#30363d",
                       command=self.destroy).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # Pre-fill if editing
        if acc:
            self.lbl_entry.insert(0, acc.get("label", ""))
            self.key_entry.insert(0, acc.get("api_key", ""))
            self.profile_entry.insert(0, acc.get("profile", ""))
            self.model_menu.set(acc.get("model", MODELS[0]))
            self._set_mode(acc.get("mode", "subscription"))
        else:
            self._set_mode("subscription")

    def _set_mode(self, mode):
        self._mode.set(mode)
        if mode == "api":
            self.api_btn.configure(fg_color=C["api"], text_color=C["bg"])
            self.sub_btn.configure(fg_color="#21262d", text_color=C["meta"])
            self._sub_info.pack_forget()
            self._profile_frame.pack_forget()
            self._key_frame.pack(fill="x", padx=20, pady=5, before=self.model_menu)
        else:
            self.sub_btn.configure(fg_color=C["sub"], text_color=C["bg"])
            self.api_btn.configure(fg_color="#21262d", text_color=C["meta"])
            self._key_frame.pack_forget()
            self._sub_info.pack(fill="x", padx=20, pady=5, before=self.model_menu)
            self._profile_frame.pack(fill="x", padx=20, pady=(0, 5), before=self.model_menu)

    def _toggle_vis(self):
        self.key_entry.configure(show="" if self.key_entry.cget("show") == "•" else "•")

    def _save(self):
        label   = self.lbl_entry.get().strip()
        mode    = self._mode.get()
        key     = self.key_entry.get().strip()
        model   = self.model_menu.get()
        profile = self.profile_entry.get().strip()

        if not label:
            messagebox.showwarning("Missing label", "Please enter a label.", parent=self)
            return
        if mode == "api" and not key:
            messagebox.showwarning("Missing key", "Enter an API key for API Credits mode.", parent=self)
            return

        if self._acc_id:
            update_account(self._acc_id, label=label, mode=mode,
                           api_key=key, model=model, profile=profile)
        else:
            add_account(label, mode, key, model, profile=profile)

        self.destroy()
        if self._on_save:
            self._on_save()


# ── Main account manager window ────────────────────────────────────────────────

class AccountManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Account Manager")
        self.geometry("440x520")
        self.minsize(380, 300)
        self.resizable(True, True)          # resizable so list never clips
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])

        self.F_BOLD = ctk.CTkFont(size=13, weight="bold")
        self.F_UI   = ctk.CTkFont(size=13)
        self.F_SM   = ctk.CTkFont(size=11)

        self._status_var = tk.StringVar()
        self._last_mtime  = 0.0   # only redraw when config changes
        self._build_ui()
        self._refresh()
        self._poll()

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Header ──
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="Accounts", font=self.F_BOLD,
                     text_color=C["text"]).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(hdr, text="＋  Add Account", width=120, height=30,
                      font=self.F_SM, command=self._add).grid(row=0, column=1)

        ctk.CTkLabel(self, text="Active account is used for all new messages.",
                     font=self.F_SM, text_color=C["meta"]
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(44, 0))

        # ── Scrollable account list (takes all remaining space) ──
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 0))
        self.list_frame.grid_columnconfigure(0, weight=1)

        # ── Status bar ──
        ctk.CTkLabel(self, textvariable=self._status_var,
                     font=self.F_SM, text_color=C["sub"]
                     ).grid(row=2, column=0, pady=(4, 10))

    def _refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        accounts  = list_accounts()
        active_id = get_active_id()

        if not accounts:
            ctk.CTkLabel(self.list_frame, text="No accounts yet — click ＋ Add Account.",
                         font=self.F_SM, text_color=C["meta"]).grid(pady=30)
            return

        for acc_id, acc in accounts:
            self._build_row(acc_id, acc, acc_id == active_id)

    def _build_row(self, acc_id, acc, is_active):
        card = ctk.CTkFrame(
            self.list_frame,
            fg_color=C["hover"] if is_active else C["card"],
            corner_radius=10,
            border_width=2 if is_active else 0,
            border_color=C["active"] if is_active else C["border"],
        )
        card.grid(sticky="ew", pady=4, padx=2)
        card.grid_columnconfigure(0, weight=1)

        # Left: info
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        info.grid_columnconfigure(0, weight=1)

        name_row = ctk.CTkFrame(info, fg_color="transparent")
        name_row.grid(row=0, column=0, sticky="ew")
        name_row.grid_columnconfigure(0, weight=1)

        prefix = "✦  " if is_active else "   "
        ctk.CTkLabel(name_row, text=prefix + acc["label"], font=self.F_BOLD,
                     text_color=C["text"] if is_active else "#adbac7",
                     anchor="w").grid(row=0, column=0, sticky="w")

        badge_color = C["sub"] if acc["mode"] == "subscription" else C["api"]
        badge_text  = "sub" if acc["mode"] == "subscription" else "api"
        ctk.CTkLabel(name_row, text=f"● {badge_text}", font=self.F_SM,
                     text_color=badge_color).grid(row=0, column=1)

        ctk.CTkLabel(info, text=acc.get("model", ""), font=self.F_SM,
                     text_color=C["meta"], anchor="w").grid(row=1, column=0, sticky="w")

        # Right: action buttons
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=0, column=1, padx=(0, 10), pady=10)

        if not is_active:
            ctk.CTkButton(btns, text="Switch", width=66, height=28, font=self.F_SM,
                           command=lambda aid=acc_id: self._switch(aid)
                           ).pack(side="left", padx=2)

        ctk.CTkButton(btns, text="Edit", width=48, height=28, font=self.F_SM,
                       fg_color="#21262d", hover_color="#30363d",
                       command=lambda aid=acc_id, a=acc: self._edit(aid, a)
                       ).pack(side="left", padx=2)

        if len(list_accounts()) > 1:
            ctk.CTkButton(btns, text="✕", width=28, height=28, font=self.F_SM,
                           fg_color="#21262d", hover_color="#6e1313",
                           text_color=C["error"],
                           command=lambda aid=acc_id, lbl=acc["label"]: self._delete(aid, lbl)
                           ).pack(side="left", padx=2)

    def _add(self):
        AccountDialog(self, on_save=self._refresh)

    def _edit(self, acc_id, acc):
        AccountDialog(self, acc_id=acc_id, acc=acc, on_save=self._refresh)

    def _switch(self, acc_id):
        set_active(acc_id)
        label = dict(list_accounts()).get(acc_id, {}).get("label", acc_id)
        self._status(f"✓ Switched to {label}")
        self._refresh()

    def _delete(self, acc_id, label):
        if not messagebox.askyesno("Delete account", f"Delete '{label}'?"):
            return
        remove_account(acc_id)
        self._refresh()

    def _status(self, msg, error=False):
        self._status_var.set(msg)
        self.after(3000, lambda: self._status_var.set(""))

    def _poll(self):
        import os
        from config_manager import CONFIG_PATH
        try:
            mtime = os.path.getmtime(CONFIG_PATH)
        except FileNotFoundError:
            mtime = 0.0
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self._refresh()
        self.after(1000, self._poll)


if __name__ == "__main__":
    AccountManager().mainloop()
