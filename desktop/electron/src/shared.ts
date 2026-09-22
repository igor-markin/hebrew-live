export const PROTOCOL_VERSION = 1;

export type UiLocale = "en" | "ru";

export interface DesktopPreferences {
  schemaVersion: 1;
  onboardingComplete: boolean;
  showWelcome: boolean;
  lastStep: string;
  uiLocale?: UiLocale;
  languageConfigured: boolean;
  audioConfirmed: boolean;
}

export interface ControllerEvent {
  v: number;
  kind: "event";
  event: string;
  data: Record<string, unknown>;
}

export interface BootstrapData {
  preferences: DesktopPreferences;
  preferredLanguages: string[];
  suggestedUiLocale: UiLocale;
  controllerAvailable: boolean;
  controllerError?: string;
  onboardingImages: string[];
  githubUrl: string;
}

export interface HebrewLiveBridge {
  bootstrap(): Promise<BootstrapData>;
  inventory(): Promise<Record<string, unknown>>;
  languages(): Promise<Record<string, unknown>>;
  preflight(): Promise<Record<string, unknown>>;
  prepare(): Promise<Record<string, unknown>>;
  cancelPreparation(): Promise<Record<string, unknown>>;
  enginePreferences(): Promise<Record<string, unknown>>;
  saveLanguages(values: { ui_locale: UiLocale; target_language: string }): Promise<Record<string, unknown>>;
  confirmAudio(values: { save_raw_audio: boolean }): Promise<Record<string, unknown>>;
  saveOnboarding(values: Partial<DesktopPreferences>): Promise<DesktopPreferences>;
  beginMicrophoneCheck(): Promise<{ granted: boolean; status: string }>;
  startBackend(): Promise<Record<string, unknown>>;
  restartBackend(): Promise<Record<string, unknown>>;
  requestQuit(): Promise<void>;
  setUiLocale(value: UiLocale): Promise<DesktopPreferences>;
  exitDuringPreparation(): Promise<void>;
  showHelp(): Promise<void>;
  openExternal(url: string): Promise<boolean>;
  copyDiagnostics(): Promise<boolean>;
  onEvent(listener: (event: ControllerEvent) => void): () => void;
}
