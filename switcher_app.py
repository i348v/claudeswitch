"""
ClaudeSwitch — Account Manager
Manage multiple accounts and switch between them seamlessly.
Launched via the ⚙ button in the main client, or: python switcher_app.py
"""
import json
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import customtkinter as ctk


def _run_claude_login(parent, on_cookies=None):
    """Open claude.ai/login in an embedded WebKit window, capture session cookies."""
    webview_script = Path(__file__).parent / "webview_login.py"

    dlg = ctk.CTkToplevel(parent)
    dlg.title("Sign in to Claude")
    dlg.geometry("360x160")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(fg_color="#0d1117")

    F_TITLE = ctk.CTkFont(size=14, weight="bold")
    F_BODY  = ctk.CTkFont(size=12)
    F_SM    = ctk.CTkFont(size=11)

    ctk.CTkLabel(dlg, text="Sign in to Claude", font=F_TITLE,
                 text_color="#e6edf3").pack(pady=(18, 4))
    status_var = tk.StringVar(value="Sign in with Google, Apple, or email\nin the window that just opened…")
    ctk.CTkLabel(dlg, textvariable=status_var, font=F_BODY,
                 text_color="#8b949e", wraplength=320,
                 justify="center").pack(pady=(0, 8), padx=20)

    cancel_ev = threading.Event()
    wv_proc   = [None]

    def _cancel():
        cancel_ev.set()
        if wv_proc[0]:
            try: wv_proc[0].terminate()
            except Exception: pass
        try: dlg.destroy()
        except Exception: pass

    ctk.CTkButton(dlg, text="Cancel", height=28, font=F_SM,
                  fg_color="#21262d", hover_color="#30363d",
                  command=_cancel).pack(pady=(0, 14))

    def _bg():
        try:
            proc = subprocess.Popen(
                [sys.executable, str(webview_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            wv_proc[0] = proc
            raw = proc.stdout.readline()
            proc.wait()
            err_out = proc.stderr.read().decode("utf-8", errors="replace").strip()
        except Exception as e:
            parent.after(0, lambda: status_var.set(f"Error: {e}"))
            return

        if cancel_ev.is_set():
            return

        try:
            cookies = json.loads(raw.decode("utf-8", errors="replace").strip() or "{}")
        except Exception:
            cookies = {}

        if not cookies.get("sessionKey"):
            msg = "Sign-in cancelled or failed."
            if err_out:
                import sys as _sys
                print(f"[webview_login] stderr:\n{err_out}", file=_sys.stderr, flush=True)
                log_path = Path(__file__).parent / "webview_error.log"
                log_path.write_text(err_out)
                msg = "Sign-in failed — see webview_error.log for details."
            parent.after(0, lambda: status_var.set(msg))
            return

        def _done():
            status_var.set("✓ Signed in! Click Save Account to finish.")
            if on_cookies:
                on_cookies(cookies)
            dlg.after(1800, dlg.destroy)

        parent.after(0, _done)

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
        self.geometry("440x480")
        self.minsize(380, 380)
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])
        self.grab_set()

        self._acc_id          = acc_id
        self._on_save         = on_save
        self._cookies         = acc.get("cookies", {}) if acc else {}
        self._original_cookies = dict(self._cookies)
        self._original_org_id  = acc.get("org_id", "") if acc else ""

        F_UI = ctk.CTkFont(size=13)
        F_SM = ctk.CTkFont(size=11)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        pad = {"padx": 20, "pady": 5}

        # Label
        ctk.CTkLabel(scroll, text="Label", font=F_SM, text_color=C["meta"],
                     anchor="w").pack(fill="x", padx=20, pady=(14, 0))
        self.lbl_entry = ctk.CTkEntry(scroll, placeholder_text="e.g. Personal, Work, Free Account",
                                      height=34, font=F_UI)
        self.lbl_entry.pack(fill="x", **pad)

        # Mode toggle
        ctk.CTkLabel(scroll, text="Mode", font=F_SM, text_color=C["meta"],
                     anchor="w").pack(fill="x", padx=20, pady=(8, 0))
        mode_row = ctk.CTkFrame(scroll, fg_color="transparent")
        mode_row.pack(fill="x", **pad)
        mode_row.grid_columnconfigure((0, 1), weight=1)

        self._mode = tk.StringVar(value="subscription")
        self.sub_btn = ctk.CTkButton(mode_row, text="● Claude.ai Account", height=34,
                                      font=F_SM, fg_color=C["sub"], text_color=C["bg"],
                                      command=lambda: self._set_mode("subscription"))
        self.sub_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.api_btn = ctk.CTkButton(mode_row, text="● API Key", height=34,
                                      font=F_SM, fg_color="#21262d", text_color=C["meta"],
                                      command=lambda: self._set_mode("api"))
        self.api_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Subscription sign-in box
        self._sub_info = ctk.CTkFrame(scroll, fg_color="#1c2128", corner_radius=8)
        self._session_lbl = ctk.CTkLabel(
            self._sub_info,
            text="No session — click Sign In to connect your Claude.ai account.",
            font=F_SM, text_color=C["meta"], justify="left", anchor="w",
            wraplength=360)
        self._session_lbl.pack(padx=14, pady=(12, 8))
        ctk.CTkButton(self._sub_info, text="Sign In (Google, Apple, or email)",
                       height=32, font=F_SM,
                       fg_color="#1f6feb", hover_color="#1a5cb0", text_color="#fff",
                       command=self._do_signin).pack(fill="x", padx=14, pady=(0, 12))

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

        # Save / Cancel
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
            self.model_menu.set(acc.get("model", MODELS[0]))
            self._set_mode(acc.get("mode", "subscription"))
            self._refresh_session_label()
        else:
            self._set_mode("subscription")

    def _refresh_session_label(self):
        if self._cookies.get("sessionKey"):
            self._session_lbl.configure(
                text="✓ Session active — click Sign In to re-authenticate.",
                text_color=C["sub"])
        else:
            self._session_lbl.configure(
                text="No session — click Sign In to connect your Claude.ai account.",
                text_color=C["meta"])

    def _do_signin(self):
        def _got_cookies(cookies):
            self._cookies = cookies
            self._refresh_session_label()
        _run_claude_login(self, on_cookies=_got_cookies)

    def _set_mode(self, mode):
        self._mode.set(mode)
        if mode == "api":
            self.api_btn.configure(fg_color=C["api"], text_color=C["bg"])
            self.sub_btn.configure(fg_color="#21262d", text_color=C["meta"])
            self._sub_info.pack_forget()
            self._key_frame.pack(fill="x", padx=20, pady=5, before=self.model_menu)
        else:
            self.sub_btn.configure(fg_color=C["sub"], text_color=C["bg"])
            self.api_btn.configure(fg_color="#21262d", text_color=C["meta"])
            self._key_frame.pack_forget()
            self._sub_info.pack(fill="x", padx=20, pady=5, before=self.model_menu)

    def _toggle_vis(self):
        self.key_entry.configure(show="" if self.key_entry.cget("show") == "•" else "•")

    def _save(self):
        label = self.lbl_entry.get().strip()
        mode  = self._mode.get()
        key   = self.key_entry.get().strip()
        model = self.model_menu.get()

        if not label:
            messagebox.showwarning("Missing label", "Please enter a label.", parent=self)
            return
        if mode == "api" and not key:
            messagebox.showwarning("Missing key", "Enter an API key.", parent=self)
            return
        if mode == "subscription" and not self._cookies.get("sessionKey"):
            messagebox.showwarning("Not signed in",
                                   "Please click Sign In to connect your Claude.ai account.",
                                   parent=self)
            return

        if self._acc_id:
            cookies_changed = self._cookies != self._original_cookies
            update_account(self._acc_id, label=label, mode=mode,
                           api_key=key, model=model,
                           cookies=self._cookies,
                           org_id="" if cookies_changed else self._original_org_id)
        else:
            add_account(label, mode, key, model, cookies=self._cookies)

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
