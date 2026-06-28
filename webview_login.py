#!/usr/bin/env python3
"""
WebKit login window for ClaudeSwitch.
Opens claude.ai/login, detects successful sign-in, extracts session cookies.
Prints cookies as JSON to stdout and exits.
"""
import json

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

_CHROME_JS = """
(function() {
  if (!window.chrome) {
    window.chrome = {
      runtime: {
        connect: function() {
          return {postMessage:function(){},onDisconnect:{addListener:function(){}},
                  onMessage:{addListener:function(){}},disconnect:function(){}};
        },
        sendMessage: function() {},
        id: undefined,
        getManifest: function() { return {}; }
      },
      loadTimes: function() { return {}; },
      csi: function() { return {}; },
      app: { isInstalled: false }
    };
  }
  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch(e) {}
  try { Object.defineProperty(navigator, 'vendor',    { get: () => 'Google Inc.' }); } catch(e) {}
  try { Object.defineProperty(navigator, 'platform',  { get: () => 'Linux x86_64' }); } catch(e) {}
  try {
    if (window.outerWidth  === 0) { Object.defineProperty(window, 'outerWidth',  { get: () => window.innerWidth  + 20 }); }
    if (window.outerHeight === 0) { Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 80 }); }
  } catch(e) {}
})();
"""

# Any claude.ai page that isn't part of the login/auth flow means we're logged in
_SKIP_PATHS = ("/login", "/auth", "/oauth", "/sign", "/verify", "/magic")
_SKIP_HOSTS = ("accounts.google", "appleid.apple", "apple.com")


def _is_logged_in(uri: str) -> bool:
    if not uri:
        return False
    if "claude.ai" not in uri:
        return False
    for host in _SKIP_HOSTS:
        if host in uri:
            return False
    for path in _SKIP_PATHS:
        if path in uri:
            return False
    return True


def _make_chrome_spoof():
    """Create a fresh UserScript each time — don't reuse across UserContentManagers."""
    return WebKit2.UserScript(
        _CHROME_JS,
        WebKit2.UserContentInjectedFrames.ALL_FRAMES,
        WebKit2.UserScriptInjectionTime.START,
        None, None,
    )


def _apply_settings(wv):
    s = wv.get_settings()
    s.set_property("user-agent", _UA)
    s.set_enable_javascript(True)
    s.set_enable_javascript_markup(True)
    s.set_enable_page_cache(True)
    try:
        s.set_property("hardware-acceleration-policy",
                        WebKit2.HardwareAccelerationPolicy.NEVER)
    except Exception:
        pass
    wv.get_user_content_manager().add_script(_make_chrome_spoof())


def main():
    ctx = WebKit2.WebContext.new_ephemeral()
    emitted = [False]
    done_btn = [None]
    _login_timer_set = [False]

    def _emit_cookies():
        if emitted[0]:
            return False
        emitted[0] = True
        cm = ctx.get_cookie_manager()
        all_cookies = {}
        domains = ["https://claude.ai", "https://api.claude.ai", "https://anthropic.com"]
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
        return False

    def _show_done_button(win):
        if done_btn[0]:
            return
        overlay = win.get_child()
        if not isinstance(overlay, Gtk.Overlay):
            return
        btn = Gtk.Button(label="✓  Done — I'm signed in")
        btn.get_style_context().add_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.set_valign(Gtk.Align.END)
        btn.set_margin_bottom(16)
        btn.connect("clicked", lambda _: _emit_cookies())
        overlay.add_overlay(btn)
        overlay.show_all()
        done_btn[0] = btn

    def _check_uri(uri, win_ref):
        if emitted[0] or _login_timer_set[0]:
            return
        if not _is_logged_in(uri):
            return
        _login_timer_set[0] = True
        if win_ref and isinstance(win_ref, Gtk.Window):
            GLib.idle_add(_show_done_button, win_ref)
        GLib.timeout_add(1200, _emit_cookies)

    def on_load_changed(webview, event):
        if emitted[0]:
            return
        if event in (WebKit2.LoadEvent.COMMITTED, WebKit2.LoadEvent.FINISHED):
            _check_uri(webview.get_uri() or "", webview.get_toplevel())

    def on_uri_changed(webview, _param):
        if emitted[0]:
            return
        _check_uri(webview.get_uri() or "", webview.get_toplevel())

    def on_popup_create(parent_wv, nav_action):
        """Google/Apple OAuth popup — use new_with_related_view so context is shared."""
        popup_wv = WebKit2.WebView.new_with_related_view(parent_wv)
        popup_wv.connect("load-changed", on_load_changed)
        popup_wv.connect("notify::uri", on_uri_changed)
        popup_win = Gtk.Window()
        popup_win.set_title("Sign in")
        popup_win.set_default_size(520, 640)
        popup_win.set_position(Gtk.WindowPosition.CENTER)
        popup_win.add(popup_wv)
        popup_win.show_all()
        return popup_wv

    wv = WebKit2.WebView.new_with_context(ctx)
    _apply_settings(wv)
    wv.connect("load-changed", on_load_changed)
    wv.connect("notify::uri", on_uri_changed)
    wv.connect("create", on_popup_create)

    overlay = Gtk.Overlay()
    overlay.add(wv)

    win = Gtk.Window()
    win.set_title("Sign in to Claude  —  ClaudeSwitch")
    win.set_default_size(520, 700)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.connect("destroy", Gtk.main_quit)
    win.add(overlay)
    win.show_all()
    wv.load_uri(LOGIN_URL)
    Gtk.main()

    if not emitted[0]:
        print(json.dumps({}), flush=True)


if __name__ == "__main__":
    main()
