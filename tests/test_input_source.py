"""Microphone or phone: the phone check, the saved choice, the window actions and the moment
capture starts."""
import json
import subprocess
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from hebrew_live import phone_audio, preferences
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.runtime import chosen_input, run_session
from hebrew_live.session import Session

from test_runtime_lifecycle import Browser, InputStream, VAD, args as session_args, custom_models, process_engine


def adb(stdout='', code=0, error=None):
    calls = []
    def run(arguments, **options):
        calls.append((arguments, options))
        if error: raise error
        return types.SimpleNamespace(returncode=code, stdout=stdout)
    run.calls = calls
    return run


def wait_for(condition, seconds=3.):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition(): return True
        time.sleep(.01)
    return False


class PhoneStatusTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(phone_audio, find_scrcpy=lambda: '/opt/homebrew/bin/scrcpy',
                                      find_adb=lambda: '/opt/homebrew/bin/adb')
        patcher.start(); self.addCleanup(patcher.stop)

    def test_adb_device_states_map_to_window_codes(self):
        head = 'List of devices attached\n'
        cases = {head + 'X\tdevice\n': 'ready', head + 'X         device usb:1 model:Pixel\n': 'ready', head: 'no_device', head + '\n': 'no_device',
                 head + 'X\tunauthorized usb:1\n': 'unauthorized', head + 'X\tauthorizing\n': 'unauthorized',
                 head + 'X\toffline\n': 'offline', head + 'X\tno permissions (user)\n': 'no_permissions',
                 head + 'X\trecovery\n': 'wrong_mode', head + 'X\tsomething new\n': 'unknown',
                 head + 'X\tdevice\nY\tdevice\n': 'several_devices', head + 'X\tdevice\nY\tunauthorized\n': 'several_devices',
                 '* daemon not running; starting now at tcp:5037\n* daemon started successfully\n' + head + 'X\tdevice\n': 'ready'}
        for output, expected in cases.items():
            self.assertEqual(phone_audio.status(adb(output)), expected, output)

    def test_adb_is_started_then_asked_with_deadlines_and_failures_are_named(self):
        run = adb('List of devices attached\n')
        phone_audio.status(run)
        (started, start_options), (arguments, options) = run.calls
        self.assertEqual(started, ['/opt/homebrew/bin/adb', 'start-server'])
        self.assertEqual(start_options['timeout'], phone_audio.START_SECONDS); self.assertEqual(start_options['stdout'], subprocess.DEVNULL)
        self.assertEqual(arguments, ['/opt/homebrew/bin/adb', 'devices']); self.assertEqual(options['timeout'], 3.)
        self.assertEqual(phone_audio.status(adb(error=subprocess.TimeoutExpired('adb', 3))), 'timeout')
        self.assertEqual(phone_audio.status(adb(error=FileNotFoundError())), 'adb_failed')
        self.assertEqual(phone_audio.status(adb(code=1)), 'adb_failed')

    def test_a_cold_service_that_keeps_its_output_open_does_not_hold_up_the_check(self):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'adb'
            script.write_text('#!/bin/sh\nif [ "$1" = start-server ]; then (sleep 4) & exit 0; fi\n'
                              'printf "List of devices attached\\nX\\tdevice\\n"\n')
            script.chmod(0o755)
            with mock.patch.object(phone_audio, 'find_adb', return_value=str(script)):
                began = time.monotonic()
                self.assertEqual(phone_audio.status(), 'ready')
                self.assertLess(time.monotonic() - began, 3.)

    def test_missing_tools_are_named_before_adb_runs(self):
        run = adb('List of devices attached\nX\tdevice\n')
        with mock.patch.object(phone_audio, 'find_scrcpy', return_value=None):
            self.assertEqual(phone_audio.status(run), 'no_scrcpy')
        with mock.patch.object(phone_audio, 'find_adb', return_value=None):
            self.assertEqual(phone_audio.status(run), 'no_adb')
        self.assertEqual(run.calls, [])
        self.assertTrue(set(phone_audio._STATES.values()) <= set(phone_audio.STATUSES))


class FindAdbTests(unittest.TestCase):
    def test_override_then_path_then_homebrew(self):
        with mock.patch.dict('os.environ', {'HEBREW_LIVE_ADB': '/fake/adb'}):
            self.assertEqual(phone_audio.find_adb(), '/fake/adb')
        with mock.patch.dict('os.environ', {}, clear=True), mock.patch('shutil.which', return_value=None), \
             mock.patch('os.access', side_effect=lambda path, mode: path == '/opt/homebrew/bin/adb'):
            self.assertEqual(phone_audio.find_adb(), '/opt/homebrew/bin/adb')   # Finder gives no Homebrew PATH

    def test_scrcpy_gets_the_same_adb_as_the_check(self):
        seen = {}
        class Process:
            def __init__(self, arguments, env=None, **_): seen.update(env)
            def poll(self): return 0
        with mock.patch.object(phone_audio, 'find_adb', return_value='/fake/adb'):
            with phone_audio.PhoneAudio(lambda block: None, lambda reason: None, executable='scrcpy', popen=Process):
                pass
        self.assertEqual(seen['ADB'], '/fake/adb')


class PreferenceTests(unittest.TestCase):
    def test_input_source_defaults_to_microphone_and_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(preferences.read(tmp), {})
            preferences.save(tmp, ui_locale='ru')
            self.assertEqual(preferences.read(tmp)['input_source'], 'microphone')
            preferences.save(tmp, input_source='phone')
            self.assertEqual(preferences.read(tmp)['input_source'], 'phone')
            with self.assertRaises(ValueError): preferences.save(tmp, input_source='bluetooth')
            self.assertEqual(preferences.read(tmp)['input_source'], 'phone')   # a bad value never lands on disk
            path = Path(tmp) / 'preferences.json'
            path.write_text(json.dumps(dict(json.loads(path.read_text()), input_source=1)))
            with self.assertRaises(ValueError): preferences.read(tmp)


def post(ui, payload):
    request = urllib.request.Request(ui.url + 'action', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'Origin': 'http://' + ui.host})
    try:
        with urllib.request.urlopen(request) as response: return response.status
    except urllib.error.HTTPError as error:
        return error.code


class WindowActionTests(unittest.TestCase):
    def window(self, probe):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        ui = BrowserUI(open_browser=False).__enter__()
        def close(): ui.finished_seen.set(); ui.__exit__(None, None, None)
        self.addCleanup(close)
        ui.preference_folder = Path(tmp.name); ui.phone_probe = probe
        return ui

    def test_choosing_the_phone_saves_it_and_checks_it(self):
        ui = self.window(lambda: 'unauthorized')
        self.assertEqual(ui.state['input_source'], 'microphone')
        self.assertEqual(post(ui, {'action': 'input_source', 'value': 'phone'}), 200)
        self.assertTrue(wait_for(lambda: ui.state['phone_status'] == 'unauthorized'))
        self.assertEqual(ui.state['input_source'], 'phone')
        self.assertEqual(preferences.read(ui.preference_folder)['input_source'], 'phone')
        self.assertEqual(post(ui, {'action': 'pause'}), 409)                  # Start refused while not ready
        ui.phone_probe = lambda: 'ready'
        self.assertEqual(post(ui, {'action': 'check_phone'}), 202)
        self.assertTrue(wait_for(lambda: ui.state['phone_status'] == 'ready'))
        self.assertEqual(post(ui, {'action': 'pause'}), 200)
        self.assertEqual(post(ui, {'action': 'input_source', 'value': 'microphone'}), 200)
        self.assertEqual(preferences.read(ui.preference_folder)['input_source'], 'microphone')

    def test_a_slow_old_check_never_overwrites_a_newer_one(self):
        release = threading.Event(); answers = iter(['no_device', 'ready'])
        def probe():
            answer = next(answers)
            if answer == 'no_device': release.wait(2)
            return answer
        ui = self.window(probe)
        ui.check_phone(); ui.check_phone()
        self.assertTrue(wait_for(lambda: ui.state['phone_status'] == 'ready'))
        release.set(); time.sleep(.1)
        self.assertEqual(ui.state['phone_status'], 'ready')

    def test_choice_is_refused_once_recording_started_finished_or_forced(self):
        ui = self.window(lambda: 'ready')
        self.assertEqual(post(ui, {'action': 'input_source', 'value': 'radio'}), 400)
        for state in ({'recording_started': True}, {'finished': True}, {'input_source_locked': True}):
            ui.details(**dict(dict(recording_started=False, finished=False, input_source_locked=False), **state))
            self.assertEqual(post(ui, {'action': 'input_source', 'value': 'phone'}), 409, state)
        self.assertFalse((ui.preference_folder / 'preferences.json').exists())
        self.assertEqual(ui.state['input_source'], 'microphone')

    def test_microphone_start_is_never_blocked_by_phone_status(self):
        ui = self.window(lambda: 'no_device')
        ui.details(phone_status='no_device')
        self.assertEqual(post(ui, {'action': 'pause'}), 200)


class PhoneProcess:
    """Stands in for PhoneAudio; `fail_after` seconds later it reports scrcpy's exit."""
    entered = None; fail_after = None
    def __init__(self, on_audio, on_end, on_event=None, **_):
        self.on_end, self.on_event = on_end, on_event
    def __enter__(self):
        PhoneProcess.entered.set()
        if self.fail_after is not None:
            self.on_event('phone_capture_exit', attempt=1, returncode=1, reason='ERROR: Could not find any ADB device',
                          audio=False, restart=False, log=[])
            threading.Timer(self.fail_after, self.on_end, args=('ERROR: Could not find any ADB device',)).start()
        return self
    def __exit__(self, *_): pass


class ScriptedBrowser(Browser):
    """Chooses `source` in the waiting window, presses Start, then quits once `quit_when(state)` holds."""
    def __init__(self, source, quit_when=None):
        super().__init__(); self.source = source; self.quit_when = quit_when
    def read(self):
        self.actions += 1
        if self.actions == 1: self.state.update(input_source=self.source); return [' ']
        if self.quit_when and self.quit_when(self.state): self.quit_when = None; return ['q']
        return []


class CaptureStartTests(unittest.TestCase):
    def run_window(self, browser, status, options=None):
        PhoneProcess.entered = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); session = Session(root / 'logs', 'he-en', {}, save_audio=False)
            options = options or session_args(root); options.start_paused = True
            with mock.patch('hebrew_live.cli.validate_custom_models', custom_models), \
                 mock.patch('hebrew_live.remote_engine.RemoteEngine', side_effect=process_engine), \
                 mock.patch('hebrew_live.cli.VAD', VAD), \
                 mock.patch('sounddevice.query_devices', return_value={'default_samplerate': 16000, 'name': 'fake mic'}), \
                 mock.patch('sounddevice.InputStream', InputStream), \
                 mock.patch.object(phone_audio, 'status', side_effect=status), \
                 mock.patch.object(phone_audio, 'PhoneAudio', PhoneProcess):
                done = threading.Thread(target=run_session, args=(options, session, browser), daemon=True)
                done.start(); done.join(20)
            self.assertFalse(done.is_alive(), 'session hung')
            return [json.loads(line) for path in root.rglob('*.diagnostics.jsonl') for line in path.read_text().splitlines()]

    def test_window_choice_is_read_when_start_is_pressed(self):
        self.assertEqual(chosen_input(types.SimpleNamespace(), None), 'microphone')
        browser = Browser(); browser.state['input_source'] = 'phone'
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertEqual(chosen_input(types.SimpleNamespace(phone=False), browser), 'phone')
            browser.state['input_source'] = 'microphone'
            self.assertEqual(chosen_input(types.SimpleNamespace(phone=True), browser), 'phone')

    def test_phone_session_records_at_the_phone_rate(self):
        browser = ScriptedBrowser('phone', lambda state: state.get('capture_active'))
        self.run_window(browser, ['ready'])
        self.assertTrue(PhoneProcess.entered.is_set())
        self.assertEqual((browser.state['rate'], browser.state['input_kind']), (48000, 'Телефон'))
        self.assertEqual(browser.state['phone_status'], 'ready'); self.assertTrue(browser.state['recording_started'])

    def test_phone_not_ready_at_start_returns_to_ready_with_the_reason(self):
        browser = ScriptedBrowser('phone', lambda state: state.get('input_error') == 'phone_not_ready')
        self.run_window(browser, ['no_device'])
        self.assertFalse(PhoneProcess.entered.is_set())
        self.assertEqual(browser.state['phone_status'], 'no_device')
        self.assertFalse(browser.state.get('recording_started'))

    def test_pulled_cable_ends_the_session_with_the_reason(self):
        browser = ScriptedBrowser('phone')
        with mock.patch.object(PhoneProcess, 'fail_after', .3):
            self.run_window(browser, ['ready', 'no_device'])
        self.assertEqual((browser.state['input_error'], browser.state['phone_status']), ('phone_stopped', 'no_device'))
        self.assertTrue(browser.prepared)

    def test_why_the_phone_stopped_stays_in_the_session_log(self):
        browser = ScriptedBrowser('phone')
        with mock.patch.object(PhoneProcess, 'fail_after', .3):
            events = self.run_window(browser, ['ready', 'ready'])
        names = [event['event'] for event in events]
        self.assertIn('phone_capture_exit', names)
        stopped = next(event for event in events if event['event'] == 'phone_stopped')
        self.assertEqual((stopped['reason'], stopped['status']), ('ERROR: Could not find any ADB device', 'capture_failed'))

    def test_scrcpy_failure_with_the_phone_still_seen_is_not_called_ready(self):
        browser = ScriptedBrowser('phone')
        with mock.patch.object(PhoneProcess, 'fail_after', .3):
            self.run_window(browser, ['ready', 'ready'])
        self.assertEqual((browser.state['input_error'], browser.state['phone_status']), ('phone_stopped', 'capture_failed'))

    def test_phone_flag_forces_the_phone_and_locks_the_switch(self):
        browser = ScriptedBrowser('microphone', lambda state: state.get('capture_active'))
        with tempfile.TemporaryDirectory() as tmp:
            options = session_args(Path(tmp)); options.phone = True
            self.run_window(browser, ['ready'], options)
        self.assertTrue(PhoneProcess.entered.is_set())
        first = next(call for call in browser.detail_calls if 'input_source' in call)
        self.assertEqual((first['input_source'], first['input_source_locked']), ('phone', True))

    def test_microphone_is_the_default_and_never_asks_adb(self):
        browser = ScriptedBrowser('microphone', lambda state: state.get('capture_active'))
        status = mock.Mock(side_effect=AssertionError('adb asked'))
        with mock.patch.dict('os.environ', {}, clear=True):
            self.run_window(browser, status)
        self.assertEqual((browser.state['rate'], browser.state['input_kind'], browser.state['device']), (16000, 'Микрофон', 'fake mic'))
        first = next(call for call in browser.detail_calls if 'input_source' in call)   # set before the window acts
        self.assertEqual((first['input_source'], first['input_source_locked']), ('microphone', False))
        self.assertFalse(PhoneProcess.entered.is_set())


if __name__ == '__main__':
    unittest.main()
