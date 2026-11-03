// Every annotated clue of the format fixtures climbs its ladder.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ARMED, CLIMBABLE, ROOT, assert, clueText, entryId, path } = T;
// --- a puzzle file renders: every annotated clue climbs its ladder ---
// A file stores the wordplay tree and none of the fields derivable from it;
// the shim derives them (fetch_puzzle.browser_puzzle reads annotation.view_puzzle),
// so app.js reads type, blocks, indicators and assembly it never stored.
// Proved here end to end on the format fixtures (tools/fixtures/format-puzzles,
// frozen Guardian cryptics): each is booted as its browser form, every
// annotated clue's ladder is climbed, and every one must have rungs. Each is
// climbed twice from the same seed, and the two climbs must match: the panel a
// clue shows depends on nothing but the puzzle. tests/test_shim_format.py
// checks the data.
for (const puz of JSON.parse(require("child_process").execFileSync("python3", ["-c",
    "import json, fetch_puzzle as fp\n"
    + "from pathlib import Path\n"
    + "print(json.dumps([fp.browser_puzzle(fp.read_puzzle_file(f))"
    + " for f in sorted(Path('fixtures/format-puzzles/cryptic').glob('*.json'))]))"],
  { cwd: path.join(ROOT, "tools"), encoding: "utf8", maxBuffer: 1 << 28 }))) {
  const ID = "smoke-format";
  const ladders = (puz) => {
    // The anagram ring deals its tiles with Math.random (app.js dealRing), so
    // two boots of one clue deal differently and every ring rung "differs".
    // Every draw here comes from one seeded stream (mulberry32): the boot's,
    // and each clue's started afresh so one clue's deal never depends on what
    // an earlier one drew. The boot is seeded too, and each clue's stream
    // starts before its reset: the clue selected on boot (usually the first,
    // 1A) deals its ring then, and app.js keeps the deal (`ring`, keyed by
    // answer and fodder) through reset-puzzle, so its climb draws nothing and
    // shows the boot's deal. The boot and every clue start from the same seed,
    // so a ring kept from the boot is the very deal a fresh climb makes.
    const SEED = 0x5eed;
    const seeded = (seed) => () => {
      seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const random = Math.random;
    Math.random = seeded(SEED);
    const p = Object.assign({}, puz, { id: ID });
    const d = require("../fake_dom.js").boot({
      query: "?p=" + ID,
      storage: { "ct:seen": JSON.stringify({ last: "2000-01-01", days: 5 }) },
      index: (ix) => {
        ix.puzzles.push({ id: ID, number: p.number, series: p.series, name: p.name, setter: p.setter,
                          date: p.date, file: ID + ".js", hasSolutions: true, annotated: true });
        global.window.CRYPTIC_PUZZLES = Object.assign(global.window.CRYPTIC_PUZZLES || {}, { [ID]: p });
      },
    });
    const reg = d.registry, out = {};
    const arm = () => {
      const row = reg["hint-next"].children.find((b) => ARMED.test(b.textContent || ""));
      if (row) row.onclick();
      else if (/data-arm="blocks-tell" class="[^"]*arm-cost/.test(reg["hint-body"].innerHTML)) reg["guess-tell"].onclick();
    };
    p.entries.forEach((e) => {
      const row = e.annotation && reg["clue-" + entryId(e)];
      if (!row || !row.listeners.click) return;
      // A clean slate per clue, as the corpus sweeps take one: what an earlier
      // clue cost must not show here.
      Math.random = seeded(SEED);
      reg["reset-puzzle"].onclick();
      row.listeners.click[0]();
      const seen = [];
      for (let n = 0; n < 40; n++) {
        const btn = reg["hint-next"].children.find(CLIMBABLE);
        if (!btn) break;
        btn.onclick();
        arm();
        if (reg["hint-body"].innerHTML.includes('class="hint-step guess"')) { reg["guess-tell"].onclick(); arm(); }
        seen.push(reg["hint-clue"].innerHTML + reg["hint-body"].innerHTML);
      }
      out[entryId(e)] = seen;
    });
    d.stop();
    Math.random = random;
    return out;
  };
  const first = ladders(puz), again = ladders(puz);
  const annotated = puz.entries.filter((e) => e.annotation).map(entryId);
  assert(annotated.length >= 5, `format: ${puz.id} has annotated clues to climb: ${annotated.length}`);
  assert(puz.entries.every((e) => !e.annotation || (Array.isArray(e.annotation.type) && e.annotation.blocks)),
    `format: ${puz.id}'s shim derives every annotation's type and blocks`);
  // A clue run on by an ellipsis is shown with its neighbour, which may hold the ladder.
  const silent = annotated.filter((id) => !(first[id] || []).length)
    .filter((id) => !/^\s*(…|\.\.\.)|(…|\.\.\.)\s*$/.test(clueText(puz.entries.find((e) => entryId(e) === id))));
  assert(!silent.length, `format: every annotated clue in ${puz.id} climbs a ladder; these do not: ${silent.join(", ")}`);
  const differ = annotated.filter((id) => JSON.stringify(first[id]) !== JSON.stringify(again[id]));
  assert(!differ.length, `format: ${puz.id}'s clues climb the same ladder twice from one seed; these do not: ${differ.join(", ")}`);
}
