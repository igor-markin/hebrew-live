import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, statSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { acceptDesktopAgreement, DEFAULT_PREFERENCES, readDesktopPreferences, saveDesktopPreferences } from "../src/preferences.ts";
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
  assert.equal(readDesktopPreferences(file).asrBackend, "fast");
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
  assert.throws(() => saveDesktopPreferences(file, DEFAULT_PREFERENCES, { acceptedAgreementVersion: AGREEMENT_VERSION }), /unsupported/);
});

test("optional accurate mode persists and is validated on read", () => {
  const folder = mkdtempSync(path.join(os.tmpdir(), "hebrew-live-recognition-"));
  const file = path.join(folder, "preferences.json");
  saveDesktopPreferences(file, DEFAULT_PREFERENCES, { asrBackend: "turbo" });
  assert.equal(readDesktopPreferences(file).asrBackend, "turbo");
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
