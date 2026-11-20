/* Splits the test scripts across the parallel jobs of tests.yml.

   Every job feeds it the SAME list — the one its `for t in <globs>` loop
   collects — and asks for one shard of it. The split is a pure function of that
   list, so the jobs agree without talking to each other: every file lands in
   exactly one shard, and a file nobody's glob matched is a file that runs
   nowhere, which is what tests/test_ci_coverage.js is there to catch.

   Balance is by cost, not by count: a few scripts are most of the suite's
   runtime and putting two of them in one shard makes that shard the wall clock.
   COST holds their measured seconds; anything not listed is assumed light. A
   stale entry costs balance and nothing else — an unknown test still runs, just
   possibly in a shard that finishes later than it could.

   A script too heavy to fit in one job is split into SLICES: it appears as
   several items, "tools/smoke_test.js 0/4" .. "3/4", each landing in a shard
   like any other item. The workflow runs the part after the space as CI_SLICE,
   and the script itself decides what a slice of it means.

   Only the scripts in PAGES read the generated site pages, which take a
   minute and a half to build, so only a shard handed one of them builds them;
   `--needs-pages` answers that for a shard's list. A page reader missing from
   PAGES fails loudly on the missing file, it does not pass quietly.

   A script in PARALLEL is single-threaded and touches nothing but its own
   output, so a shard runs all of its PARALLEL items at once beside the rest
   (the runner has CORES cores); LPT charges such an item COST/CORES, and
   hands a shard no more than CORES of them, counting a SLOTS script as its
   share, while another shard has room.
   `--parallel` prints the PARALLEL items of a shard's list, `--serial` the rest.

   Usage: printf '%s\n' tests/test_a.sh ... | node tools/ci_shards.js <i> <n>
          printf '%s\n' <shard's items> | node tools/ci_shards.js --needs-pages */
"use strict";

// Runner seconds, measured on CI. Every script that took three seconds or
// more is here; the default covers the rest and any test written since.
const COST = {
  // One slice of the whole corpus with nothing cached, the case a code change
  // pays; a slice whose every puzzle is cached is dropped before it runs
  // (tools/ci_cache.js).
  "tools/smoke_test.js": 480,
  "tests/test_push_conflict.sh": 17,
  "tests/test_reconstruct_grid.py": 25,
  "tests/test_paper_mode.js": 62,
  // A real Chromium saving ~200 puzzles, then reloading with the server gone.
  "tests/test_offline_library.js": 40,
  "tests/test_file_trove_puzzles.sh": 54,
  "tests/test_solve_queue_clues.sh": 66,
  "tests/test_shim_format.py": 59,
  "tests/test_acquire_book.py": 61,
  "tests/test_provenance.py": 28,
  "tests/test_blog_facts.sh": 34,
  // 209 s locally with the corpus-wide clue index (~50 s) it no longer builds.
  "tests/test_file_archive_org_puzzles.py": 150,
  "tests/test_puzzle_invariants.py": 7,
  "tests/test_alert_claimed.sh": 6,
  "tests/test_repair_fetched.py": 5,
  "tests/test_letter_facts.sh": 4,
  "tests/test_og_tags.js": 4,
  // Reads every puzzle shim (~65k) once.
  "tests/test_formula_math.js": 130,
};
const DEFAULT_COST = 3;

// How many slices each splittable script runs as (see the header).
const SLICES = { "tools/smoke_test.js": 40 };

// See the header: all run concurrently within a shard, each charged COST/CORES.
const PARALLEL = new Set(["tools/smoke_test.js"]);
const CORES = 4;
// Serial scripts that hold as much memory as a PARALLEL item while the shard's
// PARALLEL items run beside them: each takes that many of the shard's CORES
// slots. The archive.org filer loads the scan readers (numpy, OpenCV) and its
// corpus; four smoke slices beside it killed the runner (13:41 and 18:12 UTC,
// 29 Oct 2026), three did not.
const SLOTS = { "tests/test_file_archive_org_puzzles.py": 1 };
const slots = (item) => (PARALLEL.has(fileOf(item)) ? 1 : SLOTS[fileOf(item)] || 0);
const used = (bin) => bin.files.reduce((n, f) => n + slots(f), 0);

// The scripts that read what tools/build_seo_pages.py writes.
const PAGES = new Set(["tools/smoke_test.js", "tests/test_og_tags.js"]);
// Runner seconds to build them, charged once to a shard that holds a reader.
const PAGE_BUILD = 95;

const fileOf = (item) => item.split(" ")[0];

/* Each file as the items it runs as: itself, or one per slice. */
function items(files) {
  return files.flatMap((f) => (SLICES[f]
    ? Array.from({ length: SLICES[f] }, (_, i) => `${f} ${i}/${SLICES[f]}`)
    : [f]));
}

const needsPages = (list) => list.some((item) => PAGES.has(fileOf(item)));

/* Longest-processing-time-first: hand each item, heaviest first, to whichever
   shard would finish soonest with it, counting the page build a shard pays
   the first time it is handed a page reader. Ties break on the name so the
   answer does not depend on the order the caller happened to list the files
   in. */
function shards(files, count) {
  const bins = Array.from({ length: count }, () => ({ load: 0, pages: false, files: [] }));
  const cost = (item) => {
    const f = fileOf(item);
    const c = f in COST ? COST[f] : DEFAULT_COST;
    return PARALLEL.has(f) ? c / CORES : c;
  };
  const extra = (bin, item) => (PAGES.has(fileOf(item)) && !bin.pages ? PAGE_BUILD : 0);
  items(files)
    .sort((a, b) => cost(b) - cost(a) || (a < b ? -1 : a > b ? 1 : 0))
    .forEach((item) => {
      const after = (bin) => bin.load + cost(item) + extra(bin, item);
      // A shard runs its PARALLEL items all at once, and each holds about a
      // core and ~1 GB. A shard with no slot left takes no more of them (nor a
      // SLOTS script) while another has room. LPT alone charges a PARALLEL item
      // COST/CORES, so a shard light on serial work was handed five smoke
      // slices, or four beside the archive.org test, and either is more than
      // the runner holds: "the runner has received a shutdown signal" in the
      // middle of the sweep, every run, whichever shard got the extra one.
      const need = slots(item);
      const fits = (bin) => used(bin) + need <= CORES;
      const roomy = need > 0 && bins.some(fits);
      const ok = (bin) => !roomy || fits(bin);
      let best = bins.findIndex(ok);
      for (let i = best + 1; i < count; i++) if (ok(bins[i]) && after(bins[i]) < after(bins[best])) best = i;
      bins[best].load = after(bins[best]);
      bins[best].pages = bins[best].pages || PAGES.has(fileOf(item));
      bins[best].files.push(item);
    });
  return bins.map((b) => b.files);
}

module.exports = { shards, items, fileOf, needsPages, COST, DEFAULT_COST, SLICES, PAGES, PARALLEL, CORES, SLOTS, slots };

const stdinList = () => require("fs").readFileSync(0, "utf8").split("\n").filter(Boolean);
if (require.main === module && process.argv[2] === "--needs-pages") {
  process.exit(needsPages(stdinList()) ? 0 : 1);
} else if (require.main === module && /^--(parallel|serial)$/.test(process.argv[2] || "")) {
  const want = process.argv[2] === "--parallel";
  const out = stdinList().filter((item) => PARALLEL.has(fileOf(item)) === want);
  if (out.length) console.log(out.join("\n"));
} else if (require.main === module) {
  const index = Number(process.argv[2]);
  const count = Number(process.argv[3]);
  if (!Number.isInteger(count) || count < 1 ||
      !Number.isInteger(index) || index < 0 || index >= count) {
    console.error(`usage: node ${process.argv[1]} <shard-index> <shard-count>`);
    process.exit(2);
  }
  const files = require("fs").readFileSync(0, "utf8")
    .split("\n").map((l) => l.trim()).filter(Boolean);
  if (!files.length) {
    // A job that silently runs nothing reports success. Say so instead.
    console.error("ci_shards: no test files on stdin — the globs matched nothing");
    process.exit(2);
  }
  console.log(shards(files, count)[index].join("\n"));
}
