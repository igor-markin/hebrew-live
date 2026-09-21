export type UiLocale='en'|'ru'|'he';
export type LocaleRequest={value:UiLocale;previous:UiLocale};

export function beginLocaleRequest(current:UiLocale,saved:UiLocale|undefined,value:UiLocale,pending:LocaleRequest|null):LocaleRequest|null{
  if(pending||value===current)return null;
  return {value,previous:saved||current};
}

export function reconcileLocale(saved:UiLocale,request:LocaleRequest|null):{locale:UiLocale;request:LocaleRequest|null}{
  if(!request)return {locale:saved,request:null};
  return saved===request.value?{locale:saved,request:null}:{locale:request.value,request};
}

export function rollbackLocale(saved:UiLocale|undefined,request:LocaleRequest):UiLocale{
  return saved||request.previous;
}

const en={
  connecting:'Connecting…',translating:'Translating…',original:'Original',recognized:'Recognized {language}',
  speechMissing:'Speech was not recognized',fragmentFailed:'Could not process this fragment',fragment:'Fragment {number}',
  draft:'Preliminary translation',continued:'Continued in the next message',retrying:'Processing again…',retry:'Process again',
  pauseFirst:'Pause the recording first.',previous:'Previous version',recordingControls:'Recording controls',
  listening:'Listening',playing_recording:'Playing recording',finishing_translation:'Finishing translation…',opening_audio:'Opening audio…',
  loading_models:'Loading local models…',preparing_session:'Preparing a new session…',app_closed:'Application closed',
  finishing:'Finishing processing…',cancelling:'Cancelling remaining processing…',session_finished:'Session finished · models unloaded',
  paused:'Paused',saved_session:'Saved session',runtime_status:'Working…',recordingEnding:'finishing recording',
  recordingPaused:'recording paused',recordingPreparing:'preparing recording',recordingContinues:'recording continues',recordingUpdating:'updating recording state',
  newRecording:'New recording',cancelRemaining:'Cancel remaining processing',cancelShort:'Cancelling…',continue:'Continue',pause:'Pause',finishRecording:'Finish recording',
  settings:'Settings',readingDraft:'Text updates while speech continues. The previous version remains in history.',
  readingEarly:'Early text may change when the utterance finishes. The previous version remains in history.',
  interfaceLanguage:'Interface language',targetLanguage:'Translate Hebrew into',targetBoundary:'The new target applies to audio captured after the change. Pending speech keeps its original target.',
  customCapability:'This list follows the selected prompt contract. A custom model was not quality-tested across these languages.',
  english:'English',russian:'Russian',hebrew:'Hebrew',lightTheme:'Light theme',darkTheme:'Dark theme',clearScreen:'Clear screen',
  cancelConfirm:'Cancel the remaining processing? The unfinished translation tail will be lost.',loadSessionsError:'Could not load the conversation list.',
  openArchiveError:'Could not open this conversation. Its files may have been moved or damaged.',deleteConfirm:'Delete session {label}?\nAudio, translation, transcript, and all technical logs will be permanently deleted.',
  deleteError:'The session could not be deleted completely. Check its folder before trying again.',liveTitle:'Live translation',ordinaryMode:'standard mode',experimentMode:'experimental mode',
  timeout:'The local application did not respond within 6 seconds.',badSnapshot:'The local application returned an incompatible data snapshot.',
  httpError:'The local application returned error {code}.',noResponse:'Could not get a response from the local application.',lastSnapshot:'The last valid snapshot is shown.',
  secondsAgo:'Data last updated {seconds} sec. ago.',openFolderError:'Could not open the selected conversation folder.',actionError:'The action was not accepted. Check the application state before trying again.',
  sessions:'Sessions',closeSessions:'Close session list',searchPlaceholder:'Search conversations or dates',searchSaved:'Search saved conversations',
  savedConversations:'Saved conversations',currentSession:'Current session',saved:'Saved',noneSaved:'No saved conversations yet.',nothingFound:'Nothing matches this search.',
  retryButton:'Try again',deleteSession:'Delete session {label}',deleteTitle:'Delete session',savedConversation:'Saved conversation',readOnly:'Saved conversation · read only',
  onThisMac:'On this Mac · local models',backToLive:'Back to live translation',feedLabel:'Recognized speech and translation',
  noMessages:'This conversation has no saved messages.',conversationUnavailable:'Conversation unavailable.',loadingConversation:'Loading conversation…',chooseAgain:'Choose the conversation again.',
  loadingBeforeRecord:'Loading models. Recording has not started.',closed:'Application closed.',readyNew:'Recording finished. You can start a new session.',recordingFinished:'Recording finished.',
  readyToSpeak:'Select “Continue” when you are ready to speak.',waitingSpeech:'Listening. Waiting for speech…',sessionSaved:'Session saved',
  filesInFolder:'Audio, transcript, translation, and technical logs are in the session folder.',openFinder:'Open folder in Finder',backToCurrent:'Back to current translation',
  lateNotBetter:'A later version is not necessarily more accurate.',targetChangeError:'The target language change could not be queued. Try again.',
  targetBusyError:'The target language was not changed because the recording state changed. Try again when the controls are ready.',
  targetPreferenceError:'The target changed for this session, but the choice could not be saved for the next session.',
  repeatedGeneration:'Repeated generation',translationIncomplete:'Translation did not finish',emptyTranslation:'Empty translation',translationError:'Translation error',retryFailed:'Processing again failed.',
  cancelledFragment:'Cancelled',translationLimit:'Translation limit reached',nonHebrewSkipped:'Non-Hebrew text was recognized; translation was skipped.',finalUnavailable:'A finished version is unavailable; the early text was not confirmed.',
  retryStateChanged:'The session state changed or the original fragment recording is unavailable.',archiveIncomplete:'The technical log contains an incomplete record.',inputFile:'File',inputMicrophone:'Microphone',
  renderFailed:'The screen could not be displayed',renderRecovery:'The last response did not change saved data. Reload the page to restore the interface.',reload:'Reload page',
  direction:'{source} → {target}'
};

type Dictionary={ [K in keyof typeof en]: string };

const ru:Dictionary={
  connecting:'Подключаюсь…',translating:'Перевожу…',original:'Оригинал',recognized:'Распознанный {language}',speechMissing:'Речь не распознана',
  fragmentFailed:'Не удалось обработать фрагмент',fragment:'Фрагмент {number}',draft:'Предварительный перевод',continued:'Продолжение в следующем сообщении',
  retrying:'Обрабатываю повторно…',retry:'Повторить обработку',pauseFirst:'Сначала поставь запись на паузу.',previous:'Предыдущая версия',recordingControls:'Управление записью',
  listening:'Слушаю',playing_recording:'Воспроизведение записи',finishing_translation:'Завершаю перевод…',opening_audio:'Открываю аудио…',loading_models:'Загрузка локальных моделей…',
  preparing_session:'Подготовка новой сессии…',app_closed:'Приложение закрыто',finishing:'Завершаю обработку…',cancelling:'Отменяю оставшуюся обработку…',
  session_finished:'Сессия завершена · модели выгружены',paused:'Пауза',saved_session:'Сохранённая сессия',runtime_status:'Работаю…',recordingEnding:'завершение записи',
  recordingPaused:'запись на паузе',recordingPreparing:'запись подготавливается',recordingContinues:'запись продолжается',recordingUpdating:'состояние записи обновляется',
  newRecording:'Новая запись',cancelRemaining:'Отменить оставшуюся обработку',cancelShort:'Отменяю…',continue:'Продолжить',pause:'Пауза',finishRecording:'Завершить запись',
  settings:'Настройки',readingDraft:'Текст обновляется во время речи. Предыдущая версия остаётся в истории.',readingEarly:'Ранний текст может измениться при завершении. Предыдущая версия остаётся в истории.',
  interfaceLanguage:'Язык интерфейса',targetLanguage:'Переводить с иврита на',targetBoundary:'Новый язык применяется к аудио, записанному после изменения. Уже принятая речь сохраняет прежний язык.',
  customCapability:'Список следует выбранному prompt-контракту. Пользовательская модель не проверялась на качество для всех этих языков.',
  english:'Английский',russian:'Русский',hebrew:'Иврит',lightTheme:'Светлая тема',darkTheme:'Тёмная тема',clearScreen:'Очистить экран',
  cancelConfirm:'Отменить оставшуюся обработку? Неполный хвост перевода будет потерян.',loadSessionsError:'Не удалось загрузить список разговоров.',openArchiveError:'Не удалось открыть этот разговор. Файлы могли быть перемещены или повреждены.',
  deleteConfirm:'Удалить сессию {label}?\nАудио, перевод, расшифровка и все технические логи будут удалены без возможности восстановления.',deleteError:'Не удалось полностью удалить сессию. Проверь её папку перед повтором.',
  liveTitle:'Живой перевод',ordinaryMode:'обычный режим',experimentMode:'эксперимент',timeout:'Локальное приложение не ответило за 6 секунд.',badSnapshot:'Локальное приложение вернуло несовместимый снимок данных.',
  httpError:'Локальное приложение ответило с ошибкой {code}.',noResponse:'Не удалось получить ответ локального приложения.',lastSnapshot:'Показан последний корректный снимок.',secondsAgo:'Данные обновлялись {seconds} сек. назад.',
  openFolderError:'Не удалось открыть папку выбранного разговора.',actionError:'Действие не принято. Проверь состояние приложения перед повтором.',sessions:'Сессии',closeSessions:'Закрыть список сессий',
  searchPlaceholder:'Поиск по разговору или дате',searchSaved:'Поиск сохранённых разговоров',savedConversations:'Сохранённые разговоры',currentSession:'Текущая сессия',saved:'Сохранённые',noneSaved:'Сохранённых разговоров пока нет.',nothingFound:'По этому запросу ничего не найдено.',
  retryButton:'Повторить',deleteSession:'Удалить сессию {label}',deleteTitle:'Удалить сессию',savedConversation:'Сохранённый разговор',readOnly:'Сохранённый разговор · только чтение',onThisMac:'На этом Mac · локальные модели',
  backToLive:'К текущему переводу',feedLabel:'Распознанная речь и перевод',noMessages:'В этом разговоре нет сохранённых сообщений.',conversationUnavailable:'Разговор недоступен.',loadingConversation:'Загружаю разговор…',chooseAgain:'Выбери разговор ещё раз.',
  loadingBeforeRecord:'Загружаю модели. Запись ещё не началась.',closed:'Приложение закрыто.',readyNew:'Запись завершена. Можно начать новую сессию.',recordingFinished:'Запись завершена.',readyToSpeak:'Нажми «Продолжить», когда будешь готов говорить.',waitingSpeech:'Слушаю. Ожидаю речь…',
  sessionSaved:'Сессия сохранена',filesInFolder:'Аудио, расшифровка, перевод и технические логи находятся в папке сессии.',openFinder:'Открыть папку в Finder',backToCurrent:'К текущему переводу',lateNotBetter:'Поздняя версия не обязательно точнее ранней.',
  targetChangeError:'Не удалось поставить смену языка в очередь. Попробуй снова.',targetBusyError:'Язык перевода не изменён: состояние записи успело измениться. Повтори, когда элементы управления станут доступны.',targetPreferenceError:'Язык изменён для этой сессии, но выбор не удалось сохранить для следующей.',repeatedGeneration:'Повтор генерации',translationIncomplete:'Перевод не завершён',emptyTranslation:'Пустой перевод',translationError:'Ошибка перевода',retryFailed:'Повторная обработка не удалась.',
  cancelledFragment:'Отменено',translationLimit:'Достигнут лимит перевода',nonHebrewSkipped:'Распознан текст на другом языке; перевод пропущен.',finalUnavailable:'Завершённая версия недоступна; ранний текст не подтверждён.',direction:'{source} → {target}',
  retryStateChanged:'Состояние сессии изменилось или исходная запись фрагмента недоступна.',archiveIncomplete:'В журнале есть неполная запись.',inputFile:'Файл',inputMicrophone:'Микрофон',
  renderFailed:'Экран не удалось отобразить',renderRecovery:'Последний ответ не изменил сохранённые данные. Обнови страницу, чтобы восстановить интерфейс.',reload:'Обновить страницу'
};

const he:Dictionary={
  connecting:'מתחבר…',translating:'מתרגם…',original:'מקור',recognized:'{language} שזוהתה',speechMissing:'הדיבור לא זוהה',fragmentFailed:'לא ניתן היה לעבד את הקטע',fragment:'קטע {number}',
  draft:'תרגום ראשוני',continued:'המשך בהודעה הבאה',retrying:'מעבד שוב…',retry:'עיבוד חוזר',pauseFirst:'יש להשהות תחילה את ההקלטה.',previous:'גרסה קודמת',recordingControls:'פקדי הקלטה',
  listening:'מקשיב',playing_recording:'משמיע הקלטה',finishing_translation:'מסיים את התרגום…',opening_audio:'פותח שמע…',loading_models:'טוען מודלים מקומיים…',preparing_session:'מכין הפעלה חדשה…',
  app_closed:'היישום נסגר',finishing:'מסיים את העיבוד…',cancelling:'מבטל את יתרת העיבוד…',session_finished:'ההפעלה הסתיימה · המודלים שוחררו',paused:'מושהה',saved_session:'הפעלה שמורה',runtime_status:'מעבד…',
  recordingEnding:'מסיים הקלטה',recordingPaused:'ההקלטה מושהית',recordingPreparing:'מכין הקלטה',recordingContinues:'ההקלטה נמשכת',recordingUpdating:'מעדכן את מצב ההקלטה',
  newRecording:'הקלטה חדשה',cancelRemaining:'ביטול יתרת העיבוד',cancelShort:'מבטל…',continue:'המשך',pause:'השהיה',finishRecording:'סיום הקלטה',settings:'הגדרות',
  readingDraft:'הטקסט מתעדכן במהלך הדיבור. הגרסה הקודמת נשמרת בהיסטוריה.',readingEarly:'הטקסט הראשוני עשוי להשתנות בסיום המשפט. הגרסה הקודמת נשמרת בהיסטוריה.',
  interfaceLanguage:'שפת הממשק',targetLanguage:'תרגום מעברית אל',targetBoundary:'שפת היעד החדשה חלה על שמע שנקלט לאחר השינוי. דיבור שכבר נקלט נשאר עם היעד הקודם.',
  customCapability:'הרשימה מבוססת על חוזה ההנחיה שנבחר. מודל מותאם אישית לא נבדק לאיכות בכל השפות האלה.',
  english:'אנגלית',russian:'רוסית',hebrew:'עברית',lightTheme:'ערכת נושא בהירה',darkTheme:'ערכת נושא כהה',clearScreen:'ניקוי המסך',cancelConfirm:'לבטל את יתרת העיבוד? סוף התרגום שלא הושלם יאבד.',
  loadSessionsError:'לא ניתן היה לטעון את רשימת השיחות.',openArchiveError:'לא ניתן היה לפתוח את השיחה. ייתכן שהקבצים הועברו או נפגמו.',deleteConfirm:'למחוק את ההפעלה {label}?\nהשמע, התרגום, התמלול וכל היומנים הטכניים יימחקו לצמיתות.',
  deleteError:'לא ניתן היה למחוק את ההפעלה במלואה. יש לבדוק את התיקייה לפני ניסיון נוסף.',liveTitle:'תרגום חי',ordinaryMode:'מצב רגיל',experimentMode:'מצב ניסיוני',timeout:'היישום המקומי לא הגיב בתוך 6 שניות.',
  badSnapshot:'היישום המקומי החזיר תמונת נתונים לא תואמת.',httpError:'היישום המקומי החזיר שגיאה {code}.',noResponse:'לא התקבלה תשובה מהיישום המקומי.',lastSnapshot:'מוצגת תמונת הנתונים התקינה האחרונה.',secondsAgo:'הנתונים עודכנו לפני {seconds} שניות.',
  openFolderError:'לא ניתן היה לפתוח את תיקיית השיחה שנבחרה.',actionError:'הפעולה לא התקבלה. יש לבדוק את מצב היישום לפני ניסיון נוסף.',sessions:'הפעלות',closeSessions:'סגירת רשימת ההפעלות',searchPlaceholder:'חיפוש בשיחות או בתאריכים',searchSaved:'חיפוש בשיחות שמורות',
  savedConversations:'שיחות שמורות',currentSession:'ההפעלה הנוכחית',saved:'שמורות',noneSaved:'אין עדיין שיחות שמורות.',nothingFound:'לא נמצאו תוצאות לחיפוש.',retryButton:'ניסיון נוסף',deleteSession:'מחיקת ההפעלה {label}',deleteTitle:'מחיקת הפעלה',
  savedConversation:'שיחה שמורה',readOnly:'שיחה שמורה · לקריאה בלבד',onThisMac:'ב-Mac הזה · מודלים מקומיים',backToLive:'חזרה לתרגום החי',feedLabel:'דיבור מזוהה ותרגום',noMessages:'אין בשיחה הזאת הודעות שמורות.',conversationUnavailable:'השיחה אינה זמינה.',loadingConversation:'טוען שיחה…',chooseAgain:'יש לבחור שוב את השיחה.',
  loadingBeforeRecord:'טוען מודלים. ההקלטה עדיין לא התחילה.',closed:'היישום נסגר.',readyNew:'ההקלטה הסתיימה. אפשר להתחיל הפעלה חדשה.',recordingFinished:'ההקלטה הסתיימה.',readyToSpeak:'יש לבחור „המשך” כשמוכנים לדבר.',waitingSpeech:'מקשיב. ממתין לדיבור…',
  sessionSaved:'ההפעלה נשמרה',filesInFolder:'השמע, התמלול, התרגום והיומנים הטכניים נמצאים בתיקיית ההפעלה.',openFinder:'פתיחת התיקייה ב-Finder',backToCurrent:'חזרה לתרגום הנוכחי',lateNotBetter:'גרסה מאוחרת אינה בהכרח מדויקת יותר.',
  targetChangeError:'לא ניתן היה להכניס את שינוי שפת היעד לתור. יש לנסות שוב.',targetBusyError:'שפת היעד לא שונתה כי מצב ההקלטה השתנה. יש לנסות שוב כשהפקדים זמינים.',targetPreferenceError:'שפת היעד שונתה להפעלה הזאת, אך לא ניתן היה לשמור את הבחירה להפעלה הבאה.',repeatedGeneration:'יצירה חוזרת',translationIncomplete:'התרגום לא הסתיים',emptyTranslation:'תרגום ריק',translationError:'שגיאת תרגום',retryFailed:'העיבוד החוזר נכשל.',
  cancelledFragment:'בוטל',translationLimit:'הגענו למגבלת התרגום',nonHebrewSkipped:'זוהה טקסט שאינו בעברית; התרגום דולג.',finalUnavailable:'גרסה סופית אינה זמינה; הטקסט המוקדם לא אומת.',direction:'{source} ← {target}',
  retryStateChanged:'מצב ההפעלה השתנה או שהקלטת הקטע המקורית אינה זמינה.',archiveIncomplete:'ביומן הטכני יש רשומה חלקית.',inputFile:'קובץ',inputMicrophone:'מיקרופון',
  renderFailed:'לא ניתן להציג את המסך',renderRecovery:'התשובה האחרונה לא שינתה נתונים שמורים. יש לטעון מחדש את הדף כדי לשחזר את הממשק.',reload:'טעינת הדף מחדש'
};

const dictionaries={en,ru,he};
export type TextKey=keyof typeof en;
export const translator=(locale:UiLocale)=>(key:TextKey,values:Record<string,string|number>={})=>
  dictionaries[locale][key].replace(/\{(\w+)\}/g,(_,name)=>String(values[name]??''));

export function languageName(locale:UiLocale,code:string,fallback=code):string{
  const normalized=code==='zh-cn'?'zh-Hans':code==='zh-tw'?'zh-Hant':code;
  try{return new Intl.DisplayNames([locale],{type:'language'}).of(normalized)||fallback;}catch{return fallback;}
}

export const htmlLanguage=(code:string)=>code==='zh-cn'?'zh-Hans':code==='zh-tw'?'zh-Hant':code;
export const isRtlLanguage=(code:string)=>['ar','fa','he','ug','ur'].includes(code);
export function directionParts(direction:string):[string,string]{const at=direction.indexOf('-');return at<0?['he','en']:[direction.slice(0,at),direction.slice(at+1)];}

export function issueText(locale:UiLocale,value:string):string{
  const tx=translator(locale);const known:Record<string,TextKey>={'Повтор генерации':'repeatedGeneration','Перевод не завершён':'translationIncomplete','Пустой перевод':'emptyTranslation','Ошибка перевода':'translationError','Повторная обработка не удалась.':'retryFailed','Состояние сессии изменилось или исходная запись фрагмента недоступна.':'retryStateChanged',
    'Речь не распознана':'speechMissing','Отменено':'cancelledFragment','Достигнут лимит перевода':'translationLimit','Распознан текст на другом языке; перевод пропущен':'nonHebrewSkipped','Завершённая версия недоступна; ранний текст не подтверждён':'finalUnavailable'};
  if(value.startsWith('Ошибка перевода:'))return tx('translationError')+value.slice('Ошибка перевода'.length);
  return known[value]?tx(known[value]):value;
}
