export type Mode = 'single' | 'versions';
export interface Snapshot {
  eventId: string; op: number; fragment: number; revision: number; status: string;
  source: string; translation: string; closed: boolean; closureReason: string | null; callIndex: number;
}
export interface Example { id: string; title: string; early: Snapshot; terminal: Snapshot }
export interface Entry { snapshot: Snapshot; terminal: boolean }
export interface View { entries: Entry[]; history: Snapshot | null; unavailable: boolean; replaced: boolean }
const tokens = (s: string) => s.match(/[\p{L}\p{N}_]+(?:[-’'][\p{L}\p{N}_]+)*|[^\p{L}\p{N}_\s]/gu) ?? [];
export function compatible(early: string, terminal: string): boolean {
  const left = tokens(early), right = tokens(terminal);
  return terminal.startsWith(early) && left.every((word, i) => right[i] === word);
}
export function publication(example: Example, completed: boolean, mode: Mode): View {
  const { early, terminal } = example;
  const original: Entry = { snapshot: early, terminal: false };
  if (!completed) return { entries: [original], history: null, unavailable: false, replaced: false };
  // Validate before constructing any visible update: a rejected/empty final is not confirmation.
  if (terminal.status !== 'accepted' || !terminal.closed || !terminal.source.trim() || !terminal.translation.trim()) {
    return { entries: [original], history: null, unavailable: true, replaced: false };
  }
  const conflict = !compatible(early.translation, terminal.translation);
  const changed = early.source !== terminal.source || early.translation !== terminal.translation;
  const final: Entry = { snapshot: terminal, terminal: true };
  if (mode === 'versions' && conflict) return { entries: [original, final], history: null, unavailable: false, replaced: false };
  return { entries: [final], history: changed ? early : null, unavailable: false, replaced: conflict };
}
export interface State { selected: string; completed: boolean; mode: Mode; dark: boolean }
export type Action = {type: 'close'} | {type: 'reset'} | {type: 'select'; id: string} | {type: 'mode'; mode: Mode} | {type: 'theme'};
export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'close': return state.completed ? state : {...state, completed: true};
    case 'reset': return {...state, completed: false};
    case 'select': return action.id === state.selected ? state : {...state, selected: action.id, completed: false};
    case 'mode': return {...state, mode: action.mode};
    case 'theme': return {...state, dark: !state.dark};
  }
}
