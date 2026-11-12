/* The first screen's arm b (A/B 1 in app-core.js): the same checks the smoke test
   makes of arm a's dialog, for the #tap-hint line with the dialog behind a link.

   tools/fake_dom.js pins every boot to arm a, so the smoke test never sees arm b.
   This boots a first-ever visit with arm b drawn and walks only the first
   screen: it renders, nothing throws or logs an error, and its actions work
   (open the intro, start from it, type to dismiss the line). Not a second pass
   of the corpus: one fixed puzzle, two boots. */
"use strict";
const { boot } = require("../tools/fake_dom.js");

const ID = "cryptic-30066";
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const errors = [];
const realError = console.error;
console.error = (...a) => { errors.push(a.join(" ")); realError(...a); };
process.on("uncaughtException", (e) => { errors.push(String((e && e.stack) || e)); });

// First-ever visit: empty storage, arm b drawn.
const d = boot({ query: "?p=" + ID, arm: "b" });
const reg = d.registry, st = d.storage;
const hidden = (r, id) => r[id].classList.contains("hidden");
const ab = () => JSON.parse(st["ct-ab1"] || "null") || {};

check(ab().arm === "b", "the first visit is enrolled in arm b: " + st["ct-ab1"]);
check(ab().sent && ab().sent.indexOf("visit") >= 0, "the visit step is recorded for arm b");
check(st["ct:nux"] === "0", "the first-visit cursor is written: " + st["ct:nux"]);
check(!!reg["grid"] && reg["grid"].children.length > 0, "the grid renders");
check(hidden(reg, "welcome"), "arm b does not block the grid with the dialog");
check(!hidden(reg, "tap-hint"), "arm b shows the tap-hint line instead");
check(!!reg["intro-open"] && !!reg["intro-open"].onclick, "the intro link is wired");

reg["intro-open"].onclick();
check(!hidden(reg, "welcome"), "the link opens the short intro dialog");
check(hidden(reg, "tap-hint"), "and the line steps aside while it is open");
check(ab().sent.indexOf("intro") >= 0, "opening it is recorded as the intro step");

reg["welcome-go"].onclick();
check(hidden(reg, "welcome"), "starting closes the dialog");
check(hidden(reg, "tap-hint"), "and the first-screen line does not come back");
check(st["ct:nux"] === "1", "the cursor moves to the ladder line: " + st["ct:nux"]);

// A fresh arm b visit that types before opening the intro: the line goes.
const d2 = boot({ query: "?p=" + ID, arm: "b" });
const r2 = d2.registry;
check(!hidden(r2, "tap-hint"), "a fresh arm b visit shows the line again");
for (const f of d2.docListeners["keydown"] || []) {
  try { f({ key: "q", preventDefault() {}, shiftKey: false, target: r2["kbd"] }); } catch (e) { errors.push(String(e)); }
}
check(hidden(r2, "tap-hint"), "typing a letter hides the line");
check(hidden(r2, "welcome"), "and the dialog stays shut");

check(errors.length === 0, "no console errors or exceptions: " + errors.slice(0, 3).join(" | "));
d.stop(); d2.stop();
console.error = realError;
if (failures) { console.log(failures + " failure(s)"); process.exit(1); }
console.log("all first-screen arm b checks passed");
