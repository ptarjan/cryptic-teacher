/* Where a puzzle's file lives, for node: puzzles/<series>/<year>/<id>.json.

   The same rule as tools/puzzle_paths.py, which owns it and documents it: the
   series from the id, the year of the puzzle's `date` (YYYY-MM-DD) or a book puzzle's
   `year`, `undated` when it holds neither. The browser never reads these
   files — it loads the flat puzzles/<id>.js shims — so only harnesses that
   read the sources need this. */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const PUZZLE_DIR = path.join(ROOT, "puzzles");
const UNDATED = "undated";
// The id shape puzzle_files() globs for: <series>-<number>.json.
const PUZZLE_FILE = /^[a-z0-9]+-\d[^/]*\.json$/;

function yearFolder(puzzle) {
  if (puzzle.year !== undefined) return String(puzzle.year);
  if (puzzle.date === undefined) return UNDATED;
  return puzzle.date.slice(0, 4);
}

function seriesFolder(id) {
  const m = /^([a-z0-9]+)-/.exec(String(id));
  if (!m) throw new Error(`${id} is not a namespaced puzzle id (<series>-<number>)`);
  return m[1];
}

function fileFor(puzzle, dir = PUZZLE_DIR) {
  return path.join(dir, seriesFolder(puzzle.id), yearFolder(puzzle), `${puzzle.id}.json`);
}

function dirs(d) {
  try {
    return fs.readdirSync(d, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name);
  } catch (err) {
    if (err.code === "ENOENT") return [];
    throw err;
  }
}

// Every puzzle source file, absolute, sorted by id.
function puzzleFiles(dir = PUZZLE_DIR) {
  const out = [];
  for (const series of dirs(dir)) {
    for (const year of dirs(path.join(dir, series))) {
      const y = path.join(dir, series, year);
      for (const name of fs.readdirSync(y)) if (PUZZLE_FILE.test(name)) out.push(path.join(y, name));
    }
  }
  return out.sort((a, b) => path.basename(a).localeCompare(path.basename(b)));
}

// The file holding puzzle `id`, or null.
function find(id, dir = PUZZLE_DIR) {
  const s = path.join(dir, seriesFolder(id));
  const hits = dirs(s).map((y) => path.join(s, y, `${id}.json`)).filter((f) => fs.existsSync(f));
  if (hits.length > 1) throw new Error(`${id} is filed twice: ${hits.join(", ")}`);
  return hits[0] || null;
}

// The puzzle in `file` as the browser reads it: the generated shim
// (puzzles/<id>.js, built by fetch_puzzle.browser_puzzle), where a format v2
// file's name, series, type, answer, indicators, linkWords, blocks and assembly
// are derived (annotation.view_puzzle). A node tool that reads those fields
// reads them from here, never from the source JSON, which stores none of them
// in v2. A legacy file with no shim is its own view; a v2 file with none is
// an error (run python3 tools/fetch_puzzle.py --reindex).
function readView(file, dir = PUZZLE_DIR) {
  const raw = JSON.parse(fs.readFileSync(file, "utf8"));
  const shim = path.join(dir, `${path.basename(file, ".json")}.js`);
  if (!fs.existsSync(shim)) {
    if (raw.series !== undefined) return raw;
    throw new Error(`${file} is format v2 and has no shim ${shim}: run python3 tools/fetch_puzzle.py --reindex`);
  }
  const window = {};
  new Function("window", fs.readFileSync(shim, "utf8"))(window);
  return window.CRYPTIC_PUZZLES[raw.id];
}

module.exports = { PUZZLE_DIR, UNDATED, yearFolder, fileFor, puzzleFiles, find, readView };
