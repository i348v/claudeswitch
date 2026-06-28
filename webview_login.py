#!/usr/bin/env python3
"""
WebKit login window for ClaudeSwitch.
Opens claude.ai/login, detects successful sign-in, extracts session cookies.
Prints cookies as JSON to stdout and exits.
No args needed — always opens the claude.ai login page.
"""
import json
import sys

import gi
gi.require_version('WebKit2', '4.1')
gi.require_version('Gtk', '3.0')
from gi.repository import WebKit2, Gtk, GLib

LOGIN_URL = "https://claude.ai/login"

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_CHROME_SPOOF = WebKit2.UserScript(
    """
    (function() {
      if (!window.chrome) {
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
      }
      try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch(e) {}
    })();
    """,
    WebKit2.UserContentInjectedFrames.ALL_FRAMES,
    WebKit2.UserScriptInjectionTime.START,
    None, None,
)


def _is_logged_in(uri: str) -> bool:
    """True once claude.ai redirects away from the login/auth pages."""
    if not uri or "claude.ai" not in uri:
        return False
    for skip in ("/login", "/auth", "/oauth", "/sign", "accounts.google", "appleid.apple"):
        if skip in uri:
            return False
    from urllib.parse import urlparse
    path = urlparse(uri).path
    return path in ("/", "/new", "/recents") or path.startswith("/chat") or path.startswith("/project")


def _apply_settings(wv):
    s = wv.get_settings()
    s.set_property("user-agent", _UA)
    s.set_enable_javascript(True)
    s.set_enable_javascript_markup(True)
    s.set_enable_page_cache(True)
    wv.get_user_content_manager().add_script(_CHROME_SPOOF)


def main():
    ctx = WebKit2.WebContext.new_ephemeral()
    emitted = [False]

    def _emit_cookies():
        if emitted[0]:
            return False  # GLib timeout: don't repeat
        emitted[0] = True

        cm = ctx.get_cookie_manager()
        all_cookies = {}
        domains = ["https://claude.ai", "https://api.claude.ai"]
        pending = [len(domains)]

        def got_cookies(source, result, _domain):
            try:
                for c in source.get_cookies_finish(result):
                    all_cookies[c.get_name()] = c.get_value()
            except Exception:
                pass
            pending[0] -= 1
            if pending[0] == 0:
                print(json.dumps(all_cookies), flush=True)
                GLib.idle_add(Gtk.main_quit)

        for domain in domains:
            cm.get_cookies(domain, None, got_cookies, domain)

        return False  # don't repeat timeout

    def on_load_changed(webview, event):
        if emitted[0]:
            return
        if event == WebKit2.LoadEvent.FINISHED:
            uri = webview.get_uri() or ""
            if _is_logged_in(uri):
                GLib.timeout_add(800, _emit_cookies)

    def _make_webview():
        wv = WebKit2.WebView.new_with_context(ctx)
        _apply_settings(wv)
        wv.connect("load-changed", on_load_changed)
        wv.connect("create", on_popup_create)
        return wv

    def on_popup_create(webview, navigation_action):
        """Google/Apple OAuth opens in a popup — show it in a new window."""
        popup_wv = _make_webview()
        popup_win = Gtk.Window()
        popup_win.set_title("Sign in")
        popup_win.set_default_size(480, 640)
        popup_win.set_position(Gtk.WindowPosition.CENTER)
        popup_win.add(popup_wv)
        popup_win.show_all()
        return popup_wv

    wv = _make_webview()
    win = Gtk.Window()
    win.set_title("Sign in to Claude")
    win.set_default_size(520, 700)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.connect("destroy", Gtk.main_quit)
    win.add(wv)
    win.show_all()
    wv.load_uri(LOGIN_URL)
    Gtk.main()

    # If window was closed without logging in, emit empty dict
    if not emitted[0]:
        print(json.dumps({}), flush=True)


if __name__ == "__main__":
    main()
