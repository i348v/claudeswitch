import os
import pty
import re
import select
import shutil
import subprocess
import threading
import anthropic
from config_manager import get_active

# Strip ANSI colour / cursor codes that the CLI emits when connected to a TTY
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\r')


def chat(messages, on_chunk=None, stop_event: threading.Event = None,
         system_prompt: str = "", on_usage=None):
    """
    messages:      [{"role": "user"|"assistant", "content": str|list}, ...]
    on_chunk:      called with each text chunk as it arrives
    stop_event:    set to cancel mid-stream
    system_prompt: optional project-level system prompt
    on_usage:      called with {"input_tokens": int, "output_tokens": int, "model": str}
    Returns full response text.
    """
    acc = get_active()
    if acc["mode"] == "api":
        return _api(messages, acc, on_chunk, stop_event, system_prompt, on_usage)
    return _subscription(messages, acc, on_chunk, stop_event, system_prompt)


def _api(messages, acc, on_chunk, stop_event, system_prompt="", on_usage=None):
    if not acc.get("api_key"):
        raise ValueError(
            f"Account '{acc['label']}' has no API key. "
            "Open the Account Manager and add one."
        )
    client = anthropic.Anthropic(api_key=acc["api_key"])
    api_msgs = [{"role": m["role"], "content": m["content"]} for m in messages]

    model = acc.get("model", "claude-sonnet-4-6")
    kwargs = dict(model=model, max_tokens=8096, messages=api_msgs)
    if system_prompt:
        kwargs["system"] = system_prompt

    full = ""
    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            if stop_event and stop_event.is_set():
                break
            full += text
            if on_chunk:
                on_chunk(text)
        # Capture token usage after stream completes
        if on_usage:
            try:
                usage = stream.get_final_message().usage
                on_usage({"input_tokens": usage.input_tokens,
                           "output_tokens": usage.output_tokens,
                           "model": model})
            except Exception:
                pass
    return full


def _build_prompt(messages) -> str:
    """Flatten message history into a single prompt string for the CLI."""
    def _text(content) -> str:
        if isinstance(content, list):
            return "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return str(content)

    if len(messages) == 1:
        return _text(messages[0]["content"])

    parts = []
    for m in messages[:-1]:
        label = "Human" if m["role"] == "user" else "Assistant"
        parts.append(f"{label}: {_text(m['content'])}")
    context = "\n\n".join(parts)
    return (
        f"<conversation_history>\n{context}\n</conversation_history>\n\n"
        f"{_text(messages[-1]['content'])}"
    )


def _subscription(messages, acc, on_chunk, stop_event: threading.Event = None,
                  system_prompt: str = ""):
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise FileNotFoundError(
            "'claude' CLI not found in PATH. "
            "Install Claude Code or switch to API mode."
        )

    prompt = _build_prompt(messages)
    if system_prompt:
        prompt = f"<system>\n{system_prompt}\n</system>\n\n{prompt}"
    cmd = [claude_bin, "-p", prompt, "--model", acc.get("model", "claude-sonnet-4-6")]
    if acc.get("profile"):
        cmd += ["--profile", acc["profile"]]

    # Open a pseudo-TTY so the Node CLI streams output instead of buffering it
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdout=slave_fd,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    os.close(slave_fd)  # parent doesn't need the slave end

    full = ""
    try:
        while True:
            if stop_event and stop_event.is_set():
                proc.terminate()
                break

            ready, _, _ = select.select([master_fd], [], [], 0.1)
            if ready:
                try:
                    raw = os.read(master_fd, 512)
                    chunk = _ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
                    if chunk:
                        full += chunk
                        if on_chunk:
                            on_chunk(chunk)
                except OSError:
                    break
            elif proc.poll() is not None:
                # Process finished — drain any remaining output
                try:
                    while True:
                        r, _, _ = select.select([master_fd], [], [], 0.05)
                        if not r:
                            break
                        raw = os.read(master_fd, 512)
                        chunk = _ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
                        if chunk:
                            full += chunk
                            if on_chunk:
                                on_chunk(chunk)
                except OSError:
                    pass
                break
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    proc.wait()
    if proc.returncode not in (0, -15) and not (stop_event and stop_event.is_set()):
        raise RuntimeError(f"claude CLI exited with code {proc.returncode}")

    return full.strip()
