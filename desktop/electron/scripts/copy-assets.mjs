import { cpSync, mkdirSync } from "node:fs";

mkdirSync(new URL("../build/renderer/", import.meta.url), { recursive: true });
for (const name of ["index.html", "styles.css"]) {
  cpSync(new URL(`../src/renderer/${name}`, import.meta.url), new URL(`../build/renderer/${name}`, import.meta.url));
}
