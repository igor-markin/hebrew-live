"""Causal text assembly: revisable ASR tail, separate committed translation boundary."""
from dataclasses import dataclass,field
import re


def lexical(text):
    return ''.join(re.findall(r'\w+',text.casefold()))

# Generic grammatical blockers, not a domain glossary or semantic classifier.
OPEN={'אבל','אלא','אם','כי','כאשר','ליד','אצל','של','את','עם','בלי','עד','לפני','אחרי','עדיין',
      'איך','כדי','לגבי','עבור','ו','על','אל','מן','בין','בתוך','מתוך','בגלל','למרות','גם','רק','ש','ה',
      'но','если','потому','чтобы','возле','около','без','для','перед','после','или','а','что','когда','ещё',
      'в','во','на','с','со','к','ко','от','до','из','у','о','об','про','за','под','над','при','между','через','рядом','только'}
# Dependent starts are not good right edges for a punctuation-free cut. This is
# a conservative function-word heuristic, not a dictionary of expressions.
DEPENDENT_RIGHT={'של','את','ש','ה','גם','רק','же','бы','ли','только'}
# Unlike an ordinary noun (which may head a longer noun phrase), these pronouns
# can already complete a preceding preposition/direct-object marker.
CLOSED_PRONOUN={'זה','זו','זאת','אותו','אותה','אותם','אותן',
                'это','этого','этому','этим','этом','меня','тебя','него','неё','нее','нас','вас','них','ним','ней'}
COMPLEMENT_HEAD={'את','עם','בלי','על','אל','ליד','אצל','של','לגבי','עבור','לפני','אחרי',
                 'в','во','на','с','со','к','ко','от','до','из','у','о','об','про','за','под','над','для','без','перед','после'}
SHORT={'כן','לא','תודה','בסדר','שלום','да','нет','спасибо','хорошо','здравствуйте'}
ABBREVIATIONS={'dr','mr','mrs','prof','г','ул','д','стр','т','тд','тп'}


def ending(words):
    if not words:return False
    last=lexical(words[-1]['word'])
    return last not in OPEN and not (last in {'לא','не'} and len(words)>1)


def punctuation(words,index):
    value=words[index]['word'].strip().rstrip('\"\'»”׳״')
    if lexical(value) in ABBREVIATIONS:return False
    if re.search(r'\d\.$',value) and index+1<len(words) and re.match(r'\s*\d',words[index+1]['word']):return False
    # Ellipsis is explicitly NOT proof of a finished sentence.
    return bool(re.search(r'(?<!\.)[.!?;]$',value)) and not value.endswith('...')


def boundary_mark(words,index):
    value=words[index]['word'].strip().rstrip('\"\'»”׳״')
    if punctuation(words,index):return value[-1]
    return value[-1:] if value.endswith((',',':')) else ''


def align_words(old,new):
    """Monotone one-to-one matches; maximize count, then minimize time drift.

    Insertions/deletions cost a skipped match. Equal words cannot cross or reuse
    an occurrence. Timestamp distance resolves competing repeated occurrences.
    """
    m,n=len(old),len(new)
    old_text=[lexical(w['word']) for w in old]
    new_text=[lexical(w['word']) for w in new]
    scores=[[(0,0.) for _ in range(n+1)] for _ in range(m+1)]
    moves=[[0]*(n+1) for _ in range(m+1)]
    for i,p in enumerate(old,1):
        for j,w in enumerate(new,1):
            best,move=scores[i-1][j],1
            if scores[i][j-1]>best:best,move=scores[i][j-1],2
            ds,de=abs(p['start']-w['start']),abs(p['end']-w['end'])
            if old_text[i-1]==new_text[j-1] and new_text[j-1] and ds<.5 and de<.5:
                count,cost=scores[i-1][j-1];candidate=(count+1,cost-ds-de)
                if candidate>=best:best,move=candidate,3
            scores[i][j],moves[i][j]=best,move
    matches={};i,j=m,n
    while i and j:
        move=moves[i][j]
        if move==3:matches[j-1]=i-1;i-=1;j-=1
        elif move==1:i-=1
        else:j-=1
    return matches


def edge_allowed(words,cut):
    """Mandatory vetoes apply even when the deadline relaxes right context."""
    if not ending(words[:cut]):return False
    if cut<len(words) and lexical(words[cut]['word']) in DEPENDENT_RIGHT:return False
    closed=(cut>=2 and lexical(words[cut-1]['word']) in CLOSED_PRONOUN
            and lexical(words[cut-2]['word']) in COMPLEMENT_HEAD)
    if not closed and any(lexical(w['word']) in OPEN|{'לא','не'}
                          for w in words[max(0,cut-2):cut]):return False
    return True


def context_sufficient(words,cut):
    tail=words[cut:cut+2]
    return len(tail)==2 and all(w.get('stable') for w in tail)


def safe_edge(words,cut,lookahead=False):
    return edge_allowed(words,cut) and (not lookahead or context_sufficient(words,cut))


def hard_cut(words,limit,pause):
    """Score legal edges only. No score can override a grammatical veto.

    Two words are the minimum non-sentence unit. Scores are experimental,
    not a syntactic probability or a guarantee of useful translation.
    """
    candidates=[]
    for cut in range(2,limit+1):
        if not edge_allowed(words,cut):continue
        left=words[cut-1];tail=words[cut:]
        gap=tail[0]['start']-left['end'] if tail else 0.
        mark=boundary_mark(words,cut-1)
        score=min(cut,6)*.3
        if left.get('boundary_stable'):score+=2
        elif mark:score-=1  # New punctuation alone is weak evidence.
        score+=min(max(gap,0)/pause,2)
        if gap<.12:score-=.4
        if len(tail)==1:score-=.8
        candidates.append((score,cut))
    # Relaxation must be monotone: never discard an edge already admitted
    # by the strict policy merely because its heuristic score is low.
    eligible=[c for c in candidates if c[0]>=.4 or context_sufficient(words,c[1])]
    return max(eligible)[1] if eligible else None


@dataclass
class Unit:
    source: str
    words: list
    reason: str
    incomplete: bool=False
    correction_of: tuple=()
    unconfirmed: bool=False
    @property
    def start(self):return self.words[0]['start']
    @property
    def end(self):return self.words[-1]['end']
    @property
    def fragments(self):return sorted({w['fragment'] for w in self.words})


@dataclass
class PhraseBuffer:
    pending: list=field(default_factory=list)
    watermark: float=-1.
    committed: list=field(default_factory=list)
    edge: float=.25

    def update(self, words, window_start, now, fragment, final=False, status=None):
        """Times are absolute accepted-audio seconds within one direction period."""
        status=status or ('accepted' if words else 'empty')
        if status not in ('accepted','empty','rejected'):raise ValueError('Invalid ASR status')
        # Absence/rejection does not confirm or erase the preceding hypothesis.
        if status!='accepted':return
        incoming=[dict(w,start=w['start']+window_start,end=w['end']+window_start,fragment=fragment) for w in words]
        old=self.pending
        # Match the already published tail near its timestamp, allowing ASR drift.
        cut=self.watermark
        for previous in reversed(self.committed[-5:]):
            matches=[w for w in incoming if lexical(w['word'])==lexical(previous['word']) and abs(w['end']-previous['end'])<.45]
            if matches:
                match=min(matches,key=lambda w:abs(w['end']-previous['end']))
                if previous is self.committed[-1]:cut=max(cut,match['end'])
                break
        fresh=[w for w in incoming if (w['start']+w['end'])/2>cut+.001]
        # Retained words outside this window already occupy their own position;
        # they must not also confirm a new repeated word at the window's start.
        revisable=[w for w in old if w['end']>window_start+.001]
        matches=align_words(revisable,fresh)
        for i,w in enumerate(fresh):
            prior_index=matches.get(i)
            prior=revisable[prior_index] if prior_index is not None else None
            w['word_stable']=bool(final or (prior is not None and w['end']<=now-self.edge))
            w['stable']=w['word_stable']  # Existing consumers use this eligibility flag.
            mark=boundary_mark(fresh,i)
            w['boundary_stable']=bool(w['word_stable'] and mark and prior is not None
                                      and mark==boundary_mark(revisable,prior_index))
            next_prior=matches.get(i+1)
            w['previous_gap']=(revisable[next_prior]['start']-prior['end']
                               if prior is not None and next_prior==prior_index+1 else None)
        # An overlapping ASR window revises only its portion of the uncommitted tail.
        retained=[w for w in old if w['end']<=window_start+.001]
        # This audio has left the overlapping ASR window: another hypothesis
        # can no longer confirm it. Keep the last available words, but release
        # their hold on newer speech and explicitly mark this fallback.
        for w in retained:
            if not w.get('stable'):
                w['stable']=True
                w['unconfirmed']=True
        if incoming:self.pending=retained+fresh
        self.pending.sort(key=lambda w:(w['start'],w['end']))

    def take(self, now, quiet=0., max_wait=4., pause=.6, final=False, force=None, *, deadline_policy=None):
        if force and force not in {"eof","pause","direction","models","clear","resume","control_flush","stop"}:
            raise ValueError("force is reserved for control boundaries")
        if deadline_policy not in (None,"natural","soft","hard"):raise ValueError("Invalid deadline policy")
        units=[]
        while self.pending:
            stable=[]
            for w in self.pending:
                if not force and (not w.get('stable') or (deadline_policy=='hard' and not w.get('word_stable'))):break
                stable.append(w)
            if not stable:break
            # A standalone negative is an answer only when there is an actual
            # pause, not a provisional ASR full stop or an expired deadline.
            lone_negative=len(stable)==1 and lexical(stable[0]['word']) in {'לא','не','нет'}
            negative_answer=lone_negative and len(self.pending)==1 and final and quiet>=pause
            # A final acoustic window confirms its words, not its punctuation.
            # Only the caller's real trailing silence can close that window as
            # speech. Internal timestamp gaps provide a separate pause signal.
            def paused(cut):
                if cut<len(self.pending):
                    previous_gap=self.pending[cut-1].get('previous_gap')
                    return (previous_gap is not None and previous_gap>=pause
                            and self.pending[cut].get('stable',False)
                            and self.pending[cut]['start']-self.pending[cut-1]['end']>=pause)
                return final and quiet>=pause
            def confirmed(cut):
                return stable[cut-1].get('boundary_stable',False) or paused(cut)
            def safe(cut):
                return ending(self.pending[:cut]) and (deadline_policy not in ("soft","hard") or edge_allowed(self.pending,cut)) and not (cut==1 and lexical(stable[0]['word']) in {'לא','не','нет'} and not negative_answer)
            deadline=(now-self.pending[0]['start']>=max_wait if deadline_policy is None else deadline_policy in ('soft','hard'))
            sentences=[i+1 for i in range(len(stable)) if punctuation(stable,i) and confirmed(i+1) and safe(i+1)]
            boundary=(sentences[-1] if deadline else sentences[0]) if sentences else None
            reason='sentence';incomplete=False
            if not boundary and deadline:
                commas=[i+1 for i in range(len(stable)) if boundary_mark(stable,i) in (',',':') and confirmed(i+1) and safe(i+1)]
                if commas:boundary=commas[-1];reason='clause_boundary'
            if not boundary:
                pauses=[i for i in range(1,len(stable)+1) if paused(i) and safe(i)]
                if pauses:
                    boundary=pauses[-1] if deadline else pauses[0];reason='clause_pause'
                    if boundary==1 and lexical(stable[0]['word']) in SHORT:reason='short_reply'
            if not boundary and deadline_policy=='hard' and not lone_negative:
                boundary=hard_cut(self.pending,len(stable),pause)
                reason='hard_deadline';incomplete=True
            if not boundary and deadline and deadline_policy!='hard' and not lone_negative:
                # Never publish the whole stable prefix merely because it aged.
                # Hold at least two words to inspect the other side of the cut.
                boundary=next((i for i in range(len(stable)-2,1,-1)
                               if safe_edge(self.pending,i,lookahead=True)),None)
                reason='deadline';incomplete=True
            if force:
                boundary=len(self.pending);stable=self.pending;reason=force
                incomplete=not (punctuation(stable,len(stable)-1) and ending(stable))
            if not boundary:break
            chosen=stable[:boundary]
            units.append(Unit(' '.join(w['word'].strip() for w in chosen).strip(),chosen,reason,incomplete,unconfirmed=any(w.get('unconfirmed') or not w.get('stable') for w in chosen)))
            self.watermark=max(self.watermark,chosen[-1]['end'])
            self.committed=(self.committed+chosen)[-64:]
            self.pending=self.pending[boundary:]
            if deadline_policy in ("soft","hard"):break
        return units
