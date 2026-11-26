"""Conversation text size: saved with the other preferences, so a new window (a new port, an
empty localStorage) opens with the size the owner chose."""
import json
import tempfile
import unittest
from pathlib import Path

from hebrew_live import preferences
from hebrew_live.browser_ui import BrowserUI

from test_input_source import post


class TextSizePreferenceTests(unittest.TestCase):
    def test_saved_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn('text_size', preferences.read(tmp))
            preferences.save(tmp, text_size='smallest')
            self.assertEqual(preferences.read(tmp)['text_size'], 'smallest')
            with self.assertRaises(ValueError): preferences.save(tmp, text_size='huge')
            self.assertEqual(preferences.read(tmp)['text_size'], 'smallest')   # a bad value never lands on disk

    def test_an_unknown_saved_size_is_normal_and_keeps_the_other_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            preferences.save(tmp, ui_locale='ru')
            path = Path(tmp) / 'preferences.json'
            path.write_text(json.dumps(dict(json.loads(path.read_text()), text_size='giant')))
            saved = preferences.read(tmp)
            self.assertEqual(saved['text_size'], 'normal')
            self.assertEqual(saved['ui_locale'], 'ru')


class TextSizeActionTests(unittest.TestCase):
    def window(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        ui = BrowserUI(open_browser=False).__enter__()
        def close(): ui.finished_seen.set(); ui.__exit__(None, None, None)
        self.addCleanup(close)
        ui.preference_folder = Path(tmp.name)
        return ui

    def test_the_window_saves_the_chosen_size(self):
        ui = self.window()
        self.assertEqual(ui.state['text_size'], 'normal')
        self.assertEqual(post(ui, {'action': 'text_size', 'value': 'small'}), 200)
        self.assertEqual(ui.state['text_size'], 'small')
        self.assertEqual(preferences.read(ui.preference_folder)['text_size'], 'small')

    def test_an_unknown_size_is_refused_and_not_saved(self):
        ui = self.window()
        self.assertEqual(post(ui, {'action': 'text_size', 'value': 'huge'}), 400)
        self.assertFalse((ui.preference_folder / 'preferences.json').exists())


if __name__ == '__main__':
    unittest.main()
