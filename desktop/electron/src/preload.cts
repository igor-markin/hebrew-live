import { contextBridge, ipcRenderer } from "electron";
import type { ControllerEvent, DesktopPreferences, HebrewLiveBridge, UiLocale } from "./shared.js";

const bridge: HebrewLiveBridge = {
  bootstrap: () => ipcRenderer.invoke("desktop:bootstrap"),
  inventory: () => ipcRenderer.invoke("desktop:inventory"),
  languages: () => ipcRenderer.invoke("desktop:languages"),
  preflight: () => ipcRenderer.invoke("desktop:preflight"),
  prepare: () => ipcRenderer.invoke("desktop:prepare"),
  cancelPreparation: () => ipcRenderer.invoke("desktop:cancel-preparation"),
  enginePreferences: () => ipcRenderer.invoke("desktop:engine-preferences"),
  saveLanguages: (values: { ui_locale: UiLocale; target_language: string }) =>
    ipcRenderer.invoke("desktop:save-languages", values),
  confirmAudio: (values: { save_raw_audio: boolean }) => ipcRenderer.invoke("desktop:confirm-audio", values),
  saveOnboarding: (values: Partial<DesktopPreferences>) => ipcRenderer.invoke("desktop:save-onboarding", values),
  beginMicrophoneCheck: () => ipcRenderer.invoke("desktop:microphone"),
  startBackend: () => ipcRenderer.invoke("desktop:start-backend"),
  restartBackend: () => ipcRenderer.invoke("desktop:restart-backend"),
  requestQuit: () => ipcRenderer.invoke("desktop:quit"),
  setUiLocale: (value: UiLocale) => ipcRenderer.invoke("desktop:set-ui-locale", value),
  exitDuringPreparation: () => ipcRenderer.invoke("desktop:exit-preparation"),
  showHelp: () => ipcRenderer.invoke("desktop:help"),
  openExternal: (url: string) => ipcRenderer.invoke("desktop:open-external", url),
  copyDiagnostics: () => ipcRenderer.invoke("desktop:copy-diagnostics"),
  onEvent: (listener: (event: ControllerEvent) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, value: ControllerEvent) => listener(value);
    ipcRenderer.on("desktop:event", handler);
    return () => ipcRenderer.removeListener("desktop:event", handler);
  },
};

const workingBridge = {
  requestQuit: bridge.requestQuit,
  showHelp: bridge.showHelp,
  setUiLocale: bridge.setUiLocale,
};

contextBridge.exposeInMainWorld("hebrewLive", window.location.protocol === "file:" ? bridge : workingBridge);
