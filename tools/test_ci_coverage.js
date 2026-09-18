/* Every test in tools/ runs somewhere a later push cannot cancel.

   A GitHub workflow with `concurrency: cancel-in-progress: true` abandons
   everything still running in it the moment another push arrives. That is right
   for a deploy — nobody wants the older of two builds to publish — and wrong
   for a check, because a check a later push can cancel is a check that is
   optional. tools/smoke_test.js was reachable only from pages.yml, which has
   exactly that block, and the file was missed by tests.yml's `tools/test_*`
   glob for the only reason that it spells the word the other way round. A
   naming convention that silently excludes a file is a convention that decides
   what gets tested without anybody choosing.

   So the convention is asserted rather than assumed: a file in tools/ that
   looks like a test must be matched by the globs in the workflow that cannot be
   cancelled. A new test is wired in by being named, and a test named something
   nobody thought of fails here instead of quietly never running.

   Usage: node tools/test_ci_coverage.js */
"use strict";
const fs = require("fs");
const path = require("path");
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

const cancellable = (f) =>
  /^\s*cancel-in-progress:\s*true\b/m.test(undecorated(read(f)));

/* --- the test workflow is the one nothing can cancel --- */
assert(!/^\s*concurrency\s*:/m.test(undecorated(read("tests.yml"))),
  "tests.yml declares no concurrency group, so a later push cannot cancel a check");
/* --- and the deploy is still superseded by a newer push --- */
assert(cancellable("pages.yml"),
  "pages.yml still cancels an in-flight deploy when a newer push arrives, so the " +
  "older of two builds cannot publish");

/* --- every test entry point is matched by the globs in tests.yml --- */
// The globs are read out of the workflow rather than restated here; a second
// copy of the list of what gets run is a copy to disagree with.
const loop = undecorated(read("tests.yml")).match(/for\s+t\s+in\s+([^;\n]+?)\s*;?\s*do/);
assert(loop, "tests.yml still runs its tests from a `for t in <globs>; do` loop");
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
const body = undecorated(read("tests.yml"));
assert(/case\s+"\$t"\s+in\s+\*\.sh\)\s*run=bash/.test(body) && /run=node/.test(body),
  "the loop picks its interpreter from the extension, so both spellings run");

console.log(failures
  ? `${failures} failure(s)`
  : `ok: ${entryPoints.length} test entry point(s), all run by tests.yml`);
process.exit(failures ? 1 : 0);
