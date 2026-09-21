import contextlib
import io
import os
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hebrew_live import cli


ROOT=Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)/'source with spaces';self.root.mkdir()
        shutil.copy2(ROOT/'run.sh',self.root/'run.sh')
        self.bin=self.root/'fake-bin';self.bin.mkdir()
        self.log=self.root/'uv.log'
        self._script('uname',"""#!/bin/sh
if [ "${1:-}" = -s ]; then printf '%s\\n' "${FAKE_SYSTEM:-Darwin}"; else printf '%s\\n' "${FAKE_MACHINE:-arm64}"; fi
""")
        self._script('sysctl',"""#!/bin/sh
printf '%s\\n' "${FAKE_ROSETTA:-0}"
""")
        self._script('uv',"""#!/bin/sh
printf 'ENV<%s><%s><%s><%s>\n' "$UV_PROJECT_ENVIRONMENT" "${UV_PYTHON_INSTALL_DIR:-}" "$UV_CACHE_DIR" "$HF_HOME" >> "$UV_LOG"
for argument in "$@"; do printf '<%s>' "$argument" >> "$UV_LOG"; done
printf '\\n' >> "$UV_LOG"
if [ "${1:-}" = sync ]; then
    project_env=${UV_PROJECT_ENVIRONMENT:-.venv}
    case "$*" in
        *"--check"*)
            if [ -n "${FAKE_CHECK_STATUS+x}" ]; then exit "$FAKE_CHECK_STATUS"; fi
            [ -f "$project_env/.fake-ready" ]
            exit $?
            ;;
    esac
    status=${FAKE_SYNC_STATUS:-0}
    mkdir -p "$project_env/bin"; : > "$project_env/bin/python"; chmod +x "$project_env/bin/python"
    if [ "$status" -eq 0 ]; then : > "$project_env/.fake-ready"; fi
    exit "$status"
fi
case "$*" in
    *"print(mx.__file__)"*) exit "${FAKE_MLX_IMPORT_STATUS:-0}" ;;
    *"mx.metal.is_available"*) exit "${FAKE_METAL_STATUS:-0}" ;;
    *"he-ru model-info"*) printf '%s\\n' 'model terms inventory'; exit 0 ;;
    *"he-ru setup --accept-model-terms"*)
        status=${FAKE_SETUP_STATUS:-0}
        if [ "$status" -eq 0 ]; then mkdir -p "$HEBREW_LIVE_HOME/models"; printf '{}\\n' > "$HEBREW_LIVE_HOME/models/manifest.json"; fi
        exit "$status"
        ;;
    *"he-ru listen"*) exit "${FAKE_FINAL_STATUS:-0}" ;;
esac
exit "${FAKE_FINAL_STATUS:-0}"
""")
        self.app_root=self.root/'app data'
        self.env=dict(os.environ,PATH=f'{self.bin}:{os.environ.get("PATH","")}',UV_LOG=str(self.log),HEBREW_LIVE_HOME=str(self.app_root),
                      FAKE_SYSTEM='Darwin',FAKE_MACHINE='arm64',FAKE_ROSETTA='0')

    def tearDown(self):
        self.temporary.cleanup()

    def _script(self,name,text):
        path=self.bin/name;path.write_text(text);path.chmod(0o755)

    def _ready(self,models=True):
        python=self.app_root/'runtime/.venv/bin/python';python.parent.mkdir(parents=True,exist_ok=True)
        python.touch();python.chmod(0o755)
        (self.app_root/'runtime/.venv/.fake-ready').touch()
        if models:
            manifest=self.app_root/'models/manifest.json';manifest.parent.mkdir(parents=True);manifest.write_text('{}\n')

    def _run(self,*arguments,env=None):
        return subprocess.run([str(self.root/'run.sh'),*arguments],cwd=self.root,
                              env=env or self.env,stdin=subprocess.DEVNULL,
                              text=True,capture_output=True,check=False)

    def _run_tty(self,input_bytes,*arguments):
        master,slave=pty.openpty()
        process=subprocess.Popen([str(self.root/'run.sh'),*arguments],cwd=self.root,env=self.env,
                                 stdin=slave,stdout=slave,stderr=slave,close_fds=True)
        os.close(slave);os.write(master,input_bytes)
        output=bytearray();deadline=time.monotonic()+5
        try:
            while process.poll() is None and time.monotonic()<deadline:
                readable,_,_=select.select([master],[],[],0.05)
                if readable:
                    try:output.extend(os.read(master,65536))
                    except OSError:break
            process.wait(timeout=max(0.1,deadline-time.monotonic()))
            while True:
                try:
                    chunk=os.read(master,65536)
                    if not chunk:break
                    output.extend(chunk)
                except OSError:break
        finally:
            os.close(master)
            if process.poll() is None:process.kill()
        return process.returncode,output.decode(errors='replace')

    def _calls(self):
        return self.log.read_text() if self.log.exists() else ''

    def test_unsupported_os_intel_and_rosetta_fail_before_uv(self):
        cases=(('Linux','arm64','0','requires macOS'),('Darwin','x86_64','0','Intel Macs'),
               ('Darwin','x86_64','1','Rosetta'))
        for system,machine,rosetta,message in cases:
            with self.subTest(system=system,machine=machine,rosetta=rosetta):
                if self.log.exists():self.log.unlink()
                env=dict(self.env,FAKE_SYSTEM=system,FAKE_MACHINE=machine,FAKE_ROSETTA=rosetta)
                result=self._run('listen',env=env)
                self.assertEqual(result.returncode,64)
                self.assertIn(message,result.stderr)
                self.assertEqual(self._calls(),'')

    def test_metal_failure_stops_before_model_download(self):
        self._ready(models=False)
        result=self._run('setup','--accept-model-terms',env=dict(self.env,FAKE_METAL_STATUS='5'))
        self.assertEqual(result.returncode,69)
        self.assertIn('Metal is unavailable',result.stderr)
        calls=self._calls();self.assertIn('<python><-c>',calls)
        self.assertNotIn('<he-ru><setup>',calls)

    def test_ready_byo_run_is_offline_preserves_spaces_and_skips_setup(self):
        self._ready(models=False)
        custom=self.root/'my models/asr';custom.parent.mkdir()
        result=self._run('listen','--asr-model',str(custom),'--translation-model',str(self.root/'my models/mt'),
                         '--vad-model',str(self.root/'my models/vad.onnx'))
        self.assertEqual(result.returncode,0,result.stderr)
        calls=self._calls()
        self.assertNotIn('<sync><--frozen><--python>',calls);self.assertNotIn('<he-ru><setup>',calls)
        self.assertIn(f'<--asr-model><{custom}>',calls)
        self.assertIn('<run><--offline><--frozen><--no-sync><he-ru><listen>',calls)

    def test_interactive_model_setup_can_be_cancelled(self):
        self._ready(models=False)
        status,output=self._run_tty(b'n\n')
        self.assertEqual(status,130,output)
        self.assertIn('Model setup cancelled',output)
        self.assertNotIn('<he-ru><setup>',self._calls())

    def test_interactive_dependency_bootstrap_can_be_cancelled(self):
        status,output=self._run_tty(b'n\n')
        self.assertEqual(status,69,output)
        self.assertIn('environment is not prepared',output)
        self.assertEqual(self._calls(),'')

    def test_unprepared_noninteractive_run_does_not_bootstrap(self):
        result=self._run()
        self.assertEqual(result.returncode,69)
        self.assertIn('environment is not prepared',result.stderr)
        self.assertEqual(self._calls(),'')

    def test_no_tty_never_implies_model_acknowledgement(self):
        self._ready(models=False)
        result=self._run()
        self.assertEqual(result.returncode,130)
        self.assertIn('Model setup cancelled',result.stderr)
        self.assertNotIn('<he-ru><setup>',self._calls())

    def test_explicit_one_command_bootstraps_sets_up_and_listens(self):
        result=self._run('--accept-model-terms')
        self.assertEqual(result.returncode,0,result.stderr)
        calls=self._calls()
        expected=('<sync><--frozen><--python><3.12>','<sync><--frozen><--offline><--check>',
                  'print(mx.__file__)','mx.metal.is_available',
                  '<he-ru><model-info>','<he-ru><setup><--accept-model-terms>',
                  '<he-ru><listen>')
        positions=[calls.index(value) for value in expected]
        self.assertEqual(positions,sorted(positions))

    def test_incomplete_environment_requires_explicit_repair(self):
        python=self.app_root/'runtime/.venv/bin/python';python.parent.mkdir(parents=True);python.touch();python.chmod(0o755)
        result=self._run('listen')
        self.assertEqual(result.returncode,69)
        self.assertIn('incomplete or stale',result.stderr)
        calls=self._calls();self.assertIn('<sync><--frozen><--offline><--check>',calls)
        self.assertNotIn('<python><-c>',calls)

    def test_missing_mlx_package_is_not_reported_as_metal_failure(self):
        self._ready()
        result=self._run('listen',env=dict(self.env,FAKE_MLX_IMPORT_STATUS='6'))
        self.assertEqual(result.returncode,69)
        self.assertIn('MLX package cannot be imported',result.stderr)
        self.assertIn('Metal was not tested',result.stderr)
        self.assertNotIn('Metal is unavailable',result.stderr)
        self.assertNotIn('mx.metal.is_available',self._calls())

    def test_sync_network_failure_preserves_status_and_partial_env_is_not_ready(self):
        result=self._run('--bootstrap','report',env=dict(self.env,FAKE_SYNC_STATUS='17'))
        self.assertEqual(result.returncode,17)
        self.assertIn('network, disk, Python, or package error',result.stderr)
        self.assertTrue((self.app_root/'runtime/.venv/bin/python').exists())
        self.assertFalse((self.app_root/'runtime/.venv/.fake-ready').exists())
        if self.log.exists():self.log.unlink()
        retry=self._run('report')
        self.assertEqual(retry.returncode,69)
        self.assertIn('incomplete or stale',retry.stderr)
        self.assertNotIn('<sync><--frozen><--python>',self._calls())

    def test_explicit_retry_repairs_environment_after_failed_sync(self):
        first=self._run('--bootstrap','report',env=dict(self.env,FAKE_SYNC_STATUS='9'))
        self.assertEqual(first.returncode,9)
        if self.log.exists():self.log.unlink()
        second=self._run('--bootstrap','report')
        self.assertEqual(second.returncode,0,second.stderr)
        calls=self._calls()
        self.assertIn('<sync><--frozen><--offline><--check>',calls)
        self.assertIn('<sync><--frozen><--python><3.12>',calls)
        self.assertIn('<he-ru><report>',calls)

    def test_final_command_status_is_propagated(self):
        self._ready()
        result=self._run('listen',env=dict(self.env,FAKE_FINAL_STATUS='7'))
        self.assertEqual(result.returncode,7)

    def test_storage_and_uninstall_preview_are_read_only_and_contained(self):
        storage=self._run('storage',env=dict(self.env,FAKE_SYSTEM='Linux'))
        self.assertEqual(storage.returncode,0,storage.stderr)
        self.assertIn(f'Managed data root: {self.app_root}',storage.stdout)
        self.assertIn(f'project environment: {self.app_root}/runtime/.venv',storage.stdout)
        self.assertEqual(self._calls(),'')
        preview=self._run('uninstall','--dry-run',env=dict(self.env,FAKE_SYSTEM='Linux'))
        self.assertEqual(preview.returncode,0,preview.stderr)
        self.assertIn('Dry run only; nothing was deleted.',preview.stdout)
        self.assertIn('External BYO model files are intentionally excluded',preview.stdout)
        self.assertFalse(self.app_root.exists())

    def test_launcher_preview_rejects_python_only_path_overrides_before_uv(self):
        result=self._run('--models',str(self.root/'elsewhere'),'storage',env=dict(self.env,FAKE_SYSTEM='Linux'))
        self.assertEqual(result.returncode,64)
        self.assertIn('does not accept --models or --log-dir overrides',result.stderr)
        self.assertIn('he-ru --models PATH --log-dir PATH storage',result.stderr)
        self.assertEqual(self._calls(),'')

    def test_fresh_default_root_keeps_uv_and_python_paths_central_across_second_run(self):
        home=self.root/'fresh home';home.mkdir()
        env=dict(self.env,HOME=str(home));env.pop('HEBREW_LIVE_HOME')
        first=self._run('--bootstrap','report',env=env)
        second=self._run('report',env=env)
        self.assertEqual(first.returncode,0,first.stderr);self.assertEqual(second.returncode,0,second.stderr)
        central=home/'Library/Application Support/Hebrew Live CLI'
        expected=f'ENV<{central}/runtime/.venv><{central}/runtime/python><{central}/cache/uv><{central}/cache/huggingface>'
        calls=self._calls();environment_lines=[line for line in calls.splitlines() if line.startswith('ENV<')]
        self.assertTrue(environment_lines);self.assertTrue(all(line==expected for line in environment_lines))
        self.assertEqual(calls.count('<sync><--frozen><--python><3.12>'),1)
        self.assertEqual(calls.count('<run><--offline><--frozen><--no-sync><he-ru><report>'),2)
        self.assertTrue((central/'runtime/.venv/.fake-ready').is_file())
        self.assertFalse((central/'models').exists())
        for name in ('.venv','.cache','models','logs','.local-settings'):
            self.assertFalse((self.root/name).exists(),name)

    def test_existing_source_storage_is_not_migrated(self):
        (self.root/'.local-settings').mkdir()
        env=dict(self.env);env.pop('HEBREW_LIVE_HOME')
        result=self._run('storage',env=env)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Storage mode: legacy-source',result.stdout)
        self.assertIn(f'Managed data root: {self.root}',result.stdout)
        preview=self._run('uninstall','--dry-run',env=env)
        self.assertEqual(preview.returncode,0,preview.stderr)
        self.assertIn('mixes source and app-owned data',preview.stdout)
        self.assertNotIn('then move the managed data root to Trash',preview.stdout)
        self.assertTrue((self.root/'.local-settings').is_dir())


class PlatformGuardTests(unittest.TestCase):
    @patch.object(cli.platform,'system',return_value='Linux')
    @patch.object(cli.platform,'machine',return_value='arm64')
    def test_python_entrypoint_rejects_non_macos(self,machine,system):
        with self.assertRaisesRegex(RuntimeError,'requires macOS'):
            cli.require_supported_platform()

    @patch.object(cli.platform,'system',return_value='Darwin')
    @patch.object(cli.platform,'machine',return_value='x86_64')
    def test_python_entrypoint_rejects_rosetta_or_intel(self,machine,system):
        with self.assertRaisesRegex(RuntimeError,'native Apple Silicon arm64'):
            cli.require_supported_platform()

    @patch.object(cli.platform,'system',return_value='Darwin')
    @patch.object(cli.platform,'machine',return_value='arm64')
    def test_python_entrypoint_requires_working_metal(self,machine,system):
        with patch.object(cli.importlib,'import_module',side_effect=ImportError('no device')):
            with self.assertRaisesRegex(RuntimeError,'Metal device'):
                cli.require_supported_platform()
        mx=Mock();mx.int32=object();mx.gpu=object();mx.array.return_value=object();mx.metal.is_available.return_value=True
        with patch.object(cli.importlib,'import_module',return_value=mx):
            cli.require_supported_platform()
        mx.set_default_device.assert_called_once_with(mx.gpu)
        mx.eval.assert_called_once()

    def test_model_info_stays_available_without_runtime_guard(self):
        with patch.object(cli,'require_supported_platform') as guard, \
             patch.object(sys,'argv',['he-ru','model-info']),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(),0)
        guard.assert_not_called()


if __name__=='__main__':unittest.main()
