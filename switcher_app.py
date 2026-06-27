"""
ClaudeSwitch — Account Manager
Manage multiple accounts and switch between them seamlessly.
Launched via the ⚙ button in the main client, or: python switcher_app.py
"""
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from config_manager import (
    load, save,
    get_active_id, set_active,
    list_accounts, add_account,
    update_account, remove_account,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":      "#0d1117",
    "card":    "#161b22",
    "border":  "#21262d",
    "hover":   "#1c2128",
    "sub":     "#3fb950",
    "api":     "#d29922",
    "text":    "#e6edf3",
    "meta":    "#8b949e",
    "error":   "#f85149",
    "active":  "#1f6feb",
}

MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-8",
    "claude-haiku-4-5-20251001",
]


class AccountManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Account Manager")
        self.geometry("420x580")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])

        self.F_BOLD = ctk.CTkFont(size=13, weight="bold")
        self.F_UI   = ctk.CTkFont(size=13)
        self.F_SM   = ctk.CTkFont(size=11)

        self._editing: str | None = None  # acc_id being edited
        self._status_var = tk.StringVar()

        self._build_ui()
        self._refresh()
        self._poll()

    def _build_ui(self):
        # Title
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 4))
        ctk.CTkLabel(top, text="Account Manager", font=self.F_BOLD,
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(top, text="＋ Add Account", width=110, height=28,
                      font=self.F_SM, command=self._show_add_form).pack(side="right")

        ctk.CTkLabel(self, text="Click an account to make it active.",
                     font=self.F_SM, text_color=C["meta"]).pack(padx=20, anchor="w")

        # Account list (scrollable)
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", height=280)
        self.list_frame.pack(fill="x", padx=20, pady=(8, 0))
        self.list_frame.grid_columnconfigure(0, weight=1)

        # Divider
        ctk.CTkFrame(self, height=1, fg_color=C["border"]).pack(fill="x", padx=20, pady=12)

        # Add / Edit form (hidden until needed)
        self.form_frame = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=12)
        # (packed on demand)

        self._build_form()

        # Status
        ctk.CTkLabel(self, textvariable=self._status_var,
                     font=self.F_SM, text_color=C["sub"]).pack(pady=(4, 8))

    def _build_form(self):
        f = self.form_frame
        pad = {"padx": 14, "pady": 4}

        ctk.CTkLabel(f, text="ADD ACCOUNT", font=ctk.CTkFont(size=10),
                     text_color=C["meta"]).pack(anchor="w", padx=14, pady=(12, 0))

        self.form_label = ctk.CTkEntry(f, placeholder_text="Label  e.g. Work API",
                                       height=32, font=self.F_UI)
        self.form_label.pack(fill="x", **pad)

        mode_row = ctk.CTkFrame(f, fg_color="transparent")
        mode_row.pack(fill="x", **pad)
        mode_row.grid_columnconfigure((0, 1), weight=1)

        self.form_mode = tk.StringVar(value="subscription")
        self.sub_btn = ctk.CTkButton(mode_row, text="● Subscription", height=30,
                                      font=self.F_SM, fg_color=C["sub"], text_color=C["bg"],
                                      command=lambda: self._set_form_mode("subscription"))
        self.sub_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.api_btn = ctk.CTkButton(mode_row, text="● API Credits", height=30,
                                      font=self.F_SM, fg_color="#21262d", text_color=C["meta"],
                                      command=lambda: self._set_form_mode("api"))
        self.api_btn.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.key_frame = ctk.CTkFrame(f, fg_color="transparent")
        self.key_frame.pack(fill="x", padx=14, pady=4)
        self.key_frame.grid_columnconfigure(0, weight=1)
        self.form_key = ctk.CTkEntry(self.key_frame, placeholder_text="sk-ant-...",
                                      show="•", height=32, font=self.F_UI)
        self.form_key.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(self.key_frame, text="👁", width=32, height=32,
                       fg_color="#21262d", hover_color="#30363d",
                       command=self._toggle_key_vis).grid(row=0, column=1)
        self.key_frame.pack_forget()

        self.form_model = ctk.CTkOptionMenu(f, values=MODELS, height=30, font=self.F_SM,
                                             fg_color="#21262d", button_color="#30363d",
                                             dropdown_fg_color=C["card"])
        self.form_model.set(MODELS[0])
        self.form_model.pack(fill="x", **pad)

        btn_row = ctk.CTkFrame(f, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(4, 12))
        btn_row.grid_columnconfigure((0, 1), weight=1)
        self.save_btn = ctk.CTkButton(btn_row, text="Save", height=30, font=self.F_UI,
                                       command=self._save_form)
        self.save_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(btn_row, text="Cancel", height=30, font=self.F_UI,
                       fg_color="#21262d", hover_color="#30363d",
                       command=self._hide_form).grid(row=0, column=1, padx=(4, 0), sticky="ew")

    def _refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        active_id = get_active_id()
        accounts = list_accounts()

        for acc_id, acc in accounts:
            is_active = acc_id == active_id
            self._build_account_row(acc_id, acc, is_active)

        if not accounts:
            ctk.CTkLabel(self.list_frame, text="No accounts yet. Add one above.",
                         font=self.F_SM, text_color=C["meta"]).grid(pady=20)

    def _build_account_row(self, acc_id: str, acc: dict, is_active: bool):
        card = ctk.CTkFrame(
            self.list_frame,
            fg_color=C["hover"] if is_active else C["card"],
            corner_radius=10,
            border_width=2 if is_active else 0,
            border_color=C["active"] if is_active else C["border"],
        )
        card.grid(sticky="ew", pady=3)
        card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        inner.grid_columnconfigure(0, weight=1)

        # Label + mode badge
        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)

        label_text = ("✦  " if is_active else "   ") + acc["label"]
        ctk.CTkLabel(top_row, text=label_text, font=self.F_BOLD,
                     text_color=C["text"] if is_active else "#adbac7",
                     anchor="w").grid(row=0, column=0, sticky="w")

        mode_color = C["sub"] if acc["mode"] == "subscription" else C["api"]
        mode_text  = "sub" if acc["mode"] == "subscription" else "api"
        ctk.CTkLabel(top_row, text=f"● {mode_text}", font=self.F_SM,
                     text_color=mode_color).grid(row=0, column=1, padx=(4, 0))

        # Model
        ctk.CTkLabel(inner, text=acc.get("model", ""), font=self.F_SM,
                     text_color=C["meta"], anchor="w").grid(row=1, column=0, sticky="w")

        # Buttons
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=0, column=1, padx=(0, 8), pady=8)

        if not is_active:
            ctk.CTkButton(btn_row, text="Switch", width=64, height=26, font=self.F_SM,
                           command=lambda aid=acc_id: self._switch(aid)).pack(side="left", padx=2)

        ctk.CTkButton(btn_row, text="Edit", width=48, height=26, font=self.F_SM,
                       fg_color="#21262d", hover_color="#30363d",
                       command=lambda aid=acc_id, a=acc: self._show_edit_form(aid, a)
                       ).pack(side="left", padx=2)

        if len(list_accounts()) > 1:
            ctk.CTkButton(btn_row, text="✕", width=28, height=26, font=self.F_SM,
                           fg_color="#21262d", hover_color="#6e1313", text_color=C["error"],
                           command=lambda aid=acc_id, lbl=acc["label"]: self._delete(aid, lbl)
                           ).pack(side="left", padx=2)

    def _switch(self, acc_id: str):
        set_active(acc_id)
        self._refresh()
        acc = dict(list_accounts())[acc_id] if acc_id in dict(list_accounts()) else {}
        cfg = load()
        label = cfg["accounts"][acc_id]["label"]
        self._status(f"✓ Switched to {label}")

    def _delete(self, acc_id: str, label: str):
        if not messagebox.askyesno("Delete account", f"Delete '{label}'?"):
            return
        remove_account(acc_id)
        self._refresh()

    # ── Form ──────────────────────────────────────────────────────────────────

    def _show_add_form(self):
        self._editing = None
        self.form_label.delete(0, tk.END)
        self.form_key.delete(0, tk.END)
        self.form_model.set(MODELS[0])
        self._set_form_mode("subscription")
        self.form_frame.pack(fill="x", padx=20, pady=(0, 4))
        # Update title
        for w in self.form_frame.winfo_children():
            if isinstance(w, ctk.CTkLabel) and "ACCOUNT" in (w.cget("text") or ""):
                w.configure(text="ADD ACCOUNT")
                break

    def _show_edit_form(self, acc_id: str, acc: dict):
        self._editing = acc_id
        self.form_label.delete(0, tk.END)
        self.form_label.insert(0, acc["label"])
        self.form_key.delete(0, tk.END)
        self.form_key.insert(0, acc.get("api_key", ""))
        self.form_model.set(acc.get("model", MODELS[0]))
        self._set_form_mode(acc["mode"])
        self.form_frame.pack(fill="x", padx=20, pady=(0, 4))

    def _hide_form(self):
        self.form_frame.pack_forget()
        self._editing = None

    def _save_form(self):
        label = self.form_label.get().strip()
        mode  = self.form_mode.get()
        key   = self.form_key.get().strip()
        model = self.form_model.get()

        if not label:
            self._status("⚠ Enter a label.", error=True); return
        if mode == "api" and not key:
            self._status("⚠ Enter an API key for API mode.", error=True); return

        if self._editing:
            update_account(self._editing, label=label, mode=mode, api_key=key, model=model)
            self._status(f"✓ Updated '{label}'")
        else:
            acc_id = add_account(label, mode, key, model)
            self._status(f"✓ Added '{label}'")

        self._hide_form()
        self._refresh()

    def _set_form_mode(self, mode: str):
        self.form_mode.set(mode)
        if mode == "api":
            self.api_btn.configure(fg_color=C["api"], text_color=C["bg"])
            self.sub_btn.configure(fg_color="#21262d", text_color=C["meta"])
            self.key_frame.pack(fill="x", padx=14, pady=4,
                                before=self.form_model)
        else:
            self.sub_btn.configure(fg_color=C["sub"], text_color=C["bg"])
            self.api_btn.configure(fg_color="#21262d", text_color=C["meta"])
            self.key_frame.pack_forget()

    def _toggle_key_vis(self):
        self.form_key.configure(show="" if self.form_key.cget("show") == "•" else "•")

    def _status(self, msg: str, error: bool = False):
        self._status_var.set(msg)
        color = C["error"] if error else C["sub"]
        for w in self.winfo_children():
            if isinstance(w, ctk.CTkLabel) and w.cget("textvariable"):
                w.configure(text_color=color)
        self.after(3500, lambda: self._status_var.set(""))

    def _poll(self):
        self._refresh()
        self.after(2000, self._poll)


if __name__ == "__main__":
    AccountManager().mainloop()
