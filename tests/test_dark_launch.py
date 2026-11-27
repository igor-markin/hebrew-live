"""A dark launch is dark from the first frame: live.html carries the saved theme before any script."""
import json
import tempfile
import types
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from hebrew_live.browser_ui import DARK_BACKGROUND, BrowserUI, themed_page


def page(ui):
    with urllib.request.urlopen(ui.url + 'live/') as response:
        return response.read().decode()


class DarkLaunchTests(unittest.TestCase):
    def test_the_page_is_served_with_the_theme_the_window_has_now(self):
        with BrowserUI(open_browser=False, live=True, dark_theme=True) as ui:
            html = page(ui)
            self.assertIn('<html data-theme="dark" ', html)
            self.assertIn(f'<meta name="theme-color" content="{DARK_BACKGROUND}"/>', html)
            with ui.lock: ui.state.update(dark_theme=False)        # switched to light in the window
            html = page(ui)
            self.assertIn('<html data-theme="light" ', html)
            self.assertIn('<meta name="theme-color" content="#f6f6f2"/>', html)
            ui.finished_seen.set()

    def test_without_a_saved_choice_the_page_stays_light(self):
        with BrowserUI(open_browser=False, live=True) as ui:
            self.assertFalse(ui.state['dark_theme'])
            self.assertIn('<html data-theme="light" ', page(ui))
            ui.finished_seen.set()
        self.assertFalse(BrowserUI(open_browser=False, live=True, dark_theme='yes').state['dark_theme'])

    def test_the_marker_goes_on_the_html_element_only(self):
        source = b'<!doctype html>\n<html lang="en" dir="ltr"><head><meta name="theme-color" content="#f6f6f2"/></head><body><html x></body></html>'
        dark = themed_page(source, True)
        self.assertEqual(dark.count(b'data-theme'), 1)
        self.assertTrue(dark.startswith(b'<!doctype html>\n<html data-theme="dark" lang="en"'))

    def test_the_dark_colour_is_the_window_styles_dark_background(self):
        css = (Path(__file__).parents[1] / 'experiments/publication-ui-preview/src/styles.css').read_text()
        dark = css.split(':root[data-theme="dark"]', 1)[1].split('}', 1)[0]
        self.assertIn(f'--background:{DARK_BACKGROUND};', dark.replace(' ', ''))

    def test_the_window_starts_with_the_saved_theme_before_the_session_reads_it(self):
        # The window loads as soon as the server is up; the session applies the preferences later.
        from hebrew_live import cli
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / '.local-settings'; folder.mkdir()
            (folder / 'preferences.json').write_text(json.dumps({'schema_version': 4, 'dark_theme': True}))
            seen = {}
            class Stop(Exception): pass
            class Browser:
                def __init__(self, **options): seen.update(options)
                def __enter__(self): raise Stop
                def __exit__(self, *_): return False
            args = types.SimpleNamespace(models=Path(tmp) / 'models', ui='browser', command='listen', publication='draft')
            with mock.patch('hebrew_live.browser_ui.BrowserUI', Browser):
                with self.assertRaises(Stop): cli.run(args, None)
            self.assertIs(seen.get('dark_theme'), True)
            (folder / 'preferences.json').write_text('{broken')
            seen.clear()
            with mock.patch('hebrew_live.browser_ui.BrowserUI', Browser):
                with self.assertRaises(Stop): cli.run(args, None)
            self.assertIs(seen.get('dark_theme'), False)   # a damaged file is light here; the session reports it


if __name__ == '__main__':
    unittest.main()
