#!/usr/bin/env python3
"""Exercise source bootstrap, tests, wheel, sdist, and installs outside the repo."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]


def run(command,cwd,env):
    print('+',' '.join(map(str,command)),flush=True)
    subprocess.run([str(item) for item in command],cwd=cwd,env=env,check=True)


def install_and_probe(artifact:Path,folder:Path,env:dict):
    probe_env=dict(env)
    probe_env.pop('PYTHONPATH',None);probe_env.pop('PYTHONHOME',None)
    probe_cwd=folder.parent/(folder.name+'-cwd');probe_cwd.mkdir()
    run([sys.executable,'-m','venv',folder],probe_cwd,probe_env)
    python=folder/'bin/python';pip=folder/'bin/pip';command=folder/'bin/he-ru'
    run([pip,'install','--no-deps',artifact.resolve()],probe_cwd,probe_env)
    run([python,ROOT/'scripts/probe_installed_package.py'],probe_cwd,probe_env)
    output=subprocess.check_output([command,'report'],cwd=probe_cwd,env=probe_env,text=True)
    report=json.loads(output);assert report['schema_version']==1 and 'package_versions' in report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hebrew-live-public-smoke-') as temporary:
        temporary=Path(temporary);export=temporary/'hebrew-live-cli-0.1.0-alpha-source'
        npm_cache=temporary/'npm-cache'
        env=dict(os.environ,UV_CACHE_DIR=str(ROOT/'.cache/uv'),HF_HOME=str(temporary/'hf'),HEBREW_LIVE_HOME=str(temporary/'data'),npm_config_cache=str(npm_cache))
        run([sys.executable,ROOT/'scripts/build_public_export.py','--output',export],ROOT,env)
        if not os.access(export/'run.sh',os.X_OK):raise RuntimeError('source launcher is not executable')
        run(['/bin/sh','-n','run.sh'],export,env)
        frontend=export/'experiments/publication-ui-preview'
        npm_ci=['npm','ci'];uv_offline=['--offline'] if args.offline else []
        if args.offline:npm_ci.append('--offline')
        run(npm_ci,frontend,env);run(['npm','test'],frontend,env);run(['npm','run','build'],frontend,env)
        run(['uv','sync','--frozen',*uv_offline],export,env)
        test_env=dict(env,PYTHONPATH=str(export/'src'))
        run([export/'.venv/bin/python','-B','-m','unittest','discover','-s','tests'],export,test_env)
        run(['uv','build',*uv_offline],export,env)
        wheels=sorted((export/'dist').glob('*.whl'));sdists=sorted((export/'dist').glob('*.tar.gz'))
        if len(wheels)!=1 or len(sdists)!=1:raise RuntimeError('expected exactly one wheel and one sdist')
        install_and_probe(wheels[0],temporary/'wheel-venv',env)
        unpacked=temporary/'sdist';unpacked.mkdir()
        with tarfile.open(sdists[0]) as archive:archive.extractall(unpacked,filter='data')
        roots=[path for path in unpacked.iterdir() if path.is_dir()]
        if len(roots)!=1:raise RuntimeError('sdist has an unexpected root layout')
        if not os.access(roots[0]/'run.sh',os.X_OK):raise RuntimeError('sdist launcher is absent or not executable')
        run(['/bin/sh','-n',roots[0]/'run.sh'],roots[0],env)
        rebuilt=temporary/'sdist-wheel';rebuilt.mkdir()
        run(['uv','build','--wheel','--out-dir',rebuilt,*uv_offline],roots[0],env)
        rebuilt_wheels=list(rebuilt.glob('*.whl'))
        if len(rebuilt_wheels)!=1:raise RuntimeError('sdist did not rebuild exactly one wheel')
        install_and_probe(rebuilt_wheels[0],temporary/'sdist-venv',env)
        npm_cache_bytes=sum(path.stat().st_size for path in npm_cache.rglob('*') if path.is_file())
        print(json.dumps({'clean_export':'passed','source_and_sdist_launcher':'executable and shell syntax passed',
                          'frontend':'passed','python':'passed',
                          'wheel_asset_install_probe':'passed','sdist_rebuild_asset_install_probe':'passed',
                          'source_dependencies':'installed by uv sync; isolated artifact probes intentionally use pip --no-deps',
                          'npm_cache_bytes':npm_cache_bytes,'npm_source':'locked package-lock registry URLs'},indent=2))


if __name__=='__main__':main()
