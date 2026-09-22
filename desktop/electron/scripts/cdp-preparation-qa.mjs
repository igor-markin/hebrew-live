#!/usr/bin/env node
/* Local-only preparation-window QA helper. Requires --remote-debugging-port. */
import { writeFile } from "node:fs/promises";

const [portValue, command = "state", targetId = "", value = "", screenshot] = process.argv.slice(2);
const port = Number(portValue);
if (!Number.isInteger(port) || port < 1) throw new Error("usage: cdp-preparation-qa.mjs PORT COMMAND [ID] [VALUE] [SCREENSHOT]");

const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("preparation page is unavailable");
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

if (command === "click") {
  await evaluate(`(() => { const node=document.getElementById(${JSON.stringify(targetId)}); if(!node) throw new Error('missing control'); node.click(); return true; })()`);
} else if (command === "set") {
  await evaluate(`(() => {
    const node=document.getElementById(${JSON.stringify(targetId)}); if(!node) throw new Error('missing control');
    if(node instanceof HTMLInputElement && node.type==='checkbox') node.checked=${value === "true"};
    else node.value=${JSON.stringify(value)};
    node.dispatchEvent(new Event('change',{bubbles:true})); return true;
  })()`);
} else if (command !== "state") {
  throw new Error(`unsupported command: ${command}`);
}

await new Promise((resolve) => setTimeout(resolve, 500));
const state = await evaluate(`(() => ({
  title:document.title,
  heading:document.querySelector('h1,h2')?.innerText ?? '',
  body:document.body.innerText.slice(0,4000),
  controls:Array.from(document.querySelectorAll('button,input,select')).map((node)=>({
    id:node.id,tag:node.tagName.toLowerCase(),text:node.innerText||'',value:node.value,
    disabled:Boolean(node.disabled),checked:'checked' in node?Boolean(node.checked):undefined,
  })),
}))()`);
if (screenshot) {
  const capture = await send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await writeFile(screenshot, Buffer.from(capture.data, "base64"));
}
console.log(JSON.stringify(state, null, 2));
socket.close();
