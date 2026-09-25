import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from hebrew_live.browser_ui import BrowserUI
from hebrew_live.cli import SPEC, bug_report, core_spec, validate_custom_models, verify


def model_files(root,assets):
    names=[]
    for asset in assets:
        folder=SPEC.get(asset,{}).get('folder',asset)
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
                for key in ('asr','translation','vad')}
        self.assertEqual(core_spec(legacy),core_spec(SPEC))

    def test_legacy_manifest_keeps_exact_core_identity_and_required_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=('asr','translation','vad')
            legacy={key:{name:value for name,value in SPEC[key].items()
                         if name in {'repo','revision','folder','url'}} for key in assets}
            (models/'manifest.json').write_text(json.dumps({'spec':legacy,'files':model_files(models,assets)}))
            verify(models,assets)

    def test_legacy_manifest_cannot_select_unpinned_optional_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=('asr','translation','vad')
            legacy={key:{name:value for name,value in SPEC[key].items()
                         if name in {'repo','revision','folder','url'}} for key in assets}
            files=model_files(models,assets+('asr_multilingual',))
            (models/'manifest.json').write_text(json.dumps({'spec':legacy,'files':files}))
            with self.assertRaisesRegex(RuntimeError,'absent from the setup manifest'):
                verify(models,{'asr_multilingual'})

    def test_empty_and_incomplete_manifests_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['asr','asr_multilingual','translation','vad']
            manifest={'schema_version':2,'assets':assets,'spec':SPEC,'files':{}}
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'no verified files'):verify(models,{'asr'})
            manifest['files']=model_files(models,['asr'])
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'omits critical'):verify(models,{'asr'})

    def test_new_manifest_pins_selected_coverage_and_rejects_retired_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['asr','asr_multilingual','translation','vad']
            spec=copy.deepcopy(SPEC);spec['asr_multilingual']['revision']='different'
            manifest={'schema_version':2,'assets':assets,'spec':spec,'files':model_files(models,assets)}
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'revisions changed'):verify(models,{'asr_multilingual'})
            manifest['spec']=SPEC;(models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'Unknown required model asset'):verify(models,{'translation_7b'})

    def test_desktop_three_asset_manifest_and_original_four_asset_manifest_are_valid(self):
        for assets in (['asr','translation','vad'],['asr','asr_multilingual','translation','vad']):
            with self.subTest(assets=assets),tempfile.TemporaryDirectory() as tmp:
                models=Path(tmp)
                manifest={'schema_version':2,'assets':assets,'spec':SPEC,'files':model_files(models,assets)}
                (models/'manifest.json').write_text(json.dumps(manifest))
                verify(models,set(assets))

    def test_bundled_fast_asr_needs_only_translation_and_vad_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['translation','vad']
            manifest={'schema_version':2,'assets':assets,'spec':SPEC,'files':model_files(models,assets)}
            (models/'manifest.json').write_text(json.dumps(manifest))
            verify(models,set(assets))
            with self.assertRaisesRegex(RuntimeError,'absent from the setup manifest'):
                verify(models,{'asr'})

    def test_old_manifest_may_keep_retired_unused_files_without_exposing_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            models=Path(tmp);assets=['asr','asr_multilingual','translation','vad']
            files=model_files(models,assets)
            files['translation-7b/model.safetensors']='0'*64
            spec=copy.deepcopy(SPEC);spec['translation_7b']={'repo':'retired','revision':'old','folder':'translation-7b'}
            manifest={'schema_version':2,'assets':assets+['translation_7b'],'spec':spec,'files':files}
            (models/'manifest.json').write_text(json.dumps(manifest))
            verify(models,set(assets))
            with self.assertRaisesRegex(RuntimeError,'Unknown required model asset'):
                verify(models,{'translation_7b'})

    def test_custom_model_layouts_are_external_to_managed_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);managed=root/'managed';managed.mkdir()
            asr=root/'custom-asr';asr.mkdir();(asr/'config.json').write_text('{}');(asr/'weights.safetensors').touch()
            mt=root/'custom-mt';mt.mkdir();(mt/'config.json').write_text('{}');(mt/'tokenizer.json').write_text('{}');(mt/'model.safetensors').touch()
            vad=root/'custom-vad.onnx';vad.touch()
            values=validate_custom_models(managed,asr,mt,vad)
            self.assertEqual(values,{'asr':asr.resolve(),'translation':mt.resolve(),'vad':vad.resolve()})
            inside=managed/'asr';inside.mkdir();(inside/'config.json').write_text('{}');(inside/'weights.safetensors').touch()
            with self.assertRaisesRegex(ValueError,'outside'):
                validate_custom_models(managed,inside,None,None)

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
            models=Path(tmp);assets=['asr','asr_multilingual','translation','vad']
            files=model_files(models,assets);files['../outside']='0'*64
            manifest={'schema_version':2,'assets':assets,'spec':SPEC,'files':files}
            (models/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(RuntimeError,'manifest is invalid'):
                verify(models,{'asr'})
