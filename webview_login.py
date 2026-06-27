#!/usr/bin/env python3
"""
Ephemeral WebKit login window for ClaudeSwitch.
Launched as a subprocess: python3 webview_login.py <auth_url>
Prints the OAuth code to stdout and exits when sign-in completes.
Uses GTK + WebKit2 directly (no pywebview dependency).
"""
import sys
from urllib.parse import urlparse, parse_qs

import gi
gi.require_version('WebKit2', '4.1')
gi.require_version('Gtk', '3.0')
from gi.repository import WebKit2, Gtk, GLib

CALLBACK_PATH = "/oauth/code/callback"


def _emit_code(code: str):
    print(code, flush=True)
    GLib.idle_add(Gtk.main_quit)


def main(auth_url: str):
    # Ephemeral context = fresh slate, no stored cookies, no existing session
    ctx = WebKit2.WebContext.new_ephemeral()
    wv  = WebKit2.WebView.new_with_context(ctx)
    emitted = [False]

    def on_decide_policy(webview, decision, decision_type):
        """Intercept the OAuth redirect before the page loads."""
        if emitted[0]:
            return False
        if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            try:
                uri = decision.get_navigation_action().get_request().get_uri() or ""
            except Exception:
                return False
            if CALLBACK_PATH in uri:
                params = parse_qs(urlparse(uri).query)
                code   = params.get("code", [None])[0]
                if code:
                    emitted[0] = True
                    decision.ignore()
                    _emit_code(code)
                    return True
        return False

    def on_load_changed(webview, event):
        """Fallback: catch code if the policy handler missed it."""
        if emitted[0]:
            return
        if event in (WebKit2.LoadEvent.COMMITTED, WebKit2.LoadEvent.FINISHED):
            uri = webview.get_uri() or ""
            if CALLBACK_PATH in uri:
                params = parse_qs(urlparse(uri).query)
                code   = params.get("code", [None])[0]
                if code:
                    emitted[0] = True
                    _emit_code(code)

    wv.connect("decide-policy", on_decide_policy)
    wv.connect("load-changed",  on_load_changed)

    win = Gtk.Window()
    win.set_title("Sign in to Claude")
    win.set_default_size(520, 700)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.connect("destroy", Gtk.main_quit)
    win.add(wv)
    win.show_all()
    wv.load_uri(auth_url)
    Gtk.main()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    main(sys.argv[1])
