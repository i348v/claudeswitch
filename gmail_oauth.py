"""
Gmail OAuth: opens a browser for Sign in with Google, then watches the inbox
for the Anthropic export email and downloads it automatically.
"""
import os
import re
import threading
import urllib.request
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SECRET_FILE = Path(__file__).parent / "client_secret.json"
TOKEN_FILE  = Path.home() / ".claude_client" / "gmail_token.json"


def _get_creds() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def _extract_url(body: str) -> str | None:
    urls = re.findall(r'https?://[^\s<>"\'\\]+', body)
    for url in urls:
        low = url.lower()
        if any(k in low for k in (".zip", "export", "download", "data")):
            return url.rstrip(".,)")
    return None


def _get_body(service, msg_id: str) -> str:
    import base64
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload", {})
    parts = payload.get("parts", [payload])
    body = ""
    for part in parts:
        data = part.get("body", {}).get("data", "")
        if data:
            body += base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return body


def watch(on_status, on_found, on_error, stop_event: threading.Event):
    """
    Opens browser for Google login, then polls Gmail every 20s for the
    Anthropic export email and downloads the zip automatically.
    """
    try:
        on_status("Opening browser for Google Sign-In…")
        creds   = _get_creds()
        service = build("gmail", "v1", credentials=creds)

        # Snapshot existing message IDs
        on_status("Signed in. Watching inbox for Anthropic export email…")
        resp = service.users().messages().list(userId="me", maxResults=500).execute()
        seen = {m["id"] for m in resp.get("messages", [])}

        while not stop_event.is_set():
            stop_event.wait(timeout=20)
            if stop_event.is_set():
                break

            resp    = service.users().messages().list(userId="me", maxResults=500).execute()
            all_ids = {m["id"] for m in resp.get("messages", [])}
            new_ids = all_ids - seen
            seen    = all_ids

            for msg_id in new_ids:
                meta = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject"]
                ).execute()
                headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
                sender  = headers.get("From", "").lower()

                if "anthropic.com" not in sender:
                    continue

                subject = headers.get("Subject", "")
                on_status(f"Anthropic email found: '{subject}' — extracting link…")

                body = _get_body(service, msg_id)
                url  = _extract_url(body)

                if not url:
                    on_status("Email found but no download link detected. Try manual import.")
                    continue

                on_status("Downloading export file…")
                dest = Path.home() / "Downloads" / "claude_export_auto.zip"
                urllib.request.urlretrieve(url, str(dest))

                on_found(str(dest))
                return

        on_status("Watcher stopped.")

    except FileNotFoundError:
        on_error("client_secret.json not found. Place it in the claude_client/ folder.")
    except Exception as exc:
        on_error(str(exc))
