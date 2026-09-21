import { useEffect, useReducer, useState } from 'react';
import { Button } from '@heroui/react/button';
import { Card } from '@heroui/react/card';
import { Disclosure } from '@heroui/react/disclosure';
import data from './data/public-cases.json';
import { publication, reducer } from './policy';
import type { Example, Snapshot } from './policy';

const examples: Example[] = data.cases;
function Icon({kind}: {kind: 'moon' | 'sun' | 'arrow' | 'reset' | 'history' | 'check'}) {
  const paths = {moon: 'M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z', sun: 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0', arrow: 'M5 12h14m-5-5 5 5-5 5', reset: 'M3 10a9 9 0 1 1 2 8M3 4v6h6', history: 'M3 10a9 9 0 1 1 2 8M3 4v6h6m3-3v5l3 2', check: 'm5 12 4 4L19 6'};
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]}/></svg>;
}
function SnapshotText({snapshot, terminal, history = false}: {snapshot: Snapshot; terminal: boolean; history?: boolean}) {
  return <div className={`snapshot ${history ? 'snapshot--history' : ''}`} data-event={snapshot.eventId}>
    <div className="russian"><p className="field-label">{terminal ? 'Перевод после завершения' : 'Показанная часть перевода'}</p><p className="translation" lang="ru" dir="ltr">{snapshot.translation}</p></div>
    <div className="hebrew"><p className="field-label">Распознанный иврит на этом шаге</p><p className="source" lang="he" dir="rtl">{snapshot.source}</p></div>
  </div>;
}
function PreviousVersion({snapshot}: {snapshot: Snapshot}) {
  return <Disclosure className="history">
    <Disclosure.Heading><Disclosure.Trigger className="history-trigger"><Icon kind="history"/><span>Предыдущая версия</span><Disclosure.Indicator/></Disclosure.Trigger></Disclosure.Heading>
    <Disclosure.Content><Disclosure.Body className="history-body"><SnapshotText snapshot={snapshot} terminal={false} history/></Disclosure.Body></Disclosure.Content>
  </Disclosure>;
}
function ReadingArea({example, completed, mode}: {example: Example; completed: boolean; mode: 'single' | 'versions'}) {
  const view = publication(example, completed, mode);
  return <section className="reading-area" aria-label="Перевод выбранной реплики">
    <p className="sr-only" role="status" aria-live="polite">{view.unavailable ? 'Завершённая версия недоступна' : completed ? 'Показана версия после завершения речи' : 'Показан текст перед завершением речи'}</p>
    {view.entries.map((entry, i) => <Card key={i} className={`speech-card ${view.replaced ? 'speech-card--replaced' : ''}`} data-terminal={entry.terminal}>
      <Card.Header className="speech-heading"><span className={`state-dot ${entry.terminal ? 'state-dot--closed' : ''}`}/><h3>{entry.terminal ? 'Версия после завершения речи' : 'Перед завершением речи'}</h3></Card.Header>
      <Card.Content className="speech-content"><SnapshotText snapshot={entry.snapshot} terminal={entry.terminal}/></Card.Content>
      {i === 0 && view.history ? <Card.Footer className="speech-footer"><PreviousVersion key={example.id + completed + mode} snapshot={view.history}/></Card.Footer> : null}
    </Card>)}
    {view.unavailable ? <p className="unavailable" role="status">Завершённая версия недоступна</p> : null}
    <p className="reading-note">{completed ? 'Поздняя версия не обязательно точнее ранней.' : 'Русский текст — только показанная часть перевода всего исходника на этом шаге.'}</p>
  </section>;
}
export default function App() {
  const [state, dispatch] = useReducer(reducer, {selected: examples[0].id, completed: false, mode: 'single', dark: false});
  const [flash, setFlash] = useState(false);
  const example = examples.find(e => e.id === state.selected)!;
  useEffect(() => {document.documentElement.dataset.theme = state.dark ? 'dark' : 'light';}, [state.dark]);
  useEffect(() => {
    if (!flash) return;
    const timeout = window.setTimeout(() => setFlash(false), 180);
    return () => window.clearTimeout(timeout);
  }, [flash]);
  function close() { if (!state.completed) {dispatch({type: 'close'});setFlash(true);} }
  return <div className="app-shell">
    <header className="app-header"><div className="brand"><span className="brand-mark" aria-hidden="true"><span/><span/></span><span>Живой перевод</span></div><Button className="theme-button" variant="tertiary" onPress={() => dispatch({type:'theme'})} aria-label={state.dark ? 'Включить светлую тему' : 'Включить тёмную тему'}><Icon kind={state.dark ? 'sun' : 'moon'}/><span>{state.dark ? 'Светлая тема' : 'Тёмная тема'}</span></Button></header>
    <main>
      <div className="intro"><h1>Как показывать перевод</h1><p>Сохранённые результаты. Пошаговое сравнение интерфейсов</p></div>
      <div className="workspace">
        <aside aria-label="Примеры реплик"><h2 className="sidebar-title">Выбери реплику</h2><nav className="case-list">{examples.map((item, i) => <Button key={item.id} variant="tertiary" className="case-button" aria-pressed={item.id===state.selected} onPress={() => {dispatch({type:'select', id:item.id});setFlash(false);}}><span className="case-number">{String(i+1).padStart(2,'0')}</span><span>{item.title}</span><span className="case-indicator" aria-hidden="true"/></Button>)}</nav><p className="sidebar-note">Два состояния одной реплики.<br/>Без новых переводов.</p></aside>
        <div className="comparison">
          <div className="comparison-toolbar"><div className="mode-switch" role="group" aria-label="Способ отображения"><Button variant="tertiary" aria-pressed={state.mode==='single'} onPress={() => dispatch({type:'mode', mode:'single'})}>Одна карточка</Button><Button variant="tertiary" aria-pressed={state.mode==='versions'} onPress={() => dispatch({type:'mode', mode:'versions'})}>Две версии</Button></div><span className="step-label">{state.completed ? 'После завершения' : 'Перед завершением'}</span></div>
          <div className="example-heading"><h2>{example.title}</h2><p>Сравни, как меняется уже прочитанная реплика.</p></div>
          <div className="actions"><Button className="finish-button" variant="primary" onPress={close} aria-disabled={state.completed}>{state.completed ? 'Завершение показано' : 'Показать завершение'}<Icon kind={state.completed ? 'check' : 'arrow'}/></Button><Button className="reset-button" variant="tertiary" onPress={() => {dispatch({type:'reset'});setFlash(false);}}><Icon kind="reset"/>Начать заново</Button></div>
          <div className={flash ? 'publication-flash' : ''}><ReadingArea example={example} completed={state.completed} mode={state.mode}/></div>
        </div>
      </div>
    </main>
    <footer className="app-footer"><span>Макет интерфейса · работает локально</span><span>Время обработки здесь не воспроизводится</span></footer>
  </div>;
}
