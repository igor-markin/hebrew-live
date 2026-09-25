"""Scrollable terminal captions, independent of recognition status messages."""
import re
import os
import sys
import threading

# Abbreviations must not turn every period into a sentence break.
ABBREVIATIONS = {'г.', 'ул.', 'д.', 'кв.', 'стр.', 'им.', 'руб.', 'коп.', 'т.е.', 'т.д.', 'т.п.', 'др.', 'проф.', 'тов.', 'см.', 'Mr.', 'Mrs.', 'Dr.'}


def sentence_layout(value):
    """Return display text and source indices (for stable draft colouring)."""
    result = []; indices = []; cursor = 0
    for match in re.finditer(r'[.!?…]+[\"\'»”’)]*(?:\s+|$)', value):
        end = match.end()
        punctuation = match.group().rstrip()
        if punctuation.startswith('…') or punctuation.startswith('..'):
            continue  # A hesitation is not a completed sentence.
        before = value[:match.start()+1]
        token = before.split()[-1] if before.split() else ''
        abbrev = punctuation.startswith('.') and (token in ABBREVIATIONS or bool(re.fullmatch(r'[A-ZА-ЯЁ]\.', token)))
        # Compound Russian abbreviations with spaces: т. е., т. д., т. п.
        abbrev = abbrev or bool(re.search(r'\bт\.\s*[едп]\.$', before, re.I))
        abbrev = abbrev or (token == 'т.' and bool(re.match(r'\s*[едп]\.', value[match.start()+1:], re.I)))
        if abbrev:
            continue
        trimmed = end
        while trimmed > cursor and value[trimmed-1].isspace():
            trimmed -= 1
        result.append(value[cursor:trimmed]);indices.extend(range(cursor, trimmed))
        if end < len(value):
            result.append('\n\n');indices.extend([trimmed, trimmed])
        cursor = end
    result.append(value[cursor:]);indices.extend(range(cursor, len(value)))
    return ''.join(result), indices


def visual_line(line):
    """Reorder terminal cells with Unicode BiDi while carrying draft colours."""
    from bidi import algorithm as bidi
    from rich.text import Text
    # Isolates are unsupported by the Python BiDi V5 implementation. Model-supplied
    # directional controls are not content; determine direction from actual text.
    logical = line.copy()
    storage=bidi.get_empty_storage()
    base=bidi.get_base_level(logical.plain)
    storage['base_level']=base;storage['base_dir']=('L','R')[base]
    bidi.get_embedding_levels(logical.plain,storage)
    for i,char in enumerate(storage['chars']):
        char['draft']=any(span.start<=i<span.end and str(span.style)=='yellow' for span in logical.spans)
    storage['chars']=[ch for ch in storage['chars'] if ch['type'] not in ('LRI','RLI','FSI','PDI')]
    for step in (bidi.explicit_embed_and_overrides,bidi.resolve_weak_types,
                 bidi.resolve_neutral_types,bidi.resolve_implicit_levels,
                 bidi.reorder_resolved_levels,bidi.apply_mirroring):
        step(storage,False)
    text=Text(style='white')
    for char in storage['chars']:
        text.append(char['ch'],style='yellow' if char['draft'] else 'white')
    return text, bool(base)


class TranslationScreen:
    def __init__(self, native_bidi=None):
        self.native_bidi = os.environ.get('TERM_PROGRAM') == 'Apple_Terminal' if native_bidi is None else native_bidi
        self.status = 'Opening audio…'
        self.groups = {}
        self.history = []
        self.source_history = []
        self.draft_history = []
        self.sources = {}
        self.source_preview = ''
        self.source_sid = None
        self.preview = ''
        self.level = self.lag = 0.
        self.lock = threading.RLock()
        self.generation = 0
        self.contexts = {}
        self.top = None
        self.direction = 'he-en'
        self.topic = 'none'
        self._line_cache = (None, None)

    def clear(self, generation):
        self.generation = generation
        self.first_text_delay=None
        self.groups.clear()
        self.history.clear();self.source_history.clear();self.draft_history.clear();self.sources.clear()
        self.source_preview = '';self.source_sid = None
        self.preview = '';self.top = None

    def update(self, kind, sid, value):
        if kind == 'context':
            self.contexts[sid] = value
            return
        settings = self.contexts.get(sid)
        if settings and settings.generation < self.generation:
            if kind in ('final','group_final','live_publication'):self.contexts.pop(sid, None)
            return
        if kind == 'live_stream':
            group=self.groups.get(sid)
            if group and not group['complete']:
                group['stream']=dict(value)
                group['revision']=group.get('revision',0)+1
            return
        if kind == 'live_stream_clear':
            group=self.groups.get(sid)
            if group and group.pop('stream',None) is not None:
                group['revision']=group.get('revision',0)+1
            return
        if kind == 'live_publication':
            from copy import deepcopy
            revision=self.groups.get(sid,{}).get('revision',0)+1
            self.groups[sid]=dict(id=f'{self.generation}:{sid}', direction=settings.direction if settings else self.direction,
                                 part=settings.part if settings else 1,
                                 blocks=[], complete=value['stage']!='open', live=deepcopy(value),revision=revision)
            if value['stage']!='open':self.contexts.pop(sid,None)
            return
        if kind in ('block_source','block_translation','group_progress','group_final'):
            from .feed import changed
            group=self.groups.setdefault(sid,dict(id=f'{self.generation}:{sid}',direction=settings.direction if settings else self.direction,part=settings.part if settings else 1,blocks=[],complete=False,correction=None))
            if kind=='block_source':
                if not any(b['id']==value['id'] for b in group['blocks']):
                    group['blocks'].append(dict(id=value['id'],source=value['source'],translation='',complete=False))
            elif kind=='block_translation':
                block=next((b for b in group['blocks'] if b['id']==value['id']),None)
                if block is not None and value['translation'].startswith(block['translation']):
                    block.update(translation=value['translation'],complete=value['complete'],issue=value.get('issue'))
            elif kind=='group_progress':
                old=group.get('final_progress',{}).get('translation','')
                if not group['complete'] and value['translation'].startswith(old):
                    group['final_progress']=dict(value)
                    if not old and value.get('first_delay') is not None:self.first_text_delay=value['first_delay']
            else:
                group['complete']=True
                group['final']=dict(value)
                if value.get('first_delay') is not None:self.first_text_delay=value['first_delay']
                progress=group.get('final_progress')
                if progress and not value['translation'].startswith(progress['translation']):
                    group['final']['translation']=progress['translation']
                    group['final']['issue']=value['translation']
                source=' '.join(b['source'] for b in group['blocks'])
                target=' '.join(b['translation'] for b in group['blocks'])
                if changed(source,target,value['source'],value['translation']):group['correction']=dict(value)
                self.contexts.pop(sid,None)
            group['revision']=group.get('revision',0)+1
            return
        if kind == 'source':
            self.sources[sid] = value
            if self.source_sid != sid:
                self.preview = ''
                self.source_preview = value
            elif not self.preview:
                self.source_preview = value
            # Retain the last matched pair while a new revision is translating.
            self.source_sid = sid
        elif kind == 'final':
            self.finalize(value, self.sources.pop(sid, ''))
            self.source_preview = '';self.source_sid = None
            self.contexts.pop(sid, None)
        elif kind == 'preview':
            self.source_preview = self.sources.get(sid,self.source_preview)
            self.preview = value

    def finalize(self, text, source=''):
        with self.lock:
            if text or source:
                self.draft_history.append(self.preview.strip())
                self.history.append(text.strip())
                self.source_history.append(source.strip())
            self.preview = ''

    def caption(self):
        from rich.text import Text
        with self.lock:
            confirmed = ' '.join(self.history)
            draft = self.preview.strip()
            value = confirmed + (' ' if confirmed and draft else '') + draft
            displayed, mapping = sentence_layout(value)
            text = Text(displayed, style='white')
            if draft:
                start = len(value)-len(draft)
                first = next((i for i, source in enumerate(mapping) if source >= start), len(displayed))
                text.stylize('yellow', first, len(displayed))
            if not value:
                text.append('Waiting for speech…', style='dim')
            return text

    @property
    def has_sources(self):
        return bool(self.source_preview or any(self.source_history))

    def plain(self):
        if self.groups:
            return '\n\n' .join(b['source']+'\n'+b['translation'] for g in self.groups.values() for b in g['blocks'])
        if not self.has_sources:
            return self.caption().plain
        blocks=[]
        for i,target in enumerate(self.history):
            source=self.source_history[i] if i<len(self.source_history) else ''
            draft=self.draft_history[i] if i<len(self.draft_history) else ''
            blocks.append(('Оригинал: '+source+'\n\nДинамический перевод: '+draft+'\n\nПолный перевод: ' if source else '')+target.strip())
        if self.source_preview or self.preview:
            blocks.append('Оригинал (черновик): '+self.source_preview+'\nПеревод: '+self.preview)
        return ('\n\n'+'─'*48+'\n\n').join(blocks)

    def paired_lines(self, width):
        from rich.console import Console
        from rich.text import Text
        cell=max(1,min(width,88))
        console=Console(width=max(1,cell))
        def wrapped(value,style):
            logical=Text(value.strip(),style=style)
            output=[]
            for line in logical.wrap(console,max(1,cell)):
                if style=='yellow':line.stylize('yellow')
                from rich.cells import cell_len
                from bidi.algorithm import get_base_level
                rtl=bool(get_base_level(value))
                visual=line.copy() if self.native_bidi else visual_line(line)[0]
                if rtl:
                    visual=Text(' '*max(0,cell-cell_len(visual.plain)))+visual
                if style=='dim':visual.stylize('dim')
                output.append(visual)
            return output
        pairs=[(self.source_history[i] if i<len(self.source_history) else '',v,False,self.draft_history[i] if i<len(self.draft_history) else '')
               for i,v in enumerate(self.history)]
        if self.source_preview or self.preview:
            pairs.append((self.source_preview,self.preview,True,''))
        rows=[]
        if self.groups:
            for group in self.groups.values():
                if group.get('live'):
                    v=group['live'];pair=v['current']
                    rows.extend(wrapped(pair['source'],'dim'));rows.append(Text())
                    rows.extend(wrapped(pair['translation'],'white'));rows.append(Text())
                    if v.get('issue'):rows.extend(wrapped(v['issue'],'yellow'))
                for block in group['blocks']:
                    rows.extend(wrapped(block['source'],'dim'));rows.append(Text())
                    rows.extend(wrapped(block['translation'],'white'));rows.append(Text())
                final=group.get('final') or group.get('final_progress')
                if final and not final.get('sequential'):
                    rows.extend(wrapped(final['source'],'dim'));rows.append(Text())
                    rows.extend(wrapped(final['translation'],'white'));rows.append(Text())
                if group['complete']:
                    rows.append(Text('─'*cell,style='dim'));rows.append(Text())
            return rows
        for source,target,draft,saved_draft in pairs:
            if not source and not draft:
                rows.extend(wrapped(target,'white'))
                rows.append(Text())
                continue
            a=wrapped(source,'dim');b=wrapped(target,'yellow' if draft else 'white')
            rows.extend(a)
            rows.append(Text())
            if not draft:
                rows.extend(wrapped(saved_draft,'yellow'))
                rows.append(Text())
            rows.extend(b)
            rows.append(Text())
            rows.append(Text('─'*cell,style='dim'))
            rows.append(Text())
        return rows or [Text('Waiting for speech…',style='dim')]

    def lines(self, width):
        from rich.console import Console
        key = (repr(self.groups), tuple(self.history), tuple(self.source_history), tuple(self.draft_history), self.source_preview, self.preview, width)
        if self._line_cache[0] != key:
            lines=self.paired_lines(width) if self.groups or self.has_sources else self.caption().wrap(Console(width=max(1,width)), max(1,width))
            self._line_cache = (key, lines)
        return self._line_cache[1]

    def viewport(self, width, height):
        lines = self.lines(width)
        last = max(0, len(lines)-height)
        top = last if self.top is None else min(self.top, last)
        return lines[top:top+height], top, len(lines)

    def scroll(self, amount, width, height):
        _, top, total = self.viewport(width, height)
        self.top = max(0, min(max(0,total-height), top+amount))


def style_runs(line):
    """Non-overlapping final styles; later spans override earlier spans."""
    if not line.plain:return []
    styles=[str(line.style) or 'white']*len(line.plain)
    for span in line.spans:
        styles[span.start:span.end]=[str(span.style)]*(span.end-span.start)
    runs=[];start=0
    for i in range(1,len(styles)+1):
        if i==len(styles) or styles[i]!=styles[start]:
            runs.append((start,i,styles[start]));start=i
    return runs


def disable_status_key():
    # macOS cbreak otherwise consumes Ctrl+T as SIGINFO instead of a hotkey.
    import termios
    if hasattr(termios, 'VSTATUS'):
        settings=termios.tcgetattr(sys.stdin.fileno())
        settings[6][termios.VSTATUS]=b'\x00'
        termios.tcsetattr(sys.stdin.fileno(),termios.TCSANOW,settings)


class TerminalKeys:
    """Unbuffered fallback input for redirected output; one read drains a burst."""
    def __enter__(self):
        self.saved = None
        if sys.stdin.isatty():
            import termios, tty
            self.saved = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            disable_status_key()
        return self

    def read(self):
        import os, select
        if self.saved and select.select([sys.stdin.fileno()], [], [], 0)[0]:
            return os.read(sys.stdin.fileno(), 64).decode('utf8', errors='ignore')
        return ''

    def __exit__(self, *args):
        if self.saved:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.saved)


class Terminal:
    def __enter__(self):
        import curses
        self.c = curses
        self.window = curses.initscr()
        try:
            curses.noecho();curses.cbreak();self.window.keypad(True);self.window.nodelay(True)
            disable_status_key()
            try:curses.curs_set(0)
            except curses.error:pass
            self.color = curses.has_colors()
            if self.color:
                curses.start_color();curses.use_default_colors()
                curses.init_pair(1,curses.COLOR_WHITE,-1);curses.init_pair(2,curses.COLOR_YELLOW,-1)
                # A_DIM made Hebrew almost invisible on the user's dark theme.
                curses.init_pair(3,248 if curses.COLORS>=256 else curses.COLOR_CYAN,-1)
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            return self
        except BaseException:
            self.__exit__();raise

    def __exit__(self, *args):
        self.window.keypad(False);self.c.nocbreak();self.c.echo();self.c.endwin()

    def keys(self, screen):
        c = self.c
        h,w = self.window.getmaxyx();height=max(1,h-5);width=max(1,w-1)
        actions = []
        for _ in range(64):
            try:key=self.window.get_wch()
            except c.error:break
            if key == c.KEY_UP:screen.scroll(-1,width,height)
            elif key == c.KEY_DOWN:screen.scroll(1,width,height)
            elif key == c.KEY_PPAGE:screen.scroll(-height,width,height)
            elif key == c.KEY_NPAGE:screen.scroll(height,width,height)
            elif key == c.KEY_END:screen.top=None
            elif key == c.KEY_MOUSE:
                try:
                    state=c.getmouse()[4]
                    if state & c.BUTTON4_PRESSED:screen.scroll(-3,width,height)
                    elif state & getattr(c,'BUTTON5_PRESSED',0):screen.scroll(3,width,height)
                except c.error:pass
            elif isinstance(key,str):actions.append(key)
        return actions

    def draw(self, screen, control, stopping):
        c=self.c;h,w=self.window.getmaxyx();width=max(1,w-1);height=max(1,h-5)
        self.window.erase()
        status = stopping or ('Paused' if control.paused else screen.status)
        warning = ' · RU ASR experimental' if control.settings.direction == 'ru-he' else ''
        header=f'{control.settings.direction.upper()} · {status} · topic: {control.settings.topic}{warning}'
        self.put(0,0,header,c.A_BOLD)
        self.put(1,0,f'Mic {"▮"*min(10,int(screen.level*200))} · Delay {screen.lag:.1f}s')
        self.put(2,0,'='*width)
        lines, top, total = screen.viewport(width,height)
        for row,line in enumerate(lines,3):
            from rich.cells import cell_len
            if screen.has_sources:
                rtl=False  # Each row has already undergone BiDi independently.
            else:
                line,rtl=(line,False) if screen.native_bidi else visual_line(line)
            plain=line.plain
            left=max(0,width-cell_len(plain)) if rtl else 0
            # Emit each uniform style run once. Overpainting full lines and spans
            # independently causes native terminal BiDi to reorder the same text twice.
            for begin,finish,style in style_runs(line):
                attr=(c.color_pair(3) if self.color else 0) if style=='dim' else (
                    (c.color_pair(2) if self.color else c.A_BOLD) if style=='yellow'
                    else (c.color_pair(1) if self.color else 0))
                self.put(row,left+cell_len(plain[:begin]),plain[begin:finish],attr)
        if h>=5:
            self.put(h-2,0,f'{top+1}–{min(total,top+height)}/{total} · End: latest')
            self.put(h-1,0,'Space: pause · ^L: clear · ^T: direction · Q: stop')
        # Native BiDi paints outside curses' logical cell bookkeeping. A diff
        # against that bookkeeping leaves ghosts and shifted punctuation.
        # In Apple Terminal, redraw only when the visible body/geometry changes;
        # meter/status-only updates keep the normal lightweight refresh.
        # Only native RTL content/layout needs a physical reset; Russian token
        # growth must not clear the whole terminal at every update.
        import unicodedata
        rtl_rows=tuple((i,line.plain) for i,line in enumerate(lines)
                       if any(unicodedata.bidirectional(ch) in ('R','AL') for ch in line.plain))
        body=(h,w,rtl_rows)
        if screen.native_bidi and body!=getattr(self,'_last_body',None):
            self.window.clearok(True)
        self._last_body=body
        self.window.noutrefresh();c.doupdate()

    def put(self,row,col,text,style=0):
        h,w=self.window.getmaxyx()
        if row>=h or col>=w-1:return
        from rich.cells import set_cell_size
        try:self.window.addstr(row,col,set_cell_size(text,max(0,w-col-1)).rstrip(),style)
        except self.c.error:pass
