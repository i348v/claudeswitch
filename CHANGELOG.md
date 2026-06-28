# Changelog

All notable changes to ClaudeSwitch are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Sidebar conversations grouped by account with colored section headers
- Collapsible account sections (click header to collapse/expand)
- "Show N more" pagination — sidebar loads 40 conversations per account
  and expands on demand (prevents UI freeze with large histories)
- Account color palette — each account gets a distinct colored stripe
- Empty-config graceful handling — app starts cleanly with no accounts added

### Fixed
- Sidebar freeze on startup when hundreds of conversations exist
  (creating 200+ widgets on the main thread blocked X11 event loop)
- App crash (KeyError) when launching with no accounts configured

---

## [1.3.0] - 2026-06-27

### Changed
- **Removed Claude Code CLI dependency entirely** — subscription mode now
  uses direct HTTP requests to claude.ai internal API via session cookies.
  No `claude` binary required. Works with any claude.ai account (free, Pro,
  any tier) without developer API access.

### Added
- Embedded WebKit2 login window — sign in with Google, Apple, or email
  directly inside the app; session cookies captured automatically
- Chrome user-agent spoofing and popup handling in login flow

---

## [1.2.0] - 2026-06-27

### Added
- Right-click context menus on chat area and input box (copy, paste, select all)
- Full keyboard shortcut suite: Ctrl+C, Ctrl+V, Ctrl+A, Ctrl+Z, Ctrl+Enter
- Multi-account conversation context menu — reassign a conversation to any account

### Fixed
- Text selection in chat widget — allow select without allowing edit
- Right-click binding order (Button-3 vs ButtonRelease-3)

---

## [1.1.0] - 2026-06-27

### Added
- **Token usage & cost display** — per-response and session totals shown in sidebar
- **Message attribution banners** — shows which account sent each message
  when a conversation spans multiple accounts
- **Auto account-switch banner** — inline notice when the active account
  changes mid-conversation
- **Apple Sign-In support** in the account auth flow
- Touchpad / mousewheel scroll fixed for Linux (Button-4/5 events)

---

## [1.0.0] - 2026-06-26

### Added
- **Multi-account switching** — add unlimited Claude.ai accounts and API keys;
  switch between them with a floating always-on-top switcher window
- **Projects** — folders with custom system prompts; conversations scoped to a project
- **File attachments** — attach images, PDFs, and text/code files to any message
- **Message editing** — click the ✏ icon on any past message to resubmit from
  that point; history after the edit is truncated and replaced
- **Conversation search** — live search box filters the sidebar as you type
- **Artifact export** — export any conversation to a styled, self-contained HTML file
- **Claude.ai conversation import** — import your existing claude.ai history via
  IMAP email (Gmail OAuth or App Password) or direct file
- **Real streaming** in subscription mode via SSE — token-by-token rendering,
  no waiting for the full response
- **Stop generation** — cancel a streaming response mid-flight
- **Local SQLite storage** — all conversations and messages stored at
  `~/.claude_client/conversations.db`; nothing leaves your machine except the
  actual API call
- **Model selector** in the header — switch between available Claude models
  per account
- **Seamless context handoff** — switching accounts mid-conversation replays
  full history so Claude retains context
- MIT license
