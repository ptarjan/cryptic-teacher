// Build blind solve-packets: a clue, then its hint rungs one at a time, answer removed.
//
//   node tools/make_hint_packets.js 30078 > /tmp/packets.json
//   node tools/make_hint_packets.js 30078 --key /tmp/key.json
//
// WHY A SOLVER AND NOT A RUBRIC
//
// The validators check ~30 mechanical properties and every one of them can pass on
// an annotation that teaches nothing — 36 walkthroughs that merely redrew the
// building blocks sat in validator-green puzzles for weeks (2026-08-09). The gap is
// judgement, and the temptation is to bolt on a grader that scores hints 1-5 for
// "clarity". That is a fitted number standing in for a fact we can just query:
// does the hint get a solver from stuck to solved? So the grader is a SOLVER. Hand a
// model the clue with no answer, feed it rungs one at a time, and record the rung it
// cracks on. Right or wrong at rung k is computable; "clarity: 4" is an opinion with
// a decimal point on it.
//
// The curve names the defect, which a score never does:
//   * never solves, even at the last teaching rung -> the parse or the prose is broken
//   * two adjacent rungs with the same outcome across many clues -> the upper rung is
//     not earning its place in the ladder
//   * solves cold, before any rung -> nothing is being measured; drop the clue
//
// THE CONTROL IS NOT OPTIONAL. rungs[0] is the clue alone. A grader weaker than the
// annotator will fail clues that are fine, so the hint's value is the DELTA between
// cold and rung k, never the raw solve rate. (Benchmark, 2026-08-08: Sonnet
// under-solves and Haiku fabricates answers that fit the enumeration. Neither is
// disqualified as a judge — but both need their cold baseline subtracted.)
//
// The judge must not be the model that wrote the hints. Opus grading Opus shares the
// blind spot: it passed all 36 re-narrated walkthroughs while writing them.
//
// The rungs come from booting the real app.js over tools/fake_dom.js and clicking
// the real buttons, not from re-deriving the ladder here. ladderSteps() builds a
// different ladder per clue — no indicators rung when there are no indicators, two
// definitions for a double — and a packet that guessed at that would be grading a
// screen no learner ever sees.
"use strict";
const fs = require("fs");
const path = require("path");
const { boot, ROOT } = require("./fake_dom.js");

const args = process.argv.slice(2);
const puzzleId = args.find((a) => /^\d+$/.test(a));
const keyPath = (() => { const i = args.indexOf("--key"); return i >= 0 ? args[i + 1] : null; })();
if (!puzzleId) {
  console.error("usage: node tools/make_hint_packets.js <puzzle-id> [--key out.json]");
  process.exit(2);
}

const dom = boot({ query: "?p=" + puzzleId });
const { registry } = dom;
const puz = (global.window.CRYPTIC_PUZZLES || {})[puzzleId];
if (!puz) { console.error("no such puzzle: " + puzzleId); process.exit(2); }

const text = (html) => String(html)
  .replace(/<[^>]*>/g, " ")
  .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<")
  .replace(/&gt;/g, ">").replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"')
  .replace(/\s+/g, " ").trim();

// Some rungs hand over the answer by construction, and that is not a bug in the
// annotation. A hidden word is one block, so "drunk now nobody" -> UNKNOWN IS the
// building-blocks rung; ditto a double definition whose halves each spell the whole
// word. Redacting keeps the judge honest — a solve at that rung has to be a solve,
// not a copy — but the rung is also marked givesAnswer, because a clue solved there
// measures nothing and scoring must drop it rather than bank it as a win. On 30078
// that is 3 clues of 25, all of them correct annotations.
const redact = (s, answer) => {
  const bare = String(answer || "").replace(/[^A-Za-z]/g, "");
  if (bare.length < 3) return s;
  const spaced = bare.split("").join("[\\s-]?");
  return s.replace(new RegExp(`\\b${spaced}\\b`, "gi"), "█".repeat(bare.length));
};

const packets = [];
const key = [];
let leaked = 0;

for (const e of puz.entries) {
  if (!e.annotation || e.annotation.linkedTo) continue;
  const row = registry["clue-" + e.id];
  if (!row || !row.listeners.click) continue;
  row.listeners.click[0]();

  const answer = e.solution || (e.annotation && e.annotation.answer) || "";
  const rungs = [];
  // rung 0 is the control: the clue on its own, exactly as the grid presents it.
  rungs.push({ n: 0, label: "no hints", text: "" });

  for (let guard = 0; guard < 10; guard++) {
    const btn = registry["hint-next"].children[0];
    if (!btn || !btn.onclick) break;
    // "Fill in answer" ends the ladder by writing the solution into the grid.
    if (!/^Show hint/.test(btn.textContent || "")) break;
    const label = btn.textContent;
    btn.onclick();
    const body = text(registry["hint-body"].innerHTML);
    if (/\bAnswer:/.test(body)) break; // the reveal rung is not a teaching rung
    const after = redact(body, answer);
    const givesAnswer = after !== body;
    if (givesAnswer) leaked++;
    rungs.push({ n: rungs.length, label, text: after, givesAnswer });
  }

  packets.push({
    puzzle: puzzleId,
    id: e.id,
    number: e.number,
    direction: e.direction,
    clue: e.clue, // the enumeration is already in the clue text: "... (8)"
    rungs
  });
  key.push({ puzzle: puzzleId, id: e.id, answer });
}

if (leaked) {
  console.error(`note: ${leaked} rung(s) spell the answer out (hidden words, whole-word ` +
    "double definitions). Redacted, and marked givesAnswer — score them as unmeasurable, not as solves.");
}
if (keyPath) {
  fs.writeFileSync(keyPath, JSON.stringify(key, null, 2) + "\n");
  console.error(`key for ${key.length} clues -> ${keyPath} (never show this to the judge)`);
}
process.stdout.write(JSON.stringify({ puzzle: puzzleId, builtFrom: path.relative(ROOT, __filename), packets }, null, 2) + "\n");
