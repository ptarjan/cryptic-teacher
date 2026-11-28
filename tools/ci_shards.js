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
   (the runner has CORES cores); LPT charges such an item COST/CORES, and
   hands a shard no more than CORES of them, counting a SLOTS script as its
   share, while another shard has room.
   `--parallel` prints the PARALLEL items of a shard's list, `--serial` the rest.

   Usage: printf '%s\n' tests/test_a.sh ... | node tools/ci_shards.js <i> <n>
          printf '%s\n' <shard's items> | node tools/ci_shards.js --needs-pages */
"use strict";

// Runner seconds, measured on CI from the step logs (the span of each
// script's log group, the mean of two full runs). Every script that took five
// seconds or more is here; DEFAULT_COST covers the rest and any test written
// since. Re-measure when a shard's wall clock drifts from its siblings'.
const COST = {
  // One slice: ~3.7 minutes booting and loading, then ~2.3 s for each puzzle
  // it sweeps, the sample every slice carries (~51) plus ci_cache.js's
  // MAX_UNCACHED owed ones. A slice whose every puzzle is cached is dropped
  // before it runs (tools/ci_cache.js).
  "tools/smoke_test.js": 400,
  "tests/test_edition_queue.py": 775, "tests/test_file_archive_org_puzzles.py": 317,
  "tests/test_formula_math.js": 239, "tests/test_scan_queue.py": 165,
  "tests/test_reconstruct_grid.py": 128, "tests/test_puzzle_invariants.py": 117,
  "tests/test_row_cache.py": 111, "tests/test_solve_queue_clues.sh": 109,
  "tests/test_file_trove_puzzles.sh": 96, "tests/test_no_media_scans.py": 88,
  "tests/test_acquire_book.py": 73, "tests/test_prereset_pool.sh": 73,
  "tests/test_repair_fetched.py": 68, "tests/test_paper_mode.js": 67,
  "tests/test_vlm_reader.py": 62, "tests/test_failed_inputs.sh": 61,
  "tests/test_empty_keys.py": 45, "tests/test_source_answer_wrong.py": 45,
  "tests/test_letter_facts.sh": 44, "tests/test_indy_titled.py": 42,
  "tests/test_clues_only.py": 41, "tests/test_free_elimination_blocks.js": 40,
  "tests/test_corpus_queue.py": 36, "tests/test_blog_clues_only.py": 34,
  "tests/test_under_crossing.py": 34, "tests/test_validate_scope.py": 34,
  "tests/test_gale_inbox.py": 33, "tests/test_shim_format.py": 33, "tests/test_durable.sh": 32,
  "tests/test_blog_facts.sh": 31, "tests/test_og_tags.js": 31, "tests/test_unit_queue.sh": 30,
  "tests/test_block_confirm.js": 28, "tests/test_ocr_vote_checks.py": 27,
  "tests/test_page_cache.py": 27, "tests/test_puzzle_rows.sh": 26,
  "tests/test_push_conflict.sh": 25, "tests/test_coverage.py": 22, "tests/test_share_url.js": 21,
  "tests/test_ocr_remote.py": 19, "tests/test_quotes.js": 19, "tests/test_alert_claimed.sh": 17,
  "tests/test_times_dates.py": 17, "tests/test_gale_fetch.py": 15,
  "tests/test_push_puzzle_commit.sh": 14, "tests/test_reprints.js": 14,
  "tests/test_times_grids.py": 14, "tests/test_json_merge.sh": 12, "tests/test_ft_puzzles.py": 11,
  "tests/test_puzzle_integrity.py": 11, "tests/test_puzzle_tag_badges.js": 11,
  "tests/test_puzzle_worker.sh": 11, "tests/test_unclued_squares.js": 11,
  "tests/test_validate_speed.py": 11, "tests/test_ctc_hintcheck.py": 10,
  "tests/test_file_gale_listener.py": 10, "tests/test_idx_decoder.js": 10,
  "tests/test_index_idx.py": 10, "tests/test_progress.py": 10, "tests/test_scan_reread.py": 10,
  "tests/test_shape_queue.py": 10, "tests/test_annotate_disclosure.py": 9,
  "tests/test_drop_restores_hint.py": 9, "tests/test_jigsaw.js": 9, "tests/test_own_rows.sh": 9,
  "tests/test_prereset_watch.sh": 9, "tests/test_save_grid.js": 9,
  "tests/test_desktop_hosts.py": 8, "tests/test_free_wheel.js": 8,
  "tests/test_listener_grid.py": 8, "tests/test_ocr_text_central.py": 8,
  "tests/test_og_card_key.py": 8, "tests/test_parse_timesforthetimes.sh": 8,
  "tests/test_solve_clock.js": 8, "tests/test_straight_ladder.js": 8,
  "tests/test_anagram_line.js": 7, "tests/test_bg_job.sh": 7,
  "tests/test_first_screen_arm_b.js": 7, "tests/test_genius_puzzles.py": 7,
  "tests/test_overtype.js": 7, "tests/test_provenance.py": 7, "tests/test_push_silent_fail.sh": 7,
  "tests/test_refresh_window.py": 7, "tests/test_app_tab_pages.js": 6,
  "tests/test_formula_hint.js": 6, "tests/test_gale_mephisto_read.py": 6,
  "tests/test_progressive_list.js": 6, "tests/test_push_batch.sh": 6,
  "tests/test_puzzle_format.py": 6, "tests/test_reindex_changed.py": 6,
  "tests/test_solve_misses.py": 6, "tests/test_validate_shard.py": 6, "tests/test_ask_yield.py": 5,
  "tests/test_gale_listener.py": 5, "tests/test_nightly_worktree.sh": 5,
  "tests/test_privateeye_scans.py": 5,
};
const DEFAULT_COST = 1;
// Every serial script is followed by the dirty-tree check (`git status` over
// the ~54k-file tree), ~2 s each, which over ~400 scripts is minutes a run.
const ITEM_OVERHEAD = 2;

// How many slices each splittable script runs as (see the header).
const SLICES = { "tools/smoke_test.js": 12 };

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
// Runner seconds to restore, unpack and build them, charged once to a shard
// that holds a reader. The restored page store is usually a commit behind
// (pages.yml saves it after its own build), and its code key then re-renders
// every page.
const PAGE_BUILD = 310;

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
   in.

   The PARALLEL page readers go first, whatever their cost. Placed among the
   rest by cost, each one lands beside a heavy serial script already placed
   and opens one more shard's page build: the slices end up one or two to a
   shard, every one of those shards pays the build, and the busiest is the
   build plus a full slice plus that script. Placed first, into empty shards,
   they fill one shard's CORES slots before opening the next (the build is
   charged once a shard), and the serial scripts then balance around them. */
function shards(files, count) {
  const bins = Array.from({ length: count }, () => ({ load: 0, pages: false, files: [] }));
  const cost = (item) => {
    const f = fileOf(item);
    const c = f in COST ? COST[f] : DEFAULT_COST;
    return PARALLEL.has(f) ? c / CORES : c + ITEM_OVERHEAD;
  };
  const extra = (bin, item) => (PAGES.has(fileOf(item)) && !bin.pages ? PAGE_BUILD : 0);
  const first = (item) => (PARALLEL.has(fileOf(item)) && PAGES.has(fileOf(item)) ? 0 : 1);
  items(files)
    .sort((a, b) => first(a) - first(b) || cost(b) - cost(a) || (a < b ? -1 : a > b ? 1 : 0))
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
      // A PARALLEL page reader fills a shard that already builds the pages
      // before it opens another (see the header): LPT alone would open a new
      // one, since an empty shard plus the build still looks lighter than a
      // shard already charged for it.
      const pack = first(item) === 0 && bins.some((bin) => bin.pages && fits(bin));
      const ok = (bin) => (!roomy || fits(bin)) && (!pack || bin.pages);
      let best = bins.findIndex(ok);
      for (let i = best + 1; i < count; i++) if (ok(bins[i]) && after(bins[i]) < after(bins[best])) best = i;
      bins[best].load = after(bins[best]);
      bins[best].pages = bins[best].pages || PAGES.has(fileOf(item));
      bins[best].files.push(item);
    });
  return bins.map((b) => b.files);
}

module.exports = { shards, items, fileOf, needsPages, COST, DEFAULT_COST, ITEM_OVERHEAD, SLICES, PAGES, PAGE_BUILD, PARALLEL, CORES, SLOTS, slots };

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
