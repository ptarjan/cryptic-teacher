/* A full browser store is told to the solver once; a missing one is not.

   Every read and write of storage goes through `store` (app-core.js). When
   setItem throws QuotaExceededError, progress silently stops saving, so the
   solver gets one short note per session in #toasts. When storage is just
   unavailable (private mode: any other error) nothing is shown. Nothing here
   reaches the network. */
"use strict";
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const entryId = (e) => e.number + "-" + e.direction;
function scenario(err) {
  const d = require("../tools/fake_dom.js").boot({ query: "?p=cryptic-30066" });
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: d.registry["kbd"] });
  const puz = (global.window.CRYPTIC_PUZZLES || {})["cryptic-30066"];
  const entry = (puz.entries || []).find((e) => e.solution && e.length >= 5);
  d.registry["clue-" + entryId(entry)].listeners.click[0]();
  global.window.localStorage.setItem = () => { throw err; };
  const blur = () => d.winListeners["blur"].forEach((f) => f());
  key(entry.solution[0]); blur();
  key(entry.solution[1]); blur();
  return d;
}

const quota = Object.assign(new Error("full"), { name: "QuotaExceededError", code: 22 });
let d = scenario(quota);
const toasts = d.registry["toasts"].children || [];
check(toasts.length === 1, "a quota error shows one note, even after two failed saves: " + toasts.length);
check(/can't be saved/.test((toasts[0] && toasts[0].textContent) || ""), "the note says progress cannot be saved");

d = scenario(new Error("SecurityError"));
check((d.registry["toasts"].children || []).length === 0, "unavailable storage stays silent");

console.log(failures ? `\n${failures} FAILURE(S)` : "\nSTORAGE FULL TEST PASSED");
process.exit(failures ? 1 : 0);
