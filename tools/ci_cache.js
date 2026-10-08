/* The per-puzzle result cache that lets every push check the whole corpus.

   A result is cached per (check, puzzle). It stands while two hashes are
   unchanged: the puzzle file's git blob, and the check's CODE KEY, a hash of
   the git blobs of every file the check declares it depends on (CHECKS). A
   check that cannot name its dependencies declares `deps: null`, meaning every
   tracked file outside puzzles/. So a push that only adds or edits puzzles
   re-runs the check on just those puzzles, and a push that changes a check's
   code re-runs that check on all of them.

   The cache is one JSON file, carried between runs by actions/cache in
   tests.yml (restored from the newest entry, saved under the commit):
     { "<check>": { code, pass: { "<puzzle path>": "<blob>" }, shapes } }
   Only passing results go in it: a slice of the check writes its results file
   (resultsFor) only when it passed, and `merge` folds those into the restored
   cache, dropping every entry whose code key or blob is no longer current.

   Rare-shape checks ("the corpus holds an example of X") are statements about
   the whole corpus, so a slice that re-ran a few puzzles cannot make them. The
   shapes each passing slice saw are kept under the check's code key and
   unioned, and `merge` writes the union for tools/check_shapes.js. A code
   change re-runs every slice, so the union is rebuilt from scratch; between
   code changes it can still credit a shape to a puzzle that has since been
   edited, which nightly-smoke.yml's cache-free run catches.

   Usage:
     node tools/ci_cache.js --drop-cached <cache.json>   < test items
         prints the items still owing work: a slice "i/n" (i > 0) of a cached
         check is dropped when every puzzle in it is cached. Slice 0 always
         stays, since it carries the check's non-sweep assertions.
     node tools/ci_cache.js merge <cache.json> <results dir> <out.json> <shapes dir>
         folds the passing slices' results in, writes the new cache and the
         shape union, and fails when any puzzle is left unchecked. */
"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { execFileSync } = require("child_process");

const ROOT = path.join(__dirname, "..");

// Each cached check, by the test file that runs it, and the files its result
// depends on (path prefixes), or null for "everything outside puzzles/".
//
// smoke_test.js's list is every file it requires or reads, directly or through
// the code it runs: the JS it requires, the app and pages it boots, the Python
// that builds the pages and index it reads (build_seo_pages.py, fetch_puzzle.py,
// build_abbreviations.py and every tools/ module they import) and the data
// under tools/data/. Left out on purpose: puzzles/ (keyed per puzzle), docs/,
// the *.md files, scratch/, household-plugins/, .github/ and the rest of
// tools/. The one assertion over the whole tree, build_readme.py
// --check-layout (every tracked file has a row in docs/LAYOUT.md), and the
// shelled-out sub-tests are made by slice 0, which is never skipped, so a
// docs-only push still gets them and they need no key. tools/test_ci_cache_deps.js keeps the list from going stale:
// it fails when a file the smoke test reaches is not named here.
// Over-including costs a re-run; under-including serves a stale pass.
const SMOKE_DEPS = [
    "app.js", "analytics.js", "index.html", "style.css", "qr.js", "quotes.js", "sw.js", "site.webmanifest",
    "favicon", "apple-touch-icon", "icon-192.png", "icon-512.png", "og.png", "sync/", "vendor/",
    "tools/acquire_book.py", "tools/alert.sh", "tools/annotation.py", "tools/annotation_backlog.json",
    "tools/app_tables.py", "tools/apply_solution.py", "tools/archive_coverage.py", "tools/blog_facts.py",
    "tools/blog_facts_gold.jsonl", "tools/book_queue.py", "tools/boilerplate.py", "tools/build_abbreviations.py",
    "tools/build_lexicon.js", "tools/build_readme.py", "tools/build_seo_pages.py", "tools/canberra_london_numbers.py",
    "tools/check_shapes.js", "tools/ci_cache.js", "tools/clue_index.py", "tools/clue_types.py", "tools/clues_only.py",
    "tools/clueability.py", "tools/code_reach.py", "tools/corroborate.py", "tools/ctc_transcripts.py",
    "tools/daily_update.sh", "tools/data/", "tools/definitions.py", "tools/deleted_paths.py", "tools/desktop_busy.py", "tools/difficulty.py",
    "tools/difficulty_check.py", "tools/difficulty_page.html", "tools/downloads.py", "tools/enumeration.py",
    "tools/errata.py", "tools/fake_dom.js", "tools/fetch_lexicon.sh",
    "tools/fetch_archive_org_editions.py", "tools/fetch_ia_book.py", "tools/fetch_privateeye.py", "tools/fetch_puzzle.py", "tools/fetch_times_listing.py",
    "tools/file_archive_org_puzzles.py", "tools/file_penguin_puzzle.py",
    "tools/file_trove_puzzles.py", "tools/find_answer_leaks.py", "tools/grid_fill.py", "tools/grid_verdict.py",
    "tools/groups.py", "tools/hidden_messages.py", "tools/indicator_keys.py", "tools/json_merge.py",
    "tools/letter_facts.py", "tools/light_spec.py", "tools/make_og.sh", "tools/make_og_card.py",
    "tools/nightly_worktree.sh", "tools/normalise_linked_enumerations.py", "tools/ocr_clues.py",
    "tools/ocr_full_pass.sh", "tools/ocr_remote.py", "tools/og_card.html",
    "tools/og_page_card.html", "tools/page_card.py", "tools/parallel.py", "tools/parse_penguin_book.py",
    "tools/prereset_backfill.sh", "tools/provenance.py", "tools/push_puzzle_commit.sh",
    "tools/puzzle_integrity.py", "tools/puzzle_paths.js", "tools/puzzle_paths.py",
    "tools/puzzle_schema.py", "tools/puzzle_tags.py", "tools/quotes.py", "tools/reconstruct_grid.py", "tools/reprints.py",
    "tools/reindex.js", "tools/scan_crop.py", "tools/scan_queue.py", "tools/series.py",
    "tools/showcase.py", "tools/smoke_test.js", "tools/stamp_assets.py",
    "tools/test_alert_claimed.sh", "tools/test_nightly_worktree.sh",
    "tools/test_notify_race.js", "tools/test_prereset_paths.sh", "tools/test_push_hold.js",
    "tools/trove_clue_ocr.py", "tools/trove_grid.py", "tools/trove_solution_ocr.py",
    "tools/tutorial.html", "tools/unstage_unparsable.sh", "tools/validate_annotations.py", "tools/vlm_reader.py",
];
const CHECKS = {
  "tools/smoke_test.js": { deps: SMOKE_DEPS },
};

// Every tracked file as path -> blob, read from the commit's tree, so it needs
// no blob on disk (a blob:none clone has the trees) and ignores build output.
let treeMemo = null;
function tree() {
  if (treeMemo) return treeMemo;
  treeMemo = new Map();
  const out = execFileSync("git", ["-C", ROOT, "ls-tree", "-r", "-z", "HEAD"],
    { encoding: "utf8", maxBuffer: 1 << 28 });
  for (const rec of out.split("\0")) {
    const tab = rec.indexOf("\t");
    if (tab > 0) treeMemo.set(rec.slice(tab + 1), rec.slice(0, tab).split(" ")[2]);
  }
  return treeMemo;
}

const isPuzzle = (p) => p.startsWith("puzzles/") && p.endsWith(".json");
const idOf = (p) => path.basename(p, ".json");

/* puzzle path -> blob, every puzzle in the commit. */
function puzzles() {
  return new Map([...tree()].filter(([p]) => isPuzzle(p)));
}

const keyMemo = {};
function codeKey(check) {
  if (keyMemo[check]) return keyMemo[check];
  const deps = CHECKS[check].deps;
  const h = crypto.createHash("sha256").update(check + "\n");
  for (const [p, blob] of [...tree()].sort(([a], [b]) => (a < b ? -1 : 1))) {
    if (p.startsWith("puzzles/")) continue;
    if (deps && !deps.some((d) => p.startsWith(d))) continue;
    h.update(`${blob} ${p}\n`);
  }
  return (keyMemo[check] = h.digest("hex"));
}

// FNV-1a of the puzzle id: stable across runs and machines. The one slicing
// rule, shared with tools/smoke_test.js's CI_SLICE.
function inSlice(id, i, n) {
  let h = 2166136261;
  for (const c of String(id)) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
  return h % n === i;
}

function readCache(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) {
    if (e.code === "ENOENT") return {};
    throw e;
  }
}

/* The ids in slice i/n whose cached result for `check` is missing or stale. */
function uncached(cache, check, i, n) {
  const entry = cache[check];
  const pass = entry && entry.code === codeKey(check) ? entry.pass : {};
  const out = [];
  for (const [p, blob] of puzzles()) {
    const id = idOf(p);
    if (inSlice(id, i, n) && pass[p] !== blob) out.push(id);
  }
  return out;
}

/* The results file a passing slice writes: the puzzles it checked, by id. */
function resultsFor(check, ids, shapes) {
  const byId = new Map([...puzzles()].map(([p, blob]) => [idOf(p), [p, blob]]));
  const pass = {};
  for (const id of ids) if (byId.has(id)) pass[byId.get(id)[0]] = byId.get(id)[1];
  return { check, code: codeKey(check), pass, shapes };
}

function merge(cacheFile, resultsDir, outFile, shapesDir) {
  const cache = readCache(cacheFile);
  const all = puzzles();
  const results = fs.existsSync(resultsDir)
    ? fs.readdirSync(resultsDir).filter((f) => f.endsWith(".json"))
      .map((f) => JSON.parse(fs.readFileSync(path.join(resultsDir, f), "utf8")))
    : [];
  const out = {};
  let bad = 0;
  for (const check of Object.keys(CHECKS)) {
    const code = codeKey(check);
    const old = cache[check] && cache[check].code === code ? cache[check] : { pass: {}, shapes: {} };
    const entry = { code, pass: {}, shapes: { ...old.shapes } };
    let fresh = 0;
    for (const [p, blob] of Object.entries(old.pass)) if (all.get(p) === blob) entry.pass[p] = blob;
    for (const r of results.filter((r) => r.check === check && r.code === code)) {
      for (const [p, blob] of Object.entries(r.pass)) {
        if (all.get(p) === blob) { fresh += entry.pass[p] ? 0 : 1; entry.pass[p] = blob; }
      }
      for (const [k, v] of Object.entries(r.shapes || {})) entry.shapes[k] = entry.shapes[k] || v;
    }
    out[check] = entry;
    const missing = [...all.keys()].filter((p) => !entry.pass[p]);
    console.log(`${check}: ${all.size - missing.length} of ${all.size} puzzles pass `
      + `(${fresh} newly passed in this run)`);
    if (missing.length) {
      bad++;
      console.error(`FAIL: ${check} has no passing result for ${missing.length} puzzle(s), e.g. `
        + missing.slice(0, 5).join(", ") + " (a slice failed or never ran)");
    }
    if (shapesDir) {
      fs.mkdirSync(shapesDir, { recursive: true });
      fs.writeFileSync(path.join(shapesDir, path.basename(check, ".js") + ".json"),
        JSON.stringify({ slice: 0, of: 1, shapes: entry.shapes }));
    }
  }
  fs.writeFileSync(outFile, JSON.stringify(out));
  return bad;
}

module.exports = { CHECKS, SMOKE_DEPS, codeKey, puzzles, inSlice, readCache, uncached, resultsFor, idOf };

if (require.main === module && process.argv[2] === "--drop-cached") {
  const cache = readCache(process.argv[3]);
  for (const item of fs.readFileSync(0, "utf8").split("\n").filter(Boolean)) {
    const [file, slice] = item.split(" ");
    const m = /^(\d+)\/(\d+)$/.exec(slice || "");
    if (CHECKS[file] && m && +m[1] > 0 && !uncached(cache, file, +m[1], +m[2]).length) {
      console.error(`${item}: every puzzle cached, skipped`);
      continue;
    }
    console.log(item);
  }
} else if (require.main === module && process.argv[2] === "merge") {
  process.exit(merge(...process.argv.slice(3, 7)) ? 1 : 0);
} else if (require.main === module) {
  console.error("usage: node tools/ci_cache.js --drop-cached <cache> | merge <cache> <results dir> <out> [<shapes dir>]");
  process.exit(2);
}
