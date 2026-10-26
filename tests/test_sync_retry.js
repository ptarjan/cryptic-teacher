// A sync push that fails must never lose a save, and must retry on its own.
//
//     node tests/test_sync_retry.js
//
// Runs app.js's sync scheduler block (between its "---- sync scheduler" and
// "---- end sync scheduler ----" markers) as written, in a vm, against a fake
// sync server, a fake clock and the real sync/merge.js. Checked: a 503 or a
// network error leaves the save in localStorage and schedules a retry that
// gets it to the server without the solver typing again; retries back off
// 30s, 60s, ... up to 15 minutes; coming back online retries at once; a
// failed join retries as a join, so a 404 never seeds a mistyped code; and
// pushes are at most one a minute, with a hidden tab flushing the one waiting.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const APP = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const CTMerge = require("../sync/merge.js");
const start = APP.indexOf("// ---- sync scheduler");
const end = APP.indexOf("// ---- end sync scheduler ----");
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };
if (start < 0 || end < start) {
  console.error("FAIL: app.js has lost its sync scheduler markers");
  process.exit(1);
}
const BLOCK = APP.slice(start, end);

function harness() {
  let now = 1_700_000_000_000;
  let timers = [], seq = 0;
  const local = {};          // localStorage's ct:<id> saves
  const server = { down: false, kind: "503", stored: null, gets: 0, puts: 0 };
  const listeners = {};
  const notes = [];
  const ctx = {
    CTMerge, console, JSON, Math, Promise, Error, Object,
    Date: { now: () => now },
    setTimeout: (fn, ms) => { const id = ++seq; timers.push({ id, at: now + ms, fn }); return id; },
    clearTimeout: (id) => { timers = timers.filter((t) => t.id !== id); },
    window: { addEventListener: (t, f) => { listeners[t] = f; } },
    syncOn: () => true,
    syncNote: (m) => notes.push(m),
    restoreState: () => {}, refreshAll: () => {},
    localEnvelope: () => ({ v: 1, puzzles: JSON.parse(JSON.stringify(local)) }),
    applyEnvelope: (env) => {
      Object.keys(env.puzzles || {}).forEach((id) => { local[id] = CTMerge.mergePuzzle(local[id], env.puzzles[id]); });
      return false;
    },
    syncFetch: (method, body) => {
      if (server.down) {
        return Promise.reject(server.kind === "network" ? new TypeError("Failed to fetch") : new Error("sync " + server.kind));
      }
      if (method === "GET") { server.gets++; return Promise.resolve(server.stored); }
      server.puts++;
      server.stored = CTMerge.mergeSaves(server.stored, body);
      return Promise.resolve(server.stored);
    },
  };
  vm.createContext(ctx);
  vm.runInContext(BLOCK + "\nthis.api = { syncPushSoon, syncPush, syncPull, syncFlush };", ctx);
  const settle = () => new Promise((r) => setImmediate(r));
  async function advance(ms) {
    const until = now + ms;
    for (;;) {
      await settle();
      timers.sort((a, b) => a.at - b.at);
      const t = timers[0];
      if (!t || t.at > until) break;
      timers.shift();
      now = t.at;
      t.fn();
    }
    now = until;
    await settle();
  }
  const type = (id, letter) => {
    local[id] = { letters: { "0,0": letter }, letterAt: { "0,0": now }, updated: now };
    ctx.api.syncPushSoon();
  };
  const onServer = (id) => !!(server.stored && server.stored.puzzles[id] &&
    JSON.stringify(server.stored.puzzles[id].letters) === JSON.stringify(local[id].letters));
  const pending = () => timers.map((t) => t.at - now).sort((a, b) => a - b);
  return { ctx, api: ctx.api, server, local, listeners, notes, advance, type, onServer, pending, settle };
}

(async () => {
  for (const kind of ["503", "429", "network"]) {
    const h = harness();
    h.server.down = true; h.server.kind = kind;
    h.type("guardian-1", "A");
    await h.advance(2000);
    assert(h.local["guardian-1"] && h.local["guardian-1"].letters["0,0"] === "A",
      `${kind}: the save is still in localStorage after the failed push`);
    assert(h.server.stored === null, `${kind}: nothing reached the server while it was down`);
    assert(h.pending().length === 1, `${kind}: a failed push schedules a retry by itself (pending: ${h.pending()})`);
    h.server.down = false;
    await h.advance(30 * 1000);
    assert(h.onServer("guardian-1"), `${kind}: the retry, with no further typing, got the save to the server`);
    assert(h.notes[h.notes.length - 1] === "Synced", `${kind}: the status line says Synced once the retry lands`);
    assert(h.pending().length === 0, `${kind}: nothing is left scheduled after a successful retry`);
  }

  {
    // Backoff: 30s, 60s, 120s, ... capped at 15 minutes.
    const h = harness();
    h.server.down = true;
    h.type("times-1", "B");
    await h.advance(2000);
    const waits = [];
    for (let i = 0; i < 8; i++) {
      const w = h.pending()[0];
      waits.push(w / 1000);
      await h.advance(w);
    }
    assert(JSON.stringify(waits) === JSON.stringify([30, 60, 120, 240, 480, 900, 900, 900]),
      "retries back off 30, 60, 120, 240, 480 then hold at 900 seconds: got " + waits);
    assert(h.server.puts === 0 && h.local["times-1"].letters["0,0"] === "B",
      "an hour of failures later the save is still local, intact");
    // Coming back online retries straight away, not at the next backoff.
    h.server.down = false;
    h.listeners.online();
    await h.advance(0);
    assert(h.onServer("times-1"), "the online event retries at once and the save lands");
  }

  {
    // A retry after a push that did land costs a read, not a write.
    const h = harness();
    h.type("fifteen-1", "C");
    await h.advance(2000);
    assert(h.server.puts === 1, "the first push went up");
    h.server.down = true;
    h.api.syncPull();
    await h.advance(0);
    h.server.down = false;
    const puts = h.server.puts;
    await h.advance(30 * 1000);
    assert(h.server.gets >= 1 && h.server.puts === puts,
      "a retry that finds the server already has everything does not write again");
  }

  {
    // A failed join retries as a join: its 404 goes to `missing`, never a PUT.
    const h = harness();
    h.local["azed-1"] = { letters: { "0,0": "D" }, updated: 1 };
    let missing = 0;
    h.server.down = true;
    h.api.syncPull(() => { missing++; });
    await h.advance(0);
    h.server.down = false;
    await h.advance(30 * 1000);
    assert(missing === 1 && h.server.puts === 0,
      `a failed join's retry hits the 404 as a join (missing=${missing}, puts=${h.server.puts})`);
  }

  {
    // At most one push a minute while typing; hiding the tab flushes it.
    const h = harness();
    h.type("everyman-1", "E");
    await h.advance(2000);
    assert(h.server.puts === 1, "the first change pushes after two seconds of quiet");
    h.type("everyman-1", "F");
    await h.advance(2000);
    assert(h.server.puts === 1, "a second change inside the minute waits");
    await h.advance(60 * 1000);
    assert(h.server.puts === 2 && h.onServer("everyman-1"), "and goes up a minute after the last push");
    h.type("everyman-1", "G");
    h.api.syncFlush();
    await h.advance(0);
    assert(h.server.puts === 3 && h.onServer("everyman-1"), "a hidden tab pushes the waiting change at once");
    assert(h.pending().length === 0, "and leaves no timer behind");
  }

  if (fails.length) {
    fails.forEach((f) => console.error("FAIL: " + f));
    process.exit(1);
  }
  console.log("ok: sync retries failed pushes and never drops a save");
})();
