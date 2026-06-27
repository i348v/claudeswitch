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
from config_manager import load as load_cfg, save as save_cfg
from store import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversations,
    get_messages,
    init_db,
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

        # Fonts (must come after super().__init__)
        self.F_UI   = ctk.CTkFont(size=13)
        self.F_BOLD = ctk.CTkFont(size=13, weight="bold")
        self.F_SM   = ctk.CTkFont(size=11)
        self.F_MONO = ctk.CTkFont(family=MONO[0], size=MONO[1])

        init_db()
        self._build_ui()
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

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=C["sidebar"])
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(1, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(sb, fg_color="transparent", height=54)
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(14, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="ClaudeSwitch", font=self.F_BOLD,
                     text_color="#e6edf3").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            hdr, text="⚙", width=30, height=30, fg_color="transparent",
            hover_color=C["border"], font=ctk.CTkFont(size=16),
            command=self._open_switcher,
        ).grid(row=0, column=1)

        self.conv_scroll = ctk.CTkScrollableFrame(sb, fg_color="transparent", corner_radius=0)
        self.conv_scroll.grid(row=1, column=0, sticky="nsew", padx=4)
        self.conv_scroll.grid_columnconfigure(0, weight=1)

        bot = ctk.CTkFrame(sb, fg_color="transparent")
        bot.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        bot.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(bot, text="＋  New Chat", height=34,
                      font=self.F_UI, command=self._new_conv,
                      ).grid(row=0, column=0, sticky="ew")

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

        # Model selector
        cfg = load_cfg()
        self.model_var = tk.StringVar(value=cfg.get("model", MODELS[0]))
        self.model_menu = ctk.CTkOptionMenu(
            hdr, values=MODELS, variable=self.model_var,
            width=200, height=28, font=self.F_SM,
            command=self._on_model_change,
            fg_color="#21262d", button_color="#30363d",
            dropdown_fg_color=C["sidebar"],
        )
        self.model_menu.grid(row=0, column=1, padx=6, pady=14)

        self.mode_pill = ctk.CTkLabel(
            hdr, text="● Subscription", font=self.F_SM, text_color=C["asst_acc"]
        )
        self.mode_pill.grid(row=0, column=2, padx=(0, 4), pady=14)

        ctk.CTkButton(
            hdr, text="🗑", width=30, height=30, fg_color="transparent",
            hover_color="#21262d", font=ctk.CTkFont(size=15),
            command=self._delete_conv,
        ).grid(row=0, column=3, padx=(0, 10), pady=14)

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
            state=tk.DISABLED,
            relief=tk.FLAT,
            padx=28, pady=18,
            selectbackground=C["select"],
            insertbackground="#e6edf3",
            spacing1=2, spacing3=6,
            cursor="arrow",
        )
        vsb = ctk.CTkScrollbar(chat_wrap, command=self.chat.yview)
        self.chat.configure(yscrollcommand=vsb.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.md = MarkdownRenderer(self.chat)

        # ── Input bar ──
        inp_bar = ctk.CTkFrame(main, height=98, corner_radius=0, fg_color=C["sidebar"])
        inp_bar.grid(row=2, column=0, sticky="ew")
        inp_bar.grid_columnconfigure(0, weight=1)
        inp_bar.grid_propagate(False)

        self.inp = ctk.CTkTextbox(inp_bar, height=62, font=self.F_UI, wrap="word")
        self.inp.grid(row=0, column=0, padx=(14, 6), pady=14, sticky="ew")
        self.inp.bind("<Return>",       self._on_enter)
        self.inp.bind("<Shift-Return>", lambda e: None)

        btn_box = ctk.CTkFrame(inp_bar, fg_color="transparent")
        btn_box.grid(row=0, column=1, padx=(0, 14), pady=14, sticky="ns")

        self.send_btn = ctk.CTkButton(
            btn_box, text="Send", width=90, height=28,
            font=self.F_UI, command=self._send,
        )
        self.send_btn.pack(pady=(4, 4))

        ctk.CTkButton(
            btn_box, text="📎 Artifact", width=90, height=28,
            font=self.F_SM, fg_color="#21262d", hover_color="#30363d",
            text_color="#adbac7", command=self._export_artifact,
        ).pack()

    # ── Config polling ─────────────────────────────────────────────────────────

    def _poll_config(self):
        cfg = load_cfg()
        if cfg["mode"] == "api":
            self.mode_pill.configure(text="● API Credits", text_color=C["api_acc"])
        else:
            self.mode_pill.configure(text="● Subscription", text_color=C["asst_acc"])
        self.after(1500, self._poll_config)

    def _on_model_change(self, model: str):
        cfg = load_cfg()
        cfg["model"] = model
        save_cfg(cfg)

    # ── Response queue polling ─────────────────────────────────────────────────

    def _poll_response(self):
        try:
            while True:
                item = self.rq.get_nowait()
                if item["type"] == "chunk":
                    self._update_stream(item["accumulated"])
                elif item["type"] == "done":
                    self._finish(item["text"])
                elif item["type"] == "error":
                    self._show_error(item["text"])
        except queue.Empty:
            pass
        self.after(40, self._poll_response)

    # ── Sidebar ────────────────────────────────────────────────────────────────

    def _refresh_sidebar(self):
        for w in self.conv_scroll.winfo_children():
            w.destroy()
        self._conv_buttons.clear()

        for conv in get_conversations():
            label = conv["title"][:32] + ("…" if len(conv["title"]) > 32 else "")
            is_active = conv["id"] == self.current_conv_id
            btn = ctk.CTkButton(
                self.conv_scroll,
                text=label, anchor="w", height=30, font=self.F_SM,
                fg_color=C["user_bg"] if is_active else "transparent",
                hover_color=C["user_bg"],
                text_color="#e6edf3" if is_active else "#adbac7",
                command=lambda cid=conv["id"]: self._load_conv(cid),
            )
            btn.grid(sticky="ew", pady=1, padx=2)
            self._conv_buttons[conv["id"]] = btn

    # ── Conversation ops ───────────────────────────────────────────────────────

    def _new_conv(self):
        self.current_conv_id = create_conversation()
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
        for m in self.messages:
            if m["role"] == "user":
                self._write_user_header()
                self.chat.insert(tk.END, f"  {m['content']}\n", "user_body")
            else:
                mode = m.get("mode", cfg["mode"])
                self._write_asst_header(mode)
                self.md.render(m["content"])
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

        title = self.messages[0]["content"][:50] if self.messages else "New Conversation"
        self.title_lbl.configure(text=title)
        self._refresh_sidebar()

    def _delete_conv(self):
        if not self.current_conv_id:
            return
        if not messagebox.askyesno("Delete", "Delete this conversation? This cannot be undone."):
            return
        delete_conversation(self.current_conv_id)
        self._new_conv()

    # ── Chat display helpers ───────────────────────────────────────────────────

    def _clear_chat(self):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state=tk.DISABLED)

    def _write_user_header(self):
        self.chat.insert(tk.END, "\n")
        self.chat.insert(tk.END, "  You\n", "user_acc")

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
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _update_stream(self, accumulated: str):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete(self._stream_idx, tk.END)
        self.chat.insert(self._stream_idx, accumulated, "streaming")
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _finish(self, full_text: str):
        cfg = load_cfg()
        # Remove raw streaming text, render with markdown
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete(self._stream_idx, tk.END)
        self.md.render(full_text)
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

        add_message(self.current_conv_id, "assistant", full_text, cfg["mode"], cfg.get("model", ""))
        self.messages.append({"role": "assistant", "content": full_text, "mode": cfg["mode"]})

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
        self.chat.configure(state=tk.DISABLED)
        self._set_loading(False)

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
        if not text:
            return

        self.inp.delete("1.0", tk.END)
        cfg = load_cfg()
        add_message(self.current_conv_id, "user", text, cfg["mode"])
        self.messages.append({"role": "user", "content": text})

        self.chat.configure(state=tk.NORMAL)
        self._write_user_header()
        self.chat.insert(tk.END, f"  {text}\n", "user_body")
        self._write_asst_header(cfg["mode"])
        self._begin_stream()

        self._set_loading(True)
        self._stop_event.clear()

        api_msgs = [{"role": m["role"], "content": m["content"]} for m in self.messages]
        threading.Thread(target=self._worker, args=(api_msgs,), daemon=True).start()

    def _stop(self):
        self._stop_event.set()

    def _worker(self, msgs: list[dict]):
        try:
            accumulated = ""
            stop = self._stop_event

            def on_chunk(chunk: str):
                nonlocal accumulated
                if stop.is_set():
                    return
                accumulated += chunk
                self.rq.put({"type": "chunk", "accumulated": accumulated})

            result = chat(msgs, on_chunk=on_chunk, stop_event=stop)
            if not stop.is_set():
                self.rq.put({"type": "done", "text": result})
            else:
                self.rq.put({"type": "done", "text": accumulated or result})
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
        self.chat.configure(state=tk.DISABLED)

    # ── Open switcher ──────────────────────────────────────────────────────────

    def _open_switcher(self):
        switcher = Path(__file__).parent / "switcher_app.py"
        subprocess.Popen([sys.executable, str(switcher)], close_fds=True)


if __name__ == "__main__":
    ChatApp().mainloop()
