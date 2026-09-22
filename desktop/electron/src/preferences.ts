import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { DesktopPreferences } from "./shared.js";

export const DEFAULT_PREFERENCES: DesktopPreferences = {
  schemaVersion: 1,
  onboardingComplete: false,
  showWelcome: true,
  lastStep: "welcome",
  languageConfigured: false,
  audioConfirmed: false,
};

export function readDesktopPreferences(file: string): DesktopPreferences {
  try {
    const parsed = JSON.parse(readFileSync(file, "utf8")) as Partial<DesktopPreferences>;
    if (parsed.schemaVersion !== 1) return { ...DEFAULT_PREFERENCES };
    return {
      ...DEFAULT_PREFERENCES,
      ...parsed,
      uiLocale: parsed.uiLocale === "ru" || parsed.uiLocale === "en" ? parsed.uiLocale : undefined,
      schemaVersion: 1,
    };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function saveDesktopPreferences(file: string, current: DesktopPreferences,
                                       patch: Partial<DesktopPreferences>): DesktopPreferences {
  const allowed = new Set([
    "onboardingComplete", "showWelcome", "lastStep", "uiLocale", "languageConfigured", "audioConfirmed",
  ]);
  if (Object.keys(patch).some((key) => !allowed.has(key))) throw new Error("unsupported_preference");
  if (patch.uiLocale !== undefined && patch.uiLocale !== "en" && patch.uiLocale !== "ru") {
    throw new Error("unsupported_interface_language");
  }
  const result: DesktopPreferences = { ...current, ...patch, schemaVersion: 1 };
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.tmp-${process.pid}`;
  writeFileSync(temporary, `${JSON.stringify(result, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  chmodSync(temporary, 0o600);
  renameSync(temporary, file);
  return result;
}
