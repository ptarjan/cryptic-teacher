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
   few minutes to build, so only a shard handed one of them builds them;
   `--needs-pages` answers that for a shard's list. A page reader missing from
   PAGES fails loudly on the missing file, it does not pass quietly.

   A script in PARALLEL is single-threaded and touches nothing but its own
   output, so a shard runs all of its PARALLEL items at once beside the rest
   (the runner has CORES cores); LPT counts such an item as running beside the
   shard's serial scripts, and hands a shard no more than PARALLEL_PER_SHARD of
   them (and no more than CORES slots, counting a SLOTS script as its share).
   `--parallel` prints the PARALLEL items of a shard's list, `--serial` the rest.

   Usage: printf '%s\n' tests/test_a.sh ... | node tools/ci_shards.js <i> <n>
          printf '%s\n' <shard's items> | node tools/ci_shards.js --needs-pages */
"use strict";

// Runner seconds, measured on CI from the step logs: the span of each script's
// log group. `python3 tools/ci_costs.py <log of gh run view <id> --log>` prints
// these entries from a run, so a re-measure is one command and a paste. Every
// script that took five seconds or more is here; DEFAULT_COST covers the rest
// and any test written since. Re-measure when a shard's wall clock drifts from
// its siblings'.
const COST = {
  // One smoke slice's wall seconds with its shard's other slices beside it
  // (~3.7 minutes booting and loading, then ~2.3 s for each puzzle it sweeps:
  // the sample every slice carries, ~51, plus ci_cache.js's MAX_UNCACHED owed
  // ones). Measured on three four-slice shards: 498, 475 and 646 s. A slice
  // whose every puzzle is cached is dropped before it runs (tools/ci_cache.js).
  "tools/smoke_test.js": 500,
  "tests/test_edition_queue.py": 526,
  "tests/test_formula_math.js": 226,
  "tests/test_file_archive_org_puzzles.py": 205,
  "tests/test_scan_queue.py": 123,
  "tests/test_solve_queue_clues.sh": 103,
  "tests/test_paper_mode.js": 63,
  "tests/test_reconstruct_grid.py": 58,
  "tests/test_prereset_pool.sh": 57,
  "tests/test_acquire_book.py": 49,
  "tests/test_file_trove_puzzles.sh": 47,
  "tests/test_failed_inputs.sh": 38,
  "tests/test_corpus_queue.py": 35,
  "tests/test_row_cache.py": 33,
  "tests/test_indy_titled.py": 32,
  "tests/test_og_tags.js": 31,
  "tests/test_no_media_scans.py": 29,
  "tests/test_gale_inbox.py": 28,
  "tests/test_letter_facts.sh": 27,
  "tests/test_blog_clues_only.py": 25,
  "tests/test_durable.sh": 24,
  "tests/test_validate_scope.py": 22,
  "tests/test_page_cache.py": 20,
  "tests/test_clues_only.py": 19,
  "tests/test_source_answer_wrong.py": 19,
  "tests/test_puzzle_invariants.py": 17,
  "tests/test_shim_format.py": 17,
  "tests/test_unit_queue.sh": 17,
  "tests/test_alert_claimed.sh": 16,
  "tests/test_free_elimination_blocks.js": 14,
  "tests/test_blog_facts.sh": 12,
  "tests/test_empty_keys.py": 12,
  "tests/test_ocr_remote.py": 12,
  "tests/test_puzzle_format.py": 12,
  "tests/test_repair_fetched.py": 12,
  "tests/test_block_confirm.js": 11,
  "tests/test_puzzle_worker.sh": 10,
  "tests/test_progress.py": 9,
  "tests/test_share_url.js": 9,
  "tests/test_desktop_hosts.py": 8,
  "tests/test_listener_grid.py": 8,
  "tests/test_push_conflict.sh": 8,
  "tests/test_puzzle_integrity.py": 8,
  "tests/test_puzzle_rows.sh": 8,
  "tests/test_shape_queue.py": 8,
  "tests/test_sw_shell_recovery.js": 8,
  "tests/test_times_grids.py": 8,
  "tests/test_unclued_squares.js": 8,
  "tests/test_under_crossing.py": 8,
  "tests/test_bg_job.sh": 7,
  "tests/test_gale_mephisto_read.py": 7,
  "tests/test_json_merge.sh": 7,
  "tests/test_ocr_vote_checks.py": 7,
  "tests/test_og_card_key.py": 7,
  "tests/test_push_puzzle_commit.sh": 7,
  "tests/test_reprints.js": 7,
  "tests/test_times_dates.py": 7,
  "tests/test_ft_puzzles.py": 6,
  "tests/test_gale_fetch.py": 6,
  "tests/test_genius_puzzles.py": 6,
  "tests/test_index_idx.py": 6,
  "tests/test_ocr_text_central.py": 6,
  "tests/test_own_rows.sh": 6,
  "tests/test_parse_timesforthetimes.sh": 6,
  "tests/test_prereset_watch.sh": 6,
  "tests/test_quotes.js": 6,
  "tests/test_save_grid.js": 6,
  "tests/test_scan_reread.py": 6,
  "tests/test_straight_ladder.js": 6,
  "tests/test_vlm_reader.py": 6,
  "tests/test_coverage.py": 5,
  "tests/test_drop_restores_hint.py": 5,
  "tests/test_file_gale_listener.py": 5,
  "tests/test_first_screen_arm_b.js": 5,
  "tests/test_formula_hint.js": 5,
  "tests/test_jigsaw.js": 5,
  "tests/test_reindex_changed.py": 5,
  "tests/test_validate_shard.py": 5,
  "tests/test_boot_from_head.js": 0,
  "tests/test_gale_docs.py": 0,
};
const DEFAULT_COST = 1;
// Every serial script is followed by the dirty-tree check (`git status` over
// the ~54k-file tree). With the untracked cache tests.yml turns on, a status
// lstat()s the tracked files and the directories and reads no directory that
// did not change: ~0.3 s. Without it, a shard holding the built pages read
// all ~72k puzzles/<id>/ directories on every check, 1-1.7 s each.
const ITEM_OVERHEAD = 0.5;

// How many slices each splittable script runs as (see the header).
const SLICES = { "tools/smoke_test.js": 12 };

// See the header: all run concurrently within a shard.
const PARALLEL = new Set(["tools/smoke_test.js"]);
const CORES = 4;
// Most PARALLEL items one shard runs at once. They are CPU-bound and ~2 GB each
// and run beside the shard's serial scripts, so two leave cores free for those;
// four filled the runner. Fewer to a shard is more shards paying PAGE_BUILD, and
// the wall clock is a slice plus that, not the sum of the slices.
const PARALLEL_PER_SHARD = 2;
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
// Runner seconds to restore, unpack and build them, charged once to a shard
// that holds a reader. Warm (the deploy's page store and social cards, which
// a page's key includes, both restored) that is the two restores, the unpack
// and ~1 minute of fingerprinting and re-rendering what moved; cold it was
// 223-351 s. Measured as the gap between a page shard's start-to-scripts time
// and a pageless shard's (both from the run's job step timings), warm: 137 s.
const PAGE_BUILD = 140;

const fileOf = (item) => item.split(" ")[0];

/* Each file as the items it runs as: itself, or one per slice. */
function items(files) {
  return files.flatMap((f) => (SLICES[f]
    ? Array.from({ length: SLICES[f] }, (_, i) => `${f} ${i}/${SLICES[f]}`)
    : [f]));
}

const needsPages = (list) => list.some((item) => PAGES.has(fileOf(item)));

/* Longest-processing-time-first: hand each item, heaviest first, to whichever
   shard keeps the slowest shard soonest, and among those to the one that would
   finish soonest with it. A shard's finish is what it measures on
   the runner: its PARALLEL items run at once beside its serial scripts, so it
   is the longer of the two, plus the page build it pays once when it holds a
   page reader. A light page reader (test_og_tags.js) therefore joins a shard
   that builds the pages for its smoke slices, where it costs its own seconds,
   instead of a pageless shard that would pay the whole build for it. Ties
   break on the name so the answer does not depend on the order the caller
   happened to list the files in.

   The PARALLEL page readers go first, whatever their cost, into empty shards,
   PARALLEL_PER_SHARD to a shard: a slice beside a shard's other work costs no
   more wall than the slice alone, so the finish never tells shards apart and
   the cap is what spreads them. The serial scripts then balance around them,
   the busy shards taking what fits inside their slice's seconds for nothing. */
function shards(files, count) {
  const bins = Array.from({ length: count }, () => ({ serial: 0, par: 0, pages: false, files: [] }));
  const cost = (item) => (fileOf(item) in COST ? COST[fileOf(item)] : DEFAULT_COST);
  const finish = (serial, par, pages) => (pages ? PAGE_BUILD : 0) + Math.max(serial, par);
  const after = (bin, item) => {
    const c = cost(item);
    const pages = bin.pages || PAGES.has(fileOf(item));
    return PARALLEL.has(fileOf(item))
      ? finish(bin.serial, Math.max(bin.par, c), pages)
      : finish(bin.serial + c + ITEM_OVERHEAD, bin.par, pages);
  };
  const first = (item) => (PARALLEL.has(fileOf(item)) && PAGES.has(fileOf(item)) ? 0 : 1);
  items(files)
    .sort((a, b) => first(a) - first(b) || cost(b) - cost(a) || (a < b ? -1 : a > b ? 1 : 0))
    .forEach((item) => {
      // Each PARALLEL item holds about a core and 2 GB, and a SLOTS script
      // holds its share: a shard with no slot left takes no more of either
      // while another has room. "The runner has received a shutdown signal" in
      // the middle of the sweep was five slices, or four beside the archive.org
      // test.
      const need = slots(item);
      const par = PARALLEL.has(fileOf(item));
      const nPar = (bin) => bin.files.filter((f) => PARALLEL.has(fileOf(f))).length;
      const fits = (bin) => used(bin) + need <= CORES && (!par || nPar(bin) < PARALLEL_PER_SHARD);
      const roomy = need > 0 && bins.some(fits);
      const ok = (bin) => !roomy || fits(bin);
      // The run's wall clock is the slowest shard, so a shard is judged first
      // by the slowest shard it leaves; among those that leave it the same, a
      // page reader goes where the pages are already built rather than make a
      // second shard build them, and then the soonest finish wins.
      const span = Math.max(...bins.map((b) => finish(b.serial, b.par, b.pages)));
      const rank = (bin) => {
        const end = after(bin, item);
        return [Math.max(span, end), PAGES.has(fileOf(item)) && !bin.pages ? 1 : 0, end];
      };
      const better = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
      let best = bins.findIndex(ok);
      for (let i = best + 1; i < count; i++) {
        if (ok(bins[i]) && better(rank(bins[i]), rank(bins[best])) < 0) best = i;
      }
      const bin = bins[best];
      if (par) bin.par = Math.max(bin.par, cost(item));
      else bin.serial += cost(item) + ITEM_OVERHEAD;
      bin.pages = bin.pages || PAGES.has(fileOf(item));
      bin.files.push(item);
    });
  return bins.map((b) => b.files);
}

module.exports = { shards, items, fileOf, needsPages, COST, DEFAULT_COST, ITEM_OVERHEAD, SLICES, PAGES, PAGE_BUILD, PARALLEL, PARALLEL_PER_SHARD, CORES, SLOTS, slots };

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
