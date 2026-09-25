import { statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import packageInfo from "../package.json" with { type: "json" };

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const dmg = path.join(root, "dist", "electron",
  `Hebrew Live-${packageInfo.version}-arm64.dmg`);
const size = statSync(dmg).size;
const target = Math.floor(1.8 * 1024 ** 3);
const githubLimit = 2 * 1024 ** 3;
if (size > target || size >= githubLimit) {
  throw new Error(`DMG exceeds the 1.8 GiB target: ${size} bytes (${dmg})`);
}
console.log(`DMG size passed: ${size} bytes (target <= ${target})`);
