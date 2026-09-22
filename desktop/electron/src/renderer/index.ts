import type { BootstrapData, ControllerEvent, DesktopPreferences, HebrewLiveBridge, UiLocale } from "../shared.js";
import { preferredTargetLanguage } from "../security.js";

declare global {
  interface Window { hebrewLive?: HebrewLiveBridge }
}

interface ModelComponent {
  key: string;
  label: string;
  terms_url: string;
  files: Array<{ bytes: number }>;
}

interface Inventory {
  total_bytes: number;
  components: ModelComponent[];
}

interface LanguageOption { code: string; name: string; rtl?: boolean }
interface Languages { source: string; targets: LanguageOption[] }
interface FileCheck { state: string }
interface Issue { code: string; message: string }
interface Preflight {
  compatible: boolean;
  system: {
    macos: string;
    machine: string;
    memory_bytes: number | null;
    memory_reference_bytes: number;
    high_current_load: boolean;
    metal_available: boolean;
  };
  storage: {
    available_bytes: number;
    required_free_bytes: number;
    download_bytes: number;
    reserve_bytes: number;
    files: FileCheck[];
  };
  blockers: Issue[];
  warnings: Issue[];
}

type Step = "loading" | "welcome" | "preflight" | "prepare" | "languages" | "audio" |
  "launching" | "help" | "error";

const api = window.hebrewLive as HebrewLiveBridge;
const root = document.querySelector<HTMLElement>("#app") as HTMLElement;
if (!api || !root) throw new Error("desktop_bridge_unavailable");

let bootstrap: (BootstrapData & { viewReason?: string }) | null = null;
let desktopPreferences: DesktopPreferences | null = null;
let inventory: Inventory | null = null;
let languages: Languages | null = null;
let enginePreferences: Record<string, unknown> = {};
let preflight: Preflight | null = null;
let step: Step = "loading";
let welcomeSlide = 0;
let skipWelcomeNextTime = true;
let locale: UiLocale = "en";
let preflightLoading = false;
let warningAccepted = false;
let downloadConsent = false;
let preparationPhase = "idle";
let preparationDetail = "";
let preparationCode = "";
let downloadedBytes = 0;
let downloadBytes = 0;
let bytesPerSecond = 0;
let selectedTarget = "en";
let selectedUiLocale: UiLocale = "en";
let saveAudio = true;
let audioSaved = false;
let audioStatus: "idle" | "checking" | "signal" | "silent" | "permission" | "device" | "error" = "idle";
let audioDevice = "";
let audioLevel = 0;
let runtimeError = "";
let meterCleanup: (() => void) | null = null;

const text = {
  en: {
    help: "Help and feedback", quit: "Quit", back: "Back", next: "Next", skip: "Skip", continue: "Continue",
    slides: [
      ["Understand calls and meetings", "Hebrew Live listens only after you press Start and translates Hebrew speech locally as the conversation unfolds."],
      ["Original and translation together", "See the recognized Hebrew beside the translation, including careful revisions when a phrase becomes clearer."],
      ["A local archive you can return to", "Open earlier sessions without starting the microphone, then return to a new recording when you choose."],
    ],
    dontShow: "Do not show this introduction next time",
    checkingTitle: "Checking this Mac", checkingBody: "Architecture, Metal, memory pressure, and model storage are checked before anything is downloaded.",
    memory: "Memory", disk: "Disk space", compatibility: "Compatibility", load: "Current load", metal: "Metal available",
    recheck: "Check again", proceedWarning: "I understand the warning and want to continue", blocked: "Resolve the blocking item, then check again.",
    prepareTitle: "Prepare local models", prepareBody: "Three pinned components stay outside the application and are verified before use.",
    total: "Total model files", location: "Stored in Hebrew Live's existing local data folder", terms: "Terms", consent: "Allow Hebrew Live to download the missing pinned files",
    prepare: "Download and prepare", verifyWarm: "Verify and warm up", current: "Current component", speed: "Speed",
    verifying: "Checking files without an estimated percentage…", warming: "Warming the models without an estimated percentage…",
    paused: "Download paused", retry: "Continue", exit: "Exit", cancelDownload: "Stop download",
    languagesTitle: "Choose your languages", languagesBody: "The interface and translation target are independent. Hebrew remains the qualified spoken source.",
    interfaceLanguage: "Interface language", translationLanguage: "Translate Hebrew into", saveLanguages: "Save and continue",
    english: "English", russian: "Russian",
    audioTitle: "Audio and microphone", audioBody: "Texts are saved in the local archive even when the original audio is not kept.",
    saveAudio: "Save the original recording with each session", audioExplain: "Enabled by default. Your explicit confirmation is required.",
    confirmTest: "Confirm and test microphone", testing: "Checking microphone permission and input…", device: "Selected input",
    signal: "Input signal detected. The test did not create an archive session.", silent: "No audible signal was detected. Check the selected input and try again.",
    permission: "Microphone permission is not available. Allow Hebrew Live in System Settings and try again.", noDevice: "No microphone device is available.",
    tryAgain: "Try again", openApp: "Continue to Hebrew Live",
    launchingTitle: "Ready to begin", launchingBody: "Opening the working screen. Recording will remain stopped until you press Start.",
    helpTitle: "Help and feedback", helpBody: "Open the project page or copy a safe diagnostic report. Conversations, recordings, personal paths, and access tokens are not included.",
    github: "Open GitHub", copyDiagnostics: "Copy diagnostics", copied: "Diagnostics copied", returnApp: "Return to Hebrew Live",
    errorTitle: "Hebrew Live could not start its engine", errorBody: "The preparation window still works. You can retry the packaged engine or copy safe diagnostics.",
    restart: "Restart engine", working: "Working…",
  },
  ru: {
    help: "Помощь и обратная связь", quit: "Выйти", back: "Назад", next: "Далее", skip: "Пропустить", continue: "Продолжить",
    slides: [
      ["Понимай звонки и встречи", "Hebrew Live слушает только после нажатия «Начать» и локально переводит речь на иврите по ходу разговора."],
      ["Оригинал и перевод рядом", "Распознанный иврит показан вместе с переводом, включая аккуратные уточнения, когда фраза становится понятнее."],
      ["Локальный архив под рукой", "Открывай прошлые сессии без запуска микрофона и возвращайся к новой записи, когда решишь."],
    ],
    dontShow: "Не показывать знакомство при следующем запуске",
    checkingTitle: "Проверяю этот Mac", checkingBody: "До загрузки проверяются архитектура, Metal, текущая нагрузка памяти и место для моделей.",
    memory: "Память", disk: "Место на диске", compatibility: "Совместимость", load: "Текущая нагрузка", metal: "Metal доступен",
    recheck: "Проверить снова", proceedWarning: "Я понимаю предупреждение и хочу продолжить", blocked: "Исправь блокирующую проблему и повтори проверку.",
    prepareTitle: "Подготовка локальных моделей", prepareBody: "Три закреплённых компонента хранятся вне приложения и проверяются перед использованием.",
    total: "Объём файлов моделей", location: "Хранятся в существующем локальном каталоге Hebrew Live", terms: "Условия", consent: "Разрешаю Hebrew Live загрузить недостающие закреплённые файлы",
    prepare: "Загрузить и подготовить", verifyWarm: "Проверить и прогреть", current: "Текущий компонент", speed: "Скорость",
    verifying: "Проверяю файлы без выдуманного процента…", warming: "Прогреваю модели без выдуманного процента…",
    paused: "Загрузка приостановлена", retry: "Продолжить", exit: "Выйти", cancelDownload: "Остановить загрузку",
    languagesTitle: "Выбери языки", languagesBody: "Язык интерфейса и язык перевода независимы. Поддержанный источник речи — иврит.",
    interfaceLanguage: "Язык интерфейса", translationLanguage: "Переводить с иврита на", saveLanguages: "Сохранить и продолжить",
    english: "Английский", russian: "Русский",
    audioTitle: "Аудио и микрофон", audioBody: "Тексты сохраняются в локальном архиве, даже если исходная запись выключена.",
    saveAudio: "Сохранять исходную запись вместе с каждой сессией", audioExplain: "Включено по умолчанию. Нужно твоё явное подтверждение.",
    confirmTest: "Подтвердить и проверить микрофон", testing: "Проверяю разрешение и входной сигнал…", device: "Выбранный вход",
    signal: "Сигнал обнаружен. Проверка не создала запись в архиве.", silent: "Не слышу сигнала. Проверь выбранный вход и попробуй снова.",
    permission: "Нет доступа к микрофону. Разреши Hebrew Live в Системных настройках и попробуй снова.", noDevice: "Микрофон не найден.",
    tryAgain: "Попробовать снова", openApp: "Перейти в Hebrew Live",
    launchingTitle: "Готово к началу", launchingBody: "Открываю рабочий экран. Запись не начнётся, пока ты сам не нажмёшь «Начать».",
    helpTitle: "Помощь и обратная связь", helpBody: "Можно открыть GitHub или скопировать безопасную диагностику. Разговоры, записи, личные пути и токены не добавляются.",
    github: "Открыть GitHub", copyDiagnostics: "Скопировать диагностику", copied: "Диагностика скопирована", returnApp: "Вернуться в Hebrew Live",
    errorTitle: "Не удалось запустить движок Hebrew Live", errorBody: "Окно подготовки продолжает работать. Можно перезапустить упакованный движок или скопировать безопасную диагностику.",
    restart: "Перезапустить движок", working: "Выполняю…",
  },
} as const;

function t(): typeof text.en | typeof text.ru { return text[locale]; }

function formatBytes(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = Math.max(0, value);
  let index = 0;
  while (amount >= 1000 && index < units.length - 1) { amount /= 1000; index += 1; }
  return `${amount.toFixed(index >= 3 ? 2 : index === 0 ? 0 : 1)} ${units[index]}`;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[character] ?? character));
}

function shell(content: string): void {
  document.documentElement.lang = locale;
  root.innerHTML = `<div class="shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark" aria-hidden="true">א</span><span>Hebrew Live</span></div>
      <div class="top-actions"><button class="text" id="help-button">${t().help}</button><button class="text" id="quit-button">${t().quit}</button></div>
    </header>
    <section class="card">${content}</section>
  </div>`;
  document.querySelector("#help-button")?.addEventListener("click", () => { step = "help"; render(); });
  document.querySelector("#quit-button")?.addEventListener("click", () => void api.requestQuit());
}

function setButton(id: string, action: () => unknown | Promise<unknown>): void {
  document.querySelector(`#${id}`)?.addEventListener("click", () => void action());
}

async function saveStep(lastStep: string, patch: Partial<DesktopPreferences> = {}): Promise<void> {
  desktopPreferences = await api.saveOnboarding({ lastStep, ...patch });
}

function renderWelcome(): void {
  const slide = t().slides[welcomeSlide];
  const image = bootstrap?.onboardingImages[welcomeSlide] ?? "";
  shell(`<div class="welcome-grid">
    <div>
      <p class="eyebrow">${welcomeSlide + 1} / 3</p>
      <h1>${slide[0]}</h1><p class="lede">${slide[1]}</p>
      <div class="dots" aria-hidden="true">${[0,1,2].map((value) => `<span class="dot ${value === welcomeSlide ? "current" : ""}"></span>`).join("")}</div>
    </div>
    <img class="screenshot" src="${escapeHtml(image)}" alt="Hebrew Live">
  </div>
  <div class="actions split">
    <label class="check"><input id="skip-next" type="checkbox" ${skipWelcomeNextTime ? "checked" : ""}><span>${t().dontShow}</span></label>
    <div><button class="text" id="skip">${t().skip}</button> ${welcomeSlide > 0 ? `<button class="secondary" id="back">${t().back}</button>` : ""} <button id="next">${t().next}</button></div>
  </div>`);
  document.querySelector<HTMLInputElement>("#skip-next")?.addEventListener("change", (event) => {
    skipWelcomeNextTime = (event.currentTarget as HTMLInputElement).checked;
  });
  setButton("back", () => { welcomeSlide -= 1; render(); });
  const finish = async () => {
    await saveStep("preflight", { showWelcome: !skipWelcomeNextTime });
    await runPreflight();
  };
  setButton("skip", finish);
  setButton("next", async () => {
    if (welcomeSlide < 2) { welcomeSlide += 1; render(); }
    else await finish();
  });
}

function resultRow(kind: "ok" | "warning" | "error", title: string, detail: string, value: string): string {
  const icon = kind === "ok" ? "✓" : kind === "warning" ? "!" : "×";
  return `<div class="result ${kind}"><span class="result-icon" aria-hidden="true">${icon}</span><div><h3>${title}</h3><p>${detail}</p></div><span class="result-value">${value}</span></div>`;
}

function issueText(issue: Issue): string {
  const known: Record<string, { en: string; ru: string }> = {
    memory_below_reference: { en: "This Mac has less than the tested 16 GiB reference. This is a warning, not a proven minimum.", ru: "На этом Mac меньше проверенного ориентира 16 ГиБ. Это предупреждение, а не доказанный минимум." },
    current_load_high: { en: "Current CPU or memory pressure is high. Close other applications and check again.", ru: "Текущая нагрузка CPU или памяти высокая. Закрой лишние приложения и повтори проверку." },
    disk_space: { en: "There is not enough space for missing files, temporary data, and the 2 GiB reserve.", ru: "Не хватает места для недостающих файлов, временных данных и резерва 2 ГиБ." },
    metal_unavailable: { en: "Apple Metal is unavailable. Restart the Mac or update macOS before trying again.", ru: "Apple Metal недоступен. Перезагрузи Mac или обнови macOS перед повторной попыткой." },
    unsupported_architecture: { en: "This build requires an Apple Silicon Mac.", ru: "Эта сборка требует Mac с Apple Silicon." },
    unsupported_macos: { en: "This build is not compatible with the installed macOS version.", ru: "Эта сборка несовместима с установленной версией macOS." },
  };
  return known[issue.code]?.[locale] ?? issue.message;
}

function renderPreflight(): void {
  if (preflightLoading || !preflight) {
    shell(`<div class="center"><div><span class="spinner" aria-hidden="true"></span><h2>${t().checkingTitle}</h2><p class="muted">${t().checkingBody}</p></div></div>`);
    return;
  }
  const current = preflight;
  const memory = current.system.memory_bytes;
  const memoryWarning = current.warnings.some((item) => item.code === "memory_below_reference");
  const rows = [
    resultRow(current.compatible ? "ok" : "error", t().compatibility,
      `${current.system.machine} · macOS ${escapeHtml(current.system.macos)}`, current.compatible ? "OK" : "—"),
    resultRow(memoryWarning ? "warning" : "ok", t().memory,
      memoryWarning ? issueText(current.warnings.find((item) => item.code === "memory_below_reference")!) : "16 GiB tested reference",
      memory === null ? "—" : formatBytes(memory)),
    resultRow(current.blockers.some((item) => item.code === "disk_space") ? "error" : "ok", t().disk,
      `${formatBytes(current.storage.required_free_bytes)} required including reserve`, `${formatBytes(current.storage.available_bytes)} free`),
    resultRow(current.system.high_current_load ? "warning" : "ok", t().load,
      current.system.high_current_load ? issueText({ code: "current_load_high", message: "" }) : "No high-load warning", current.system.high_current_load ? "!" : "OK"),
    resultRow(current.system.metal_available ? "ok" : "error", t().metal, "MLX GPU check", current.system.metal_available ? "OK" : "—"),
  ].join("");
  const issues = [...current.blockers, ...current.warnings]
    .map((item) => `<div class="notice ${current.blockers.includes(item) ? "error" : "warning"}">${escapeHtml(issueText(item))}</div>`).join("");
  const canContinue = current.compatible && (current.warnings.length === 0 || warningAccepted);
  shell(`<div class="narrow"><p class="eyebrow">2 / 5</p><h2>${t().checkingTitle}</h2><p class="lede">${t().checkingBody}</p>
    <div class="results">${rows}</div>${issues}
    ${current.blockers.length ? `<div class="notice error">${t().blocked}</div>` : ""}
    ${current.warnings.length ? `<label class="check notice warning"><input id="warning-accept" type="checkbox" ${warningAccepted ? "checked" : ""}><span>${t().proceedWarning}</span></label>` : ""}
    <div class="actions"><button class="secondary" id="recheck">${t().recheck}</button><button id="preflight-next" ${canContinue ? "" : "disabled"}>${t().continue}</button></div>
  </div>`);
  document.querySelector<HTMLInputElement>("#warning-accept")?.addEventListener("change", (event) => {
    warningAccepted = (event.currentTarget as HTMLInputElement).checked; render();
  });
  setButton("recheck", runPreflight);
  setButton("preflight-next", async () => { await saveStep("prepare"); step = "prepare"; render(); });
}

async function runPreflight(): Promise<void> {
  step = "preflight";
  preflightLoading = true;
  warningAccepted = false;
  render();
  try {
    preflight = await api.preflight() as unknown as Preflight;
  } catch (error) {
    runtimeError = String(error);
    step = "error";
  } finally {
    preflightLoading = false;
    render();
  }
}

function modelsVerified(): boolean {
  return Boolean(preflight?.storage.files.length && preflight.storage.files.every((file) => file.state === "verified"));
}

function renderPreparation(): void {
  const components = (inventory?.components ?? []).map((component, index) => {
    const size = component.files.reduce((sum, file) => sum + file.bytes, 0);
    return `<article class="component"><span class="component-number">0${index + 1}</span><h3>${escapeHtml(component.label)}</h3><p>${formatBytes(size)}</p><button class="text terms" data-url="${escapeHtml(component.terms_url)}">${t().terms}</button></article>`;
  }).join("");
  const active = !["idle", "paused", "failed", "complete"].includes(preparationPhase);
  const percent = downloadBytes > 0 ? Math.min(100, downloadedBytes / downloadBytes * 100) : 0;
  let status = "";
  if (preparationPhase === "verifying") status = `<div class="status-panel"><div class="status-row"><strong>${t().verifying}</strong><span class="spinner"></span></div><div class="progress indeterminate"><span></span></div></div>`;
  else if (preparationPhase === "warming") status = `<div class="status-panel"><div class="status-row"><strong>${t().warming}</strong><span class="spinner"></span></div><div class="progress indeterminate"><span></span></div></div>`;
  else if (preparationPhase === "downloading" || preparationPhase === "retrying") status = `<div class="status-panel"><div class="status-row"><div><strong>${t().current}</strong><div class="small muted">${escapeHtml(preparationDetail)}</div></div><div>${formatBytes(downloadedBytes)} / ${formatBytes(downloadBytes)}<div class="small muted">${t().speed}: ${formatBytes(bytesPerSecond)}/s</div></div></div><div class="progress" style="--progress:${percent.toFixed(1)}%"><span></span></div></div>`;
  else if (preparationPhase === "paused" || preparationPhase === "failed") status = `<div class="notice error"><strong>${t().paused}</strong><div class="small">${escapeHtml(preparationMessage(preparationCode))}</div></div>`;
  const needsDownload = !modelsVerified();
  const canStart = !active && (modelsVerified() || downloadConsent);
  shell(`<div><p class="eyebrow">3 / 5</p><h2>${t().prepareTitle}</h2><p class="lede">${t().prepareBody}</p>
    <div class="components">${components}</div>
    <div class="result"><span class="result-icon">↓</span><div><h3>${t().total}</h3><p>${t().location}</p></div><span class="result-value">${formatBytes(inventory?.total_bytes ?? 0)}</span></div>
    ${needsDownload && !active ? `<label class="check notice"><input id="download-consent" type="checkbox" ${downloadConsent ? "checked" : ""}><span>${t().consent}</span></label>` : ""}
    ${status}
    <div class="actions">
      ${(preparationPhase === "paused" || preparationPhase === "failed") ? `<button class="secondary" id="prep-exit">${t().exit}</button><button id="prepare-start">${t().retry}</button>` : active ? `<button class="secondary" id="prepare-cancel">${t().cancelDownload}</button>` : `<button id="prepare-start" ${canStart ? "" : "disabled"}>${modelsVerified() ? t().verifyWarm : t().prepare}</button>`}
    </div>
  </div>`);
  document.querySelectorAll<HTMLButtonElement>(".terms").forEach((button) => button.addEventListener("click", () => void api.openExternal(button.dataset.url ?? "")));
  document.querySelector<HTMLInputElement>("#download-consent")?.addEventListener("change", (event) => {
    downloadConsent = (event.currentTarget as HTMLInputElement).checked; render();
  });
  setButton("prepare-start", startPreparation);
  setButton("prepare-cancel", () => api.cancelPreparation());
  setButton("prep-exit", () => api.exitDuringPreparation());
}

function preparationMessage(code: string): string {
  const messages: Record<string, { en: string; ru: string }> = {
    network_exhausted: { en: "The network retry budget was exhausted. Continue when the connection is stable.", ru: "Попытки сети исчерпаны. Продолжи, когда соединение станет стабильным." },
    cancelled: { en: "Preparation stopped. Completed and partial files were kept.", ru: "Подготовка остановлена. Готовые и частичные файлы сохранены." },
    disk_space: { en: "There is not enough free space, including the 2 GiB reserve.", ru: "Недостаточно свободного места с учётом резерва 2 ГиБ." },
    disk_full: { en: "The disk became full during the download.", ru: "Во время загрузки диск заполнился." },
    permission_denied: { en: "Hebrew Live cannot write to the model folder.", ru: "Hebrew Live не может записывать в каталог моделей." },
    corrupt_download: { en: "A downloaded file failed its checksum and was isolated.", ru: "Контрольная сумма файла не совпала; повреждённый файл изолирован." },
    corrupt_file: { en: "A local model file is damaged and must be downloaded again.", ru: "Локальный файл модели повреждён, его нужно загрузить заново." },
    runtime: { en: "The model warm-up failed. Safe diagnostics may help identify the cause.", ru: "Прогрев моделей завершился ошибкой. Причину можно уточнить по безопасной диагностике." },
  };
  return messages[code]?.[locale] ?? preparationDetail ?? code;
}

async function startPreparation(): Promise<void> {
  preparationPhase = "verifying";
  preparationCode = "";
  render();
  try { await api.prepare(); }
  catch (error) { preparationPhase = "failed"; preparationCode = String(error).split(":", 1)[0]; render(); }
}

function renderLanguages(): void {
  const options = languages?.targets ?? [];
  shell(`<div class="narrow"><p class="eyebrow">4 / 5</p><h2>${t().languagesTitle}</h2><p class="lede">${t().languagesBody}</p>
    <div class="fields">
      <label class="field"><span>${t().interfaceLanguage}</span><select id="ui-locale"><option value="en" ${selectedUiLocale === "en" ? "selected" : ""}>${t().english}</option><option value="ru" ${selectedUiLocale === "ru" ? "selected" : ""}>${t().russian}</option></select></label>
      <label class="field"><span>${t().translationLanguage}</span><select id="target-language">${options.map((item) => `<option value="${escapeHtml(item.code)}" ${item.code === selectedTarget ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select></label>
    </div>
    <div class="notice"><strong>עברית</strong> · Hebrew is the fixed spoken source for this desktop build.</div>
    <div class="actions"><button id="languages-save">${t().saveLanguages}</button></div>
  </div>`);
  document.querySelector<HTMLSelectElement>("#ui-locale")?.addEventListener("change", (event) => {
    selectedUiLocale = (event.currentTarget as HTMLSelectElement).value as UiLocale;
    locale = selectedUiLocale; render();
  });
  document.querySelector<HTMLSelectElement>("#target-language")?.addEventListener("change", (event) => {
    selectedTarget = (event.currentTarget as HTMLSelectElement).value;
  });
  setButton("languages-save", async () => {
    await api.saveLanguages({ ui_locale: selectedUiLocale, target_language: selectedTarget });
    locale = selectedUiLocale;
    await saveStep("audio", { uiLocale: selectedUiLocale, languageConfigured: true });
    step = "audio"; render();
  });
}

function audioMessage(): string {
  if (audioStatus === "checking") return t().testing;
  if (audioStatus === "signal") return t().signal;
  if (audioStatus === "silent") return t().silent;
  if (audioStatus === "permission") return t().permission;
  if (audioStatus === "device") return t().noDevice;
  if (audioStatus === "error") return locale === "ru" ? "Не удалось проверить входной сигнал." : "The input test could not be completed.";
  return "";
}

function renderAudio(): void {
  const showStatus = audioStatus !== "idle";
  const error = ["permission", "device", "error"].includes(audioStatus);
  shell(`<div class="narrow"><p class="eyebrow">5 / 5</p><h2>${t().audioTitle}</h2><p class="lede">${t().audioBody}</p>
    <label class="check notice"><input id="save-audio" type="checkbox" ${saveAudio ? "checked" : ""}><span><strong>${t().saveAudio}</strong><br><span class="small">${t().audioExplain}</span></span></label>
    ${showStatus ? `<div class="notice ${error ? "error" : audioStatus === "silent" ? "warning" : ""}"><div class="status-row"><strong>${escapeHtml(audioMessage())}</strong>${audioStatus === "checking" ? `<span class="spinner"></span>` : ""}</div>${audioDevice ? `<p class="small">${t().device}: ${escapeHtml(audioDevice)}</p>` : ""}<div class="meter" aria-label="Microphone level" style="--level:${Math.round(audioLevel * 100)}%"><span></span></div></div>` : ""}
    <div class="actions">
      ${audioSaved ? `<button class="secondary" id="mic-retry">${t().tryAgain}</button><button id="audio-continue">${t().openApp}</button>` : `<button id="audio-confirm">${t().confirmTest}</button>`}
    </div>
  </div>`);
  document.querySelector<HTMLInputElement>("#save-audio")?.addEventListener("change", (event) => {
    saveAudio = (event.currentTarget as HTMLInputElement).checked;
  });
  setButton("audio-confirm", async () => {
    await api.confirmAudio({ save_raw_audio: saveAudio });
    audioSaved = true;
    await saveStep("audio", { audioConfirmed: true });
    await testMicrophone();
  });
  setButton("mic-retry", testMicrophone);
  setButton("audio-continue", finishOnboarding);
}

async function testMicrophone(): Promise<void> {
  meterCleanup?.();
  audioStatus = "checking";
  audioDevice = "";
  audioLevel = 0;
  render();
  try {
    const permission = await api.beginMicrophoneCheck();
    if (!permission.granted) { audioStatus = "permission"; render(); return; }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    const track = stream.getAudioTracks()[0];
    if (!track) { audioStatus = "device"; stream.getTracks().forEach((item) => item.stop()); render(); return; }
    audioDevice = track.label || (locale === "ru" ? "Системный микрофон" : "System microphone");
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    let peak = 0;
    let frame = 0;
    let stopped = false;
    const stop = () => {
      if (stopped) return;
      stopped = true;
      cancelAnimationFrame(frame);
      stream.getTracks().forEach((item) => item.stop());
      void context.close();
    };
    meterCleanup = stop;
    const started = performance.now();
    const update = () => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const sample of samples) { const centered = (sample - 128) / 128; sum += centered * centered; }
      audioLevel = Math.min(1, Math.sqrt(sum / samples.length) * 5);
      peak = Math.max(peak, audioLevel);
      const meter = document.querySelector<HTMLElement>(".meter");
      if (meter) meter.style.setProperty("--level", `${Math.round(audioLevel * 100)}%`);
      if (performance.now() - started >= 5_000) {
        stop();
        audioStatus = peak > 0.025 ? "signal" : "silent";
        render();
        return;
      }
      frame = requestAnimationFrame(update);
    };
    frame = requestAnimationFrame(update);
  } catch (error) {
    const name = error instanceof DOMException ? error.name : "";
    audioStatus = name === "NotAllowedError" ? "permission" : name === "NotFoundError" ? "device" : "error";
    render();
  }
}

async function finishOnboarding(): Promise<void> {
  meterCleanup?.(); meterCleanup = null;
  await saveStep("ready", { onboardingComplete: true, audioConfirmed: true });
  step = "launching";
  render();
  try { await api.startBackend(); }
  catch (error) { runtimeError = String(error); step = "error"; render(); }
}

function renderLaunching(): void {
  shell(`<div class="center"><div><span class="spinner"></span><p class="eyebrow">Hebrew Live</p><h2>${t().launchingTitle}</h2><p class="muted">${t().launchingBody}</p></div></div>`);
}

function renderHelp(): void {
  shell(`<div class="narrow"><p class="eyebrow">Hebrew Live</p><h2>${t().helpTitle}</h2><p class="lede">${t().helpBody}</p>
    <div class="results"><div class="result"><span class="result-icon">↗</span><div><h3>GitHub</h3><p>${escapeHtml(bootstrap?.githubUrl ?? "")}</p></div><button class="secondary" id="github">${t().github}</button></div>
    <div class="result"><span class="result-icon">⧉</span><div><h3>${t().copyDiagnostics}</h3><p id="copy-status" class="muted">JSON</p></div><button class="secondary" id="copy">${t().copyDiagnostics}</button></div></div>
    <div class="actions"><button id="help-return">${t().returnApp}</button></div></div>`);
  setButton("github", () => api.openExternal(bootstrap?.githubUrl ?? ""));
  setButton("copy", async () => {
    await api.copyDiagnostics();
    const status = document.querySelector("#copy-status"); if (status) status.textContent = t().copied;
  });
  setButton("help-return", resumeAfterHelp);
}

async function resumeAfterHelp(): Promise<void> {
  if (desktopPreferences?.onboardingComplete && modelsVerified()) await finishOnboarding();
  else if (!desktopPreferences?.onboardingComplete) await resumeOnboarding();
  else await runPreflight();
}

function renderError(): void {
  const code = runtimeError || bootstrap?.controllerError || "backend_stopped_unexpectedly";
  shell(`<div class="center"><div><span class="result-icon" aria-hidden="true">!</span><p class="eyebrow">${escapeHtml(code.split(":", 1)[0])}</p><h2>${t().errorTitle}</h2><p class="muted">${t().errorBody}</p><div class="actions"><button class="secondary" id="error-copy">${t().copyDiagnostics}</button><button id="error-restart">${t().restart}</button></div></div></div>`);
  setButton("error-copy", () => api.copyDiagnostics());
  setButton("error-restart", async () => {
    step = "launching"; render();
    try { await api.restartBackend(); }
    catch (error) { runtimeError = String(error); step = "error"; render(); }
  });
}

function render(): void {
  if (step === "loading") { shell(`<div class="center"><div><span class="spinner"></span><p>${t().working}</p></div></div>`); return; }
  if (step === "welcome") renderWelcome();
  else if (step === "preflight") renderPreflight();
  else if (step === "prepare") renderPreparation();
  else if (step === "languages") renderLanguages();
  else if (step === "audio") renderAudio();
  else if (step === "launching") renderLaunching();
  else if (step === "help") renderHelp();
  else renderError();
}

async function resumeOnboarding(): Promise<void> {
  const last = desktopPreferences?.lastStep ?? "welcome";
  if (last === "prepare") { step = "prepare"; render(); return; }
  if (last === "languages" && modelsVerified()) { step = "languages"; render(); return; }
  if (last === "audio" && modelsVerified()) { step = "audio"; render(); return; }
  if (desktopPreferences?.showWelcome !== false) { step = "welcome"; render(); return; }
  await runPreflight();
}

async function initialize(): Promise<void> {
  render();
  bootstrap = await api.bootstrap() as BootstrapData & { viewReason?: string };
  desktopPreferences = bootstrap.preferences;
  locale = bootstrap.suggestedUiLocale;
  selectedUiLocale = desktopPreferences.uiLocale ?? locale;
  if (!bootstrap.controllerAvailable) {
    runtimeError = bootstrap.controllerError ?? "desktop_controller_unavailable";
    step = "error"; render(); return;
  }
  [inventory, languages, enginePreferences] = await Promise.all([
    api.inventory() as Promise<unknown> as Promise<Inventory>,
    api.languages() as Promise<unknown> as Promise<Languages>,
    api.enginePreferences(),
  ]);
  const supported = new Set((languages.targets ?? []).map((item) => item.code));
  const savedTarget = typeof enginePreferences.target_language === "string" ? enginePreferences.target_language : "";
  selectedTarget = supported.has(savedTarget)
    ? savedTarget
    : preferredTargetLanguage(bootstrap.preferredLanguages, supported);
  const savedUi = enginePreferences.ui_locale;
  if (!desktopPreferences.uiLocale && (savedUi === "en" || savedUi === "ru")) {
    selectedUiLocale = savedUi;
    locale = savedUi;
  }
  saveAudio = enginePreferences.save_raw_audio !== false;
  audioSaved = desktopPreferences.audioConfirmed;
  if (bootstrap.viewReason === "help") { step = "help"; render(); return; }
  if (bootstrap.viewReason === "backend_crash") { runtimeError = bootstrap.controllerError ?? "backend_stopped_unexpectedly"; step = "error"; render(); return; }
  if (!desktopPreferences.onboardingComplete && desktopPreferences.lastStep === "welcome" &&
      desktopPreferences.showWelcome !== false) {
    step = "welcome"; render(); return;
  }
  await runPreflight();
  if (desktopPreferences.onboardingComplete && modelsVerified() && preflight?.compatible) {
    await finishOnboarding();
    return;
  }
  if (!modelsVerified() && desktopPreferences.lastStep !== "welcome") {
    await saveStep("prepare"); step = "prepare"; render(); return;
  }
  await resumeOnboarding();
}

api.onEvent((event: ControllerEvent) => {
  const data = event.data;
  if (event.event === "preparation_phase") {
    preparationPhase = String(data.phase ?? "verifying");
    render();
  } else if (event.event === "verification_file") {
    preparationDetail = String(data.file ?? "");
    preparationPhase = "verifying";
    render();
  } else if (event.event === "download_file_started") {
    preparationPhase = "downloading";
    preparationDetail = String(data.label ?? data.file ?? "");
    downloadedBytes = Number(data.downloaded_bytes ?? 0);
    downloadBytes = Number(data.download_bytes ?? 0);
    render();
  } else if (event.event === "download_progress") {
    preparationPhase = "downloading";
    preparationDetail = String(data.file ?? "");
    downloadedBytes = Number(data.downloaded_bytes ?? 0);
    downloadBytes = Number(data.download_bytes ?? 0);
    bytesPerSecond = Number(data.bytes_per_second ?? 0);
    render();
  } else if (event.event === "download_retry") {
    preparationPhase = "retrying";
    preparationDetail = `${String(data.file ?? "")} · retry ${String(data.attempt ?? "")}/3 · ${String(data.delay_seconds ?? "")}s`;
    render();
  } else if (event.event === "preparation_paused" || event.event === "preparation_failed") {
    preparationPhase = event.event === "preparation_paused" ? "paused" : "failed";
    preparationCode = String(data.code ?? "runtime");
    preparationDetail = String(data.message ?? "");
    render();
  } else if (event.event === "preparation_complete") {
    preparationPhase = "complete";
    void (async () => {
      preflight = await api.preflight() as unknown as Preflight;
      await saveStep("languages");
      step = "languages";
      render();
    })();
  } else if (event.event === "backend_starting") {
    step = "launching"; render();
  } else if (event.event === "backend_exit" && data.expected !== true) {
    runtimeError = "backend_stopped_unexpectedly";
    step = "error"; render();
  }
});

void initialize().catch((error) => {
  runtimeError = String(error);
  step = "error";
  render();
});
