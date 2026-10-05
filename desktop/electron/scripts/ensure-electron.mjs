/* Install the exact locked Electron binary without changing npm security policy. */
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
let present = false;
try { present = existsSync(require("electron")); } catch { /* npm may skip postinstall */ }
if (!present) {
  const packageFolder = path.dirname(require.resolve("electron/package.json"));
  execFileSync(process.execPath, [path.join(packageFolder, "install.js")], { stdio: "inherit" });
}
if (!existsSync(require("electron"))) throw new Error("The locked Electron binary is missing");
