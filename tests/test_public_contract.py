import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from hebrew_live.browser_ui import BrowserUI
from hebrew_live.cli import SPEC, bug_report, core_spec, validate_custom_models, verify


# Whisper's identities from the releases that still downloaded it (manifests may list them).
WHISPER={'asr':{'repo':'mlx-community/ivrit-ai-whisper-large-v3-turbo-mlx',
                'revision':'53ad8c6cd8b32eb0303f093a404ae13c1b1d567f'},
         'asr_multilingual':{'repo':'mlx-community/whisper-large-v3-turbo',
                             'revision':'a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb','folder':'asr-multilingual'}}


def model_files(root,assets):
    names=[]
    for asset in assets:
        folder=SPEC.get(asset,WHISPER.get(asset,{})).get('folder',asset)
        if asset in ('asr','asr_multilingual'):names.extend((f'{folder}/config.json',f'{folder}/weights.safetensors'))
        elif asset=='translation':
            names.extend((f'{folder}/config.json',f'{folder}/model.safetensors',f'{folder}/tokenizer.json'))
        elif asset=='vad':names.append('silero.onnx')
    result={}
    for name in names:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
        result[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class PublicContractTests(unittest.TestCase):
    def test_synthetic_cross_contract_fixture_matches_backend_state_shape(self):
        fixture=json.loads((Path(__file__).parent/'fixtures'/'live_states.json').read_text())
        self.assertIn('Synthetic',fixture['provenance'])
        required={'groups','phase','status','paused','finished','direction'}
        with BrowserUI(open_browser=False) as ui:
            self.assertTrue(required.issubset(ui.state))
            for item in fixture['states']:
                state=item['state']
                self.assertTrue(required.issubset(state))
                self.assertIsInstance(json.dumps(state,ensure_ascii=False),str)

    def test_packaged_live_ui_is_present(self):
        with BrowserUI(open_browser=False,live=True) as ui:
            self.assertTrue((ui.live_root/'live.html').is_file())
            notice=(ui.live_root/'licenses'/'THIRD-PARTY-NOTICES.txt').read_text()
            self.assertIn('@fontsource/noto-sans@5.3.0',notice)
            self.assertIn('@heroui/react@3.2.4',notice)
            self.assertIn('react-aria-components@1.21.1',notice)
            self.assertIn('Locked integrity:',notice)
            self.assertNotIn('MISSING FROM INSTALLED PACKAGE',notice)
            self.assertTrue(any((ui.live_root/'assets').glob('*.js')))

    def test_model_manifest_identity_ignores_documentation_metadata(self):
        legacy={key:{name:value for name,value in SPEC[key].items()
                     if name in {'repo','revision','folder','url'}}
                for key in ('translation','vad')}
        legacy['asr']=dict(WHISPER['asr'])
        self.assertEqual(core_spec(legacy),core_spec(SPEC))

    def test_legacy_manifest_with_whisper_still_verifies_without_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp)
            legacy={key:{name:value for name,value in SPEC[key].items()
                         if name in {'repo','revision','folder','url'}} for key in ('translation','vad')}
            legacy['asr']=dict(WHISPER['asr'])
            files=model_files(models,('asr','translation','vad'))
            (models/'manifest.json').write_text(json.dumps({'spec':legacy,'files':files}))
            verify(models,('translation','vad'))
            # Whisper's files may be gone (moved to the Trash): they are no longer checked.
            for name in ('asr/config.json','asr/weights.safetensors'):(models/name).unlink()
            verify(models,('translation','vad'))
            with self.assertRaisesRegex(RuntimeError,'Unknown required model asset'):verify(models,{'asr'})

    def test_empty_and_incomplete_manifests_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['translation','vad']
            manifest={'schema_version':2,'assets':assets,'spec':SPEC,'files':{}}
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'no verified files'):verify(models,{'translation'})
            manifest['files']=model_files(models,['vad'])
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'omits critical'):verify(models,{'translation'})

    def test_new_manifest_pins_translation_and_rejects_retired_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['translation','vad']
            spec=copy.deepcopy(SPEC);spec['translation']['revision']='different'
            manifest={'schema_version':2,'assets':assets,'spec':spec,'files':model_files(models,assets)}
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'revisions changed'):verify(models,{'translation'})
            manifest['spec']=SPEC;(models/'manifest.json').write_text(json.dumps(manifest))
            for retired in ('translation_7b','asr','asr_multilingual'):
                with self.assertRaisesRegex(RuntimeError,'Unknown required model asset'):verify(models,{retired})

    def test_desktop_manifest_and_old_manifests_that_list_whisper_are_valid(self):
        for assets in (['translation','vad'],['asr','translation','vad'],['asr','asr_multilingual','translation','vad']):
            with self.subTest(assets=assets),tempfile.TemporaryDirectory() as tmp:
                models=Path(tmp);spec=dict(SPEC,**{key:WHISPER[key] for key in assets if key in WHISPER})
                manifest={'schema_version':2,'assets':assets,'spec':spec,'files':model_files(models,assets)}
                (models/'manifest.json').write_text(json.dumps(manifest))
                verify(models,{'translation','vad'})

    def test_old_manifest_may_keep_retired_unused_files_without_exposing_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['asr','asr_multilingual','translation','vad']
            files=model_files(models,assets)
            files['translation-7b/model.safetensors']='0'*64
            spec=dict(copy.deepcopy(SPEC),**WHISPER);spec['translation_7b']={'repo':'retired','revision':'old','folder':'translation-7b'}
            manifest={'schema_version':2,'assets':assets+['translation_7b'],'spec':spec,'files':files}
            (models/'manifest.json').write_text(json.dumps(manifest))
            verify(models,{'translation','vad'})
            with self.assertRaisesRegex(RuntimeError,'Unknown required model asset'):
                verify(models,{'translation_7b'})

    def test_custom_model_layouts_are_external_to_managed_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);managed=root/'managed';managed.mkdir()
            mt=root/'custom-mt';mt.mkdir();(mt/'config.json').write_text('{}');(mt/'tokenizer.json').write_text('{}');(mt/'model.safetensors').touch()
            vad=root/'custom-vad.onnx';vad.touch()
            values=validate_custom_models(managed,mt,vad)
            self.assertEqual(values,{'translation':mt.resolve(),'vad':vad.resolve()})
            inside=managed/'mt';inside.mkdir()
            with self.assertRaisesRegex(ValueError,'outside'):
                validate_custom_models(managed,inside,None)

    def test_bug_report_handles_invalid_manifest_without_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);(models/'manifest.json').write_text('{"spec": null, "files": {}}')
            report=bug_report(models)
            self.assertTrue(report['model_manifest']['readable'])
            self.assertFalse(report['model_manifest']['spec_matches'])
            self.assertIn('https://',report['model_inventory']['vad']['source'])
            self.assertNotIn(str(models),json.dumps(report))

    def test_managed_manifest_cannot_escape_model_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['translation','vad']
            files=model_files(models,assets);files['../outside']='0'*64
            manifest={'schema_version':2,'assets':assets,'spec':SPEC,'files':files}
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'manifest is invalid'):
                verify(models,{'translation'})
