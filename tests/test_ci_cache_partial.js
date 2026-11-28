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
const cc = require("../tools/ci_cache.js");

let failures = 0;
const check = (cond, msg) => { if (!cond) { failures++; console.error("FAIL:", msg); } else console.log("ok  ", msg); };

const ids = Array.from({ length: 1000 }, (_, n) => `x-${n}`);
const cap = cc.capUncached(ids);
const max = cc.MAX_UNCACHED;
check(cap.now.length === max && cap.deferred.length === 1000 - max && cap.now[0] === "x-0" && cap.deferred[0] === `x-${max}`,
  `a slice takes the first ${max} uncached puzzles and defers the rest`);
process.env.CT_MAX_UNCACHED = "5";
check(cc.capUncached(ids).now.length === 5, "CT_MAX_UNCACHED overrides the cap");
delete process.env.CT_MAX_UNCACHED;

// The order a capped slice takes them in: content no run has checked first
// (never seen, or edited since), then the longest unchecked, so successive
// runs walk the slice rather than re-check its head after every code change.
const seenEntry = { seen: { a: [cc.tag("a1"), 5], b: [cc.tag("b1"), 2], c: [cc.tag("c0"), 1] } };
const order = cc.byOwed(seenEntry, [["a", "a1"], ["b", "b1"], ["c", "c1"], ["d", "d1"]]).map(([p]) => p);
check(order.join() === "c,d,b,a",
  `edited and never-checked puzzles come first, then the oldest checked: ${order.join()}`);

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
{
  const out = JSON.parse(fs.readFileSync(path.join(tmp, "partial", "out.json"), "utf8"))[file];
  check(out.run === 1 && done.every((id) => out.seen[all.find(([p]) => cc.idOf(p) === id)[0]][1] === 1)
    && Object.keys(out.seen).length === done.length,
    "merge records which run checked each puzzle it passed, and only those");
}
// A code change drops `pass` but keeps `seen` and counts the run on.
{
  const dir = path.join(tmp, "carry");
  fs.mkdirSync(dir, { recursive: true });
  const [p0, blob0] = all[0];
  fs.writeFileSync(path.join(dir, "old.json"), JSON.stringify({ [file]: {
    code: "older code", pass: { [p0]: blob0 }, shapes: {}, run: 7, seen: { [p0]: [cc.tag(blob0), 7], "puzzles/gone.json": ["x", 1] } } }));
  cc.merge(path.join(dir, "old.json"), path.join(dir, "none"), path.join(dir, "out.json"));
  const out = JSON.parse(fs.readFileSync(path.join(dir, "out.json"), "utf8"))[file];
  check(out.run === 8 && !out.pass[p0] && out.seen[p0][1] === 7 && !out.seen["puzzles/gone.json"],
    "a code change keeps when each puzzle was last checked, and forgets deleted puzzles");
}
const nothing = run("empty", []);
check(nothing.bad === 1, "merge still fails when no slice reported at all");

const shapes = (dir) => {
  try { execFileSync("node", [path.join(__dirname, "..", "tools", "check_shapes.js"), dir], { stdio: "pipe" }); return 0; } catch (e) { return e.status; }
};
check(shapes(partial.shapes) === 0, "check_shapes passes a partial cache that has not seen every shape yet");
check(shapes(noDefer.shapes) === 1, "check_shapes fails a complete cache that lacks a shape");

fs.rmSync(tmp, { recursive: true, force: true });
console.log(failures ? `\n${failures} FAILURE(S)` : "\ntest_ci_cache_partial: all checks passed");
process.exit(failures ? 1 : 0);
