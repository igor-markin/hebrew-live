"""Hidden menu and session list: saved with the other preferences, so a new window (a new port,
an empty localStorage) opens the way the owner left it."""
import json
import tempfile
import unittest
from pathlib import Path

from hebrew_live import preferences
from hebrew_live.browser_ui import BrowserUI

from test_input_source import post


class LayoutPreferenceTests(unittest.TestCase):
    def test_saved_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn('menu_hidden', preferences.read(tmp))
            preferences.save(tmp, menu_hidden=True)
            preferences.save(tmp, sessions_hidden=True)
            saved = preferences.read(tmp)
            self.assertIs(saved['menu_hidden'], True)
            self.assertIs(saved['sessions_hidden'], True)
            preferences.save(tmp, menu_hidden=False)
            self.assertIs(preferences.read(tmp)['menu_hidden'], False)
            self.assertIs(preferences.read(tmp)['sessions_hidden'], True)

    def test_a_value_that_is_not_true_or_false_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            preferences.save(tmp, menu_hidden=True)
            with self.assertRaises(ValueError): preferences.save(tmp, menu_hidden='yes')
            self.assertIs(preferences.read(tmp)['menu_hidden'], True)   # a bad value never lands on disk

    def test_a_damaged_saved_value_shows_the_part_and_keeps_the_other_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            preferences.save(tmp, ui_locale='ru', text_size='small')
            path = Path(tmp) / 'preferences.json'
            path.write_text(json.dumps(dict(json.loads(path.read_text()), menu_hidden='yes', sessions_hidden=1)))
            saved = preferences.read(tmp)
            self.assertIs(saved['menu_hidden'], False)
            self.assertIs(saved['sessions_hidden'], False)
            self.assertEqual((saved['ui_locale'], saved['text_size']), ('ru', 'small'))


class LayoutActionTests(unittest.TestCase):
    def window(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        ui = BrowserUI(open_browser=False).__enter__()
        def close(): ui.finished_seen.set(); ui.__exit__(None, None, None)
        self.addCleanup(close)
        ui.preference_folder = Path(tmp.name)
        return ui

    def test_the_window_saves_what_was_hidden(self):
        ui = self.window()
        self.assertEqual((ui.state['menu_hidden'], ui.state['sessions_hidden']), (False, False))
        self.assertEqual(post(ui, {'action': 'menu_hidden', 'value': True}), 200)
        self.assertEqual(post(ui, {'action': 'sessions_hidden', 'value': True}), 200)
        self.assertEqual((ui.state['menu_hidden'], ui.state['sessions_hidden']), (True, True))
        saved = preferences.read(ui.preference_folder)
        self.assertEqual((saved['menu_hidden'], saved['sessions_hidden']), (True, True))
        self.assertEqual(post(ui, {'action': 'menu_hidden', 'value': False}), 200)
        self.assertIs(preferences.read(ui.preference_folder)['menu_hidden'], False)

    def test_a_value_that_is_not_true_or_false_is_refused_and_not_saved(self):
        ui = self.window()
        self.assertEqual(post(ui, {'action': 'sessions_hidden', 'value': 'yes'}), 400)
        self.assertFalse((ui.preference_folder / 'preferences.json').exists())
        self.assertIs(ui.state['sessions_hidden'], False)


if __name__ == '__main__':
    unittest.main()
