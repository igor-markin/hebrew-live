#!/usr/bin/env python3
"""Build a standalone source tree from an explicit public allowlist."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from check_public_tree import check


ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES=(
    '.gitignore','README.md','README.ru.md','LICENSE','CHANGELOG.md','CONTRIBUTING.md','PRIVACY.md',
    'SECURITY.md','SUPPORT.md','pyproject.toml','run.sh','uv.lock',
)
DOC_FILES=(
    'ARCHITECTURE.md','DEPENDENCY_INVENTORY.json','DOCKER.md','LICENSE_DECISION.md',
    'RELEASE_READINESS.md','THIRD_PARTY.md',
    'images/language-settings.jpg','images/live-translation.jpg','images/session-archive.jpg',
)
SCRIPT_FILES=('build_public_export.py','check_public_tree.py','ci_clean_smoke.py','generate_dependency_inventory.py',
              'probe_installed_package.py')
FRONTEND_FILES=(
    'README.md','package.json','package-lock.json','tsconfig.json','vite.config.ts','index.html','live.html',
    'src/App.tsx','src/Live.tsx','src/i18n.ts','src/live.css','src/liveMain.tsx','src/liveState.ts',
    'src/main.tsx','src/policy.ts','src/styles.css','src/useFollowLatest.ts',
    'src/data/public-cases.json','tests/followGrowth.test.ts','tests/i18n.test.ts','tests/liveContract.test.ts',
    'tests/liveState.test.ts','tests/policy.test.ts','public/licenses/Noto-Sans-Hebrew-OFL.txt',
    'public/licenses/Noto-Sans-OFL.txt',
)


def copy_file(relative:Path,destination:Path):
    source=ROOT/relative
    if not source.is_file():raise FileNotFoundError(f'missing allowlisted source: {relative}')
    target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)


def add_tree(source_relative:Path,destination:Path,allowed_suffixes:set[str],exclude_names:set[str]=set()):
    source=ROOT/source_relative
    for item in sorted(source.rglob('*')):
        if not item.is_file() or item.is_symlink() or item.name in exclude_names or '__pycache__' in item.parts:continue
        if item.suffix.lower() not in allowed_suffixes:continue
        copy_file(item.relative_to(ROOT),destination)


def manifest(destination:Path)->dict:
    entries=[]
    for path in sorted(item for item in destination.rglob('*') if item.is_file() and item.name!='PUBLIC-MANIFEST.json'):
        entries.append({'path':str(path.relative_to(destination)),'bytes':path.stat().st_size,
                        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'schema_version':1,'composition':'explicit allowlist; no repository history or model/runtime data',
            'files':entries}


def write_zip(source:Path,archive:Path):
    if archive.exists():raise FileExistsError(f'archive already exists: {archive}')
    archive.parent.mkdir(parents=True,exist_ok=True)
    prefix=source.name+'/'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
        for path in sorted(item for item in source.rglob('*') if item.is_file()):
            info=zipfile.ZipInfo(prefix+str(path.relative_to(source)),date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=((0o755 if os.access(path,os.X_OK) else 0o644)&0xFFFF)<<16
            bundle.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)


def build(destination:Path,archive:Path|None=None)->dict:
    destination=destination.resolve()
    if destination.exists():raise FileExistsError(f'destination already exists: {destination}')
    destination.mkdir(parents=True)
    for name in ROOT_FILES:copy_file(Path(name),destination)
    for name in DOC_FILES:copy_file(Path('docs')/name,destination)
    for name in SCRIPT_FILES:copy_file(Path('scripts')/name,destination)
    copy_file(Path('.github/workflows/ci.yml'),destination)
    copy_file(Path('.github/ISSUE_TEMPLATE/bug_report.md'),destination)
    add_tree(Path('src/hebrew_live'),destination,{'.py','.json','.html','.js','.css','.woff','.woff2','.txt'})
    add_tree(Path('tests'),destination,{'.py','.json'},exclude_names={'model_smoke.py'})
    frontend=Path('experiments/publication-ui-preview')
    for name in FRONTEND_FILES:copy_file(frontend/name,destination)
    result=manifest(destination)
    (destination/'PUBLIC-MANIFEST.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    result['scan']=check(destination)
    if archive is not None:write_zip(destination,archive.resolve())
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'build/public/hebrew-live-cli-0.1.0-alpha-source')
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    result=build(args.output,args.archive)
    print(json.dumps({'output':str(args.output.resolve()),'archive':str(args.archive.resolve()) if args.archive else None,
                      'files':len(result['files']),'bytes':sum(item['bytes'] for item in result['files'])},indent=2))


if __name__=='__main__':main()
