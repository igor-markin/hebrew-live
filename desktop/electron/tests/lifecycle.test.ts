import assert from "node:assert/strict";
import test from "node:test";
import { quitSituation } from "../src/lifecycle.ts";

test("quit distinguishes preparation, idle backend, and recording", () => {
  assert.equal(quitSituation(true, null), "preparing");
  assert.equal(quitSituation(false, null), "idle");
  assert.equal(quitSituation(false, { running: true, paused: true, stopping: false }), "idle");
  assert.equal(quitSituation(false, { running: true, ready: false }), "idle");
  assert.equal(quitSituation(false, { running: true, ready: true, recording_started: false, paused: false }), "idle");
  assert.equal(quitSituation(false, { running: true, recording_started: true, paused: true }), "recording");
  assert.equal(quitSituation(false, { running: true, paused: false, phase: "listening" }), "recording");
  assert.equal(quitSituation(false, { running: true, stopping: true }), "recording");
  assert.equal(quitSituation(false, { running: true, finished: true }), "idle");
});
