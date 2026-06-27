# ClaudeSwitch

A native desktop chat client for Claude that lets you **seamlessly switch between your Claude.ai subscription and Anthropic API credits** — mid-conversation, with one click — while keeping all your conversations stored locally on your machine.

Built because the official web app locks you into one billing mode at a time, and because your conversation history shouldn't live on someone else's server.

---

## Why ClaudeSwitch?

| Feature | Claude.ai web | ClaudeSwitch |
|---|---|---|
| Use subscription credits | ✅ | ✅ |
| Use API credits | ❌ | ✅ |
| Switch modes mid-chat | ❌ | ✅ |
| Conversations stored locally | ❌ | ✅ |
| Works offline (history) | ❌ | ✅ |
| Export conversations | ❌ | ✅ HTML |
| Open source | ❌ | ✅ MIT |

---

## Features

- **One-click mode switching** — a floating switcher window lets you toggle between your Claude.ai subscription and direct API credits at any time. The main client picks up the change within 2 seconds, no restart needed.
- **Full conversation history** — stored in SQLite at `~/.claude_client/conversations.db`. Your data never leaves your machine except for the actual API/CLI call.
- **Markdown rendering** — headers, bold, italic, inline code, fenced code blocks with language labels and copy buttons, bullet lists, numbered lists, blockquotes, horizontal rules.
- **Model selector** — switch between Haiku, Sonnet, and Opus from the header dropdown.
- **Stop generation** — cancel a response mid-stream.
- **Artifact export** — export any conversation to a styled HTML file that opens in your browser.
- **Seamless context continuity** — when you switch modes mid-conversation, the full history is replayed as context so Claude never loses the thread.

---

## Requirements

- Python 3.10+
- [Claude Code CLI](https://claude.ai/code) installed and logged in (for subscription mode)
- An [Anthropic API key](https://console.anthropic.com/) (for API credits mode)

---

## Install

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/claudeswitch.git
cd claudeswitch

# 2. Install system dependency (Linux only)
sudo apt-get install python3-tk      # Debian/Ubuntu
# brew install python-tk             # macOS

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Launch
python client_app.py
```

---

## Usage

### Main client
```bash
python client_app.py
```

- **Enter** — send message
- **Shift+Enter** — newline
- **📎 Artifact** — export conversation to HTML
- **⚙** — open the mode switcher
- **■ Stop** — cancel generation in progress

### Mode switcher
```bash
python switcher_app.py
```

Or click the **⚙** button in the main client. The switcher is a small always-on-top window. Select a mode, enter your API key if switching to API Credits, and click **Apply Switch**. The main client updates automatically.

### Subscription mode
Uses the `claude` CLI under the hood — billed to your Claude.ai subscription. Requires `claude login` to have been run at least once.

### API Credits mode
Uses the Anthropic Python SDK directly with streaming. Billed per token to your Anthropic account. Enter your `sk-ant-...` key in the switcher.

---

## Project structure

```
claudeswitch/
├── client_app.py       # Main chat GUI
├── switcher_app.py     # Floating mode switcher
├── claude_backend.py   # Routes to subscription CLI or API SDK
├── store.py            # SQLite conversation storage
├── config_manager.py   # Shared config (~/.claude_client/config.json)
├── artifacts.py        # HTML conversation export
└── requirements.txt
```

---

## Privacy & security

- Your API key is stored at `~/.claude_client/config.json` — local to your machine, never committed to this repo.
- Conversations are stored at `~/.claude_client/conversations.db` — also local only.
- In subscription mode, messages go through the `claude` CLI exactly as they would from your terminal.
- In API mode, messages go directly to `api.anthropic.com` via the official SDK.

---

## Contributing

PRs welcome. This is intentionally a single-file-per-concern codebase — keep it that way. If you add a feature, add it to the relevant file. Don't introduce a framework.

Ideas for contribution:
- Image / file attachment support
- System prompt editor
- Light mode theme
- Export to Markdown
- Conversation search
- Token usage display

---

## License

MIT — see [LICENSE](LICENSE).  
Created by [Ismael Angola Parets](https://github.com/YOUR_USERNAME).
