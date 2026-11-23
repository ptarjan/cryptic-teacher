// A slice that hangs or crawls on one puzzle must fail naming that puzzle, not
// run silent until the job's timeout cancels it. The corpus sweeps are
// synchronous, so no timer on the main thread can fire inside a stuck one: the
// check lives on a worker thread, which reads a heartbeat the sweeps write into
// shared memory and, when the heartbeat goes stale, prints the last puzzle a
// sweep opened and kills the process.
// Part of tools/smoke_test.js: required right after the harness.
"use strict";
const { Worker } = require("worker_threads");

// No heartbeat for this long: stuck inside one call. Every assertion is a
// heartbeat (harness.js), and the sweeps make one per clue.
const STALE_S = Number(process.env.SMOKE_STALE_S) || 900;
// One puzzle taking this long inside a sweep's loop is crawling: failed there
// by name (slow()) rather than left to push the slice into its timeout.
const PUZZLE_S = Number(process.env.SMOKE_PUZZLE_S) || 300;
// A progress line every this many puzzle opens, so a log shows where a slice
// is and how fast it is going while it is still running.
const REPORT_EVERY = 500;

const buf = new SharedArrayBuffer(16 + 256);
const clock = new Float64Array(buf, 0, 1);       // [last heartbeat ms]
const label = new Uint8Array(buf, 16, 256);      // the current puzzle id, utf8, zero-padded
const started = Date.now();
clock[0] = started;
let current = "";
let opens = 0;

const stageOf = () => (global.__smokeStage ? global.__smokeStage() : "sweeping");

// The sweeps call this on every step that proves they are alive (a rung taken,
// a puzzle opened); cheap, since it is one store.
const beat = () => { clock[0] = Date.now(); };

// A sweep moved to puzzle `id`. A repeat of the id already current is a beat.
function setPuzzle(id) {
  id = String(id);
  beat();
  if (id === current) return;
  current = id;
  label.fill(0);
  label.set(Buffer.from(id).subarray(0, 255));
  if (++opens % REPORT_EVERY === 0) {
    const min = ((Date.now() - started) / 60000).toFixed(1);
    console.log(`(smoke slice ${process.env.CI_SLICE || "-"}: ${opens} puzzle opens in ${min} min, `
      + `now ${id}, ${stageOf()}, rss ${Math.round(process.memoryUsage().rss / 1048576)} MB)`);
  }
}

const code = `
const { workerData } = require("worker_threads");
const fs = require("fs");
const clock = new Float64Array(workerData.buf, 0, 1);
const label = new Uint8Array(workerData.buf, 16, 256);
setInterval(() => {
  const now = Date.now();
  const id = Buffer.from(label).toString("utf8").replace(/\\0+$/, "") || "(none yet)";
  const quiet = (now - clock[0]) / 1000;
  if (quiet <= workerData.staleS) return;
  fs.writeSync(2, "FAIL: smoke slice " + workerData.slice + " made no progress for " + Math.round(quiet)
    + " s (limit " + workerData.staleS + " s); the last puzzle a sweep opened was " + id + "\\n");
  process.kill(process.pid, "SIGKILL");
}, 5000);
`;
const worker = new Worker(code, {
  eval: true,
  workerData: { buf, staleS: STALE_S, slice: process.env.CI_SLICE || "-" },
});
worker.unref();
worker.on("error", () => {});

// Fails loudly, naming the puzzle, when one puzzle of a sweep took longer than
// PUZZLE_S since `since` (a Date.now() taken as the puzzle began).
function slow(id, since, assert) {
  const s = (Date.now() - since) / 1000;
  return assert(s <= PUZZLE_S, `puzzle ${id} took ${Math.round(s)} s in one sweep step (limit ${PUZZLE_S} s)`);
}

module.exports = { beat, setPuzzle, slow };
