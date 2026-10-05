/* The smoke test's declared dependencies (SMOKE_DEPS in tools/ci_cache.js) name
   every file it can reach, so a cached pass is never served after one of them
   changes.

   Not run by loading the smoke test (that is the ten-minute thing this list
   exists to skip), so the reach is found statically, and each find must be
   covered by a declared prefix:
     - the relative require() closure of the smoke test and the scripts it
       spawns;
     - every repo path those scripts name in a string literal, as one literal
       ("tools/x.py") or as path.join(ROOT, "tools", "x.py") arguments;
     - the import closure of the Python the smoke test builds its inputs with
       (build_seo_pages, fetch_puzzle, build_abbreviations, stamp_assets,
       build_readme), lazy imports included.
   A path that is deliberately not a dependency goes in IGNORED with its reason.
   And the other way: a declared prefix that matches no tracked file is a typo,
   and docs and README changes must stay outside the list, or the point of it
   (a docs push is a cache hit) is lost.

   Usage: node tools/test_ci_cache_deps.js */
"use strict";
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { SMOKE_DEPS, CHECKS } = require("./ci_cache.js");

const ROOT = path.join(__dirname, "..");
let failures = 0;
const assert = (cond, msg) => { if (!cond) { failures++; console.error("FAIL:", msg); } return !!cond; };

const tracked = execFileSync("git", ["-C", ROOT, "ls-files", "-z"], { encoding: "utf8", maxBuffer: 1 << 28 })
  .split("\0").filter((f) => f && !f.startsWith("puzzles/"));
const trackedSet = new Set(tracked);
const covered = (f) => SMOKE_DEPS.some((d) => f.startsWith(d));

assert(CHECKS["tools/smoke_test.js"].deps === SMOKE_DEPS,
  "the smoke test's check declares SMOKE_DEPS, not null (everything)");

// Named by the scripts, but not an input to a per-puzzle result.
const IGNORED = {
  "docs/": "prose; the layout check that reads docs/LAYOUT.md is made by slice 0, which is never skipped",
  ".github/": "workflow files are named in messages, not read",
  "README.md": "named in messages, not read",
};
const ignored = (f) => Object.keys(IGNORED).some((d) => f.startsWith(d));

const reached = new Map();   // file -> why
const note = (f, why) => { if (!reached.has(f)) reached.set(f, why); };

/* --- JS: the require closure, plus the repo paths named in literals --- */
const readText = (f) => fs.readFileSync(path.join(ROOT, f), "utf8");
const jsSeen = new Set();
const jsQueue = ["tools/smoke_test.js", "tools/fake_dom.js"];
while (jsQueue.length) {
  const f = jsQueue.pop();
  if (jsSeen.has(f)) continue;
  jsSeen.add(f);
  note(f, "required or spawned");
  const src = readText(f);
  for (const m of src.matchAll(/require\(\s*["'](\.[^"']+)["']\s*\)/g)) {
    const base = path.normalize(path.join(path.dirname(f), m[1]));
    const hit = [base, base + ".js", base + ".json", base + "/index.js"].find((c) => trackedSet.has(c));
    if (assert(hit, `${f} requires ${m[1]}, which is not a tracked file`)) jsQueue.push(hit);
  }
  // "tools/x.py", "sync/worker.js" ...: a literal path from the repo root.
  for (const m of src.matchAll(/["'`]((?:tools|sync|vendor)\/[\w./-]+\.\w+)["'`]/g)) {
    if (trackedSet.has(m[1])) { note(m[1], `named in ${f}`); if (/\.js$/.test(m[1])) jsQueue.push(m[1]); }
  }
  // path.join(ROOT, "tools", "x.py") and path.join(ROOT, "style.css")
  for (const m of src.matchAll(/path\.join\(\s*ROOT\s*,\s*((?:"[^"]+"\s*,?\s*)+)\)/g)) {
    const rel = [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]).join("/");
    if (trackedSet.has(rel)) note(rel, `read by ${f}`);
  }
  for (const m of src.matchAll(/ROOT \+ "\/([^"]+)"/g)) if (trackedSet.has(m[1])) note(m[1], `read by ${f}`);
}

/* --- Python: the import closure of what builds the inputs --- */
const local = new Set(tracked.filter((f) => /^tools\/[^/]+\.py$/.test(f)).map((f) => path.basename(f, ".py")));
const pyQueue = ["build_seo_pages", "fetch_puzzle", "build_abbreviations", "stamp_assets", "build_readme"];
const pySeen = new Set();
while (pyQueue.length) {
  const mod = pyQueue.pop();
  if (pySeen.has(mod)) continue;
  pySeen.add(mod);
  const f = `tools/${mod}.py`;
  note(f, "imported by the page build");
  for (const m of readText(f).matchAll(/^[ \t]*(?:from[ \t]+(\w+)[ \t]+import|import[ \t]+([\w., \t]+))/gm)) {
    for (const name of (m[1] ? [m[1]] : m[2].split(",").map((x) => x.trim().split(/\s+/)[0].split(".")[0]))) {
      if (local.has(name)) pyQueue.push(name);
    }
  }
}

for (const [f, why] of reached) {
  if (ignored(f)) continue;
  assert(covered(f), `${f} (${why}) is not covered by SMOKE_DEPS in tools/ci_cache.js — add it, or a cached smoke pass will outlive a change to it`);
}
for (const d of SMOKE_DEPS) {
  assert(tracked.some((f) => f.startsWith(d)), `SMOKE_DEPS names ${d}, which matches no tracked file`);
}
for (const f of ["README.md", "docs/LAYOUT.md", "STYLE.md", ".github/workflows/tests.yml", "tools/corpus_queue.py"]) {
  assert(!covered(f), `${f} is outside SMOKE_DEPS, so changing it leaves the cache valid`);
}
assert(reached.size > 20, `the scan found only ${reached.size} files; it is no longer finding the smoke test's reach`);

if (failures) { console.error(`${failures} failure(s)`); process.exit(1); }
console.log(`ok: ${reached.size} reached files covered by ${SMOKE_DEPS.length} declared prefixes`);
