import json
import contextlib
import io
import os
import queue
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hebrew_live.browser_ui import BrowserUI
from hebrew_live import cli
from hebrew_live.languages import (direction_for_target, prompt_names,
                                   split_direction, target_languages,
                                   validate_direction)
from hebrew_live.preferences import read as read_preferences, save as save_preferences
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live.runtime import (persist_target_preference,
                                 target_action_blocker)
from hebrew_live.session_history import SessionHistory
from hebrew_live.stream import Boundary, Captured, Control, Settings
from hebrew_live.translation import prompt


class LanguageCapabilityTests(unittest.TestCase):
    def test_pinned_translation_contract_has_explicit_targets(self):
        self.assertEqual(len(target_languages()),45)
        self.assertEqual(direction_for_target('en'),'he-en')
        self.assertEqual(prompt_names('he-zh-tw'),('Hebrew','Chinese (Traditional)'))
        self.assertEqual(validate_direction('ru-he'),'ru-he')
        for direction in ('en-ru','he-he','he-te'):
            with self.assertRaises(ValueError):validate_direction(direction)

    def test_each_milmmt_target_uses_the_exact_registry_prompt_name(self):
        class Tokenizer:
            eos_token_ids=set()
            def encode(self,value,**_):self.value=value;return [1]
        for language in target_languages():
            tokenizer=Tokenizer()
            prompt(tokenizer,'milmmt','שלום',direction_for_target(language.code))
            self.assertIn(f'Hebrew to {language.milmmt_name}',tokenizer.value)

    def test_preferences_migrate_without_overwriting_and_persist_two_independent_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'preferences.json').write_text('{"schema_version": 2, "draft_catchup_enabled": false}')
            self.assertNotIn('target_language',read_preferences(folder))
            save_preferences(folder,target_language='fr',ui_locale='he')
            self.assertEqual(read_preferences(folder)['target_language'],'fr')
            self.assertEqual(read_preferences(folder)['ui_locale'],'he')
            self.assertEqual(json.loads((folder/'preferences.json').read_text())['schema_version'],3)

    def test_concurrent_preference_updates_do_not_lose_either_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            barrier=threading.Barrier(3)
            def update(**value):
                barrier.wait();save_preferences(folder,**value)
            first=threading.Thread(target=update,kwargs={'target_language':'fr'})
            second=threading.Thread(target=update,kwargs={'ui_locale':'he'})
            first.start();second.start();barrier.wait();first.join();second.join()
            self.assertEqual(read_preferences(folder)['target_language'],'fr')
            self.assertEqual(read_preferences(folder)['ui_locale'],'he')

    def test_language_inventory_is_read_only_and_reports_product_boundaries(self):
        from unittest.mock import patch
        import sys
        output=io.StringIO()
        with patch.object(cli,'require_supported_platform') as guard,patch.object(sys,'argv',['he-ru','languages']),contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(),0)
        guard.assert_not_called()
        self.assertIn('MiLMMT targets (45)',output.getvalue())
        self.assertIn('Overall product registry: 46 languages',output.getvalue())
        self.assertIn('does not qualify arbitrary-language live input',output.getvalue())

    def test_installed_storage_and_uninstall_are_read_only_platform_independent_previews(self):
        from unittest.mock import patch
        import sys
        for arguments,expected in ((['he-ru','storage'],'Managed data root:'),
                                   (['he-ru','uninstall','--dry-run'],'Dry run only; nothing was deleted.')):
            output=io.StringIO()
            with patch.object(cli,'require_supported_platform') as guard,patch.object(sys,'argv',arguments),contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(),0)
            guard.assert_not_called();self.assertIn(expected,output.getvalue())
            self.assertIn('external user data',output.getvalue())
        output=io.StringIO()
        with patch.dict(os.environ,{'HF_HOME':'/tmp/shared-hf-cache'}),contextlib.redirect_stdout(output):
            cli.print_installed_storage()
        self.assertIn('not assumed to be app-owned',output.getvalue())

    def test_installed_storage_reports_and_excludes_explicit_path_overrides(self):
        from unittest.mock import patch
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp)/'external models';logs=Path(tmp)/'external logs'
            output=io.StringIO()
            arguments=['he-ru','--models',str(models),'--log-dir',str(logs),'uninstall','--dry-run']
            with patch.object(sys,'argv',arguments),contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(),0)
            rendered=output.getvalue()
            self.assertIn(f'models: {models.resolve()}',rendered)
            self.assertIn(f'recordings and session logs: {logs.resolve()}',rendered)
            self.assertIn('explicit --models override',rendered)
            self.assertIn('explicit --log-dir override',rendered)
            self.assertIn('outside the assumed root-owned deletion scope',rendered)


class TargetBoundaryTests(unittest.TestCase):
    def test_runtime_rechecks_queued_target_after_model_stop_and_cancel_actions(self):
        stop=threading.Event();cancel=threading.Event()
        self.assertEqual(target_action_blocker(True,stop,cancel),'model_switch')
        self.assertIsNone(target_action_blocker(False,stop,cancel))
        stop.set();self.assertEqual(target_action_blocker(False,stop,cancel),'stopping')
        cancel.set();self.assertEqual(target_action_blocker(False,stop,cancel),'cancelling')

    def test_current_contract_preserves_legacy_ru_he_and_rejects_retired_only_target(self):
        self.assertEqual(validate_direction('ru-he'),'ru-he')
        self.assertEqual(validate_direction('he-hr'),'he-hr')
        with self.assertRaises(ValueError):validate_direction('he-bo')

    def test_target_storage_failure_keeps_applied_boundary_and_is_reported(self):
        control=Control(Settings(direction='he-en',language='he'),threading.Event())
        self.assertTrue(control.switch_target('ru'))
        events=[];session=SimpleNamespace(event=lambda name,**values:events.append((name,values)))
        def fail(*_args,**_kwargs):raise OSError('disk full')
        self.assertFalse(persist_target_preference(Path('/unused'),'ru',fail,session))
        self.assertEqual(control.settings.direction,'he-ru')
        self.assertEqual(events,[('target_language_preference_failed',{'target':'ru','error':'OSError'})])

    def test_target_switch_is_an_ordered_boundary_and_keeps_captured_settings(self):
        control=Control(Settings(direction='he-en',language='he'),threading.Event())
        control.accept(np.array([.1],dtype=np.float32),1.)
        self.assertTrue(control.switch_target('ru'))
        control.accept(np.array([.2],dtype=np.float32),2.)
        before=control.queue.get_nowait();boundary=control.queue.get_nowait();after=control.queue.get_nowait()
        self.assertIsInstance(before,Captured);self.assertEqual(before.settings.direction,'he-en')
        self.assertIsInstance(boundary,Boundary);self.assertEqual(boundary.reason,'target_language')
        self.assertEqual(boundary.settings.direction,'he-ru');self.assertEqual(boundary.settings.part,2)
        self.assertIsInstance(after,Captured);self.assertEqual(after.settings.direction,'he-ru')

    def test_translation_fingerprint_separates_targets(self):
        engine=SimpleNamespace(asr_path='asr',backend='turbo',translation_size='milmmt',
                               direction='he-en',language='he',topic='none')
        processor=RetranslationProcessor(engine,queue.Queue(),SimpleNamespace(),threading.Event())
        processor.settings=Settings(direction='he-en',language='he');first=processor.fingerprint()
        processor.settings=Settings(direction='he-ru',language='he');engine.direction='he-ru'
        self.assertNotEqual(first,processor.fingerprint())

    def test_pending_phrase_jobs_keep_their_own_target_after_switch(self):
        from hebrew_live.phrase_buffer import Unit
        from hebrew_live.phrase_inference import PhraseProcessor
        calls=[]
        class Engine:
            def translate(self,text):
                calls.append((text,self.direction));yield text,'stop'
        log=SimpleNamespace(event=lambda *args,**kwargs:None)
        processor=PhraseProcessor(Engine(),queue.Queue(),log,threading.Event())
        processor.last=SimpleNamespace(end=1.,offset=1.)
        unit=lambda text:Unit(text,[dict(word=text,start=0.,end=1.,fragment=1)],'sentence')
        processor.settings=Settings(direction='he-en',language='he',mode='phrases')
        processor.enqueue(unit('old'))
        processor.settings=Settings(part=2,direction='he-ru',language='he',mode='phrases')
        processor.enqueue(unit('new'))
        processor.drain()
        self.assertEqual(calls,[('old','he-en'),('new','he-ru')])

    def test_archive_reads_new_multisegment_and_legacy_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'20260920-120000-1234abcd';folder.mkdir()
            for number,direction,target in ((1,'he-bo','བོད་སྐད'),(2,'ru-he','שלום')):
                event=dict(event='live_publication',segment=number,current=dict(source='מקור',translation=target),history=[],stage='closed',issue=None,reason='silence')
                (folder/f'{number:03d}-{direction}.diagnostics.jsonl').write_text(json.dumps(event,ensure_ascii=False)+'\n')
            state=SessionHistory(root).read(folder.name)
            self.assertEqual([group['direction'] for group in state['groups']],['he-bo','ru-he'])
            self.assertEqual(state['direction'],'ru-he')


class BrowserLanguageActionTests(unittest.TestCase):
    def post(self,ui,payload):
        request=urllib.request.Request(ui.url+'action',data=json.dumps(payload).encode(),
            headers={'Content-Type':'application/json','Origin':'http://'+ui.host})
        return urllib.request.urlopen(request)

    def test_browser_admits_only_advertised_target_and_supported_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            with BrowserUI(open_browser=False) as ui:
                self.assertEqual(ui.state['direction'],'he-en')
                ui.preference_folder=Path(tmp)/'settings'
                ui.details(target_languages=[dict(code='en',name='English',rtl=False),dict(code='ru',name='Russian',rtl=False)])
                with self.post(ui,{'action':'target_language','value':'ru'}) as response:self.assertEqual(response.status,202)
                self.assertEqual(ui.actions.get_nowait(),{'target_language':'ru'})
                with self.post(ui,{'action':'ui_locale','value':'he'}) as response:self.assertEqual(response.status,200)
                self.assertEqual(read_preferences(ui.preference_folder)['ui_locale'],'he')
                with self.assertRaises(urllib.error.HTTPError) as error:self.post(ui,{'action':'target_language','value':'te'})
                self.assertEqual(error.exception.code,409)

    def test_failed_locale_save_returns_error_without_claiming_the_new_locale(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            with BrowserUI(open_browser=False) as ui:
                ui.preference_folder=Path(tmp)/'settings'
                with patch('hebrew_live.preferences.save',side_effect=OSError('read only')):
                    with self.assertRaises(urllib.error.HTTPError) as error:self.post(ui,{'action':'ui_locale','value':'he'})
                self.assertEqual(error.exception.code,500)
                self.assertEqual(ui.state['ui_locale'],'en')


if __name__=='__main__':unittest.main()
