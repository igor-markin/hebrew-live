import json,tempfile,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from hebrew_live.browser_ui import BrowserUI
from hebrew_live.session import Session
class FolderTests(unittest.TestCase):
 def test_folder_fixed_path_origin_and_complete_files(self):
  with tempfile.TemporaryDirectory() as d:
   session=Session(Path(d),'he-ru',{})
   with BrowserUI(open_browser=False,live=True) as ui:
    ui.prepare_exports(session)
    self.assertEqual(ui.exports,{})
    self.assertEqual(ui.session_folder,session.path.resolve())
    self.assertTrue(list(session.path.glob('*.diagnostics.jsonl')))
    self.assertTrue(all(p.log.closed for p in session.parts.values()))
    def request(origin):
     return urllib.request.Request(ui.url+'action',data=json.dumps({'action':'open_folder','value':'/tmp/other'}).encode(),headers={'Origin':origin,'Content-Type':'application/json'})
    with patch('subprocess.run') as run:
     with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(request('http://evil.invalid'))
     run.assert_not_called()
     with urllib.request.urlopen(request('http://'+ui.host)) as response:self.assertEqual(response.status,200)
     self.assertEqual(run.call_args.args[0],['/usr/bin/open',str(session.path.resolve())])
    ui.finished_seen.set()
 def test_live_exit_has_no_countdown(self):
  with BrowserUI(open_browser=False,live=True) as ui:
   ui.session_folder=Path('/tmp')
   with patch.object(ui.finished_seen,'wait',return_value=True) as wait:
    ui.__exit__(None,None,None)
    wait.assert_called_once_with(None)
   ui.finished_seen.set()
