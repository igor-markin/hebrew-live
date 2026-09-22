#!/usr/bin/env node
/* Local-only QA helper. Launch Electron with --remote-debugging-port first. */
import { writeFile } from "node:fs/promises";

const [portValue, mode = "state", output, widthValue, heightValue] = process.argv.slice(2);
const port = Number(portValue);
if (!Number.isInteger(port) || port < 1) throw new Error("usage: cdp-qa.mjs PORT MODE [OUTPUT] [WIDTH] [HEIGHT]");

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function pageTarget() {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
    const page = targets.find((target) => target.type === "page" && /^http:\/\/127\.0\.0\.1:\d+\/.+\/live\/$/.test(target.url));
    if (page) return page;
    await pause(250);
  }
  throw new Error("working page did not become available");
}

const target = await pageTarget();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let nextId = 1;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(String(event.data));
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});
function send(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

await send("Runtime.enable");
await send("Page.enable");

if (mode === "start") {
  await evaluate(`(() => { const button=[...document.querySelectorAll('.live-toolbar button')].find((item) => /^(Start recording|Начать запись|New recording|Новая запись)$/.test(item.textContent?.trim() ?? '')); if(!button) throw new Error('start button unavailable'); button.click(); return true; })()`);
  await pause(750);
} else if (mode === "finish") {
  await evaluate(`(() => { const button=[...document.querySelectorAll('.live-toolbar button')].find((item) => /^(Finish recording|Завершить запись)$/.test(item.textContent?.trim() ?? '')); if(!button) throw new Error('finish button unavailable'); button.click(); return true; })()`);
  await pause(750);
} else if (mode === "quit") {
  const clicked = await evaluate(`(() => { const button=[...document.querySelectorAll('button')].find((item) => /^(Выйти из Hebrew Live|Quit Hebrew Live)$/.test(item.textContent?.trim() ?? '')); if(!button) throw new Error('quit button unavailable'); button.click(); return true; })()`);
  console.log(JSON.stringify({ clicked }, null, 2));
  await pause(1000);
  socket.close();
  process.exit(0);
} else if (mode === "settings") {
  if (widthValue && heightValue) {
    await send("Emulation.setDeviceMetricsOverride", {
      width: Number(widthValue), height: Number(heightValue), deviceScaleFactor: 1, mobile: false,
    });
  }
  await evaluate(`(() => { const details=document.querySelector('.live-settings'); if(!details) throw new Error('settings unavailable'); details.open=true; return true; })()`);
  await pause(250);
} else if (mode === "reset") {
  await send("Emulation.clearDeviceMetricsOverride");
  await send("Emulation.setEmulatedMedia", { features: [] });
  await pause(250);
} else if (mode === "theme") {
  await evaluate(`(() => { const button=document.querySelector('.live-settings-panel .actions button'); if(!button) throw new Error('theme button unavailable'); button.click(); return true; })()`);
  await pause(250);
} else if (mode === "locale") {
  if (output !== "en" && output !== "ru") throw new Error("locale must be en or ru");
  await evaluate(`(() => { const select=document.querySelector('.live-settings-panel select'); if(!select) throw new Error('locale selector unavailable'); select.value=${JSON.stringify(output)}; select.dispatchEvent(new Event('change',{bubbles:true})); return true; })()`);
  await pause(1000);
} else if (mode === "reduced-motion") {
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await pause(250);
}

const state = await evaluate(`(() => {
  const rect = (selector) => { const node=document.querySelector(selector); if(!node) return null; const box=node.getBoundingClientRect(); return {left:box.left,top:box.top,right:box.right,bottom:box.bottom,width:box.width,height:box.height}; };
  const panel=rect('.live-settings-panel'); const sidebar=rect('.session-sidebar');
  return {
    title: document.title,
    viewport: {width:innerWidth,height:innerHeight},
    theme: document.documentElement.dataset.theme ?? '',
    reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
    status: document.querySelector('.live-status')?.innerText ?? '',
    buttons: Array.from(document.querySelectorAll('.live-toolbar button')).map((button)=>({text:button.innerText,disabled:button.disabled})),
    messages: Array.from(document.querySelectorAll('.live-feed .speech-card')).slice(-5).map((card)=>card.innerText),
    settings: panel,
    sidebar,
    settingsFits: panel ? panel.left >= 0 && panel.right <= innerWidth && (!sidebar || panel.left >= sidebar.right) : null,
  };
})()`);

if (output) {
  const capture = await send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(output, Buffer.from(capture.data, "base64"));
}
console.log(JSON.stringify(state, null, 2));
socket.close();
