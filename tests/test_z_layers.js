/* Stacking order lives in one place: the --z-* layers in style.css :root.

   Every z-index is a named layer, or 0-2 for ordering inside one component; no
   script sets a z-index of its own. Layers keep their order (strip under the
   pinned clue under popovers ... under the update pill). */
"use strict";
const fs = require("fs");
const path = require("path");
const root = path.join(__dirname, "..");
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const css = fs.readFileSync(path.join(root, "style.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
const layers = {};
for (const m of css.matchAll(/--z-([a-z-]+):\s*(\d+)/g)) layers[m[1]] = Number(m[2]);
const used = [...css.matchAll(/z-index:\s*([^;}]+)/g)].map((m) => m[1].trim());
const bad = used.filter((v) => !/^[0-2]$/.test(v) && !/^var\(--z-[a-z-]+\)$/.test(v));
check(bad.length === 0, "every z-index is 0-2 or a --z layer: " + bad.join(","));
const undef = used.map((v) => (/^var\(--z-([a-z-]+)\)$/.exec(v) || [])[1]).filter((n) => n && !(n in layers));
check(undef.length === 0, "every layer used is defined: " + undef.join(","));
const order = ["strip", "sticky", "popover", "page-panel", "scrim", "tabbar", "toast", "celebration", "update"];
check(order.every((n, i) => n in layers && (i === 0 || layers[order[i - 1]] < layers[n])),
  "layers are defined in stacking order");

const scripts = fs.readdirSync(root).filter((f) => /^app.*\.js$/.test(f));
const inline = scripts.filter((f) => /z-?[iI]ndex/.test(fs.readFileSync(path.join(root, f), "utf8").replace(/\/\/.*$/gm, "")));
check(inline.length === 0, "no script sets a z-index: " + inline.join(","));

console.log(failures ? `\n${failures} FAILURE(S)` : "\nZ LAYERS TEST PASSED");
process.exit(failures ? 1 : 0);
