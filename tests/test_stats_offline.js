/* The stats read every puzzle with a save, finished ones included (their
   answers and clue types are in the puzzle file), so a finished puzzle's file
   must stay on the device; and offline the stats must not wait on files the
   device does not hold.

     node tests/test_stats_offline.js */
"use strict";
const src = require("../tools/app_src").read(__dirname + "/..");
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

// ---- 1. saveOffline: nothing finished is dropped; a lost finished file is asked for again
{
  const a = src.indexOf("  function saveOffline(");
  const b = src.indexOf("  /* Self-update.");
  const code = src.slice(a, b);
  const run = (held) => {
    const sent = [];
    const BY_ID = {
      done1: { id: "done1", file: "done1.js", v: "d1" },
      open1: { id: "open1", file: "open1.js", v: "o1" },
    };
    const env = {
      isOffline: () => false, listFull: () => true, loadShards: () => {}, isAppMode: () => false,
      offlineBatch: () => [], offlineBusy: false, syncFails: false, P: null, BY_ID,
      savedProgress: () => ({ done1: {}, open1: {} }),
      pickerStatus: (p) => ({ done: p.id === "done1" }),
      store: { get: (k, d) => (k === "ct:offline-batch" ? ["done1.js", "gone.js"] : d), set() {} },
      at: (u) => u, puzzleUrl: (p) => "puzzles/" + p.file + ".gz?v=" + p.v,
      offlineNote() {}, offlineBtn() {}, offlineRefresh() {}, readyText: String, offlineCount: () => 0,
      OFFLINE_KEY: "k", OFFLINE_BATCH_KEY: "ct:offline-batch", OFFLINE_CAP: 250, $: () => ({ classList: { contains: () => true } }),
      renderPicker() {}, navigator: { serviceWorker: { ready: Promise.resolve({ active: { postMessage: (m) => sent.push(m) } }) } },
      MessageChannel: function () { this.port1 = {}; this.port2 = {}; },
    };
    const names = Object.keys(env);
    const f = new Function(...names, "held", `
      let offlineFiles = held;
      ${code}
      return saveOffline;`);
    const save = f(...names.map((n) => env[n]), held);
    save(true, true);
    return new Promise((ok) => setImmediate(() => ok(sent[0])));
  };
  (async () => {
    const m = await run(new Set(["done1.js", "open1.js", "gone.js"]));
    check(m && !m.drop.some((u) => /done1/.test(u)), "a finished puzzle's file is not dropped");
    check(m && m.drop.some((u) => /gone\.js/.test(u)), "a file no save needs is still dropped");
    check(m && m.keep.some((u) => /done1/.test(u)) && m.keep.some((u) => /open1/.test(u)),
      "the worker is told to keep finished and unfinished alike");
    const lost = await run(new Set(["open1.js"]));
    check(lost && lost.urls.length === 1 && /done1\.js\.gz\?v=d1/.test(lost.urls[0]),
      "a finished puzzle's file the device lost is fetched again: " + JSON.stringify(lost && lost.urls));
    stats();
  })();
}

// ---- 2. the stats panel offline asks only for what is held, and says what it left out
function stats() {
  const a = src.indexOf("  let statsMissing = 0;");
  const b = src.indexOf("  function renderStats()");
  const code = src.slice(a, b);
  const asked = [];
  const env = {
    savedProgress: () => ({ held: {}, lost: {}, lost2: {} }),
    BY_ID: { held: { id: "held" }, lost: { id: "lost" }, lost2: { id: "lost2" } },
    INDEX: { puzzles: [] },
    window: { CRYPTIC_PUZZLES: {} },
    offlineHas: (p) => p.id === "held",
    loadPuzzle: (id, cb) => { asked.push(id); cb(); },
  };
  const names = Object.keys(env);
  const api = new Function(...names, `${code}; return { whenStartedLoaded, missing: () => statsMissing };`)(...names.map((n) => env[n]));
  let done = 0;
  api.whenStartedLoaded(() => { done++; }, false);
  check(done === 1 && asked.join() === "held", "offline, only the held puzzle is asked for: " + asked);
  check(api.missing() === 2, "and the two it could not read are counted for the panel's note: " + api.missing());
  process.exit(failures ? 1 : 0);
}
