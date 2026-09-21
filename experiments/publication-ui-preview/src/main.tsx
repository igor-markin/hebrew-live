import { Component, StrictMode } from 'react';
import type {ErrorInfo, ReactNode} from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/noto-sans/cyrillic-400.css';
import '@fontsource/noto-sans/cyrillic-500.css';
import '@fontsource/noto-sans/cyrillic-600.css';
import '@fontsource/noto-sans/latin-400.css';
import '@fontsource/noto-sans/latin-500.css';
import '@fontsource/noto-sans/latin-600.css';
import '@fontsource/noto-sans-hebrew/hebrew-400.css';
import './styles.css';
import App from './App';
import Live from './Live';
class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(error:Error,info:ErrorInfo){console.error('Local UI render failed',error,info);}
  render(){return this.state.failed?<main className="fatal-error" role="alert"><h1>Экран не удалось отобразить</h1><p>Последний ответ не изменил сохранённые данные. Обнови страницу, чтобы восстановить интерфейс.</p><button onClick={()=>location.reload()}>Обновить страницу</button></main>:this.props.children;}
}

createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary>{location.pathname.endsWith('/live/') ? <Live/> : <App/>}</ErrorBoundary></StrictMode>);

// Typography is optional: controls and polling are available immediately.
void (async()=>{
  await Promise.all([400,500,600].flatMap(weight=>[
    document.fonts.load(`${weight} 24px "Noto Sans"`,'Перевод'),
    document.fonts.load(`${weight} 24px "Noto Sans"`,'ABC0123'),
  ]));
  await document.fonts.load('400 24px "Noto Sans Hebrew"','שלום');
  if(!document.fonts.check('400 24px "Noto Sans"','Перевод')||!document.fonts.check('400 24px "Noto Sans Hebrew"','שלום'))throw new Error('Local fonts unavailable');
})().catch(error=>{document.documentElement.dataset.fonts='fallback';console.warn('Local fonts unavailable; using system fallback',error);});
