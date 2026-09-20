/* Rebuild puzzles/index.json, puzzles/index.js and the per-puzzle .js shims,
   for the node harnesses.

   All of them are generated from the puzzles/<id>.json sources and none are
   committed, so a fresh clone has none and a working tree has whatever the last
   rebuild left. Anything that reads one calls this first:

     require("./reindex").reindex();

   One call per process, however many times it is asked: tools/smoke_test.js
   boots the app nine times, nothing in a test process writes puzzle files, and
   the rebuild is eighteen seconds of python reading 15,992 files.

   Eighteen seconds ONCE PER PROCESS was the problem: a smoke-test run spends it
   three times over, because tools/test_push_hold.js and tools/test_notify_race.js
   are separate processes that call this too, and CI spends it a fourth time in
   the build step before any test starts. Every one of those rebuilds wrote the
   same bytes. So the work is skipped when the output is already newer than
   everything it is derived from — see current() — which is the ordinary state
   of both a developer's tree and a CI job whose build step has already run.

   It shells out to the same code path the site's build uses
   (tools/fetch_puzzle.py --reindex) rather than reimplementing the manifest
   here. A second implementation is a second answer to what a puzzle's content
   hash and difficulty rating are, and the browser only ever sees the first. */
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const PUZZLES = path.join(ROOT, "puzzles");
let built = false;

// One pass over puzzles/: the newest mtime among the sources, how many there
// are, and which of them have a shim beside them. Stats rather than a content
// hash on purpose — hashing the inputs means reading 748 MB, which is most of
// what the rebuild costs in the first place, and a stat is what tells us
// whether reading them could possibly change the answer.
function scanPuzzles() {
  const src = [];
  const js = new Set();
  for (const name of fs.readdirSync(PUZZLES)) {
    // The same shape puzzle_files() globs for in fetch_puzzle.py:
    // <series>-<number>.json, which is not index.json and not a static page.
    if (/-\d[^/]*\.json$/.test(name)) src.push(name.slice(0, -5));
    else if (name.endsWith(".js")) js.add(name.slice(0, -3));
  }
  let at = 0;
  for (const id of src) {
    const m = fs.statSync(path.join(PUZZLES, id + ".json")).mtimeMs;
    if (m > at) at = m;
  }
  return { ids: src, at, shimmed: src.every((id) => js.has(id)) };
}

// Newest mtime among the entries of `dir` whose name `keep` accepts.
function newest(dir, keep) {
  let at = 0;
  for (const name of fs.readdirSync(dir)) {
    if (keep(name)) {
      const m = fs.statSync(path.join(dir, name)).mtimeMs;
      if (m > at) at = m;
    }
  }
  return at;
}

/* Is the index on disk already the index this rebuild would write?

   True only when every input is OLDER than the output, which is what makes the
   check conservative in the one direction that matters: anything it cannot
   account for — a missing file, an unreadable directory, a clock that went
   backwards — reads as stale and pays the eighteen seconds. A wrong "stale" is
   slow; a wrong "current" is a test suite reading yesterday's corpus.

   The inputs are the puzzle sources, and the code that turns them into a
   manifest: fetch_puzzle.py itself, difficulty.py and the lexicon it scores
   against, series.py. Named by directory rather than by file, so a new module
   under tools/ is covered by existing here rather than by being added to a
   list somebody forgets.

   Mtimes alone cannot see a DELETED puzzle — removing a file leaves every
   survivor older than the index that still lists it — so the count in the
   manifest is held against the count of sources on disk as well.

   The shims are checked for EXISTENCE, one per source, and never counted:
   build_shims() does not prune, so a tree that has had puzzles deleted carries
   orphan .js files forever and a count would read as stale on every run —
   which is a rebuild that cannot fix what it is reacting to. A checkout with
   the manifest but not the shims cannot load a puzzle, and that is what this
   catches. */
function current() {
  const out = ["index.json", "index.js"].map((f) => {
    try { return fs.statSync(path.join(PUZZLES, f)).mtimeMs; } catch (e) { return 0; }
  });
  const builtAt = Math.min(out[0], out[1]);
  if (!builtAt) return false;

  try {
    const src = scanPuzzles();
    if (src.at > builtAt || !src.shimmed) return false;

    for (const [dir, keep] of [[path.join(ROOT, "tools"), (f) => f.endsWith(".py")],
                               [path.join(ROOT, "tools", "data"), () => true]]) {
      if (newest(dir, keep) > builtAt) return false;
    }

    const manifest = JSON.parse(fs.readFileSync(path.join(PUZZLES, "index.json"), "utf8"));
    return Array.isArray(manifest.puzzles) && manifest.puzzles.length === src.ids.length;
  } catch (e) { return false; }   // anything unreadable is a tree to rebuild
}

function reindex() {
  if (built) return;
  built = true;
  if (current()) {
    // The one thing a skipped rebuild would otherwise drop. reindex() ends by
    // stamping index.html with the content hashes of the assets it names, and
    // tools/smoke_test.js fails on a stale stamp — so a run that skips the
    // manifest still has to restamp, or editing app.js and running the suite
    // reports a stale ?v= that the suite itself used to fix. Cheap: it hashes
    // twelve files rather than reading sixteen thousand.
    execFileSync("python3", [path.join(ROOT, "tools", "stamp_assets.py")],
      { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] });
    return;
  }
  // stdout swallowed (one "indexed N puzzle(s)" line nobody reads), stderr kept:
  // a python that is missing or a rebuild that fails must say so where the test
  // output is, not silently leave a stale index behind.
  execFileSync("python3", [path.join(ROOT, "tools", "fetch_puzzle.py"), "--reindex"],
    { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] });
}

module.exports = { reindex };
