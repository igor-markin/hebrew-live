import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  Menu,
  session,
  shell,
  systemPreferences,
  type MessageBoxOptions,
  type MessageBoxReturnValue,
} from "electron";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { DesktopControllerClient } from "./protocol.js";
import { acceptDesktopAgreement, DEFAULT_PREFERENCES, readDesktopPreferences, saveDesktopPreferences } from "./preferences.js";
import { allowedBackendUrl, allowedExternalUrl, preferredUiLocale } from "./security.js";
import { AGREEMENT_VERSION, type BootstrapData, type ControllerEvent, type DesktopPreferences, type RecognitionMode, type UiLocale } from "./shared.js";
import { quitSituation, type BackendState } from "./lifecycle.js";
import { navigateBackend } from "./backendNavigation.js";

const APP_DATA_FOLDER = "Hebrew Live CLI";
const GITHUB_URL = "https://github.com/igor-markin/hebrew-live";

function bundledProofHome(): string | undefined {
  if (!app.isPackaged) return undefined;
  const file = path.join(process.resourcesPath, "desktop-launch.json");
  if (!existsSync(file)) return undefined;
  try {
    const value = JSON.parse(readFileSync(file, "utf8")) as { data_home?: unknown };
    return typeof value.data_home === "string" && path.isAbsolute(value.data_home)
      ? path.resolve(value.data_home)
      : undefined;
  } catch {
    return undefined;
  }
}

const dataHome = process.env.HEBREW_LIVE_HOME
  ? path.resolve(process.env.HEBREW_LIVE_HOME)
  : bundledProofHome() ?? path.join(app.getPath("appData"), APP_DATA_FOLDER);
const desktopFolder = path.join(dataHome, "desktop");
const modelsFolder = path.join(dataHome, "models");
const preferencesFile = path.join(desktopFolder, "preferences.json");
app.setPath("userData", path.join(desktopFolder, "electron"));

let mainWindow: BrowserWindow | null = null;
let controller: DesktopControllerClient | null = null;
let controllerStarting: Promise<void> | null = null;
let controllerError: string | undefined;
let preferences: DesktopPreferences = { ...DEFAULT_PREFERENCES };
let preparing = false;
let allowWindowClose = false;
let quitInProgress = false;
let microphoneExpectedUntil = 0;
let backendBase: string | null = null;
let prepViewReason: "normal" | "help" | "backend_crash" | "accurate_setup" = "normal";
let navigationGeneration = 0;

function publicError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.split(":", 1)[0] || "desktop_error";
}

function engineExecutable(): string {
  if (app.isPackaged) return path.join(process.resourcesPath, "engine", "Hebrew Live");
  return path.resolve(app.getAppPath(), "../../dist/desktop-engine/Hebrew Live/Hebrew Live");
}

function onboardingImages(): string[] {
  const folder = app.isPackaged
    ? path.join(process.resourcesPath, "onboarding")
    : path.resolve(app.getAppPath(), "../../docs/images");
  return ["live-translation.jpg", "language-settings.jpg", "session-archive.jpg"]
    .map((name) => pathToFileURL(path.join(folder, name)).href);
}

function legalText(document: UiLocale | "gemma"): string {
  const name = document === "gemma" ? "gemma_terms.txt" : `EULA.${document}.txt`;
  const file = app.isPackaged
    ? path.join(process.resourcesPath, "legal", name)
    : document === "gemma" ? path.resolve(app.getAppPath(), "../../src/hebrew_live/gemma_terms.txt")
      : path.resolve(app.getAppPath(), `../../docs/legal/${name}`);
  return readFileSync(file, "utf8");
}

function requireAcceptedAgreement(): void {
  if (preferences.acceptedAgreementVersion !== AGREEMENT_VERSION) throw new Error("agreement_not_accepted");
}

function prepFile(): string {
  return path.join(app.getAppPath(), "build", "renderer", "index.html");
}

function sendEvent(event: ControllerEvent): void {
  const window = mainWindow;
  if (window && !window.isDestroyed()) window.webContents.send("desktop:event", event);
}

function showMessageBox(options: MessageBoxOptions): Promise<MessageBoxReturnValue> {
  return mainWindow ? dialog.showMessageBox(mainWindow, options) : dialog.showMessageBox(options);
}

async function loadPreparation(reason: typeof prepViewReason = "normal"): Promise<void> {
  navigationGeneration += 1;
  prepViewReason = reason;
  backendBase = null;
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const window = mainWindow;
  await window.loadFile(prepFile());
  if (!window.isDestroyed()) window.webContents.invalidate();
}

async function showBackend(url: string): Promise<void> {
  const window = mainWindow;
  if (!window || window.isDestroyed()) return;
  const generation = ++navigationGeneration;
  const current = () => generation === navigationGeneration && mainWindow === window;
  const loaded = await navigateBackend(window, url, current);
  if (loaded && current() && !window.isDestroyed()) window.webContents.invalidate();
  if (!loaded && current() && !window.isDestroyed()) {
    controllerError = "backend_ui_unavailable";
    await loadPreparation("backend_crash");
  }
}

function handleControllerEvent(event: ControllerEvent): void {
  if (event.event === "preparation_complete" || event.event === "preparation_paused" ||
      event.event === "preparation_failed") preparing = false;
  if (event.event === "backend_ready") {
    const raw = event.data.url;
    const allowed = typeof raw === "string" ? allowedBackendUrl(raw) : null;
    if (!allowed) {
      controllerError = "invalid_backend_url";
      void loadPreparation("backend_crash");
    } else {
      backendBase = allowed.href;
      void showBackend(allowed.href);
    }
  }
  if (event.event === "backend_exit" && event.data.expected !== true && !quitInProgress) {
    controllerError = "backend_stopped_unexpectedly";
    void loadPreparation("backend_crash");
  }
  sendEvent(event);
}

async function ensureController(): Promise<void> {
  if (controller) {
    await controller.ready();
    return;
  }
  if (controllerStarting) return controllerStarting;
  controllerStarting = (async () => {
    const executable = engineExecutable();
    if (!existsSync(executable)) throw new Error("packaged_engine_missing");
    const created = new DesktopControllerClient(
      executable,
      ["--desktop-control", "--data-home", dataHome, "--models", modelsFolder],
      path.join(desktopFolder, "control.log"),
    );
    created.onEvent(handleControllerEvent);
    created.on("exit", () => {
      if (controller === created) controller = null;
      if (!quitInProgress) {
        controllerError = "controller_stopped_unexpectedly";
        void loadPreparation("backend_crash");
      }
    });
    await created.ready();
    controller = created;
    controllerError = undefined;
  })().catch((error: unknown) => {
    controllerError = publicError(error);
    throw error;
  }).finally(() => {
    controllerStarting = null;
  });
  return controllerStarting;
}

async function control(command: string, payload: Record<string, unknown> = {}):
  Promise<Record<string, unknown>> {
  await ensureController();
  if (!controller) throw new Error("desktop_controller_unavailable");
  return controller.request(command, payload);
}

function installNavigationPolicy(window: BrowserWindow): void {
  window.webContents.setWindowOpenHandler(({ url }) => {
    const external = allowedExternalUrl(url);
    if (external) void shell.openExternal(external.href);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    const prep = pathToFileURL(prepFile()).href;
    if (url === prep || (backendBase !== null && url.startsWith(backendBase))) return;
    event.preventDefault();
    const external = allowedExternalUrl(url);
    if (external) void shell.openExternal(external.href);
  });
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    title: "Hebrew Live",
    width: 1120,
    height: 780,
    minWidth: 760,
    minHeight: 620,
    show: false,
    backgroundColor: "#eef4ef",
    webPreferences: {
      preload: path.join(app.getAppPath(), "build", "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  });
  installNavigationPolicy(window);
  window.once("ready-to-show", () => window.show());
  window.on("close", (event) => {
    if (allowWindowClose) return;
    event.preventDefault();
    void requestApplicationQuit();
  });
  void window.loadFile(prepFile()).then(() => {
    if (!window.isDestroyed()) window.webContents.invalidate();
  });
  return window;
}

function installPermissions(): void {
  session.defaultSession.setPermissionCheckHandler((webContents, permission, _origin, details) => {
    const audioOnly = permission === "media" &&
      (!details.mediaType || details.mediaType === "audio");
    return audioOnly && Date.now() <= microphoneExpectedUntil && webContents === mainWindow?.webContents;
  });
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const mediaTypes = "mediaTypes" in details && Array.isArray(details.mediaTypes) ? details.mediaTypes : [];
    const audioOnly = permission === "media" && !mediaTypes.includes("video");
    callback(audioOnly && Date.now() <= microphoneExpectedUntil && webContents === mainWindow?.webContents);
  });
}

function installMenu(): void {
  const russian = (preferences.uiLocale ?? preferredUiLocale(app.getPreferredSystemLanguages())) === "ru";
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: "Hebrew Live",
      submenu: [
        { label: russian ? "О Hebrew Live" : "About Hebrew Live", role: "about" },
        { type: "separator" },
        {
          label: russian ? "Выйти из Hebrew Live" : "Quit Hebrew Live",
          accelerator: "CommandOrControl+Q",
          click: () => void requestApplicationQuit(),
        },
      ],
    },
    { label: russian ? "Правка" : "Edit", submenu: [{ role: "undo" }, { role: "redo" }, { type: "separator" },
      { role: "cut" }, { role: "copy" }, { role: "paste" }, { role: "selectAll" }] },
    { label: russian ? "Окно" : "Window", submenu: [{ role: "minimize" }, { role: "zoom" }, { role: "front" }] },
    {
      label: russian ? "Помощь" : "Help",
      submenu: [{
        label: russian ? "Помощь и обратная связь" : "Help and Feedback",
        click: () => void loadPreparation("help"),
      }],
    },
  ]));
}

function quitCopy() {
  const russian = (preferences.uiLocale ?? preferredUiLocale(app.getPreferredSystemLanguages())) === "ru";
  return russian ? {
    preparingMessage: "Остановить подготовку и выйти из Hebrew Live?",
    preparingDetail: "Загруженные части сохранятся и будут проверены при продолжении.",
    stopDownload: "Остановить загрузку и выйти",
    stay: "Остаться",
    recordingMessage: "Завершить запись и выйти из Hebrew Live?",
    recordingDetail: "Hebrew Live завершит принятую речь за срок до 120 секунд. Оставшуюся обработку можно отменить на рабочем экране.",
    finishAndQuit: "Завершить запись и выйти",
    timeoutMessage: "Обработка всё ещё продолжается.",
    timeoutDetail: "Отменить оставшуюся обработку и пометить сессию неполной или остаться в Hebrew Live.",
    cancelAndQuit: "Отменить обработку и выйти",
  } : {
    preparingMessage: "Stop preparation and quit Hebrew Live?",
    preparingDetail: "Downloaded parts will be kept and checked when you continue.",
    stopDownload: "Stop download and quit",
    stay: "Stay",
    recordingMessage: "Finish the recording and quit Hebrew Live?",
    recordingDetail: "Hebrew Live will finish accepted audio for up to 120 seconds. You can cancel remaining processing in the working screen.",
    finishAndQuit: "Finish recording and quit",
    timeoutMessage: "Processing is still running.",
    timeoutDetail: "Cancel the remaining processing and mark the session incomplete, or stay in Hebrew Live.",
    cancelAndQuit: "Cancel processing and quit",
  };
}

async function waitUntil(predicate: () => boolean, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return predicate();
}

async function waitForBackendExit(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const state = await control("backend_state") as BackendState;
      if (!state.running) return true;
    } catch {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function finishQuit(): Promise<void> {
  try {
    await controller?.close();
  } finally {
    controller = null;
    allowWindowClose = true;
    app.quit();
  }
}

async function requestApplicationQuit(): Promise<void> {
  if (quitInProgress) return;
  quitInProgress = true;
  let state: BackendState | null = null;
  try {
    if (controller) state = await controller.request("backend_state") as BackendState;
  } catch {
    state = null;
  }
  const situation = quitSituation(preparing, state);
  const copy = quitCopy();
  if (situation === "preparing") {
    const result = await showMessageBox({
      type: "question",
      message: copy.preparingMessage,
      detail: copy.preparingDetail,
      buttons: [copy.stopDownload, copy.stay],
      defaultId: 1,
      cancelId: 1,
    });
    if (result.response === 1) {
      quitInProgress = false;
      return;
    }
    try { await controller?.request("cancel_prepare", {}, 5_000); } catch { /* controller cleanup remains */ }
    await waitUntil(() => !preparing, 35_000);
    await finishQuit();
    return;
  }
  if (situation === "recording") {
    const result = await showMessageBox({
      type: "question",
      message: copy.recordingMessage,
      detail: copy.recordingDetail,
      buttons: [copy.finishAndQuit, copy.stay],
      defaultId: 0,
      cancelId: 1,
    });
    if (result.response === 1) {
      quitInProgress = false;
      return;
    }
    try { await controller?.request("backend_action", { action: "quit" }, 5_000); } catch { /* close below */ }
    if (!await waitForBackendExit(120_000)) {
      const timeout = await showMessageBox({
        type: "warning",
        message: copy.timeoutMessage,
        detail: copy.timeoutDetail,
        buttons: [copy.cancelAndQuit, copy.stay],
        defaultId: 1,
        cancelId: 1,
      });
      if (timeout.response === 1) {
        quitInProgress = false;
        return;
      }
      try { await controller?.request("backend_action", { action: "cancel_processing" }, 5_000); } catch { /* close below */ }
      await waitForBackendExit(10_000);
    }
    await finishQuit();
    return;
  }
  if (state?.running) {
    try { await controller?.request("backend_action", { action: "quit" }, 5_000); } catch { /* close below */ }
    await waitForBackendExit(5_000);
  }
  await finishQuit();
}

function registerIpc(): void {
  ipcMain.handle("desktop:bootstrap", async (): Promise<BootstrapData & { viewReason: string }> => {
    try { await ensureController(); } catch { /* preparation UI must stay available */ }
    return {
      preferences,
      preferredLanguages: app.getPreferredSystemLanguages(),
      suggestedUiLocale: preferences.uiLocale ?? preferredUiLocale(app.getPreferredSystemLanguages()),
      controllerAvailable: controller !== null,
      controllerError,
      onboardingImages: onboardingImages(),
      githubUrl: GITHUB_URL,
      viewReason: prepViewReason,
    };
  });
  ipcMain.handle("desktop:inventory", () => control("inventory"));
  ipcMain.handle("desktop:languages", () => control("languages"));
  ipcMain.handle("desktop:preflight", () => control("preflight"));
  ipcMain.handle("desktop:legal-text", (_event, document: UiLocale | "gemma") =>
    legalText(document === "ru" || document === "gemma" ? document : "en"));
  ipcMain.handle("desktop:accept-agreement", () => {
    preferences = acceptDesktopAgreement(preferencesFile, preferences, AGREEMENT_VERSION);
    return preferences;
  });
  ipcMain.handle("desktop:prepare", async () => {
    requireAcceptedAgreement();
    preparing = true;
    try { return await control("prepare"); }
    catch (error) { preparing = false; throw error; }
  });
  ipcMain.handle("desktop:prepare-accurate", async () => {
    requireAcceptedAgreement();
    if (preferences.asrBackend !== "turbo") throw new Error("accurate_mode_not_selected");
    preparing = true;
    try { return await control("prepare", { asr_backend: "turbo" }); }
    catch (error) { preparing = false; throw error; }
  });
  ipcMain.handle("desktop:accurate-status", () => control("accurate_status"));
  ipcMain.handle("desktop:set-recognition-mode", async (_event, mode: RecognitionMode) => {
    requireAcceptedAgreement();
    if (mode !== "fast" && mode !== "turbo") throw new Error("unsupported_recognition_mode");
    if (preparing) throw new Error("model_preparation_running");
    const state = await control("backend_state") as BackendState;
    if (state.running && (!state.ready || (!state.finished && state.recording_started !== false))) {
      throw new Error("finish_current_recording_first");
    }
    if (mode === preferences.asrBackend) return;
    if (state.running) {
      await control("backend_action", { action: "quit" });
      if (!await waitForBackendExit(30_000)) throw new Error("backend_did_not_stop");
    }
    preferences = saveDesktopPreferences(preferencesFile, preferences, { asrBackend: mode });
    if (mode === "turbo" && !(await control("accurate_status")).ready) {
      await loadPreparation("accurate_setup");
      return;
    }
    await control("start_backend", { asr_backend: mode });
  });
  ipcMain.handle("desktop:cancel-preparation", () => control("cancel_prepare"));
  ipcMain.handle("desktop:engine-preferences", () => control("preferences"));
  ipcMain.handle("desktop:save-languages", (_event, values: Record<string, unknown>) =>
    control("save_preferences", values));
  ipcMain.handle("desktop:confirm-audio", (_event, values: Record<string, unknown>) =>
    control("save_preferences", values));
  ipcMain.handle("desktop:save-onboarding", (_event, patch: Partial<DesktopPreferences>) => {
    preferences = saveDesktopPreferences(preferencesFile, preferences, patch);
    if (patch.uiLocale) installMenu();
    return preferences;
  });
  ipcMain.handle("desktop:microphone", async () => {
    microphoneExpectedUntil = Date.now() + 60_000;
    let granted = systemPreferences.getMediaAccessStatus("microphone") === "granted";
    if (!granted) granted = await systemPreferences.askForMediaAccess("microphone");
    return { granted, status: systemPreferences.getMediaAccessStatus("microphone") };
  });
  ipcMain.handle("desktop:start-backend", () => {
    requireAcceptedAgreement();
    return control("start_backend", { asr_backend: preferences.asrBackend });
  });
  ipcMain.handle("desktop:restart-backend", async () => {
    requireAcceptedAgreement();
    controllerError = undefined;
    return control("start_backend", { asr_backend: preferences.asrBackend });
  });
  ipcMain.handle("desktop:quit", () => requestApplicationQuit());
  ipcMain.handle("desktop:set-ui-locale", (_event, value: "en" | "ru") => {
    preferences = saveDesktopPreferences(preferencesFile, preferences, { uiLocale: value });
    installMenu();
    return preferences;
  });
  ipcMain.handle("desktop:exit-preparation", () => requestApplicationQuit());
  ipcMain.handle("desktop:help", () => loadPreparation("help"));
  ipcMain.handle("desktop:open-external", async (_event, raw: string) => {
    const allowed = allowedExternalUrl(raw);
    if (!allowed) return false;
    await shell.openExternal(allowed.href);
    return true;
  });
  ipcMain.handle("desktop:copy-diagnostics", async () => {
    let engine: Record<string, unknown> = {};
    try { engine = await control("diagnostics"); } catch { engine = { available: false, error: controllerError }; }
    clipboard.writeText(JSON.stringify({
      schema_version: 1,
      application: "Hebrew Live",
      app_version: app.getVersion(),
      electron: process.versions.electron,
      platform: process.platform,
      architecture: process.arch,
      engine,
    }, null, 2));
    return true;
  });
}

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.whenReady().then(() => {
    preferences = readDesktopPreferences(preferencesFile);
    installPermissions();
    registerIpc();
    installMenu();
    mainWindow = createWindow();
    void ensureController().catch(() => undefined);
  });
  app.on("window-all-closed", () => void requestApplicationQuit());
  app.on("before-quit", (event) => {
    if (allowWindowClose) return;
    event.preventDefault();
    void requestApplicationQuit();
  });
}
