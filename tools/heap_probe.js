// Diagnostic only: what holds smoke_test.js's memory in CI. On under
// SMOKE_HEAP_DIR, or in a hand-dispatched nightly-smoke.yml's slice 1/16 (the
// push token cannot add a workflow of its own). The sweep never yields, so
// there is no timer: global.__heapProbeSweep(id) is called at the top of
// smoke_test.js's reopenForSweep. The first call takes a baseline snapshot
// after a forced GC; each later one takes a snapshot when the live heap (after
// a forced GC) is another STEP_MB above the last. At most 3 snapshots in all.
// Each is summarised by tools/heap_report.py (top retainers, then growth
// against the baseline) into the log before the sweep goes on; after the last
// one the process exits, so the job is short. Every mark also logs fake_dom's
// listener / timer / beacon sizes.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const v8 = require("v8");
const vm = require("vm");
const { spawnSync } = require("child_process");

const auto = process.env.GITHUB_EVENT_NAME === "workflow_dispatch" && process.env.CT_FULL
  && process.env.CI_SLICE === "1/16";
const dir = process.env.SMOKE_HEAP_DIR || (auto ? path.join(process.env.RUNNER_TEMP || os.tmpdir(), "heap") : "");
const REPORT = path.join(__dirname, "heap_report.py");
const MB = (n) => Math.round(n / 1048576);
const STEP_MB = Number(process.env.SMOKE_HEAP_STEP_MB || 600);
const MAX_SNAPS = 3;

v8.setFlagsFromString("--expose-gc");
const gc = () => vm.runInNewContext("gc")();

const st = { els: 0, elAdds: 0, elMaxLen: 0, elMaxType: "", boots: 0, dom: null, sweeps: 0 };
let snaps = 0;
let baseLive = 0;
let nextLive = 0;       // live MB that triggers the next snapshot
let nextCheck = 0;      // heapUsed MB (no gc) worth a forced gc
let prevJson = null;
let baseJson = null;

const len = (o) => Object.values(o || {}).map((a) => a.length);
const sum = (a) => a.reduce((x, y) => x + y, 0);
function domStats() {
  const d = st.dom && st.dom.deref();
  if (!d) return "dom=none";
  const dl = len(d.docListeners), wl = len(d.winListeners);
  return `docListeners=${sum(dl)}(max ${Math.max(0, ...dl)}) winListeners=${sum(wl)}(max ${Math.max(0, ...wl)}) `
    + `pendingTimers=${d.pending.size} beacons=${d.beacons.length}`;
}
function usage() {
  const u = process.memoryUsage();
  return `rss=${MB(u.rss)} heapUsed=${MB(u.heapUsed)} external=${MB(u.external)} arrayBuffers=${MB(u.arrayBuffers)}`;
}
function mark(why, id) {
  console.log(`heap-probe mark ${why} puzzle=${id} sweeps=${st.sweeps} boots=${st.boots} ${usage()}\n`
    + `heap-probe   fake_dom: elementsCreated=${st.els} elementAddEventListenerCalls=${st.elAdds} `
    + `longestElementListenerArray=${st.elMaxLen}(${st.elMaxType}) ${domStats()}`);
}
function summarise(f) {
  const j = `${f}.json`;
  const t0 = Date.now();
  spawnSync("python3", ["-I", REPORT, f, j], { stdio: "inherit", timeout: 25 * 60 * 1000 });
  console.log(`heap-probe summarised ${path.basename(f)} in ${Math.round((Date.now() - t0) / 1000)}s`);
  try { fs.unlinkSync(f); } catch {}
  if (!fs.existsSync(j)) return;
  if (baseJson && baseJson !== j) spawnSync("python3", ["-I", REPORT, "--diff", baseJson, j], { stdio: "inherit" });
  if (prevJson && prevJson !== baseJson) spawnSync("python3", ["-I", REPORT, "--diff", prevJson, j], { stdio: "inherit" });
  prevJson = j;
  if (!baseJson) baseJson = j;
}
function snap(why, id) {
  mark(why, id);
  const f = path.join(dir, `${String(++snaps).padStart(2, "0")}-${why}.heapsnapshot`);
  const t0 = Date.now();
  v8.writeHeapSnapshot(f);
  console.log(`heap-probe wrote ${path.basename(f)} ${MB(fs.statSync(f).size)}MB in ${Math.round((Date.now() - t0) / 1000)}s`);
  summarise(f);
}

function sweep(id) {
  st.sweeps++;
  if (snaps >= MAX_SNAPS) return;
  if (!snaps) {
    gc();
    baseLive = MB(process.memoryUsage().heapUsed);
    nextLive = baseLive + STEP_MB;
    nextCheck = nextLive;
    return snap("baseline", id);
  }
  if (MB(process.memoryUsage().heapUsed) < nextCheck) return;
  gc();
  const live = MB(process.memoryUsage().heapUsed);
  if (live < nextLive) { nextCheck = live + 300 + (nextLive - live); mark("gc-below-threshold", id); return; }
  snap(`live${live}`, id);
  nextLive = live + STEP_MB;
  nextCheck = nextLive;
  if (snaps >= MAX_SNAPS) {
    console.log("heap-probe done: ending the sweep early");
    process.exit(0);
  }
}

module.exports = function start() {
  if (!dir) return;
  fs.mkdirSync(dir, { recursive: true });
  console.log(`heap-probe on: ${dir} step=${STEP_MB}MB ${usage()}`);
  global.__heapProbeSweep = sweep;
  global.__heapProbeEl = (type, n) => {
    st.elAdds++;
    if (n > st.elMaxLen) { st.elMaxLen = n; st.elMaxType = type; }
  };
  global.__heapProbeNew = () => { st.els++; };
  global.__heapProbeBoot = (dom) => { st.boots++; st.dom = new WeakRef(dom); };
};
