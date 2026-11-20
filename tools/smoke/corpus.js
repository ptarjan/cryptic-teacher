// What the first boot opened, which puzzles this run sweeps (a sample, one CI slice, or all), and the
// slice/shape bookkeeping the sweeps share.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, assert, fs, path, registry } = T;
// --- assertions after boot ---
assert(!registry["app"].classList.contains("hidden"), "app visible after boot");

// --- boot fetches the puzzle it opens, and not the others ---
// A puzzle file may only be fetched because something needs its
// contents — the puzzle being opened, or one with letters saved, which the
// picker holds against the solutions. This run starts with an empty store, so
// the count is exactly one, and any number above it is the regression.
// Also the one structural record of WHICH puzzle opened. The store holds
// exactly the file the app injected, so the id is read from here and never
// parsed back out of the rendered title.
const bootLoaded = Object.keys(global.window.CRYPTIC_PUZZLES || {});
assert(bootLoaded.length === 1,
  `boot loaded ${bootLoaded.length} puzzle files of ${global.CRYPTIC_INDEX.puzzles.length}; `
  + "it must load only the one it opens, and fetch the rest on demand");
const openId = bootLoaded[0];

// The checks below are about the corpus, not about booting, so they need all of
// it. Loaded here, deliberately after the assertion above — that ordering is the
// only thing keeping the two apart.
// p.file is the generated script the page injects, not the puzzle source, because
// this arm is testing what the browser loads. The boot above rebuilt it.
//
// Which puzzles get loaded is the ONE dial that sets this file's running time.
// Every corpus sweep below walks `window.CRYPTIC_PUZZLES` and re-opens each
// puzzle through the picker, so the whole suite costs roughly what this loop
// loads: the full index is ~16,000 puzzles and about three minutes, which is
// not a loop anyone runs between edits. Locally it therefore loads a SAMPLE —
// the newest annotated puzzle of every series, so each series' generator is
// still exercised — and the nightly (nightly-smoke.yml) loads all of it. FULL is the flag every sweep-wide
// count below is gated on, because those counts are statements about the whole
// corpus and a sample cannot make them.
const FULL = !!process.env.CT_FULL;
// CI_SLICE="i/n" makes this run one of n slices of the corpus, by puzzle id
// (tools/ci_cache.js's inSlice, the one slicing rule). The checks that are not
// sweeps run in every slice (they are seconds), except the shelled-out ones,
// which slice 0 runs alone. Unset, this run is the only slice.
const SLICE = (() => {
  const m = /^(\d+)\/(\d+)$/.exec(process.env.CI_SLICE || "");
  return m && +m[1] < +m[2] ? { i: +m[1], n: +m[2] } : { i: 0, n: 1 };
})();
const ciCache = require("../ci_cache.js");
const inSlice = (key) => ciCache.inSlice(key, SLICE.i, SLICE.n);
// tests.yml sweeps the whole corpus on every push, but through a result cache
// (tools/ci_cache.js): CT_CACHE names the restored cache, and this slice sweeps
// the sample above PLUS every puzzle of its slice with no passing result for
// this code. A passing run writes what it checked to $CT_RESULTS_OUT (end of
// this file) for the cache. The cache-free full sweep is the nightly's
// (nightly-smoke.yml, CT_FULL=1).
// At most ci_cache.js's MAX_UNCACHED of them per run: after a change to the
// code every puzzle is uncached, and a slice that took all ~1450 of them died
// with no message. The rest are DEFERRED, named in the results file, and the
// next runs take them.
const UNCACHED = process.env.CT_CACHE
  ? ciCache.capUncached(ciCache.uncached(ciCache.readCache(process.env.CT_CACHE), "tools/smoke_test.js", SLICE.i, SLICE.n))
  : { now: [], deferred: [] };
const CHANGED = new Set(UNCACHED.now);
// A run that dies without a FAIL line (killed for memory, a runner torn down)
// leaves nothing to read; this says how far it got and how much it held.
const stage = { at: "booting" };
const mb = () => Math.round(process.memoryUsage().rss / 1048576);
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    console.error(`FAIL: smoke slice ${process.env.CI_SLICE || "-"} got ${sig} while ${stage.at} (rss ${mb()} MB)`);
    process.exit(1);
  });
}
process.on("exit", (code) => {
  if (code) console.error(`(smoke slice ${process.env.CI_SLICE || "-"} exits ${code} while ${stage.at}, rss ${mb()} MB)`);
});
function load(p) {
  if (global.window.CRYPTIC_PUZZLES[p.id]) return;
  new Function("window", fs.readFileSync(path.join(ROOT, "puzzles", p.file), "utf8"))(global.window);
}
const corpus = (() => {
  const all = global.CRYPTIC_INDEX.puzzles;
  if (FULL) return all.filter((p) => inSlice(p.id) || p.id === openId);
  // `date` is "YYYY-MM-DD", which sorts as a string. A book puzzle holds a
  // `year` and no `date`: its 1 January for ordering.
  const day = (p) => (p.year !== undefined ? `${p.year}-01-01` : p.date || "");
  const newest = (f) => all.filter(f).sort((a, b) => day(b).localeCompare(day(a)));
  const bySeries = new Map();
  for (const p of newest((p) => p.annotated)) if (!bySeries.has(p.series)) bySeries.set(p.series, p);
  // The shapes individual sections go looking for, each one the newest of its
  // kind. A section that hunts the corpus for a puzzle shaped a certain way
  // finds nothing in a sample that holds none, so the sample owes one of each:
  // without it those sections do not fail, they throw, and the stack trace ends
  // the run. Un-annotated takes several because the index flag means "some clue
  // lacks an annotation" and the degradation section wants one where EVERY clue
  // does, which is only knowable once the file is loaded.
  return [].concat(
    [...bySeries.values()],
    // Twenty rather than five: most new puzzles carry a blog's facts, and both
    // the degraded panel and the blog-hint ladder below each need one.
    newest((p) => !p.annotated && p.hasSolutions).slice(0, 20),
    // The degraded panel wants one with no blog and no annotation at all, which
    // the newest twenty stop holding once the blogs cover them.
    // find, not filter: it stops at the first match instead of loading every
    // un-annotated puzzle in the index to throw all but one away.
    [newest((p) => !p.annotated && p.hasSolutions).find((p) => {
      load(p);
      const puz = global.window.CRYPTIC_PUZZLES[p.id];
      return puz && !puz.blog && puz.entries.every((e) => !e.annotation);
    })].filter(Boolean),
    newest((p) => p.solutionsUnofficial).slice(0, 1),
    newest((p) => p.annotated && p.hasSolutions && !p.solutionsUnofficial).slice(0, 1),
    newest((p) => !p.date && p.annotated).slice(0, 1),
    // Already loaded, but the sections above derive their expectations from
    // whatever booted and the sample must not be read as dropping it.
    all.filter((p) => p.id === openId),
    all.filter((p) => CHANGED.has(p.id)));
})();
stage.at = `loading ${corpus.length} puzzles`;
corpus.forEach(load);
stage.at = "sweeping the corpus";
assert(Object.keys(global.window.CRYPTIC_PUZZLES).length >= (FULL ? 25 : 5),
  "the corpus is loaded for the checks below");
if (!FULL) console.log(`(sampled ${corpus.length} puzzles of ${global.CRYPTIC_INDEX.puzzles.length}, `
  + `${CHANGED.size} of them uncached in slice ${SLICE.i}/${SLICE.n}`
  + `${UNCACHED.deferred.length ? `, ${UNCACHED.deferred.length} more deferred to later runs` : ""}; `
  + `CT_FULL=1 sweeps all of them; rss ${mb()} MB)`);
// A floor under how much a sweep found is a statement about the CORPUS, and a
// sample cannot make it. What the floor is really guarding against is a sweep
// that quietly stopped finding anything — a filter that matches nothing passes
// every assertion inside the loop by never running one — and a sample can make
// that statement. So the floor stands in CI and becomes "more than none" here.
// A slice holds about 1/n of the corpus, so it owes about 1/n of the floor.
const enough = (n, floor) => n > (FULL ? floor / SLICE.n : 0);
// "The corpus holds an example of rare shape X" is a statement about the whole
// corpus, which no sample and no single slice can make: a sample may hold none
// and a slice holds a sixteenth. So such a check goes through shape(). A run
// that finds none skips the section that needed one; it never fails on that
// alone. Under CT_FULL each slice writes which shapes it saw to $CT_SHAPES_OUT
// (end of this file), and tools/check_shapes.js, run once after every slice by
// nightly-smoke.yml, fails on a shape no slice saw or a slice that never
// reported. The section itself still runs wherever an example turns up.
const shapesSeen = {};
const shape = (name, found) => {
  shapesSeen[name] = shapesSeen[name] || !!found;
  return !!found;
};

Object.assign(T, { FULL, SLICE, UNCACHED, ciCache, corpus, enough, inSlice, openId, shape,
  shapesSeen });
