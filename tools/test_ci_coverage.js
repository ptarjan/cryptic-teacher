/* Every test in tools/ runs somewhere a later push cannot cancel, exactly once.

   A check a later push can cancel is a check that is optional, and a
   `concurrency:` group is what makes one cancellable: GitHub keeps only the
   newest PENDING run in a group and cancels the rest, whatever
   cancel-in-progress says. pages.yml declares one — it must, so that two
   deploys cannot race — so a test reachable only from there is not a test the
   repo enforces. tests.yml declares none, and that is asserted here rather
   than assumed.

   A test can also fail to run by being named something no glob catches, so the
   convention is asserted too: a file in tools/ that looks like a test must be
   matched by the globs in tests.yml. A new test is wired in by being named, and
   a test named something nobody thought of fails here instead of quietly never
   running.

   tests.yml runs those matched files across parallel shards, which adds a third
   way to go quiet: a file the globs match but no shard is handed. So this
   drives tools/ci_shards.js — the same splitter the workflow pipes the glob
   list into — over the real file list at the real shard count and asserts the
   shards partition it: every file in one, none in two, no empty shard.

   And a failure has to reach a check name: `tests-passed` is the one job that
   means the suite is green, so it must need every other job in the workflow.

   Usage: node tools/test_ci_coverage.js */
"use strict";
const fs = require("fs");
const path = require("path");
const { shards } = require("./ci_shards.js");
const ROOT = path.join(__dirname, "..");
const WORKFLOWS = path.join(ROOT, ".github/workflows");

let failures = 0;
const assert = (cond, msg) => { if (!cond) { failures++; console.error("FAIL:", msg); } return !!cond; };

// Full-line comments only: this file's own prose says "concurrency:" and the
// workflows' prose says it too, and neither is a declaration.
const undecorated = (text) => text.split("\n")
  .filter((l) => !/^\s*#/.test(l)).join("\n");

const read = (f) => fs.readFileSync(path.join(WORKFLOWS, f), "utf8");
const workflows = fs.readdirSync(WORKFLOWS).filter((f) => /\.ya?ml$/.test(f));
assert(workflows.includes("tests.yml") && workflows.includes("pages.yml"),
  "the repo still has a test workflow and a deploy workflow: " + workflows.join(", "));

const grouped = (f) => /^\s*concurrency\s*:/m.test(undecorated(read(f)));

/* --- the test workflow is the one nothing can cancel --- */
assert(!grouped("tests.yml"),
  "tests.yml declares no concurrency group, so a later push cannot cancel a check");
/* --- and the deploy is in a group, so a check living there can still be cancelled --- */
assert(grouped("pages.yml"),
  "pages.yml still declares a concurrency group, which is what makes a check " +
  "reachable only from there optional");

/* --- every test entry point is matched by the globs in tests.yml --- */
// The globs are read out of the workflow rather than restated here; a second
// copy of the list of what gets run is a copy to disagree with.
const body = undecorated(read("tests.yml"));
const loop = body.match(/for\s+t\s+in\s+([^;\n]+?)\s*;?\s*do/);
assert(loop, "tests.yml still collects its tests from a `for t in <globs>; do` loop");
const globs = loop ? loop[1].trim().split(/\s+/) : [];
assert(globs.length >= 2, "and the loop names more than one glob: " + globs.join(" "));
const matches = (rel) => globs.some((g) =>
  new RegExp("^" + g.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]*") + "$")
    .test(rel));

/* A file in tools/ "looks like a test" if its name says so. Anything matching
   that is an entry point unless it is named below — an exclusion has to be
   written down and defended, never inferred from a glob that happens to miss
   it. Empty today, and that is the honest state: every such file is a test. */
const NOT_A_TEST = [];
const candidates = fs.readdirSync(path.join(ROOT, "tools"))
  .filter((f) => /\.(js|sh)$/.test(f) && /test/i.test(f))
  .sort();
assert(candidates.length > 5, "tools/ still holds the test scripts: " + candidates.length);
NOT_A_TEST.forEach((f) => assert(candidates.includes(f),
  `'${f}' is excused from being a test but is not there any more — drop it from ` +
  "NOT_A_TEST rather than leaving an exclusion that excludes nothing"));

const entryPoints = candidates.filter((f) => !NOT_A_TEST.includes(f));
entryPoints.forEach((f) => assert(matches("tools/" + f),
  `tools/${f} is a test that nothing uncancellable runs: it matches none of the ` +
  `globs in tests.yml (${globs.join(" ")}). Name it so one of them catches it, ` +
  "or widen the loop — do not leave it reachable only from the deploy."));

// The file this was written for, named so the check cannot pass by finding
// nothing: if smoke_test.js is ever renamed this says so instead of going quiet.
assert(entryPoints.includes("smoke_test.js"),
  "tools/smoke_test.js is still the load-bearing test and still covered here");

/* --- and the loop can actually run each of them --- */
// A glob that matches a file the loop then feeds to the wrong interpreter is a
// test that fails for the wrong reason.
assert(/case\s+"\$t"\s+in\s+\*\.sh\)\s*run=bash/.test(body) && /run=node/.test(body),
  "the loop picks its interpreter from the extension, so both spellings run");

/* --- the shards partition what the globs matched --- */
// Asserting the splitter is only worth anything while the workflow is the thing
// calling it.
assert(/node\s+tools\/ci_shards\.js/.test(body),
  "tests.yml still pipes its glob list through tools/ci_shards.js to pick a shard");
const shardList = body.match(/^\s*shard:\s*\[([^\]]*)\]/m);
assert(shardList, "tests.yml still declares its shards as `shard: [...]`");
const shardIds = shardList ? shardList[1].split(",").map((s) => s.trim()).filter(Boolean) : [];
assert(shardIds.length >= 2,
  "and there is more than one of them, or the fan-out is a single job again: " +
  shardIds.join(","));
assert(shardIds.join(",") === shardIds.map((_, i) => String(i)).join(","),
  "and they are 0..n-1 in order, which is what the job passes as its shard " +
  `index alongside strategy.job-total: ${shardIds.join(",")}`);

if (shardIds.length >= 2) {
  const files = entryPoints.map((f) => "tools/" + f);
  const split = shards(files, shardIds.length);
  split.forEach((s, i) => assert(s.length > 0,
    `shard ${i} of ${shardIds.length} is handed no tests — drop a shard rather ` +
    "than paying for a job that passes by running nothing"));
  const placed = split.flat();
  const seen = new Set();
  placed.forEach((f) => {
    assert(!seen.has(f), `${f} is in two shards, so the suite pays for it twice`);
    seen.add(f);
  });
  files.forEach((f) => assert(seen.has(f),
    `${f} is matched by the globs but lands in no shard, so it runs nowhere`));
  assert(placed.length === files.length,
    `the shards hold ${placed.length} scripts and the globs matched ${files.length}`);
}

/* --- one check name carries the verdict --- */
// Branch protection and the CI watcher key on `tests-passed`. A job it does not
// need is a job that can go red without turning that check red.
// Two-space keys under `jobs:` and nowhere else — `on:` has children indented
// the same way, and `push` is not a job.
const jobsBlock = body.slice(body.search(/^jobs:\s*$/m));
const jobs = [...jobsBlock.matchAll(/^ {2}([A-Za-z0-9_-]+):$/gm)].map((m) => m[1]);
assert(jobs.length >= 2, "tests.yml still declares jobs: " + jobs.join(", "));
assert(jobs.includes("tests-passed"),
  "tests.yml still has a `tests-passed` job, the one check name that means the " +
  "suite is green: " + jobs.join(", "));
const needs = body.match(/^ {2}tests-passed:[\s\S]*?^\s*needs:\s*(\[[^\]]*\]|.*)$/m);
assert(needs, "and it declares what it needs");
const needed = needs ? needs[1].replace(/[[\]]/g, "").split(",").map((s) => s.trim()) : [];
jobs.filter((j) => j !== "tests-passed").forEach((j) => assert(needed.includes(j),
  `job '${j}' can fail without failing tests-passed — add it to that job's needs`));
assert(/^ {2}tests-passed:[\s\S]*?^\s*if:\s*always\(\)/m.test(body),
  "and it runs with `if: always()`, or a failed shard skips it and branch " +
  "protection waits on a check that never reports");

console.log(failures
  ? `${failures} failure(s)`
  : `ok: ${entryPoints.length} test entry point(s), all run by tests.yml across ` +
    `${shardIds.length} shard(s)`);
process.exit(failures ? 1 : 0);
