"""The translation on the owner's phone: a read-only copy of the window, over Tailscale only.

The main window listens on 127.0.0.1 behind a new address every launch, so a phone cannot
open it. This second server listens only on the Mac's own Tailscale address (100.64.0.0/10),
on a fixed port, behind a secret kept between launches: a link saved on the phone keeps
working. It serves the same window in a viewing mode and a trimmed copy of its state. The
only actions it takes are the recording controls (start, pause, finish, next session), so
the owner can record only when wanted; it changes no settings, lists no saved sessions and
offers no files. Tailscale encrypts the link between the owner's own devices; nothing is
sent anywhere else.
"""
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8794
TAILNET = ipaddress.ip_network('100.64.0.0/10')
TOKEN_FILE = 'phone-view-token'
VIEW_PATH = 'phone/'
_SEARCH = ('/Applications/Tailscale.app/Contents/MacOS/Tailscale', '/opt/homebrew/bin/tailscale', '/usr/local/bin/tailscale')
# What the phone needs to draw the conversation. Paths, models, exports and the phone-view link
# itself stay on the Mac.
VIEW_KEYS = ('groups', 'generation', 'phase', 'status', 'status_code', 'direction', 'target_language', 'ui_locale',
             'text_size', 'dark_theme', 'paused', 'finished', 'stopping', 'cancelling', 'lag', 'level',
             'calm_drafts', 'merge_sentences', 'frozen_sentences', 'ticker_view', 'append_view', 'publication',
             'recording_started', 'capture_active', 'input_source', 'input_kind', 'phone_status', 'input_error',
             'can_start_new', 'model_switching', 'desktop_mode')
# The recording controls, and nothing else, are taken from the phone (BrowserUI.control).
ACTIONS = ('pause', 'stop', 'start_session')
ACTION_BYTES = 256
STATUSES = ('off', 'starting', 'on', 'no_tailscale', 'port_busy', 'failed')


def port():
    value = os.environ.get('HEBREW_LIVE_PHONE_VIEW_PORT')
    try:
        number = int(value) if value else PORT
    except ValueError:
        return PORT
    return number if 1024 <= number <= 65535 else PORT


def find_tailscale():
    """An app started from Finder has no Homebrew on PATH; the Mac app keeps its CLI inside the bundle."""
    found = os.environ.get('HEBREW_LIVE_TAILSCALE') or shutil.which('tailscale')
    if found:
        return found
    return next((path for path in _SEARCH if os.access(path, os.X_OK)), None)


def tailscale_address(run=subprocess.run, executable=None):
    """The Mac's Tailscale IPv4 address, or None when Tailscale is missing, stopped or logged out.

    Asked of Tailscale itself, not guessed from the routes: a mobile hotspot can hand out a
    carrier address from the same 100.64.0.0/10 block, and the server must never listen there."""
    executable = executable or find_tailscale()
    if not executable:
        return None
    # The Mac app's own binary acts as the command line only when it sees a shell (SHLVL,
    # TERM_PROGRAM) or this variable; started from Finder it tries to open its window instead,
    # exits 0 and prints no address.
    environment = {**os.environ, 'TAILSCALE_BE_CLI': '1'}
    try:
        result = run([executable, 'ip', '-4'], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
                     env=environment)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    for line in (result.stdout or '').split():
        try:
            address = ipaddress.ip_address(line.strip())
        except ValueError:
            continue
        if address.version == 4 and address in TAILNET:
            return str(address)
    return None


def load_token(folder):
    """The secret part of the phone link, made once and kept, so a bookmark on the phone survives restarts."""
    folder = Path(folder)
    path = folder / TOKEN_FILE
    try:
        token = path.read_text(encoding='ascii').strip()
        if len(token) >= 22 and token.replace('-', '').replace('_', '').isalnum():
            return token
    except (OSError, UnicodeDecodeError):
        pass
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(24)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='ascii') as file:
        file.write(token + '\n')
    return token


def view_state(state):
    """The trimmed copy of the window's state the phone gets. Call under the window's lock."""
    view = {key: state[key] for key in VIEW_KEYS if key in state}
    session = state.get('session')
    # The phone only needs to notice a new session; the folder path stays on the Mac.
    view['session'] = hashlib.sha256(session.encode()).hexdigest()[:16] if isinstance(session, str) and session else None
    view['viewer'] = True
    return view


class PhoneView:
    """The phone's server for one window (`ui`, a BrowserUI): `start()` binds, `stop()` closes."""

    def __init__(self, ui, address, token, port_number=None, server_class=ThreadingHTTPServer):
        self.ui, self.address, self.token = ui, address, token
        self.port = port() if port_number is None else port_number
        self.server_class = server_class
        self.server = self.thread = None
        self.stopped = False

    @property
    def host(self):
        return f'{self.address}:{self.server.server_port if self.server else self.port}'

    @property
    def url(self):
        return f'http://{self.host}/{self.token}/{VIEW_PATH}'

    def allowed_host(self, value):
        """The Tailscale address, or the Mac's MagicDNS name, at this port. Anything else is
        another site's page trying the address (DNS rebinding)."""
        if not value:
            return False
        if value == self.host:
            return True
        name, _, number = value.rpartition(':')
        return number == str(self.server.server_port) and name.lower().endswith('.ts.net')

    def start(self):
        owner = self
        ui = self.ui

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass   # never log the secret link or the conversation

            def reply(self, status, data=b'{}', kind='application/json; charset=utf-8'):
                self.send_response(status)
                self.send_header('Content-Type', kind); self.send_header('Content-Length', str(len(data)))
                ui.security_headers(self)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                prefix = '/' + owner.token + '/'
                if not owner.allowed_host(self.headers.get('Host')) or not self.path.startswith(prefix):
                    return self.reply(404)
                relative = self.path[len(prefix):].split('?', 1)[0]
                if relative.startswith(VIEW_PATH):
                    asset = ui.live_asset(relative[len(VIEW_PATH):] or 'live.html')
                    return self.reply(200, *asset) if asset else self.reply(404)
                if relative == 'events' and ui.push_enabled:
                    return ui.push_state(self, lambda: view_state(ui.state), stopped=lambda: owner.stopped)
                if relative == 'state':
                    with ui.lock:
                        data = json.dumps(view_state(ui.state), ensure_ascii=False).encode()
                    return self.reply(200, data)
                return self.reply(404)

            def do_POST(self):
                host = self.headers.get('Host')
                if not owner.allowed_host(host) or self.path != '/' + owner.token + '/action':
                    return self.reply(404)
                # Only the phone's own page may press: another site's page has another Origin.
                if self.headers.get('Origin') != 'http://' + host:
                    return self.reply(403)
                if self.headers.get_content_type() != 'application/json':
                    return self.reply(415)
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= ACTION_BYTES:
                        return self.reply(400)
                    payload = json.loads(self.rfile.read(size))
                    action = payload.get('action') if isinstance(payload, dict) else None
                except ValueError:
                    return self.reply(400)
                if action not in ACTIONS:
                    return self.reply(403)
                return self.reply(*ui.control(action, origin='phone'))

            def refuse(self):
                self.reply(405)
            do_PUT = do_PATCH = do_DELETE = refuse

        self.server = self.server_class((self.address, self.port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name='phone-view', daemon=True)
        self.thread.start()
        return self

    def stop(self):
        # An open page must lose the conversation at once, not when the phone next disconnects.
        self.stopped = True
        with self.ui.state.changed:
            self.ui.state.changed.notify_all()
        if self.server:
            self.server.shutdown(); self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        self.server = self.thread = None
