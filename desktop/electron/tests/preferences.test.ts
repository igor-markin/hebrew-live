import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  acceptDesktopAgreement, DEFAULT_PREFERENCES, readDesktopPreferences, readSavedDarkTheme, saveDesktopPreferences,
  WINDOW_BACKGROUND, windowBackground,
} from "../src/preferences.ts";
import { AGREEMENT_VERSION } from "../src/shared.ts";

test("desktop onboarding preferences are separate, atomic, and private", () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-preferences-"));
  const file = path.join(folder, "desktop", "preferences.json");
  const saved = saveDesktopPreferences(file, DEFAULT_PREFERENCES, {
    uiLocale: "en",
    languageConfigured: true,
    audioConfirmed: true,
    showWelcome: false,
  });
  assert.equal(readDesktopPreferences(file).uiLocale, "en");
  assert.equal(readDesktopPreferences(file).asrBackend, "streaming");
  assert.equal(saved.showWelcome, false);
  assert.equal(statSync(file).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(file, "utf8")).schemaVersion, 1);
});

test("unsupported preference fields and interface languages are rejected", () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-preferences-"));
  const file = path.join(folder, "preferences.json");
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { token: "secret" } as never), /unsupported/);
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { uiLocale: "he" } as never), /unsupported/);
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { asrBackend: "multilingual" } as never), /unsupported/);
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { asrBackend: "fast" } as never), /unsupported/);
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { acceptedAgreementVersion: AGREEMENT_VERSION }), /unsupported/);
});

test("fixed streaming recognition persists and is validated on read", () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-recognition-"));
  const file = path.join(folder, "preferences.json");
  saveDesktopPreferences(file, DEFAULT_PREFERENCES, { asrBackend: "streaming" });
  assert.equal(readDesktopPreferences(file).asrBackend, "streaming");
  writeFileSync(file, JSON.stringify({ ...DEFAULT_PREFERENCES, asrBackend: "turbo" }));
  assert.equal(readDesktopPreferences(file).asrBackend, "streaming");
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { asrBackend: "turbo" } as never), /unsupported/);
});

test("explicit agreement acceptance persists its version and timestamp", () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-agreement-"));
  const file = path.join(folder, "preferences.json");
  const at = new Date("2026-09-23T12:00:00.000Z");
  const saved = acceptDesktopAgreement(file, DEFAULT_PREFERENCES, AGREEMENT_VERSION, at);
  assert.equal(saved.acceptedAgreementVersion, AGREEMENT_VERSION);
  assert.equal(readDesktopPreferences(file).acceptedAgreementAt, at.toISOString());
  assert.equal(statSync(file).mode & 0o777, 0o600);
});

test("a saved dark theme is known before the first window, and anything else stays light", () => {
  const home = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-theme-"));
  assert.equal(readSavedDarkTheme(home), false);                       // no engine preferences yet
  const folder = path.join(home, ".local-settings");
  mkdirSync(folder);
  const file = path.join(folder, "preferences.json");
  for (const [text, dark] of [['{"schema_version":4,"dark_theme":true}', true], ['{"dark_theme":false}', false],
                              ['{"dark_theme":"yes"}', false], ['[true]', false], ['null', false], ['{broken', false]] as const) {
    writeFileSync(file, text);
    assert.equal(readSavedDarkTheme(home), dark, text);
  }
  assert.equal(windowBackground(true), WINDOW_BACKGROUND.dark);
  assert.equal(windowBackground(false), "#eef4ef");                    // the light window is unchanged
});

test("the dark window colour is the live page's dark background", () => {
  const css = readFileSync(new URL("../../../experiments/publication-ui-preview/src/styles.css", import.meta.url), "utf8");
  const dark = /:root\[data-theme="dark"\]\s*\{[^}]*--background:\s*(#[0-9a-f]{6})/i.exec(css);
  assert.equal(dark?.[1], WINDOW_BACKGROUND.dark);
});
