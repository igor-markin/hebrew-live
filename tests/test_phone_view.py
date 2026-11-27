"""The translation on the owner's phone: a copy of the window on the Mac's Tailscale address,
behind a secret that survives restarts. It shows the conversation and takes only the recording
controls."""
import json
import os
import socket
import stat
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from hebrew_live import phone_view, preferences
from hebrew_live.browser_ui import BrowserUI

from test_input_source import post


def done(code=0, stdout=''):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr='')


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); return probe.getsockname()[1]


def get(view, route, host=None, method='GET'):
    """(status, body) of one request to the phone's server, with the Host header a phone would send."""
    request = urllib.request.Request(f'http://127.0.0.1:{view.server.server_port}/{view.token}/{route}',
                                     method=method, data=b'{}' if method == 'POST' else None,
                                     headers={'Host': host or view.host, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class TailscaleAddressTests(unittest.TestCase):
    def test_the_address_comes_from_tailscale_itself(self):
        calls = []
        def run(command, **_): calls.append(command); return done(stdout='100.101.7.12\n')
        self.assertEqual(phone_view.tailscale_address(run, executable='/bin/tailscale'), '100.101.7.12')
        self.assertEqual(calls, [['/bin/tailscale', 'ip', '-4']])

    def test_the_mac_app_binary_is_told_to_act_as_the_command_line(self):
        # Started from Finder there is no SHLVL or TERM_PROGRAM, and the app's binary would try
        # to open its window instead of printing the address.
        seen = {}
        def run(command, **options): seen.update(options.get('env') or {}); return done(stdout='100.101.7.12\n')
        with patch.dict(os.environ, {'PATH': '/usr/bin:/bin'}, clear=True):
            self.assertEqual(phone_view.tailscale_address(run, executable='/x'), '100.101.7.12')
        self.assertEqual(seen.get('TAILSCALE_BE_CLI'), '1')
        self.assertEqual(seen.get('PATH'), '/usr/bin:/bin')

    def test_anything_outside_the_tailnet_block_is_refused(self):
        for output in ('192.168.1.5\n', '10.0.0.2', 'fd7a:115c:a1e0::1', 'not an address', ''):
            self.assertIsNone(phone_view.tailscale_address(lambda *_, **__: done(stdout=output), executable='/x'), output)

    def test_stopped_missing_or_hanging_tailscale_means_no_address(self):
        self.assertIsNone(phone_view.tailscale_address(lambda *_, **__: done(1, '100.101.7.12'), executable='/x'))
        def hang(*_, **__): raise subprocess.TimeoutExpired('tailscale', 5)
        self.assertIsNone(phone_view.tailscale_address(hang, executable='/x'))
        def missing(*_, **__): raise FileNotFoundError
        self.assertIsNone(phone_view.tailscale_address(missing, executable='/x'))
        with patch.object(phone_view, 'find_tailscale', return_value=None):
            self.assertIsNone(phone_view.tailscale_address(lambda *_, **__: self.fail('must not run')))


class TokenTests(unittest.TestCase):
    def test_the_secret_is_made_once_kept_private_and_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = phone_view.load_token(tmp)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(stat.S_IMODE(os.stat(Path(tmp) / phone_view.TOKEN_FILE).st_mode), 0o600)
            self.assertEqual(phone_view.load_token(tmp), first)

    def test_a_damaged_secret_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / phone_view.TOKEN_FILE).write_text('short')
            token = phone_view.load_token(tmp)
            self.assertNotEqual(token, 'short'); self.assertEqual(phone_view.load_token(tmp), token)


class ViewStateTests(unittest.TestCase):
    def test_the_phone_gets_the_conversation_and_nothing_about_the_mac(self):
        state = {'groups': [{'id': 'g1'}], 'status': 'Слушаю', 'paused': False, 'finished': False, 'direction': 'he-ru',
                 'session': '/home/someone/Hebrew Live CLI/logs/20261126-1',
                 'session_path': '/home/someone/x', 'models': {'Перевод': 'MiLMMT'}, 'exports': [{'id': 'a'}],
                 'phone_view_url': 'http://100.1.1.1:8794/secret/phone/', 'device': 'MacBook Air Microphone',
                 'dark_theme': True, 'text_size': 'large'}
        view = phone_view.view_state(state)
        self.assertEqual(view['groups'], [{'id': 'g1'}])
        self.assertEqual((view['dark_theme'], view['text_size'], view['viewer']), (True, 'large', True))
        for key in ('session_path', 'models', 'exports', 'phone_view_url', 'device'):
            self.assertNotIn(key, view)
        self.assertNotIn('someone', json.dumps(view))
        self.assertEqual(len(view['session']), 16)
        self.assertIsNone(phone_view.view_state({'groups': []})['session'])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.ui = BrowserUI(open_browser=False, live=True).__enter__()
        def close(): self.ui.finished_seen.set(); self.ui.__exit__(None, None, None)
        self.addCleanup(close)
        with self.ui.lock:
            self.ui.state.update(groups=[{'id': 'g1', 'direction': 'he-ru', 'complete': True}], session='/home/someone/logs/1')
        self.view = phone_view.PhoneView(self.ui, '127.0.0.1', 'a' * 32, port_number=0).start()
        self.addCleanup(self.view.stop)

    def test_state_is_the_trimmed_copy(self):
        status, body = get(self.view, 'state')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data['viewer']); self.assertEqual(data['groups'][0]['id'], 'g1')
        self.assertNotIn('someone', body.decode()); self.assertNotIn('phone_view_url', data)

    def test_the_window_is_served_under_the_phone_path(self):
        status, body = get(self.view, 'phone/')
        self.assertEqual(status, 200); self.assertIn(b'<script', body)
        self.assertEqual(get(self.view, 'phone/../../etc/passwd')[0], 404)

    def test_nothing_but_viewing_is_offered(self):
        for route in ('action', 'sessions', 'vocabulary', 'session-1', 'export-1', '', 'live/'):
            self.assertEqual(get(self.view, route)[0], 404, route)
        self.assertEqual(get(self.view, 'state', method='POST')[0], 404)
        self.assertEqual(get(self.view, 'action', method='PUT')[0], 405)

    def press(self, body, origin='self', kind='application/json', host=None):
        host = host or self.view.host
        headers = {'Host': host, 'Content-Type': kind}
        if origin:
            headers['Origin'] = 'http://' + host if origin == 'self' else origin
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(f'http://127.0.0.1:{self.view.server.server_port}/{self.view.token}/action',
                                         method='POST', data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def drained(self):
        keys = []
        while not self.ui.actions.empty():
            keys.append(self.ui.actions.get_nowait())
        return keys

    def test_the_phone_starts_and_pauses_the_recording(self):
        self.assertEqual(self.press({'action': 'pause'}), 200)
        self.assertEqual(self.drained(), [' '])
        name = f'mac.tail1234.ts.net:{self.view.server.server_port}'
        self.assertEqual(self.press({'action': 'pause'}, host=name), 200)   # the MagicDNS name works too
        self.assertEqual(self.drained(), [' '])

    def test_the_phone_finishes_the_recording_once(self):
        self.assertEqual(self.press({'action': 'stop'}), 200)
        self.assertEqual(self.press({'action': 'stop'}), 200)
        self.assertEqual(self.drained(), ['q'])
        self.assertTrue(self.ui.state['stopping'])

    def test_the_phone_cannot_start_while_the_mac_does_not_see_it(self):
        with self.ui.lock:
            self.ui.state.update(input_source='phone', phone_status='not_found', recording_started=False)
        self.assertEqual(self.press({'action': 'pause'}), 409)
        self.assertEqual(self.drained(), [])

    def test_only_the_recording_controls_are_taken_and_only_from_the_page(self):
        for action in ('phone_view', 'ui_locale', 'input_source', 'quit', 'delete_session', 'vocabulary_set',
                       'open_folder', 'cancel_processing', 'clear', None):
            self.assertEqual(self.press({'action': action, 'value': True}), 403, action)
        self.assertEqual(self.press({'action': 'pause'}, origin=None), 403)
        self.assertEqual(self.press({'action': 'pause'}, origin='http://evil.example'), 403)
        self.assertEqual(self.press({'action': 'pause'}, kind='text/plain'), 415)
        self.assertEqual(self.press(b'not json'), 400)
        self.assertEqual(self.press({'action': 'pause', 'pad': 'x' * 300}), 400)
        self.assertEqual(self.press({'action': 'pause'}, host='evil.example:1'), 404)
        self.assertEqual(self.drained(), [])
        self.assertFalse(self.ui.state.get('stopping'))

    def test_a_wrong_secret_or_a_foreign_host_gets_nothing(self):
        request = urllib.request.Request(f'http://127.0.0.1:{self.view.server.server_port}/{"b" * 32}/state',
                                         headers={'Host': self.view.host})
        with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(get(self.view, 'state', host='evil.example:' + str(self.view.server.server_port))[0], 404)
        self.assertEqual(get(self.view, 'state', host='mac.tail1234.ts.net:1')[0], 404)
        self.assertEqual(get(self.view, 'state', host=f'mac.tail1234.ts.net:{self.view.server.server_port}')[0], 200)

    def test_the_push_stream_sends_the_trimmed_copy_and_ends_when_switched_off(self):
        sock = socket.create_connection(('127.0.0.1', self.view.server.server_port), timeout=3)
        sock.sendall(f'GET /{self.view.token}/events HTTP/1.1\r\nHost: {self.view.host}\r\n\r\n'.encode())
        received = b''
        while b'\n\n' not in received.split(b'\r\n\r\n', 1)[-1]:
            received += sock.recv(65536)
        head, body = received.split(b'\r\n\r\n', 1)
        self.assertIn(b'text/event-stream', head)
        first = json.loads(body.split(b'\n\n', 1)[0][6:])
        self.assertTrue(first['viewer']); self.assertNotIn('someone', json.dumps(first))
        started = time.monotonic()
        self.view.stop()
        sock.settimeout(3)
        while sock.recv(65536):
            pass   # the server closes the stream instead of waiting for the phone to leave
        self.assertLess(time.monotonic() - started, 2.5)
        sock.close()


class WindowSwitchTests(unittest.TestCase):
    def window(self, address):
        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup)
        prefs = tempfile.TemporaryDirectory(); self.addCleanup(prefs.cleanup)
        environment = patch.dict(os.environ, {'HEBREW_LIVE_HOME': home.name,
                                              'HEBREW_LIVE_PHONE_VIEW_PORT': str(free_port())})
        environment.start(); self.addCleanup(environment.stop)
        ui = BrowserUI(open_browser=False, live=True).__enter__()
        def close(): ui.finished_seen.set(); ui.__exit__(None, None, None)
        self.addCleanup(close)
        ui.preference_folder = Path(prefs.name)
        ui.tailscale_probe = lambda: address
        return ui

    def settled(self, ui, timeout=3.):
        deadline = time.monotonic() + timeout
        while ui.state['phone_view_status'] == 'starting' and time.monotonic() < deadline: time.sleep(.02)
        return ui.state['phone_view_status']

    def test_switching_on_saves_the_choice_and_shows_a_link_that_survives_a_restart(self):
        ui = self.window('127.0.0.1')
        self.assertEqual(ui.state['phone_view_status'], 'off')
        self.assertEqual(post(ui, {'action': 'phone_view', 'value': True}), 200)
        self.assertEqual(self.settled(ui), 'on')
        self.assertIs(preferences.read(ui.preference_folder)['phone_view'], True)
        url = ui.state['phone_view_url']
        self.assertTrue(url.startswith('http://127.0.0.1:' + os.environ['HEBREW_LIVE_PHONE_VIEW_PORT'] + '/'))
        self.assertTrue(url.endswith('/phone/'))
        with urllib.request.urlopen(url.replace('/phone/', '/state'), timeout=3) as response:
            self.assertTrue(json.loads(response.read())['viewer'])
        self.assertIn(phone_view.load_token(os.environ['HEBREW_LIVE_HOME']), url)

    def test_switching_off_closes_the_server(self):
        ui = self.window('127.0.0.1')
        post(ui, {'action': 'phone_view', 'value': True}); self.settled(ui)
        url = ui.state['phone_view_url']
        self.assertEqual(post(ui, {'action': 'phone_view', 'value': False}), 200)
        deadline = time.monotonic() + 3
        while ui.phone_view is not None and time.monotonic() < deadline: time.sleep(.02)
        self.assertEqual((ui.state['phone_view_status'], ui.state['phone_view_url']), ('off', None))
        with self.assertRaises(urllib.error.URLError): urllib.request.urlopen(url.replace('/phone/', '/state'), timeout=2)
        self.assertIs(preferences.read(ui.preference_folder)['phone_view'], False)

    def test_without_tailscale_the_window_says_so(self):
        ui = self.window(None)
        post(ui, {'action': 'phone_view', 'value': True})
        self.assertEqual(self.settled(ui), 'no_tailscale')
        self.assertIsNone(ui.state['phone_view_url']); self.assertIsNone(ui.phone_view)

    def test_a_busy_port_is_named(self):
        ui = self.window('127.0.0.1')
        with socket.socket() as taken:
            taken.bind(('127.0.0.1', int(os.environ['HEBREW_LIVE_PHONE_VIEW_PORT']))); taken.listen()
            post(ui, {'action': 'phone_view', 'value': True})
            self.assertEqual(self.settled(ui), 'port_busy')

    def test_only_true_or_false_is_accepted(self):
        ui = self.window('127.0.0.1')
        self.assertEqual(post(ui, {'action': 'phone_view', 'value': 'yes'}), 400)
        self.assertNotIn('phone_view', preferences.read(ui.preference_folder))


if __name__ == '__main__':
    unittest.main()
