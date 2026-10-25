/* The anagram ring turns into a line once a letter is fixed.

     node tools/test_anagram_line.js

   A ring says the letters have no order. A letter already in the grid is a
   piece of order (it is letter i of the answer), so while any tile is pinned
   the tiles stand in a line in answer order, pinned ones in their own slots.

   1. No grid letters: the ring is a ring (no .ana-line, tiles not collinear).
   2. Type the entry's first letter: .ana-line, every tile on one row, left to
      right, and the leftmost tile is that letter, marked fixed.
   3. A long multi-word answer wraps at word ends, never mid-word, and each
      word still reads left to right in its slots.
   4. Clear the letter again: back to the ring. */
"use strict";
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const bare = (s) => String(s || "").toUpperCase().replace(/[^A-Z]/g, "");
const entryId = (e) => e.number + "-" + e.direction;

// The first clue in the puzzle whose whole answer is one anagram, which is the
// only kind ringPins() will pin into.
function findClue(id, words) {
  const puz = global.window.CRYPTIC_PUZZLES[id];
  return (puz.entries || []).find((e) => {
    const a = e.annotation || {};
    const n = String(a.answer || "").split(/[^A-Za-z]+/).filter(Boolean).length;
    return e.solution && (a.type || []).includes("anagram") && words(n) &&
      ((a.assembly || {}).anagrams || []).some((x) => bare(x.gives) === bare(a.answer) && bare(x.fodder).length >= 4);
  });
}

function openRing(id, words) {
  const d = boot({ query: "?p=" + id });
  const e = findClue(id, words);
  const reg = d.registry;
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  reg["clue-" + entryId(e)].listeners.click[0]();
  for (let i = 0; i < 10 && !reg["hint-body"].innerHTML.includes("anagram-ring"); i++) {
    const btn = reg["hint-next"].children[0];
    if (!(btn && btn.onclick && !btn.disabled)) break;
    btn.onclick();
    if (reg["hint-body"].innerHTML.includes('class="hint-step guess"')) reg["guess-tell"].onclick();
  }
  const tiles = () => [...reg["hint-body"].innerHTML.matchAll(
    /<button type="button" class="ana-tile([^"]*)"[^>]*data-word="(\d+)"[\s\S]*?left:calc\(50% \+ (-?\d+)px\);\s*top:calc\(50% \+ (-?\d+)px\)[^>]*>([A-Z])</g)]
    .map((m) => ({ fixed: / fixed/.test(m[1]), word: +m[2], x: +m[3], y: +m[4], ch: m[5] }));
  const isLine = () => /class="ana-disc ana-line/.test(reg["hint-body"].innerHTML);
  return { e, reg, key, tiles, isLine };
}

{
  const t = openRing("quiptic-1396", (n) => n === 1);
  check(!!t.e, "quiptic-1396 has a one-word whole-answer anagram: " + (t.e && t.e.solution));
  const ring = t.tiles();
  check(ring.length === t.e.solution.length, `the ring is drawn with ${ring.length} tiles`);
  check(!t.isLine() && new Set(ring.map((p) => p.y)).size > 1, "with nothing in the grid it is a ring");
  check(!ring.some((p) => p.fixed), "and nothing on it is fixed");

  t.key(t.e.solution[0]);
  const line = t.tiles();
  check(t.isLine(), "typing the first letter into the grid turns the ring into a line");
  check(line.length === ring.length, "the line holds every tile: " + line.map((p) => p.ch).join(""));
  check(new Set(line.map((p) => p.y)).size === 1, "on one row");
  check(line.every((p, i) => !i || p.x > line[i - 1].x), "left to right in answer order");
  check(line[0].ch === t.e.solution[0] && line[0].fixed && line.filter((p) => p.fixed).length === 1,
    `the first slot is the fixed ${t.e.solution[0]}, and only it is fixed: ` +
    line.map((p) => (p.fixed ? `[${p.ch}]` : p.ch)).join(""));
  check(line.map((p) => p.ch).sort().join("") === t.e.solution.split("").sort().join(""),
    "the line is still the fodder's letters");

  t.key("Backspace");
  check(!t.isLine(), "clearing the grid letter puts the ring back");
}

{
  const t = openRing("quiptic-1397", (n) => n >= 4);
  check(!!t.e, "quiptic-1397 has a long multi-word anagram: " + (t.e && t.e.annotation.answer));
  t.key(t.e.solution[0]);
  const line = t.tiles();
  const words = String(t.e.annotation.answer).toUpperCase().split(/[^A-Z]+/).filter(Boolean);
  check(t.isLine() && line.length === words.join("").length, "a long answer goes to a line too");
  check(new Set(line.map((p) => p.y)).size > 1, "and wraps onto more than one row");
  check(words.every((w, i) => new Set(line.filter((p) => p.word === i).map((p) => p.y)).size === 1),
    "but never inside a word");
  check(line.every((p, i) => !i || p.y > line[i - 1].y || p.x > line[i - 1].x),
    "reading row by row, left to right, is answer order");
  check(line[0].fixed && line[0].ch === t.e.solution[0], "with the typed letter fixed in slot 1");
}

if (failures) { console.error(failures + " failed"); process.exit(1); }
console.log("all passed");
