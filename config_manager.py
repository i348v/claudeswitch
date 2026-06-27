import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude_client" / "config.json"

DEFAULTS = {
    "mode": "subscription",
    "api_key": "",
    "model": "claude-sonnet-4-6",
    "max_tokens": 8096,
}


def load():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return {**DEFAULTS, **data}
        except Exception:
            pass
    return DEFAULTS.copy()


def save(config):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def set_mode(mode, api_key=None):
    cfg = load()
    cfg["mode"] = mode
    if api_key is not None:
        cfg["api_key"] = api_key
    save(cfg)
