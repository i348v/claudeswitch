import subprocess
import shutil
import threading
import anthropic
from config_manager import get_active


def chat(messages, on_chunk=None, stop_event: threading.Event = None):
    """
    messages:    [{"role": "user"|"assistant", "content": str}, ...]
    on_chunk:    called with each text chunk as it arrives
    stop_event:  set to cancel mid-stream
    Returns full response text.
    """
    acc = get_active()
    if acc["mode"] == "api":
        return _api(messages, acc, on_chunk, stop_event)
    return _subscription(messages, acc, on_chunk)


def _api(messages, acc, on_chunk, stop_event):
    if not acc.get("api_key"):
        raise ValueError(
            f"Account '{acc['label']}' has no API key. Open the Account Manager and add one."
        )
    client = anthropic.Anthropic(api_key=acc["api_key"])
    api_msgs = [{"role": m["role"], "content": m["content"]} for m in messages]

    full = ""
    with client.messages.stream(
        model=acc.get("model", "claude-sonnet-4-6"),
        max_tokens=8096,
        messages=api_msgs,
    ) as stream:
        for text in stream.text_stream:
            if stop_event and stop_event.is_set():
                break
            full += text
            if on_chunk:
                on_chunk(text)
    return full


def _subscription(messages, acc, on_chunk):
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
        prompt = (
            f"<conversation_history>\n{context}\n</conversation_history>\n\n"
            f"{messages[-1]['content']}"
        )

    cmd = [claude_bin, "-p", prompt, "--model", acc.get("model", "claude-sonnet-4-6")]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "claude CLI returned non-zero exit code")

    response = proc.stdout.strip()
    if on_chunk:
        on_chunk(response)
    return response
