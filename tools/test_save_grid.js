/* A save loads only into the grid it was typed into.

     node tools/test_save_grid.js

   Saves live under "ct:"+puzzleId, and an id can come to name a different
   grid (a book renumbered, a grid rebuilt). app.js stamps each save with
   `grid`, a fingerprint of the lights, and restoreState resets a save that
   does not fit instead of drawing its letters into the wrong squares. A save
   from before fingerprints fits only if every square it names is a light.
   Each rejection is paired with the near-identical save that must load, so a
   check that refused everything would fail too. */
"use strict";
const CTMerge = require("../sync/merge.js");
const entryId = (e) => e.number + "-" + e.direction;
const ID = "cryptic-30066", KEY = "ct:" + ID;

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

// Boots with `seed` as this puzzle's save, types the first letter of a clue
// that does not cross `at`, and returns what was written.
function bootWith(seed, at) {
  const storage = seed ? { [KEY]: JSON.stringify(seed) } : {};
  const d = require("./fake_dom.js").boot({ query: "?p=" + ID, storage });
  const puz = global.window.CRYPTIC_PUZZLES[ID];
  const kd = d.docListeners["keydown"][0];
  const squares = (e) => Array.from({ length: e.length }, (_, i) =>
    e.direction === "across" ? (e.position.x + i) + "," + e.position.y : e.position.x + "," + (e.position.y + i));
  const entry = puz.entries.find((e) => e.solution && !squares(e).includes(at));
  d.registry["clue-" + entryId(entry)].listeners.click[0]();
  kd({ key: entry.solution[0], preventDefault() {}, shiftKey: false, target: d.registry["kbd"] });
  d.winListeners["blur"].forEach((f) => f());
  return { puz, saved: JSON.parse(d.storage[KEY]) };
}

// A light and a black square of the puzzle, from a boot with no save.
const { puz, saved: fresh } = bootWith(null, null);
const lights = new Set();
puz.entries.forEach((e) => { for (let i = 0; i < e.length; i++)
  lights.add(e.direction === "across" ? (e.position.x + i) + "," + e.position.y : e.position.x + "," + (e.position.y + i)); });
let black = null;
for (let y = 0; y < puz.dimensions.rows && !black; y++)
  for (let x = 0; x < puz.dimensions.cols && !black; x++) if (!lights.has(x + "," + y)) black = x + "," + y;
const light = [...lights].pop();
const GRID = fresh.grid;
check(typeof GRID === "string" && GRID.length > 0, "a written save carries its grid fingerprint: " + GRID);

const save = (letters, extra) => Object.assign({ letters, letterAt: {}, updated: 1 }, extra);

{
  const { saved } = bootWith(save({ [light]: "Q" }), light);
  check(saved.letters[light] === "Q" && !saved.clearedAt,
    "a save from before fingerprints, on lights only, loads: " + JSON.stringify(saved.letters));
}
{
  const { saved } = bootWith(save({ [light]: "Q", [black]: "Z" }), light);
  check(!saved.letters[light] && !saved.letters[black] && saved.clearedAt > 0 && saved.grid === GRID,
    "a save from before fingerprints naming a black square is reset: " + JSON.stringify(saved.letters));
}
{
  const { saved } = bootWith(save({ [light]: "Q" }, { grid: GRID }), light);
  check(saved.letters[light] === "Q" && !saved.clearedAt, "a save with this grid's fingerprint loads");
}
{
  const { saved } = bootWith(save({ [light]: "Q" }, { grid: "other" }), light);
  check(!saved.letters[light] && saved.clearedAt > 0 && saved.grid === GRID,
    "a save with another grid's fingerprint is reset, though its squares are all lights: " + JSON.stringify(saved.letters));
}

// The merge keeps the fingerprint, and never unions two grids' letters.
{
  const old = save({ "0,0": "A" }, { grid: "g1", updated: 10 });
  const now = save({ "1,0": "B" }, { grid: "g2", updated: 20 });
  const m = CTMerge.mergePuzzle(old, now), r = CTMerge.mergePuzzle(now, old);
  check(m.grid === "g2" && !m.letters["0,0"] && m.letters["1,0"] === "B" && JSON.stringify(m) === JSON.stringify(r),
    "merging two grids keeps only the newer one, either way round: " + JSON.stringify(m));
  const same = CTMerge.mergePuzzle(save({ "0,0": "A" }, { grid: "g2", updated: 10 }), now);
  check(same.letters["0,0"] === "A" && same.letters["1,0"] === "B" && same.grid === "g2",
    "merging one grid unions its letters");
  const legacy = CTMerge.mergePuzzle(save({ "0,0": "A" }, { updated: 30 }), now);
  check(legacy.grid === "g2" && legacy.letters["0,0"] === "A",
    "a side with no fingerprint merges in and the other side's survives");
  check(!("grid" in CTMerge.mergePuzzle(save({}), save({}))), "no fingerprint on either side writes none");
}

console.log(failures ? `\n${failures} FAILURE(S)` : "\nSAVE GRID TEST PASSED");
process.exit(failures ? 1 : 0);
