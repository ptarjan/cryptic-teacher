/* A cold result cache must be able to refill over several runs.

   After a change to the smoke test's code every puzzle is uncached; a slice
   checks only capUncached's share and names the rest as deferred. merge must
   take that as partial progress (and tools/check_shapes.js must not fail on
   the shapes of the puzzles not checked yet), but still fail a slice that
   never reported. Reads only the commit's tree, so it needs no puzzle files. */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const cc = require("./ci_cache.js");

let failures = 0;
const check = (cond, msg) => { if (!cond) { failures++; console.error("FAIL:", msg); } else console.log("ok  ", msg); };

const ids = Array.from({ length: 1000 }, (_, n) => `x-${n}`);
const cap = cc.capUncached(ids);
check(cap.now.length === 300 && cap.deferred.length === 700 && cap.now[0] === "x-0" && cap.deferred[0] === "x-300",
  "a slice takes the first 300 uncached puzzles and defers the rest");
process.env.CT_MAX_UNCACHED = "5";
check(cc.capUncached(ids).now.length === 5, "CT_MAX_UNCACHED overrides the cap");
delete process.env.CT_MAX_UNCACHED;

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ci-partial-"));
const file = "tools/smoke_test.js";
const all = [...cc.puzzles()];
const run = (name, resultsList) => {
  const dir = path.join(tmp, name);
  fs.mkdirSync(dir, { recursive: true });
  resultsList.forEach((r, n) => fs.writeFileSync(path.join(dir, `${n}.json`), JSON.stringify(r)));
  const out = path.join(dir, "out.json");
  const bad = cc.merge(path.join(dir, "none.json"), dir, out, path.join(dir, "shapes"));
  return { bad, shapes: path.join(dir, "shapes") };
};

// One slice of one: checked 3 puzzles, deferred every other.
const ids1 = all.map(([p]) => cc.idOf(p));
const done = ids1.slice(0, 3);
const rest = ids1.slice(3);
const partial = run("partial", [cc.resultsFor(file, done, { rare: false }, rest)]);
check(partial.bad === 0, "merge accepts a cache with deferred puzzles");
const noDefer = run("none", [cc.resultsFor(file, done, { rare: false }, [])]);
check(noDefer.bad === 1, "merge still fails puzzles that no slice checked or deferred");
const nothing = run("empty", []);
check(nothing.bad === 1, "merge still fails when no slice reported at all");

const shapes = (dir) => {
  try { execFileSync("node", [path.join(__dirname, "check_shapes.js"), dir], { stdio: "pipe" }); return 0; } catch (e) { return e.status; }
};
check(shapes(partial.shapes) === 0, "check_shapes passes a partial cache that has not seen every shape yet");
check(shapes(noDefer.shapes) === 1, "check_shapes fails a complete cache that lacks a shape");

fs.rmSync(tmp, { recursive: true, force: true });
console.log(failures ? `\n${failures} FAILURE(S)` : "\ntest_ci_cache_partial: all checks passed");
process.exit(failures ? 1 : 0);
