// The home-screen app's Puzzles and Stats tabs are full pages, not sheets: each
// has its own hash (#picker, #stats) pushed to history so the back gesture
// walks between tabs, no close button, and the CSS gives it the whole screen
// above the tab bar. Browser tabs keep the old panels and push nothing.
//
//     node tools/test_app_tab_pages.js
"use strict";
const fs = require("fs");
const path = require("path");
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

const d = require("./fake_dom.js").boot({ query: "?p=listener-111" });
const reg = d.registry;
const hidden = (id) => reg[id].classList.contains("hidden");
const pushed = [];
// The pushed address keeps the puzzle's query; only the hash names the tab.
const tab = (u) => u === undefined ? undefined : u.replace(/^[^#]*/, "");
global.location.pathname = "/";
global.window.history.pushState = (_s, _t, url) => {
  pushed.push(String(url));
  global.location.hash = String(url).replace(/^[^#]*/, "");
};
let standalone = true;
global.document.documentElement = { classList: { contains: (c) => c === "standalone" && standalone } };
const pop = () => (d.winListeners.popstate || []).forEach((fn) => fn());

reg["btn-picker"].onclick();
assert(!hidden("picker-panel"), "the Puzzles tab opens the picker");
assert(tab(pushed[pushed.length - 1]) === "#picker", "opening Puzzles pushes #picker: " + JSON.stringify(pushed));
reg["btn-stats"].onclick();
assert(hidden("picker-panel") && !hidden("stats-panel"), "Stats replaces Puzzles, never stacked");
assert(tab(pushed[pushed.length - 1]) === "#stats", "opening Stats pushes #stats: " + JSON.stringify(pushed));
const n = pushed.length;
reg["btn-stats"].onclick();   // the close path (toggle) leaves for the puzzle
assert(hidden("stats-panel") && pushed.length === n + 1 && tab(pushed[n]) === "",
  "back to the puzzle pushes the bare address: " + JSON.stringify(pushed));

// The back gesture: the address changes, the page follows, nothing is pushed.
const before = pushed.length;
global.location.hash = "#picker"; pop();
assert(!hidden("picker-panel"), "back to #picker shows the picker");
global.location.hash = "#stats"; pop();
assert(hidden("picker-panel") && !hidden("stats-panel"), "back to #stats shows stats");
global.location.hash = ""; pop();
assert(hidden("picker-panel") && hidden("stats-panel"), "back to the bare address shows the puzzle");
assert(pushed.length === before, "following history pushes none: " + JSON.stringify(pushed.slice(before)));

// A browser tab keeps its panels and touches no history.
standalone = false;
const m = pushed.length;
reg["btn-picker"].onclick();
assert(pushed.length === m, "outside the app the panel pushes no history");

const css = fs.readFileSync(path.join(__dirname, "..", "style.css"), "utf8");
assert(/html\.standalone #picker-panel, html\.standalone #stats-panel \{[^}]*position: fixed[^}]*bottom: calc\(56px/.test(css),
  "in the app the panels fill the screen above the tab bar");
assert(/html\.standalone #btn-picker-close, html\.standalone #btn-stats-close \{ display: none; \}/.test(css),
  "in the app the pages have no close button");

if (fails.length) { console.error(fails.map((f) => "FAIL: " + f).join("\n")); process.exit(1); }
console.log("ok: test_app_tab_pages");
