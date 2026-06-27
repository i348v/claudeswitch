"""
Watches a user's inbox via IMAP for the Anthropic data-export email,
extracts the download link, and downloads the zip automatically.
"""
import email as _email
import imaplib
import re
import threading
import urllib.request
from pathlib import Path

ANTHROPIC_DOMAINS = ["anthropic.com"]

IMAP_SERVERS = {
    "gmail.com":      ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com":    ("outlook.office365.com", 993),
    "hotmail.com":    ("outlook.office365.com", 993),
    "live.com":       ("outlook.office365.com", 993),
    "msn.com":        ("outlook.office365.com", 993),
    "yahoo.com":      ("imap.mail.yahoo.com", 993),
    "ymail.com":      ("imap.mail.yahoo.com", 993),
    "icloud.com":     ("imap.mail.me.com", 993),
    "me.com":         ("imap.mail.me.com", 993),
    "mac.com":        ("imap.mail.me.com", 993),
    "protonmail.com": ("mail.protonmail.com", 993),
    "proton.me":      ("mail.protonmail.com", 993),
}


def detect_imap(email_addr: str) -> tuple[str, int]:
    domain = email_addr.split("@")[-1].lower()
    return IMAP_SERVERS.get(domain, (f"imap.{domain}", 993))


def _get_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                raw = part.get_payload(decode=True)
                if raw:
                    body += raw.decode("utf-8", errors="ignore")
    else:
        raw = msg.get_payload(decode=True)
        if raw:
            body = raw.decode("utf-8", errors="ignore")
    return body


def _extract_url(body: str) -> str | None:
    urls = re.findall(r'https?://[^\s<>"\'\\]+', body)
    # Prefer URLs that look like file downloads or export links
    for url in urls:
        low = url.lower()
        if any(k in low for k in (".zip", "export", "download", "data")):
            return url.rstrip(".,)")
    return None


def watch(
    email_addr: str,
    password: str,
    on_status: callable,
    on_found: callable,
    on_error: callable,
    stop_event: threading.Event,
    imap_host: str = "",
    imap_port: int = 993,
):
    """
    Background thread: polls inbox every 20s for an Anthropic export email.
    on_status(msg)   — progress updates for the UI
    on_found(path)   — called with local path of downloaded zip
    on_error(msg)    — called on unrecoverable error
    stop_event       — set it to cancel
    """
    host = imap_host or detect_imap(email_addr)[0]
    port = imap_port or detect_imap(email_addr)[1]

    try:
        on_status(f"Connecting to {host}…")
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(email_addr, password)
        mail.select("INBOX")

        # Snapshot existing IDs so we only watch for NEW mail
        _, data = mail.search(None, "ALL")
        seen = set(data[0].split()) if data[0] else set()
        on_status("Connected. Watching inbox for Anthropic export email…")

        while not stop_event.is_set():
            stop_event.wait(timeout=20)
            if stop_event.is_set():
                break

            mail.select("INBOX")
            _, data = mail.search(None, "ALL")
            all_ids = set(data[0].split()) if data[0] else set()
            new_ids = all_ids - seen
            seen = all_ids

            for msg_id in new_ids:
                _, raw = mail.fetch(msg_id, "(RFC822)")
                msg = _email.message_from_bytes(raw[0][1])
                sender = msg.get("From", "").lower()

                if not any(d in sender for d in ANTHROPIC_DOMAINS):
                    continue

                subject = msg.get("Subject", "")
                on_status(f"Anthropic email found: '{subject}' — extracting link…")

                body = _get_body(msg)
                url  = _extract_url(body)

                if not url:
                    on_status("Email found but no download link detected. Try manual import.")
                    continue

                on_status("Downloading export file…")
                dest = Path.home() / "Downloads" / "claude_export_auto.zip"
                urllib.request.urlretrieve(url, str(dest))

                mail.logout()
                on_found(str(dest))
                return

        mail.logout()
        on_status("Watcher stopped.")

    except imaplib.IMAP4.error as exc:
        on_error(f"Login failed: {exc}\n\nGmail users: enable IMAP and use an App Password.")
    except Exception as exc:
        on_error(str(exc))
