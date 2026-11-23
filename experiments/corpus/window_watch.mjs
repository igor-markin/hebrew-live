// Keeps the live window open in headless Chrome while a replay runs, so the window's own log
// (`ui_render`: what was drawn and when) reaches the session diagnostics as in the app.
//   PLAYWRIGHT_CORE=/path/to/node_modules/playwright-core node window_watch.mjs URL [WIDTH HEIGHT]
// Exits when the page's server goes away (the replay finished) or after 2 hours.
import {createRequire} from 'node:module';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const [url, width = '900', height = '1000'] = process.argv.slice(2);
if (!url) { console.error('usage: window_watch.mjs URL [WIDTH HEIGHT]'); process.exit(2); }

const browser = await chromium.launch({channel: process.env.WINDOW_CHANNEL || 'chrome', headless: true});
try {
  const page = await browser.newPage({viewport: {width: Number(width), height: Number(height)},
    deviceScaleFactor: process.env.WINDOW_SHOTS ? 2 : 1, locale: process.env.WINDOW_LOCALE || 'ru-RU'});
  page.on('console', message => { if (message.type() === 'error') console.error('page:', message.text()); });
  await page.goto(url, {waitUntil: 'domcontentloaded'});
  const deadline = Date.now() + 2 * 3600e3;
  // When the replay is finished, let the last versions reach the log, then close the session
  // the way the window's Quit does; the replay's server then shuts down.
  let finishedAt = 0;
  // WINDOW_SHOTS=prefix WINDOW_SHOT_TIMES=8,15: screenshots at those seconds after the page opened.
  const opened = Date.now();
  const shots = (process.env.WINDOW_SHOT_TIMES || '').split(',').filter(Boolean).map(Number);
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 500));
    while (process.env.WINDOW_SHOTS && shots.length && Date.now() - opened >= shots[0] * 1000) {
      await page.screenshot({path: `${process.env.WINDOW_SHOTS}-${shots.shift()}s.png`}).catch(() => {});
    }
    let finished;
    try { finished = await page.evaluate(() => fetch('../state').then(r => r.json()).then(s => s.finished)); }
    catch { break; }
    if (finished && !finishedAt) finishedAt = Date.now();
    if (finishedAt && Date.now() - finishedAt > 3000) {
      await page.evaluate(() => fetch('../action', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'quit'})})).catch(() => {});
      await new Promise(resolve => setTimeout(resolve, 1500));
      break;
    }
  }
} finally {
  await browser.close();
}
