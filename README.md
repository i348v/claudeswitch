# ClaudeSwitch

A native desktop chat client for Claude that lets you **switch between multiple Claude.ai accounts and API keys** — mid-conversation, with one click — while keeping all your conversations stored locally on your machine.

Built because the official web app locks you into one account at a time, and because your conversation history shouldn't live on someone else's server.

---

## Support this project

ClaudeSwitch is free and open source. If it saves you time or money, a tip is genuinely appreciated — this took a lot of late nights to build.

- **Zelle** → `ismaelangolaparets@gmail.com`
- **Cash App** → `$ismael201`

---

## Why ClaudeSwitch?

| Feature | Claude.ai web | ClaudeSwitch |
|---|---|---|
| Multiple accounts | ❌ | ✅ |
| Use subscription credits | ✅ | ✅ |
| Use API credits | ❌ | ✅ |
| Switch accounts mid-chat | ❌ | ✅ |
| Conversations stored locally | ❌ | ✅ |
| Works offline (history) | ❌ | ✅ |
| Import from Claude.ai | ❌ | ✅ |
| Export conversations | ❌ | ✅ HTML |
| Open source | ❌ | ✅ MIT |

---

## Features

- **Multi-account switching** — add as many Claude.ai accounts or API keys as you want. A floating always-on-top switcher lets you swap instantly; the main client picks up the change within 2 seconds, no restart needed.
- **Sidebar grouped by account** — conversations are organized under their account with colored headers, collapsible sections, and live search.
- **Projects** — create folders with a custom system prompt. Every conversation in a project uses that prompt automatically.
- **File attachments** — attach images, PDFs, and text/code files to any message.
- **Message editing** — click ✏ on any past message to resubmit from that point. History after the edit is replaced.
- **Conversation search** — live-filter the sidebar as you type.
- **Artifact export** — export any conversation to a styled, self-contained HTML file.
- **Claude.ai import** — bring your existing claude.ai conversation history in via Gmail OAuth or IMAP.
- **Real streaming** — token-by-token rendering in both subscription and API mode.
- **Stop generation** — cancel mid-stream at any time.
- **Token usage & cost** — per-response and session totals shown in API mode.
- **Local SQLite storage** — everything stored at `~/.claude_client/`. Nothing leaves your machine except the actual API call.
- **No CLI dependency** — subscription mode goes directly to claude.ai via your session cookies. No `claude` binary required.

---

## Requirements

- Python 3.10+
- Linux with X11 display (macOS/Windows support planned)
- System packages: `python3-tk`, `gir1.2-webkit2-4.0`, `python3-gi`

No Anthropic API key required to use subscription mode.

---

## Install

```bash
# 1. Clone
git clone https://github.com/i348v/claudeswitch.git
cd claudeswitch

# 2. Install system dependencies (Debian/Ubuntu)
sudo apt-get install python3-tk python3-gi gir1.2-webkit2-4.0

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Launch
python client_app.py
```

---

## Usage

```bash
python client_app.py
```

### Adding your first account

Click **⚙** in the top-left corner to open the account manager. Choose:
- **Subscription** — signs you into claude.ai via an embedded browser (Google, Apple, email — any method claude.ai supports). No API key needed.
- **API Credits** — paste your `sk-ant-...` key from [console.anthropic.com](https://console.anthropic.com/).

Give the account a label (e.g. "Personal", "Work API") and click Add.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Enter | Send message |
| Shift+Enter | Newline |
| Ctrl+C | Copy selected text |
| Ctrl+V | Paste |
| Ctrl+A | Select all |
| Ctrl+Z | Undo |

---

## Project structure

```
claudeswitch/
├── client_app.py       # Main chat GUI (ChatApp)
├── switcher_app.py     # Floating account switcher window
├── claude_backend.py   # Handles API and subscription HTTP requests
├── config_manager.py   # Shared config (~/.claude_client/config.json)
├── store.py            # SQLite conversation storage
├── webview_login.py    # Embedded WebKit2 sign-in window
├── artifacts.py        # HTML conversation export
├── email_watcher.py    # Claude.ai import via IMAP
├── gmail_oauth.py      # Gmail OAuth helper
└── requirements.txt
```

---

## Privacy & security

- Session cookies and API keys are stored at `~/.claude_client/config.json` — local to your machine, never committed.
- Conversations are stored at `~/.claude_client/conversations.db` — local only.
- In subscription mode, messages go directly to `claude.ai` via your session cookies.
- In API mode, messages go directly to `api.anthropic.com` via the official SDK.

---

## Roadmap

- [ ] Markdown rendering with syntax highlighting
- [ ] Session expiry detection with inline re-auth prompt
- [ ] Desktop notification on response complete
- [ ] Auto-title generation for new conversations
- [ ] System tray / minimize to tray
- [ ] macOS and Windows support
- [ ] Android client (same cookie-based auth)

---

## Contributing

PRs welcome. This is intentionally a single-file-per-concern codebase — keep it that way. Run `python client_app.py` with `DISPLAY=:0.0` set on Linux.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a full history of changes.

---

## License

MIT — see [LICENSE](LICENSE).
Created by [Ismael Angola Parets](https://github.com/i348v).
