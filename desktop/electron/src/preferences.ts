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
  asrBackend: "fast",
};

export function readDesktopPreferences(file: string): DesktopPreferences {
  try {
    const parsed = JSON.parse(readFileSync(file, "utf8")) as Partial<DesktopPreferences>;
    if (parsed.schemaVersion !== 1) return { ...DEFAULT_PREFERENCES };
    return {
      ...DEFAULT_PREFERENCES,
      ...parsed,
      uiLocale: parsed.uiLocale === "ru" || parsed.uiLocale === "en" ? parsed.uiLocale : undefined,
      asrBackend: parsed.asrBackend === "turbo" ? "turbo" : "fast",
      schemaVersion: 1,
    };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function saveDesktopPreferences(file: string, current: DesktopPreferences,
                                       patch: Partial<DesktopPreferences>): DesktopPreferences {
  const allowed = new Set([
    "onboardingComplete", "showWelcome", "lastStep", "uiLocale", "languageConfigured", "audioConfirmed", "asrBackend",
  ]);
  if (Object.keys(patch).some((key) => !allowed.has(key))) throw new Error("unsupported_preference");
  if (patch.uiLocale !== undefined && patch.uiLocale !== "en" && patch.uiLocale !== "ru") {
    throw new Error("unsupported_interface_language");
  }
  if (patch.asrBackend !== undefined && patch.asrBackend !== "fast" && patch.asrBackend !== "turbo") {
    throw new Error("unsupported_recognition_mode");
  }
  const result: DesktopPreferences = { ...current, ...patch, schemaVersion: 1 };
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.tmp-${process.pid}`;
  writeFileSync(temporary, `${JSON.stringify(result, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  chmodSync(temporary, 0o600);
  renameSync(temporary, file);
  return result;
}

export function acceptDesktopAgreement(file: string, current: DesktopPreferences,
                                       version: string, at = new Date()): DesktopPreferences {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(version)) throw new Error("invalid_agreement_version");
  return saveAcceptedAgreement(file, current, version, at.toISOString());
}

function saveAcceptedAgreement(file: string, current: DesktopPreferences, version: string, at: string): DesktopPreferences {
  const result: DesktopPreferences = { ...current, acceptedAgreementVersion: version, acceptedAgreementAt: at };
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.tmp-${process.pid}`;
  writeFileSync(temporary, `${JSON.stringify(result, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  chmodSync(temporary, 0o600);
  renameSync(temporary, file);
  return result;
}
