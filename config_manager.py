import json
import uuid
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude_client" / "config.json"


def _migrate(data: dict) -> dict:
    """Upgrade old single-account config to multi-account format."""
    if "accounts" in data:
        return data
    acc_id = "acc_default"
    return {
        "active": acc_id,
        "accounts": {
            acc_id: {
                "label": "Default",
                "mode": data.get("mode", "subscription"),
                "api_key": data.get("api_key", ""),
                "model": data.get("model", "claude-sonnet-4-6"),
            }
        },
    }


def load() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return _migrate(json.load(f))
        except Exception:
            pass
    acc_id = "acc_default"
    return {
        "active": acc_id,
        "accounts": {
            acc_id: {
                "label": "Default",
                "mode": "subscription",
                "api_key": "",
                "model": "claude-sonnet-4-6",
            }
        },
    }


def save(cfg: dict):
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Account helpers ────────────────────────────────────────────────────────────

def get_active() -> dict:
    cfg = load()
    return cfg["accounts"][cfg["active"]]


def get_active_id() -> str:
    return load()["active"]


def set_active(acc_id: str):
    cfg = load()
    if acc_id in cfg["accounts"]:
        cfg["active"] = acc_id
        save(cfg)


def list_accounts() -> list[tuple[str, dict]]:
    cfg = load()
    return list(cfg["accounts"].items())


def add_account(label: str, mode: str, api_key: str = "",
                model: str = "claude-sonnet-4-6", profile: str = "",
                cookies: dict = None, org_id: str = "") -> str:
    cfg = load()
    acc_id = f"acc_{uuid.uuid4().hex[:8]}"
    cfg["accounts"][acc_id] = {
        "label": label,
        "mode": mode,
        "api_key": api_key,
        "model": model,
        "profile": profile,
        "cookies": cookies or {},
        "org_id": org_id,
    }
    save(cfg)
    return acc_id


def update_account(acc_id: str, **kwargs):
    cfg = load()
    if acc_id in cfg["accounts"]:
        cfg["accounts"][acc_id].update(kwargs)
        save(cfg)


def remove_account(acc_id: str):
    cfg = load()
    if acc_id not in cfg["accounts"] or len(cfg["accounts"]) <= 1:
        return
    del cfg["accounts"][acc_id]
    if cfg["active"] == acc_id:
        cfg["active"] = next(iter(cfg["accounts"]))
    save(cfg)
