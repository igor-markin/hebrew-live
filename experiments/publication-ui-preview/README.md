# Browser UI development

This React 19 workspace builds the packaged runtime UI and a separate synthetic demo.
It requires Node.js 24 and npm.

From this directory:

```sh
npm ci
npm test
npm run build
```

`npm run build` compiles `live.html` and writes production assets directly to
`../../src/hebrew_live/web/`, which is included in the Python wheel and sdist. It does
not build the demo page or include internal case data.

To inspect the synthetic comparison page during development:

```sh
npm run build:demo
npm run preview
```

The demo uses `src/data/public-cases.json`, whose provenance is explicitly synthetic.
The ignored `dist/` output and any older internal `cases.json`, archives, exports, or
recordings are excluded from public artifacts.

The supported runtime publication contract is `draft`. Start the real application
from the service root with:

```sh
./run.sh listen --ui browser --publication draft --start-paused
```

That command loads local models and can open the microphone after resume; it is not a
deterministic frontend check. The browser server listens on `127.0.0.1` behind a
random per-process route, serves packaged assets without external requests, and keeps
session data in the application data root.

Frontend tests cover strict snapshot validation, nullable fields, model policy,
follow-latest observation across appended and resized content, and a shared synthetic
backend/frontend contract fixture. They do not establish browser compatibility,
accessibility, translation quality, latency, or long-session stability.
