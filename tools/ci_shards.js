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

   Usage: printf '%s\n' tools/test_a.sh ... | node tools/ci_shards.js <i> <n> */
"use strict";

// Local wall-clock seconds, measured 2026-09-20. Every script that took three
// seconds or more is here; the other eighteen took 3.8s between them and the
// default covers both those and any test written since.
const COST = {
  "tools/test_reconstruct_grid.sh": 218,
  "tools/test_push_conflict.sh": 217,
  "tools/smoke_test.js": 215,
  "tools/test_puzzle_integrity.sh": 165,
  "tools/test_acquire_book.sh": 56,
  "tools/test_provenance.sh": 46,
  "tools/test_solve_queue_clues.sh": 23,
  "tools/test_alert_claimed.sh": 6,
  "tools/test_repair_fetched.sh": 5,
  "tools/test_ia_borrow.sh": 3,
};
const DEFAULT_COST = 3;

/* Longest-processing-time-first: hand each script, heaviest first, to whichever
   shard is emptiest. Ties break on the name so the answer does not depend on
   the order the caller happened to list the files in. */
function shards(files, count) {
  const bins = Array.from({ length: count }, () => ({ load: 0, files: [] }));
  const cost = (f) => (f in COST ? COST[f] : DEFAULT_COST);
  [...files]
    .sort((a, b) => cost(b) - cost(a) || (a < b ? -1 : a > b ? 1 : 0))
    .forEach((f) => {
      let best = 0;
      for (let i = 1; i < count; i++) if (bins[i].load < bins[best].load) best = i;
      bins[best].load += cost(f);
      bins[best].files.push(f);
    });
  return bins.map((b) => b.files);
}

module.exports = { shards, COST, DEFAULT_COST };

if (require.main === module) {
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
