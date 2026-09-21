#!/usr/bin/env python3
"""Reject private/internal material from an allowlisted public source tree."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ALLOWED_ROOTS={
    '.github','.gitignore','CHANGELOG.md','CONTRIBUTING.md','PRIVACY.md','PUBLIC-MANIFEST.json',
    'README.md','README.ru.md','LICENSE','SECURITY.md','SUPPORT.md','docs','experiments',
    'pyproject.toml','run.sh','scripts','src','tests','uv.lock',
}
FORBIDDEN_PARTS={
    '.git','.venv','.cache','.local-settings','artifacts','build','dist','exports',
    'logs','models','node_modules','__pycache__',
}
FORBIDDEN_NAMES={'src.zip','cases.json','model_smoke.py'}
TEXT_SUFFIXES={'.css','.html','.ini','.js','.json','.md','.py','.sh','.toml','.ts','.tsx','.txt','.yml','.yaml'}
PRIVATE_PATTERNS={
    'absolute macOS user path':re.compile('/'+'Users/'),
    'private route placeholder':re.compile('PRIVATE'+'_TOKEN'),
    'internal research archive':re.compile(r'(?i)hebrew-live-'+r'(?:target-commit|gpt6|identity|context-ab|right-unit)'),
    'downloads folder reference':re.compile('/'+'Downloads/'),
}
BUNDLED_PACKAGES=(
    '@fontsource/noto-sans@5.3.0','@fontsource/noto-sans-hebrew@5.3.0',
    '@heroui/react@3.2.4','@heroui/styles@3.2.4','clsx@2.1.1',
    'react@19.3.0','react-aria@3.52.1','react-aria-components@1.21.1',
    'react-dom@19.3.0','react-stately@3.50.0','scheduler@0.28.0',
    'tailwind-variants@3.3.1',
)


def check(root:Path)->dict:
    root=root.resolve()
    errors=[];files=[];total=0
    if not root.is_dir():raise ValueError(f'not a directory: {root}')
    unexpected=sorted(item.name for item in root.iterdir() if item.name not in ALLOWED_ROOTS)
    if unexpected:errors.append('unexpected root entries: '+', '.join(unexpected))
    license_path=root/'LICENSE'
    if not license_path.is_file():errors.append('missing project Apache-2.0 LICENSE')
    elif 'Apache License\n                           Version 2.0, January 2004' not in license_path.read_text():
        errors.append('project LICENSE is not the canonical Apache License 2.0 text')
    for path in sorted(item for item in root.rglob('*') if item.is_file() or item.is_symlink()):
        relative=path.relative_to(root);lower={part.lower() for part in relative.parts}
        if path.is_symlink():errors.append(f'symlink is not allowed: {relative}');continue
        if lower&FORBIDDEN_PARTS:errors.append(f'forbidden path component: {relative}')
        if path.name in FORBIDDEN_NAMES:errors.append(f'forbidden file: {relative}')
        size=path.stat().st_size;total+=size;files.append(str(relative))
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:text=path.read_text()
            except UnicodeDecodeError:
                errors.append(f'expected UTF-8 text: {relative}');continue
            for label,pattern in PRIVATE_PATTERNS.items():
                if pattern.search(text):errors.append(f'{label}: {relative}')
    required=[
        'README.md','README.ru.md','LICENSE','SECURITY.md','PRIVACY.md','CONTRIBUTING.md','run.sh',
        'docs/DOCKER.md','docs/THIRD_PARTY.md','docs/RELEASE_READINESS.md',
        'src/hebrew_live/web/live.html','src/hebrew_live/web/licenses/THIRD-PARTY-NOTICES.txt',
        'tests/fixtures/live_states.json',
        'experiments/publication-ui-preview/src/data/public-cases.json',
    ]
    for name in required:
        if not (root/name).is_file():errors.append(f'missing required public file: {name}')
    launcher=root/'run.sh'
    if launcher.is_file() and not launcher.stat().st_mode&0o111:
        errors.append('run.sh is not executable')
    notice=root/'src/hebrew_live/web/licenses/THIRD-PARTY-NOTICES.txt'
    if notice.is_file():
        text=notice.read_text()
        missing=[name for name in BUNDLED_PACKAGES if name not in text]
        if missing:errors.append('bundled third-party notice is incomplete: '+', '.join(missing))
        if 'MISSING FROM INSTALLED PACKAGE' in text:errors.append('bundled third-party notice lacks license evidence')
        if text.count('Locked source:')!=len(BUNDLED_PACKAGES) or text.count('Locked integrity:')!=len(BUNDLED_PACKAGES):
            errors.append('bundled third-party notice lacks lock provenance')
    for name in ('tests/fixtures/live_states.json','experiments/publication-ui-preview/src/data/public-cases.json'):
        path=root/name
        if path.is_file():
            value=json.loads(path.read_text())
            provenance=value.get('provenance','')
            if 'ynthetic' not in provenance:errors.append(f'fixture lacks synthetic provenance: {name}')
    if errors:raise ValueError('\n'.join(errors))
    return {'files':len(files),'bytes':total,'root_entries':sorted(item.name for item in root.iterdir())}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    args=parser.parse_args()
    print(json.dumps(check(args.root),indent=2,sort_keys=True))


if __name__=='__main__':main()
