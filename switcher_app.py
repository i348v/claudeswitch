"""
Claude Client — Mode Switcher
A small floating window to toggle between Claude subscription and API credits.
Run standalone:  python switcher_app.py
Or launched from the gear icon in the main client.
"""
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from config_manager import load as load_cfg, save as save_cfg

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":       "#0d1117",
    "card":     "#161b22",
    "border":   "#21262d",
    "sub":      "#3fb950",
    "api":      "#d29922",
    "inactive": "#484f58",
    "text":     "#e6edf3",
    "meta":     "#8b949e",
}


class SwitcherApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Mode Switcher")
        self.geometry("360x440")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=C["bg"])

        self._cfg = load_cfg()
        self._pending_mode = tk.StringVar(value=self._cfg["mode"])
        self._status_var = tk.StringVar(value="")

        self._build_ui()
        self._refresh_display()
        self._poll()

    def _build_ui(self):
        pad = {"padx": 20, "pady": 10}

        # ── Title ──
        ctk.CTkLabel(
            self, text="Mode Switcher",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=C["text"],
        ).pack(pady=(22, 4))

        ctk.CTkLabel(
            self, text="Switch between Claude subscription\nand direct API credits",
            font=ctk.CTkFont(size=11), text_color=C["meta"],
        ).pack(pady=(0, 14))

        # ── Current mode card ──
        card = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=12)
        card.pack(fill="x", **pad)

        ctk.CTkLabel(card, text="ACTIVE MODE", font=ctk.CTkFont(size=10),
                     text_color=C["meta"]).pack(pady=(12, 2))
        self.active_lbl = ctk.CTkLabel(
            card, text="", font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.active_lbl.pack(pady=(0, 12))

        # ── Toggle buttons ──
        toggle_frame = ctk.CTkFrame(self, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=20, pady=(4, 0))
        toggle_frame.grid_columnconfigure(0, weight=1)
        toggle_frame.grid_columnconfigure(1, weight=1)

        self.sub_btn = ctk.CTkButton(
            toggle_frame,
            text="● Subscription",
            height=48,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._select("subscription"),
        )
        self.sub_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.api_btn = ctk.CTkButton(
            toggle_frame,
            text="● API Credits",
            height=48,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._select("api"),
        )
        self.api_btn.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # ── API key section ──
        self.api_section = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=12)
        self.api_section.pack(fill="x", padx=20, pady=(12, 0))

        ctk.CTkLabel(
            self.api_section, text="Anthropic API Key",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=C["meta"],
        ).pack(anchor="w", padx=14, pady=(12, 4))

        key_row = ctk.CTkFrame(self.api_section, fg_color="transparent")
        key_row.pack(fill="x", padx=14, pady=(0, 12))
        key_row.grid_columnconfigure(0, weight=1)

        self.key_entry = ctk.CTkEntry(
            key_row, placeholder_text="sk-ant-...",
            show="•", height=34, font=ctk.CTkFont(size=12),
        )
        self.key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.eye_btn = ctk.CTkButton(
            key_row, text="👁", width=34, height=34,
            fg_color="#21262d", hover_color="#30363d",
            command=self._toggle_key_visibility,
        )
        self.eye_btn.grid(row=0, column=1)

        existing_key = self._cfg.get("api_key", "")
        if existing_key:
            self.key_entry.insert(0, existing_key)

        # ── Apply button ──
        self.apply_btn = ctk.CTkButton(
            self,
            text="Apply Switch",
            height=42,
            corner_radius=10,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._apply,
        )
        self.apply_btn.pack(fill="x", padx=20, pady=(14, 6))

        # ── Status label ──
        self.status_lbl = ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=ctk.CTkFont(size=11), text_color=C["meta"],
        )
        self.status_lbl.pack(pady=(2, 12))

    def _select(self, mode):
        self._pending_mode.set(mode)
        self._refresh_display()

    def _refresh_display(self):
        cfg = load_cfg()
        active = cfg["mode"]
        pending = self._pending_mode.get()

        # Active mode card
        if active == "api":
            self.active_lbl.configure(text="API Credits", text_color=C["api"])
        else:
            self.active_lbl.configure(text="Subscription", text_color=C["sub"])

        # Toggle buttons: highlight selected pending mode
        sub_active = pending == "subscription"
        api_active = pending == "api"

        self.sub_btn.configure(
            fg_color=C["sub"] if sub_active else "#21262d",
            text_color=C["bg"] if sub_active else C["inactive"],
            hover_color="#2ea043" if sub_active else "#30363d",
        )
        self.api_btn.configure(
            fg_color=C["api"] if api_active else "#21262d",
            text_color=C["bg"] if api_active else C["inactive"],
            hover_color="#b08800" if api_active else "#30363d",
        )

        # Show/hide API key section
        if pending == "api":
            self.api_section.pack(fill="x", padx=20, pady=(12, 0))
        else:
            self.api_section.pack_forget()

        # Apply button: grey out if already on this mode
        if pending == active:
            self.apply_btn.configure(
                text="Already Active",
                fg_color="#21262d",
                text_color=C["meta"],
                state="disabled",
            )
        else:
            self.apply_btn.configure(
                text=f"Switch to {'API Credits' if pending == 'api' else 'Subscription'}",
                fg_color="#1f6feb",
                text_color=C["text"],
                state="normal",
            )

    def _apply(self):
        pending = self._pending_mode.get()
        api_key = self.key_entry.get().strip() if pending == "api" else None

        if pending == "api" and not api_key:
            self._status("⚠ Enter your Anthropic API key first.", error=True)
            return

        cfg = load_cfg()
        cfg["mode"] = pending
        if api_key:
            cfg["api_key"] = api_key
        save_cfg(cfg)

        label = "API Credits" if pending == "api" else "Subscription"
        self._status(f"✓ Switched to {label}. Main client updates in ~2s.")
        self._refresh_display()

    def _status(self, msg, error=False):
        self._status_var.set(msg)
        color = "#f85149" if error else C["sub"]
        self.status_lbl.configure(text_color=color)
        # Clear after 4 seconds
        self.after(4000, lambda: self._status_var.set(""))

    def _toggle_key_visibility(self):
        current = self.key_entry.cget("show")
        self.key_entry.configure(show="" if current == "•" else "•")

    def _poll(self):
        self._refresh_display()
        self.after(1500, self._poll)


if __name__ == "__main__":
    SwitcherApp().mainloop()
