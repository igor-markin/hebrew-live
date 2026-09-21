"""Local conversation archive. Never accept a filesystem path from HTTP."""
import json
import re
from pathlib import Path

SESSION_ID = re.compile(r'\d{8}-\d{6}-[0-9a-f]{8}')
PART = re.compile(r'\d{3}-([a-z]{2,3}(?:-[a-z]{2,3})*)\.diagnostics\.jsonl')
HEADER = re.compile(r'^\[(\d+) ([\d.]+)[–-]([\d.]+)s\]$', re.M)

class SessionHistory:
    def __init__(self, root):
        self.root = Path(root)

    def folders(self):
        if not self.root.is_dir(): return {}
        return {p.name:p for p in self.root.iterdir()
                if SESSION_ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink()}

    def list(self):
        result=[]
        for name in sorted(self.folders(), reverse=True):
            label=f'{name[6:8]}.{name[4:6]}.{name[:4]} · {name[9:11]}:{name[11:13]}:{name[13:15]}'
            title=preview=''
            try:
                groups=self.read(name)['groups']
                pairs=[]
                for group in groups:
                    value=group.get('live',{}).get('current') or group.get('final') or {}
                    source=' '.join(str(value.get('source','')).split())
                    target=' '.join(str(value.get('translation','')).split())
                    if source or target:pairs.append((source,target))
                if pairs:
                    title=self.compact(pairs[0][1] or pairs[0][0],72)
                    preview=self.compact(next((target or source for source,target in pairs[1:] if source or target),pairs[0][0] or pairs[0][1]),110)
            except (OSError,ValueError,UnicodeError):
                pass
            result.append(dict(id=name,label=label,title=title or 'Разговор '+label,preview=preview))
        return result

    @staticmethod
    def compact(value, limit):
        value=' '.join(value.split())
        return value if len(value)<=limit else value[:limit-1].rstrip()+'…'

    def delete(self, identity, current=None):
        import shutil
        if not isinstance(identity,str) or not SESSION_ID.fullmatch(identity):
            raise ValueError('Invalid session ID')
        folder=self.folders().get(identity)
        if folder is None:raise FileNotFoundError(identity)
        if current and folder.resolve()==Path(current).resolve():
            raise PermissionError('Current session cannot be deleted')
        shutil.rmtree(folder)

    def read(self, identity):
        folder = self.folders().get(identity)
        if folder is None: raise FileNotFoundError(identity)
        groups = []
        warnings = []
        manifest={}
        try:
            manifest_path=folder/'session.json'
            if manifest_path.is_file() and not manifest_path.is_symlink():
                candidate=json.loads(manifest_path.read_text(encoding='utf-8'))
                if isinstance(candidate,dict):manifest=candidate
                else:warnings.append('Session metadata has an unsupported shape.')
        except (OSError,ValueError,UnicodeError):warnings.append('Session metadata is incomplete.')
        for path in sorted(folder.glob('*.diagnostics.jsonl')):
            match = PART.fullmatch(path.name)
            if not match or path.is_symlink(): continue
            direction = match[1]
            latest = {}
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    try: event = json.loads(line)
                    except (ValueError, UnicodeError):
                        warnings.append('В журнале есть неполная запись.'); continue
                    if not isinstance(event, dict) or event.get('event') != 'live_publication': continue
                    current = event.get('current')
                    if not isinstance(current,dict) or not all(isinstance(current.get(k),str) for k in ('source','translation')): continue
                    key = str(event.get('segment'))
                    latest[key] = dict(id=path.name+':'+key, direction=direction, complete=True,
                                       live={k:event[k] for k in ('current','history','stage','issue','reason') if k in event})
            if latest:
                groups.extend(latest.values())
            else:
                # Older phrase sessions have paired text records, not draft events.
                base = path.name.removesuffix('.diagnostics.jsonl')
                sources = self.records(folder/(base+'.transcript.txt'))
                targets = self.records(folder/(base+'.translation.txt'))
                for key, source in sources.items():
                    groups.append(dict(id=base+':'+key,direction=direction,complete=True,
                                       final=dict(source=source,translation=targets.get(key,''))))
        if manifest.get('partial'):warnings.append('Session capture or processing is incomplete.')
        audio_saved=manifest.get('audio_saved')
        if type(audio_saved) is not bool:audio_saved=any(folder.glob('*.audio.wav'))
        known=manifest.get('known_unprocessed',[]);discontinuities=manifest.get('capture_discontinuities',[])
        known=known if isinstance(known,list) else [];discontinuities=discontinuities if isinstance(discontinuities,list) else []
        parts=manifest.get('parts',{});parts=parts if isinstance(parts,dict) else {}
        details=[]
        for item in known:
            if not isinstance(item,dict):continue
            part=item.get('part');part_info=parts.get(str(part),{});part_info=part_info if isinstance(part_info,dict) else {}
            details.append(dict(part=part,direction=part_info.get('direction'),reason=item.get('reason','runtime_error'),
                                start=item.get('start'),end=item.get('end')))
        ranges=[f"part {item['part']} {item['direction'] or ''} · {item['start']:.3f}–{item['end']:.3f}s · {item['reason']}"
                for item in details if isinstance(item.get('start'),(int,float)) and isinstance(item.get('end'),(int,float))]
        partial_kind='mixed' if known and discontinuities else 'capture_unknown' if discontinuities else 'known_unprocessed' if known else None
        return dict(groups=groups,session=identity,session_path=str(folder.resolve()),warning=' '.join(dict.fromkeys(warnings)),
                    status='Сохранённая сессия',status_code='saved_session',finished=True,paused=True,
                    direction=groups[-1]['direction'] if groups else 'he-en',partial=bool(manifest.get('partial')),
                    partial_kind=partial_kind,partial_ranges=ranges,partial_details=details,
                    audio_saved=audio_saved,retry_supported=False)

    @staticmethod
    def records(path):
        if not path.is_file() or path.is_symlink(): return {}
        text = path.read_text(encoding='utf-8')
        matches = list(HEADER.finditer(text))
        return {m[1]:text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()
                for i,m in enumerate(matches)}
