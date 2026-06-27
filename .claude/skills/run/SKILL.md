---
description: Launch and drive the ClaudeSwitch GUI app for testing
---

# Running ClaudeSwitch

## Environment
- **Display**: Live X session at `:0.0` (1920×1080 physical, confirmed via `xrandr`)
- **Screenshot tool**: `scrot` — captures at ~1456×816 due to desktop scaling
- **Window interaction**: `xdotool` — uses **physical pixel coordinates** (1920×1080 space)
- **Python**: `python3` (not `python`)

## Launch

```bash
cd /home/izzy/projects/test/claude_client
DISPLAY=:0.0 python3 client_app.py &
sleep 4
```

## Get window info

```bash
WID=$(DISPLAY=:0.0 xdotool search --name "ClaudeSwitch" | head -1)
DISPLAY=:0.0 xdotool getwindowgeometry $WID
```

Typical output: position `760,347`, size `1160×760`.
The window right-edge lands at exactly x=1920 (screen edge).
The window bottom at y=1107 slightly exceeds the 1080 screen height — input bar is partially clipped.

## Take a screenshot

```bash
DISPLAY=:0.0 scrot /tmp/cs_test.png
```

## Interact with the app

**Important**: xdotool `--window` relative coords don't land reliably due to scaling.
Use **absolute screen coordinates** instead:

```
Window origin: (760, 347)
Input textbox: abs ~(780, 1040)   # left side of input bar
Send button:   abs ~(1850, 1047)  # top-right of input bar
```

### Type and send a message

```bash
DISPLAY=:0.0 xdotool windowraise $WID windowfocus $WID
sleep 0.3
DISPLAY=:0.0 xdotool mousemove 780 1040 click 1
sleep 0.2
DISPLAY=:0.0 xdotool type --clearmodifiers --delay 30 "Your test message here"
sleep 0.2
DISPLAY=:0.0 xdotool mousemove 1850 1047 click 1
sleep 15   # wait for response (subscription mode can take 10-20s)
DISPLAY=:0.0 scrot /tmp/cs_after_send.png
```

### Open Account Manager (⚙ button)

```bash
DISPLAY=:0.0 xdotool mousemove 726 377 click 1
sleep 2
DISPLAY=:0.0 scrot /tmp/cs_account_mgr.png
```

## Kill the app

```bash
pkill -f client_app.py
```

## Known issues / gotchas

- **Blank conversations**: Fixed — app now creates the DB row lazily on first send, not on startup.
- **Coordinate drift**: If the window position moves, re-run `getwindowgeometry` and recalculate absolute coords.
- **Send button below screen edge**: The window is 760px tall but the screen is 1080px; at y=347 origin the bottom is y=1107 (27px below). The Send button is near the bottom, so its abs y is ~1047 (still on-screen).
- **Response time**: Subscription mode goes via the `claude` CLI which can take 10–30s depending on model. Wait at least 20s before screenshotting.
