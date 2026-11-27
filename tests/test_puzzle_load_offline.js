/* A puzzle that cannot be fetched (a captive wifi never answers) must not hang the
   page, and must not be remembered as "gone": the next tap tries again. Only a
   server that ANSWERED, with a 404, settles a puzzle as missing for good.

     node tests/test_puzzle_load_offline.js */
"use strict";
const src = require("../tools/app_src").read(__dirname + "/..");
const a = src.indexOf("  const NET_WAIT_MS"), b = src.indexOf("  // The text in a .gz's bytes.");
const code = src.slice(a, b);
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

// Deterministic clock: timers run only when the test says so.
function world(fetchImpl) {
  const timers = [];
  const win = { CRYPTIC_PUZZLES: {}, fetch: fetchImpl, AbortController };
  const f = new Function("window", "BY_ID", "at", "unzipText", "setTimeout", "clearTimeout", "document", `
    ${code}
    return { loadPuzzle, fetchWithin, puzzleLoad };`);
  const api = f(win, { p1: { id: "p1", file: "p1.js" } }, (u) => u, (buf) => buf, (fn) => timers.push(fn) && timers.length,
    () => {}, { createElement: () => ({}), head: { appendChild(s) { if (s.onerror) s.onerror(); } } });
  return { api, win, fire: () => timers.splice(0).forEach((fn) => fn()) };
}
const hang = (url, opts) => new Promise((ok, no) => {
  opts.signal.addEventListener("abort", () => no(new Error("aborted")));
});
const tick = () => new Promise((ok) => setImmediate(ok));

(async () => {
  // 1. A network that never answers: the load settles once the wait runs out.
  let w = world(hang);
  let done = 0;
  w.api.loadPuzzle("p1", () => { done++; });
  await tick();
  check(done === 0, "while the network is silent the load is still waiting");
  w.fire();
  await tick(); await tick();
  check(done === 1, "when the wait runs out the load settles instead of hanging");
  check(!w.win.CRYPTIC_PUZZLES.p1, "and no puzzle appears from nowhere");
  check(w.api.puzzleLoad.p1 !== 1, "a silent network does not mark the puzzle as gone for good");
  // 2. The same puzzle asked for again really asks again.
  let asked = 0;
  w = world((u, o) => { asked++; return hang(u, o); });
  w.api.loadPuzzle("p1", () => {});
  w.fire(); await tick(); await tick();
  w.api.loadPuzzle("p1", () => {});
  check(asked === 2, "a second tap after a failure is a second request, not a remembered failure");
  // 3. A server that answers 404: the puzzle is gone, and stays settled.
  w = world(() => Promise.resolve({ ok: false, status: 404 }));
  done = 0;
  w.api.loadPuzzle("p1", () => { done++; });
  await tick(); await tick(); await tick();
  check(done === 1 && w.api.puzzleLoad.p1 === 1, "an answered 404 settles the puzzle as missing");
  process.exit(failures ? 1 : 0);
})();
