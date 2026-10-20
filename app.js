(() => {
  'use strict';

  const en = {
    title: 'Hebrew Live — live Hebrew captions on your Mac',
    description: 'Hebrew Live turns spoken Hebrew into text with a translation into one of 45 languages. Recognition and translation run on your Mac.',
    skip: 'Skip to content', navLabel: 'Sections', langLabel: 'Site language',
    navHow: 'How it works', navLook: 'Interface', navInstall: 'Install',
    eyebrow: 'For Apple Silicon Macs · alpha',
    h1a: 'They speak Hebrew.', h1b: 'You read it your way.',
    lead: 'Hebrew Live listens to your microphone, shows spoken Hebrew as text and puts a translation into one of 45 languages right beside it. Recognition and translation run on your Mac, not in the cloud.',
    download: 'Download for Mac', source: 'Source code',
    ctaMeta: 'v0.1.0-alpha.3 · 353 MB DMG · macOS 27+',
    rec: 'Recording', local: 'on this Mac',
    demoCaption: 'Demo: phrases and translations are scripted; the app looks different.',
    factsLabel: 'In short',
    fact1: 'translation languages, from English and Russian to Japanese',
    fact2n: 'Offline', fact2: 'once the models are prepared, recognition and translation need no network',
    fact3n: 'No account', fact3: 'download, install, press Start recording',
    howKicker: 'How it works', howTitle: 'The whole path from sound to translation stays inside your Mac.',
    p1t: 'Microphone', p1: 'Opens only after you press Start recording.',
    p2: 'Finds speech in the audio and drops the pauses.',
    p3: 'An ivrit.ai model trained on Hebrew turns speech into text.',
    p4: 'Translates every phrase into the language you picked.',
    howNote: 'You need the internet once, to download the models — about 3.83 GB. Conversations stay in a local archive, and recognition and translation have no cloud fallback.',
    lookKicker: 'Interface', lookTitle: 'Original and translation in one card.', shotsLabel: 'Screenshots',
    shot0: 'Saved session', shot1: 'Before recording', shot2: 'Settings',
    shotCap0: 'A saved conversation: the translation in large type, recognised Hebrew below it. English interface, demo text.',
    shotCap1: 'Ready to begin: the microphone stays closed until you press Start recording.',
    shotCap2: 'Interface language, translation target and whether to keep the source audio.',
    shotAlt0: 'Saved session: Hebrew phrases with their English translation',
    shotAlt1: 'Live translation screen, ready to begin recording',
    shotAlt2: 'Settings panel with interface and translation languages',
    installKicker: 'Install', installTitle: 'Four steps to your first conversation.',
    downloadDmg: 'Download DMG', notes: 'Release notes and SHA256SUMS',
    reqTitle: 'You will need',
    req1: 'A Mac with Apple Silicon (M1 or later)', req2: 'macOS 27 or later',
    req3: '~900 MB for the app and 3.83 GB for the models', req4: 'No Python or Homebrew to install',
    s1t: 'Download and verify', s1: 'Compare the DMG checksum with the SHA256SUMS file from the release:',
    s2t: 'Move it to Applications', s2: 'Open the DMG and drag Hebrew Live into the Applications folder.',
    s3t: 'Allow the first launch', s3: 'The alpha is not notarised by Apple, so macOS blocks it. If the checksum matched, run this in Terminal:',
    s3b: 'Without Terminal: click Done in the macOS prompt, then System Settings → Privacy & Security → Open Anyway.',
    s4t: 'Prepare the models and listen', s4: 'On first launch the app downloads its models. Then pick a microphone and a translation language and press Start recording.',
    copy: 'Copy', copied: 'Copied',
    alphaTitle: 'Straight talk about the alpha',
    a1: 'Tested on one M5 Mac with 16 GB of memory. The minimum memory is not established.',
    a2: 'Installing on another Mac, the microphone permission prompt and recording with this exact build have not been tested yet.',
    a3: 'The app listens to the microphone. It does not capture system audio, such as a call in your headphones.',
    a4: 'The code is open under Apache-2.0. The models come with their authors’ terms.',
    feedback: 'Found a bug? Open an issue →',
    footLabel: 'Links', privacy: 'Privacy', thirdParty: 'Models and licences',
  };

  const extraRu = {
    copied: 'Скопировано',
    shotCap1: 'Готов к записи: микрофон закрыт, пока вы не нажмёте «Начать запись».',
    shotCap2: 'Язык интерфейса, язык перевода и сохранение исходного звука.',
    shotAlt0: 'Сохранённая сессия: фразы на иврите и их перевод на английский',
    shotAlt1: 'Экран живого перевода перед началом записи',
    shotAlt2: 'Панель настроек с языком интерфейса и перевода',
  };

  const shots = ['assets/live-translation.jpg', 'assets/session-archive.jpg', 'assets/language-settings.jpg'];

  const names = { ru: 'Русский', en: 'English', fr: 'Français', de: 'Deutsch', es: 'Español', ja: '日本語' };
  const phrases = [
    { he: 'שלום, בוקר טוב. אפשר להתחיל את הפגישה?',
      ru: 'Здравствуйте, доброе утро. Можно начинать встречу?',
      en: 'Hello, good morning. Shall we start the meeting?',
      fr: 'Bonjour. On peut commencer la réunion ?',
      de: 'Hallo, guten Morgen. Wollen wir mit dem Meeting beginnen?',
      es: 'Hola, buenos días. ¿Empezamos la reunión?',
      ja: 'おはようございます。会議を始めましょうか？' },
    { he: 'כן. היום נדבר על התוכנית לשבוע הבא.',
      ru: 'Да. Сегодня обсудим план на следующую неделю.',
      en: 'Yes. Today we’ll discuss the plan for next week.',
      fr: 'Oui. Aujourd’hui, on parle du programme de la semaine prochaine.',
      de: 'Ja. Heute besprechen wir den Plan für nächste Woche.',
      es: 'Sí. Hoy hablaremos del plan para la próxima semana.',
      ja: 'はい。今日は来週の計画について話します。' },
    { he: 'המשימה הראשונה כבר הושלמה.',
      ru: 'Первая задача уже выполнена.',
      en: 'The first task is already done.',
      fr: 'La première tâche est déjà terminée.',
      de: 'Die erste Aufgabe ist schon erledigt.',
      es: 'La primera tarea ya está terminada.',
      ja: '最初のタスクはもう完了しました。' },
    { he: 'תודה רבה, נתראה מחר.',
      ru: 'Большое спасибо, увидимся завтра.',
      en: 'Thanks a lot, see you tomorrow.',
      fr: 'Merci beaucoup, à demain.',
      de: 'Vielen Dank, bis morgen.',
      es: 'Muchas gracias, hasta mañana.',
      ja: 'ありがとうございました。また明日。' },
  ];
  const order = { ru: ['ru', 'en', 'fr', 'de'], en: ['en', 'ru', 'es', 'ja'] };

  // Russian strings come from the markup itself, so the page reads correctly without JS.
  const ru = { ...extraRu };
  document.querySelectorAll('[data-i18n]').forEach((el) => { ru[el.dataset.i18n] = el.textContent; });
  document.querySelectorAll('[data-i18n-aria]').forEach((el) => { ru[el.dataset.i18nAria] = el.getAttribute('aria-label'); });
  ru.title = document.title;
  ru.description = document.querySelector('meta[name="description"]').content;
  const copy = { ru, en };

  let locale = 'ru';
  let shotIndex = 0;
  const t = (key) => copy[locale][key] ?? copy.ru[key] ?? '';

  function applyLocale(next, remember) {
    locale = next;
    document.documentElement.lang = next;
    document.title = t('title');
    document.querySelector('meta[name="description"]').content = t('description');
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    document.querySelectorAll('[data-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === next)));
    setShot(shotIndex, false);
    if (remember) {
      try { localStorage.setItem('hl-lang', next); } catch {}
      const url = new URL(location.href);
      url.searchParams.set('lang', next);
      history.replaceState(null, '', url);
    }
    startDemo();
  }

  // ---------- Screenshot tabs ----------
  const tabs = [...document.querySelectorAll('[data-shot]')];
  const shotImg = document.getElementById('shot-img');
  const shotCap = document.getElementById('shot-caption');
  const panel = document.getElementById('shot');

  function setShot(i, focus) {
    shotIndex = i;
    tabs.forEach((tab, n) => {
      const on = n === i;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      if (on && focus) tab.focus();
    });
    panel.setAttribute('aria-labelledby', 'tab-' + i);
    shotCap.textContent = t('shotCap' + i);
    shotImg.alt = t('shotAlt' + i);
    if (!shotImg.src.endsWith(shots[i])) shotImg.src = shots[i];
  }
  tabs.forEach((tab, n) => {
    tab.addEventListener('click', () => setShot(n, false));
    tab.addEventListener('keydown', (e) => {
      const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (d) { e.preventDefault(); setShot((shotIndex + d + tabs.length) % tabs.length, true); }
    });
  });

  // ---------- Copy buttons ----------
  document.querySelectorAll('.copy').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const text = btn.parentElement.querySelector('code').textContent;
      try { await navigator.clipboard.writeText(text); } catch { return; }
      btn.textContent = t('copied');
      btn.classList.add('done');
      setTimeout(() => { btn.textContent = t('copy'); btn.classList.remove('done'); }, 1600);
    });
  });

  // ---------- Live caption demo ----------
  const feed = document.getElementById('feed');
  const target = document.getElementById('route-target');
  const meter = document.querySelector('.meter');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let run = 0;

  const sleep = (ms, id) => new Promise((resolve, reject) => {
    const tick = () => {
      if (id !== run) return reject(new Error('stopped'));
      if (document.hidden) return setTimeout(tick, 400);
      resolve();
    };
    setTimeout(tick, ms);
  });

  function card(p, lang) {
    const li = document.createElement('li');
    li.className = 'line';
    const he = document.createElement('div');
    he.className = 'he'; he.lang = 'he'; he.dir = 'rtl';
    const tr = document.createElement('div');
    tr.className = 'tr'; tr.hidden = true;
    const tag = document.createElement('b');
    tag.textContent = lang.toUpperCase();
    const text = document.createElement('span');
    text.lang = lang; text.textContent = p[lang];
    tr.append(tag, text);
    li.append(he, tr);
    return { li, he, tr };
  }

  function trim() {
    const lines = [...feed.children];
    lines.forEach((l, n) => l.classList.toggle('old', n < lines.length - 1));
    while (feed.children.length > 4) feed.firstElementChild.remove();
  }

  function renderStatic() {
    feed.textContent = '';
    order[locale].slice(0, 3).forEach((lang, n) => {
      const c = card(phrases[n], lang);
      c.he.textContent = phrases[n].he;
      c.tr.hidden = false;
      feed.append(c.li);
    });
    trim();
    target.textContent = names[order[locale][2]];
    meter.classList.add('quiet');
  }

  async function loop(id) {
    feed.textContent = '';
    for (let k = 0; ; k++) {
      const n = k % phrases.length;
      const lang = order[locale][n];
      const p = phrases[n];
      target.textContent = names[lang];
      meter.classList.remove('quiet');
      const c = card(p, lang);
      feed.append(c.li);
      trim();
      const caret = document.createElement('span');
      caret.className = 'caret';
      c.he.append(caret);
      const words = p.he.split(' ');
      for (let w = 0; w < words.length; w++) {
        await sleep(w === 0 ? 500 : 230 + Math.random() * 160, id);
        const span = document.createElement('span');
        span.className = 'w draft';
        span.textContent = words[w];
        caret.before(span, ' ');
        // Earlier words settle as recognition firms up; the newest stays a draft.
        c.he.querySelectorAll('.w.draft').forEach((el) => { if (el !== span) el.classList.remove('draft'); });
      }
      await sleep(380, id);
      c.he.querySelectorAll('.w.draft').forEach((el) => el.classList.remove('draft'));
      caret.remove();
      meter.classList.add('quiet');
      await sleep(260, id);
      c.tr.hidden = false;
      await sleep(2300, id);
    }
  }

  function startDemo() {
    run++;
    if (reduced) { renderStatic(); return; }
    loop(run).catch(() => {});
  }

  // ---------- Init ----------
  document.querySelectorAll('[data-lang]').forEach((b) => b.addEventListener('click', () => applyLocale(b.dataset.lang, true)));
  let initial = 'ru';
  try { if (localStorage.getItem('hl-lang') === 'en') initial = 'en'; } catch {}
  const param = new URLSearchParams(location.search).get('lang');
  if (param === 'en' || param === 'ru') initial = param;
  else if (!(() => { try { return localStorage.getItem('hl-lang'); } catch { return null; } })()
           && !/^(ru|uk|be|kk)\b/i.test(navigator.language || '')) initial = 'en';
  applyLocale(initial, false);
})();
