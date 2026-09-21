import json
import tempfile
import unittest
from pathlib import Path
from hebrew_live.session_history import SessionHistory

class HistoryTests(unittest.TestCase):
    def test_versions_directions_truncated_record_and_no_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'20260910-210902-35bb9f4c';folder.mkdir()
            path=folder/'001-he-ru.diagnostics.jsonl'
            events=[dict(event='live_publication',segment=1,current=dict(source='שלום',translation=t),history=[],stage=stage)
                    for t,stage in [('','open'),('Привет','closed')]]
            original='\n'.join(json.dumps(e) for e in events)+'\n{"partial"'
            path.write_text(original)
            history=SessionHistory(root)
            result=history.read(folder.name)
            self.assertEqual(len(result['groups']),1)
            self.assertEqual(result['groups'][0]['live']['current']['translation'],'Привет')
            self.assertTrue(result['warning'])
            self.assertEqual(path.read_text(),original)
            self.assertEqual(history.list()[0]['id'],folder.name)
            self.assertEqual(history.list()[0]['title'],'Привет')
            self.assertEqual(history.list()[0]['preview'],'שלום')
            with self.assertRaises(FileNotFoundError):history.read('../'+folder.name)
            (root/'20260910-220000-12345678').symlink_to(folder,target_is_directory=True)
            self.assertEqual(len(history.list()),1)

    def test_legacy_pairing_and_file_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'20260910-210902-35bb9f4c';folder.mkdir()
            (folder/'001-ru-he.diagnostics.jsonl').write_text('{}\n')
            (folder/'001-ru-he.transcript.txt').write_text('[3 0.0–1.0s]\nПривет\n\n[4 1.0–2.0s]\nДа\n')
            (folder/'001-ru-he.translation.txt').write_text('[4 1.0–2.0s]\nכן\n\n[3 0.0–1.0s]\nשלום\n')
            groups=SessionHistory(root).read(folder.name)['groups']
            self.assertEqual([g['final']['translation'] for g in groups],['שלום','כן'])
            self.assertTrue(all(g['direction']=='ru-he' for g in groups))
            (folder/'002-he-ru.diagnostics.jsonl').symlink_to(folder/'001-ru-he.diagnostics.jsonl')
            self.assertEqual(len(SessionHistory(root).read(folder.name)['groups']),2)

    def test_delete_whole_archive_but_not_current_or_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'20260910-210902-35bb9f4c';folder.mkdir()
            (folder/'audio.wav').write_bytes(b'audio')
            (folder/'nested').mkdir();(folder/'nested'/'log').write_text('log')
            outside=root/'keep';outside.mkdir();(outside/'original').write_text('keep')
            (folder/'linked').symlink_to(outside,target_is_directory=True)
            history=SessionHistory(root)
            with self.assertRaises(PermissionError):history.delete(folder.name,folder)
            self.assertTrue((folder/'audio.wav').exists())
            with self.assertRaises(ValueError):history.delete('../keep')
            history.delete(folder.name)
            self.assertFalse(folder.exists());self.assertEqual((outside/'original').read_text(),'keep')
