// Diagnostic only: what holds smoke_test.js's memory in CI. On under
// SMOKE_HEAP_DIR, or in a hand-dispatched nightly-smoke.yml's slice 1/16 (the
// push token cannot add a workflow of its own). Logs process.memoryUsage()
// every 10 s and writes V8 heap snapshots after the corpus loads, at RSS
// thresholds and at exit; each is summarised by tools/heap_report.py in a
// child process (one at a time) into the job log, then deleted (they are GBs).
// The sweep is mostly synchronous, so the timer alone would miss its peaks:
// global.__heapProbe(tag) is also called from load() and fake_dom's boot().
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const v8 = require("v8");
const { spawn, spawnSync } = require("child_process");

const auto = process.env.GITHUB_EVENT_NAME === "workflow_dispatch" && process.env.CT_FULL
  && process.env.CI_SLICE === "1/16";
const dir = process.env.SMOKE_HEAP_DIR || (auto ? path.join(process.env.RUNNER_TEMP || os.tmpdir(), "heap") : "");
const REPORT = path.join(__dirname, "heap_report.py");
const MB = (n) => Math.round(n / 1048576);
const marks = (process.env.SMOKE_HEAP_MARKS || "1800,2600,3300").split(",").map(Number);
const counts = {};
const queue = [];
let busy = null;
let prevJson = null;
let n = 0;
let lastLog = 0;
let stageRef = { at: "-" };

function usage() {
  const u = process.memoryUsage();
  return `rss=${MB(u.rss)} heapTotal=${MB(u.heapTotal)} heapUsed=${MB(u.heapUsed)} `
    + `external=${MB(u.external)} arrayBuffers=${MB(u.arrayBuffers)}`;
}
function afterReport(f) {
  try { fs.unlinkSync(f); } catch {}
  const j = `${f}.json`;
  if (prevJson && fs.existsSync(j)) spawnSync("python3", ["-I", REPORT, "--diff", prevJson, j], { stdio: "inherit" });
  if (fs.existsSync(j)) prevJson = j;
}
function pump() {
  if (busy || !queue.length) return;
  const f = queue.shift();
  busy = spawn("python3", ["-I", REPORT, f, `${f}.json`], { stdio: ["ignore", "inherit", "inherit"] });
  busy.on("exit", () => { busy = null; afterReport(f); pump(); });
}
function snap(why) {
  const f = path.join(dir, `${String(++n).padStart(2, "0")}-${why}.heapsnapshot`);
  console.log(`heap-probe snap ${path.basename(f)} at "${stageRef.at}" before: ${usage()} counts=${JSON.stringify(counts)}`);
  v8.writeHeapSnapshot(f);
  console.log(`heap-probe snap ${path.basename(f)} after: ${usage()} size=${MB(fs.statSync(f).size)}MB`);
  queue.push(f);
  pump();
}
function check(tag) {
  if (tag) counts[tag] = (counts[tag] || 0) + 1;
  const now = Date.now();
  if (now - lastLog > 10000) {
    lastLog = now;
    console.log(`heap-probe mem at "${stageRef.at}" ${usage()} counts=${JSON.stringify(counts)}`);
  }
  const rss = MB(process.memoryUsage().rss);
  while (marks.length && rss >= marks[0]) snap(`rss${marks.shift()}`);
}

module.exports = function start(stage) {
  if (!dir) return;
  stageRef = stage;
  fs.mkdirSync(dir, { recursive: true });
  console.log(`heap-probe on: ${dir} ${usage()}`);
  global.__heapProbe = check;
  global.__heapProbeSnap = snap;
  setInterval(check, 5000).unref();
  process.on("exit", () => {
    // The exit snapshot first, while the heap still holds everything; then
    // wait out the running report and do the rest synchronously.
    const fx = path.join(dir, `${String(++n).padStart(2, "0")}-exit.heapsnapshot`);
    console.log(`heap-probe snap ${path.basename(fx)} at exit: ${usage()} counts=${JSON.stringify(counts)}`);
    v8.writeHeapSnapshot(fx);
    queue.push(fx);
    const sab = new Int32Array(new SharedArrayBuffer(4));
    while (busy) {
      // Not reaped while this handler blocks the loop: a zombie has exited.
      let st = "Z";
      try { st = fs.readFileSync(`/proc/${busy.pid}/stat`, "utf8").split(") ")[1][0]; } catch {}
      if (st === "Z") break;
      Atomics.wait(sab, 0, 0, 1000);
    }
    if (busy) afterReport(busy.spawnargs[3]);
    busy = null;
    for (const f of queue.splice(0)) {
      spawnSync("python3", ["-I", REPORT, f, `${f}.json`], { stdio: "inherit" });
      afterReport(f);
    }
  });
};
