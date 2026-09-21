#!/usr/bin/env python3
"""Probe only installed package metadata and browser assets; model deps are optional."""
from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

import hebrew_live
from hebrew_live.browser_ui import BrowserUI

BUNDLED_PACKAGES=(
    '@fontsource/noto-sans@5.3.0','@fontsource/noto-sans-hebrew@5.3.0',
    '@heroui/react@3.2.4','@heroui/styles@3.2.4','clsx@2.1.1',
    'react@19.3.0','react-aria@3.52.1','react-aria-components@1.21.1',
    'react-dom@19.3.0','react-stately@3.50.0','scheduler@0.28.0',
    'tailwind-variants@3.3.1',
)


def fetch(url):
    with urllib.request.urlopen(url,timeout=5) as response:
        data=response.read();kind=response.headers.get_content_type()
    if not data:raise RuntimeError(f'empty installed asset: {url}')
    return data,kind


def main():
    prefix=Path(sys.prefix).resolve();package=Path(hebrew_live.__file__).resolve()
    if not package.is_relative_to(prefix):
        raise RuntimeError(f'probe imported working source instead of the isolated environment: {package}')
    metadata=importlib.metadata.metadata('hebrew-live-cli')
    if metadata.get('License-Expression')!='Apache-2.0':raise RuntimeError('missing Apache-2.0 package metadata')
    license_files=[str(path) for path in importlib.metadata.files('hebrew-live-cli') or () if str(path).endswith('dist-info/licenses/LICENSE')]
    if len(license_files)!=1:raise RuntimeError('canonical project license is missing from the wheel')
    with BrowserUI(open_browser=False,live=True) as ui:
        base=ui.url+'live/'
        html,kind=fetch(base)
        if kind!='text/html':raise RuntimeError('installed live entrypoint has the wrong content type')
        links=re.findall(rb'(?:src|href)="\./([^"]+)"',html)
        urls=[urllib.parse.urljoin(base,item.decode()) for item in links]
        if not any(url.endswith('.js') for url in urls) or not any(url.endswith('.css') for url in urls):
            raise RuntimeError('installed live entrypoint does not reference JS and CSS')
        css=[]
        for url in urls:
            data,asset_kind=fetch(url)
            if url.endswith('.js') and asset_kind not in ('text/javascript','application/javascript'):
                raise RuntimeError('installed JavaScript has the wrong content type')
            if url.endswith('.css'):
                if asset_kind!='text/css':raise RuntimeError('installed CSS has the wrong content type')
                css.append((url,data))
        font_urls=[]
        for css_url,data in css:
            for name in re.findall(rb'url\(([^)]+\.(?:woff2?|WOFF2?))\)',data):
                font_urls.append(urllib.parse.urljoin(css_url,name.decode().strip('"\'')))
        if not font_urls:raise RuntimeError('installed CSS does not reference packaged fonts')
        for url in font_urls:fetch(url)
        notice,_=fetch(urllib.parse.urljoin(base,'licenses/THIRD-PARTY-NOTICES.txt'))
        notice_text=notice.decode()
        missing=[name for name in BUNDLED_PACKAGES if name not in notice_text]
        if missing:raise RuntimeError(f'bundled third-party notice is incomplete: {missing}')
        if notice_text.count('Locked source:')!=len(BUNDLED_PACKAGES) or notice_text.count('Locked integrity:')!=len(BUNDLED_PACKAGES):
            raise RuntimeError('bundled third-party notice lacks lock provenance')
        for name in ('Noto-Sans-OFL.txt','Noto-Sans-Hebrew-OFL.txt'):
            fetch(urllib.parse.urljoin(base,f'licenses/{name}'))
        state,_=fetch(ui.url+'state')
        if not isinstance(json.loads(state),dict):raise RuntimeError('installed BrowserUI state endpoint is invalid')
    print(json.dumps({'package':str(package),'license':'Apache-2.0','html':True,'javascript':True,
                      'css':True,'fonts':len(font_urls),'bundled_notices':len(BUNDLED_PACKAGES),
                      'state_endpoint':True},indent=2))


if __name__=='__main__':main()
