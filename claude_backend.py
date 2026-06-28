import json
import uuid
import threading
import anthropic
import requests
from config_manager import get_active

_WEB_BASE = "https://claude.ai"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://claude.ai/",
    "Origin": "https://claude.ai",
    "Content-Type": "application/json",
    "anthropic-client-platform": "web_claude_ai",
}


def chat(messages, on_chunk=None, stop_event: threading.Event = None,
         system_prompt: str = "", on_usage=None):
    acc = get_active()
    if acc["mode"] == "api":
        return _api(messages, acc, on_chunk, stop_event, system_prompt, on_usage)
    return _web_session(messages, acc, on_chunk, stop_event, system_prompt)


# ── API key mode ───────────────────────────────────────────────────────────────

def _api(messages, acc, on_chunk, stop_event, system_prompt="", on_usage=None):
    if not acc.get("api_key"):
        raise ValueError(
            f"Account '{acc['label']}' has no API key. "
            "Open Account Manager and add one."
        )
    client = anthropic.Anthropic(api_key=acc["api_key"])
    api_msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
    model = acc.get("model", "claude-sonnet-4-6")
    kwargs = dict(model=model, max_tokens=8096, messages=api_msgs)
    if system_prompt:
        kwargs["system"] = system_prompt

    full = ""
    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                if stop_event and stop_event.is_set():
                    break
                full += text
                if on_chunk:
                    on_chunk(text)
            if on_usage:
                try:
                    usage = stream.get_final_message().usage
                    on_usage({"input_tokens": usage.input_tokens,
                               "output_tokens": usage.output_tokens,
                               "model": model})
                except Exception:
                    pass
    except anthropic.AuthenticationError:
        raise RuntimeError("API key invalid or expired — check Account Manager.")
    except anthropic.PermissionDeniedError:
        raise RuntimeError(f"Permission denied for model '{model}'.")
    return full


# ── Web session mode ───────────────────────────────────────────────────────────

def _make_session(acc) -> requests.Session:
    cookies = acc.get("cookies", {})
    if not cookies:
        raise RuntimeError(
            f"Account '{acc['label']}' has no session. "
            "Open Account Manager → Edit → Sign In again."
        )
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.cookies.update(cookies)
    return s


def _get_org_id(session: requests.Session, acc: dict) -> str:
    """Get org_id — use cached value if available, otherwise fetch from API."""
    if acc.get("org_id"):
        return acc["org_id"]
    resp = session.get(f"{_WEB_BASE}/api/organizations", timeout=15)
    resp.raise_for_status()
    orgs = resp.json()
    if not orgs:
        raise RuntimeError("No organizations found for this account.")
    org_id = orgs[0]["uuid"]
    # Cache it back into the config
    from config_manager import load, save, get_active_id
    cfg = load()
    aid = get_active_id()
    if aid in cfg["accounts"]:
        cfg["accounts"][aid]["org_id"] = org_id
        save(cfg)
    return org_id


def _build_prompt(messages, system_prompt="") -> str:
    """Flatten message history into Human/Assistant turns."""
    def _text(content) -> str:
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return str(content)

    parts = []
    if system_prompt:
        parts.append(f"<system>\n{system_prompt}\n</system>")
    for m in messages:
        label = "Human" if m["role"] == "user" else "Assistant"
        parts.append(f"{label}: {_text(m['content'])}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def _web_session(messages, acc, on_chunk, stop_event, system_prompt=""):
    session = _make_session(acc)
    org_id  = _get_org_id(session, acc)
    model   = acc.get("model", "claude-sonnet-4-6")

    # Create a fresh conversation for this exchange
    conv_uuid = str(uuid.uuid4())
    session.post(
        f"{_WEB_BASE}/api/organizations/{org_id}/chat_conversations",
        json={"name": "", "uuid": conv_uuid},
        timeout=15,
    )

    prompt = _build_prompt(messages, system_prompt)
    payload = {
        "prompt": prompt,
        "model": model,
        "timezone": "UTC",
        "attachments": [],
        "files": [],
        "rendering_mode": "raw",
    }

    full = ""
    try:
        resp = session.post(
            f"{_WEB_BASE}/api/organizations/{org_id}/chat_conversations/{conv_uuid}/completion",
            json=payload,
            stream=True,
            timeout=60,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                f"Session expired for '{acc['label']}'. "
                "Open Account Manager → Edit → Sign In again."
            )
        resp.raise_for_status()

        for raw_line in resp.iter_lines():
            if stop_event and stop_event.is_set():
                break
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace")
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data in ("[DONE]", ""):
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue

            # Handle both old and new SSE event formats
            text = ""
            if event.get("type") == "content_block_delta":
                text = event.get("delta", {}).get("text", "")
            elif event.get("type") == "completion":
                text = event.get("completion", "")
            elif "completion" in event and isinstance(event["completion"], str):
                text = event["completion"]

            if text:
                full += text
                if on_chunk:
                    on_chunk(text)

    except requests.RequestException as e:
        raise RuntimeError(f"Network error: {e}")

    return full.strip()
