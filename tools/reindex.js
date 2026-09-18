/* Rebuild puzzles/index.json and puzzles/index.js, for the node harnesses.

   The manifest is generated from the puzzle files and is not committed, so a
   fresh clone has none and a working tree has whatever the last rebuild left.
   Anything that reads it calls this first:

     require("./reindex").reindex();

   One call per process, however many times it is asked: tools/smoke_test.js
   boots the app nine times, nothing in a test process writes puzzle files, and
   the rebuild is seven seconds.

   It shells out to the same code path the site's build uses
   (tools/fetch_puzzle.py --reindex) rather than reimplementing the manifest
   here. A second implementation is a second answer to what a puzzle's content
   hash and difficulty rating are, and the browser only ever sees the first. */
const { execFileSync } = require("child_process");
const path = require("path");

const ROOT = path.join(__dirname, "..");
let built = false;

function reindex() {
  if (built) return;
  // stdout swallowed (one "indexed N puzzle(s)" line nobody reads), stderr kept:
  // a python that is missing or a rebuild that fails must say so where the test
  // output is, not silently leave a stale index behind.
  execFileSync("python3", [path.join(ROOT, "tools", "fetch_puzzle.py"), "--reindex"],
    { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] });
  built = true;
}

module.exports = { reindex };
