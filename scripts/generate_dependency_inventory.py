#!/usr/bin/env python3
"""Normalize the complete Python and Node lock graphs for review."""
from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs/DEPENDENCY_INVENTORY.json'


def generate()->dict:
    pyproject=tomllib.loads((ROOT/'pyproject.toml').read_text())
    direct_python={item.split('[',1)[0].split('=',1)[0].split('>',1)[0].split('<',1)[0].strip().lower()
                   for item in pyproject['project']['dependencies']}
    uv=tomllib.loads((ROOT/'uv.lock').read_text())
    python=[]
    for package in uv['package']:
        artifacts=[]
        if package.get('sdist'):artifacts.append(package['sdist'])
        artifacts.extend(package.get('wheels',[]))
        python.append({'name':package['name'],'version':package.get('version'),'direct':package['name'].lower() in direct_python,
                       'source':package.get('source'),'artifacts':[{key:item[key] for key in ('url','hash','size') if key in item} for item in artifacts]})
    lock=json.loads((ROOT/'experiments/publication-ui-preview/package-lock.json').read_text())
    root=lock['packages'][''];direct_node=set(root.get('dependencies',{}))|set(root.get('devDependencies',{}))
    node=[]
    for location,value in lock['packages'].items():
        if not location:continue
        marker='node_modules/';name=location.rsplit(marker,1)[-1]
        node.append({'name':name,'version':value.get('version'),'direct':name in direct_node,
                     'development':name in root.get('devDependencies',{}),'resolved':value.get('resolved'),
                     'integrity':value.get('integrity'),'license':value.get('license')})
    return {'schema_version':1,'generated_from':['uv.lock','experiments/publication-ui-preview/package-lock.json'],
            'notice':'Inventory metadata is not a legal compatibility conclusion; package license files control.',
            'python':sorted(python,key=lambda item:(item['name'],item.get('version') or '')),
            'node':sorted(node,key=lambda item:(item['name'],item.get('version') or ''))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    rendered=json.dumps(generate(),indent=2,sort_keys=True)+'\n'
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text()!=rendered:raise SystemExit('dependency inventory is stale')
        print('dependency inventory is current')
    else:
        OUTPUT.write_text(rendered);print(OUTPUT)


if __name__=='__main__':main()
