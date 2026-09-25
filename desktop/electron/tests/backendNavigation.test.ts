import assert from "node:assert/strict";
import test from "node:test";
import { navigateBackend } from "../src/backendNavigation.ts";

test("backend page retries a failed local navigation", async () => {
  let calls = 0;
  const page = {
    loadURL: async () => { if (++calls < 3) throw new Error("connection refused"); },
    isDestroyed: () => false,
    webContents: { stop: () => undefined },
  };
  const loaded = await navigateBackend(page, "http://127.0.0.1:1234/local/live/", () => true,
    { wait: async () => undefined });
  assert.equal(loaded, true);
  assert.equal(calls, 3);
});

test("backend page stops a timed-out load and reports failure", async () => {
  let calls = 0;
  let stops = 0;
  const page = {
    loadURL: async () => { calls += 1; await new Promise<void>(() => undefined); },
    isDestroyed: () => false,
    webContents: { stop: () => { stops += 1; } },
  };
  const loaded = await navigateBackend(page, "http://127.0.0.1:1234/local/live/", () => true,
    { attempts: 2, timeoutMs: 5, wait: async () => undefined });
  assert.equal(loaded, false);
  assert.equal(calls, 2);
  assert.equal(stops, 2);
});
