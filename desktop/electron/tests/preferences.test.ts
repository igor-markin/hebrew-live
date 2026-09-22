import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { DEFAULT_PREFERENCES, readDesktopPreferences, saveDesktopPreferences } from "../src/preferences.ts";

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
  assert.equal(saved.showWelcome, false);
  assert.equal(statSync(file).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(file, "utf8")).schemaVersion, 1);
});

test("unsupported preference fields and interface languages are rejected", () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-preferences-"));
  const file = path.join(folder, "preferences.json");
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { token: "secret" } as never), /unsupported/);
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { uiLocale: "he" } as never), /unsupported/);
});
