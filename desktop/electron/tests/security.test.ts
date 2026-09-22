import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { allowedBackendUrl, allowedExternalUrl, preferredTargetLanguage, preferredUiLocale } from "../src/security.ts";

test("preferred languages follow macOS ordering and fall back to English", () => {
  assert.equal(preferredUiLocale(["fr-FR", "ru-RU", "en-US"]), "ru");
  assert.equal(preferredUiLocale(["fr-FR", "de-DE"]), "en");
  assert.equal(preferredTargetLanguage(["fr-FR", "ru-RU"], new Set(["en", "ru"])), "ru");
  assert.equal(preferredTargetLanguage(["fr-FR"], new Set(["en", "ru"])), "en");
});

test("English interface and Russian translation remain independent", () => {
  assert.equal(preferredUiLocale(["en-US", "ru-RU"]), "en");
  assert.equal(preferredTargetLanguage(["ru-RU", "en-US"], new Set(["en", "ru"])), "ru");
});

test("external and backend URLs are strictly constrained", () => {
  assert.equal(allowedExternalUrl("https://github.com/igor-markin/hebrew-live")?.hostname, "github.com");
  assert.equal(allowedExternalUrl("http://github.com/igor-markin/hebrew-live"), null);
  assert.equal(allowedExternalUrl("https://example.com"), null);
  assert.ok(allowedBackendUrl("http://127.0.0.1:43111/abcdefghijklmnopqrstuvwxyzABCDEFGH/live/"));
  assert.equal(allowedBackendUrl("http://localhost:43111/abcdefghijklmnopqrstuvwxyzABCDEFGH/live/"), null);
  assert.equal(allowedBackendUrl("http://127.0.0.1:43111/short/live/"), null);
  assert.equal(allowedBackendUrl("http://127.0.0.1:43111/abcdefghijklmnopqrstuvwxyzABCDEFGH/live/?token=x"), null);
});

test("working renderer preload exposes only lifecycle and locale commands", () => {
  const source = readFileSync(new URL("../src/preload.cts", import.meta.url), "utf8");
  const block = source.match(/const workingBridge = \{([\s\S]*?)\n\};/)?.[1] ?? "";
  const commands = [...block.matchAll(/^\s*(\w+):/gm)].map((match) => match[1]).sort();
  assert.deepEqual(commands, ["requestQuit", "setUiLocale", "showHelp"]);
  assert.doesNotMatch(block, /prepare|openExternal|copyDiagnostics|startBackend/);
});

test("controller process exit returns the shell to crash recovery", () => {
  const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(source, /created\.on\("exit", \(\) => \{[\s\S]*?controller_stopped_unexpectedly[\s\S]*?loadPreparation\("backend_crash"\)/);
});

test("macOS package uses the shipped Hebrew Live icon", () => {
  const packageConfig = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(packageConfig.build.directories.buildResources, "assets");
  assert.equal(packageConfig.build.mac.icon, "icon.png");

  const icon = readFileSync(new URL("../assets/icon.png", import.meta.url));
  assert.equal(icon.subarray(1, 4).toString("ascii"), "PNG");
  assert.equal(icon.readUInt32BE(16), 1024);
  assert.equal(icon.readUInt32BE(20), 1024);
  assert.equal(icon[25], 6);
});
