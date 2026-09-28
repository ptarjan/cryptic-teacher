/* Splits the test scripts across the parallel jobs of tests.yml.

   Every job feeds it the SAME list — the one its `for t in <globs>` loop
   collects — and asks for one shard of it. The split is a pure function of that
   list, so the jobs agree without talking to each other: every file lands in
   exactly one shard, and a file nobody's glob matched is a file that runs
   nowhere, which is what tools/test_ci_coverage.js is there to catch.

   Balance is by cost, not by count: four scripts are most of the suite's
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

   Usage: printf '%s\n' tools/test_a.sh ... | node tools/ci_shards.js <i> <n>
          printf '%s\n' <shard's items> | node tools/ci_shards.js --needs-pages */
"use strict";

// Runner seconds, measured 2026-09-28. Every script that took three seconds or
// more is here; the default covers the rest and any test written since.
const COST = {
  // One slice of four; the whole file was 1006s, and it grows with the corpus.
  "tools/smoke_test.js": 280,
  "tools/test_push_conflict.sh": 554,
  "tools/test_puzzle_integrity.sh": 318,
  "tools/test_reconstruct_grid.sh": 106,
  "tools/test_solve_queue_clues.sh": 88,
  "tools/test_shim_format.sh": 63,
  "tools/test_acquire_book.sh": 59,
  "tools/test_provenance.sh": 28,
  "tools/test_blog_facts.sh": 13,
  "tools/test_puzzle_invariants.sh": 7,
  "tools/test_alert_claimed.sh": 6,
  "tools/test_repair_fetched.sh": 5,
  "tools/test_letter_facts.sh": 4,
  "tools/test_og_tags.js": 4,
};
const DEFAULT_COST = 3;

// How many slices each splittable script runs as (see the header).
const SLICES = { "tools/smoke_test.js": 4 };

// The scripts that read what tools/build_seo_pages.py writes.
const PAGES = new Set(["tools/smoke_test.js", "tools/test_og_tags.js"]);
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
  const cost = (item) => { const f = fileOf(item); return f in COST ? COST[f] : DEFAULT_COST; };
  const extra = (bin, item) => (PAGES.has(fileOf(item)) && !bin.pages ? PAGE_BUILD : 0);
  items(files)
    .sort((a, b) => cost(b) - cost(a) || (a < b ? -1 : a > b ? 1 : 0))
    .forEach((item) => {
      const after = (bin) => bin.load + cost(item) + extra(bin, item);
      let best = 0;
      for (let i = 1; i < count; i++) if (after(bins[i]) < after(bins[best])) best = i;
      bins[best].load = after(bins[best]);
      bins[best].pages = bins[best].pages || PAGES.has(fileOf(item));
      bins[best].files.push(item);
    });
  return bins.map((b) => b.files);
}

module.exports = { shards, items, fileOf, needsPages, COST, DEFAULT_COST, SLICES, PAGES };

if (require.main === module && process.argv[2] === "--needs-pages") {
  const list = require("fs").readFileSync(0, "utf8").split("\n").filter(Boolean);
  process.exit(needsPages(list) ? 0 : 1);
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
