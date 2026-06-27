import subprocess
import shutil
import anthropic
from config_manager import load


def chat(messages, on_chunk=None, stop_event=None):
    """
    messages:    [{"role": "user"|"assistant", "content": str}, ...]
    on_chunk:    called with each text chunk as it arrives
    stop_event:  threading.Event — set it to cancel mid-stream
    Returns full response text.
    """
    cfg = load()
    if cfg["mode"] == "api":
        return _api(messages, cfg, on_chunk, stop_event)
    return _subscription(messages, cfg, on_chunk)


def _api(messages, cfg, on_chunk, stop_event):
    if not cfg.get("api_key"):
        raise ValueError("No API key set. Open the Mode Switcher and enter your Anthropic API key.")

    client = anthropic.Anthropic(api_key=cfg["api_key"])
    api_msgs = [{"role": m["role"], "content": m["content"]} for m in messages]

    full = ""
    with client.messages.stream(
        model=cfg.get("model", "claude-sonnet-4-6"),
        max_tokens=cfg.get("max_tokens", 8096),
        messages=api_msgs,
    ) as stream:
        for text in stream.text_stream:
            if stop_event and stop_event.is_set():
                break
            full += text
            if on_chunk:
                on_chunk(text)

    return full


def _subscription(messages, cfg, on_chunk):
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise FileNotFoundError(
            "'claude' CLI not found in PATH. Install Claude Code or switch to API mode."
        )

    if len(messages) == 1:
        prompt = messages[0]["content"]
    else:
        parts = []
        for m in messages[:-1]:
            label = "Human" if m["role"] == "user" else "Assistant"
            parts.append(f"{label}: {m['content']}")
        context = "\n\n".join(parts)
        prompt = f"<conversation_history>\n{context}\n</conversation_history>\n\n{messages[-1]['content']}"

    cmd = [claude_bin, "-p", prompt, "--model", cfg.get("model", "claude-sonnet-4-6")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude CLI returned non-zero exit code")

    response = proc.stdout.strip()
    if on_chunk:
        on_chunk(response)
    return response
