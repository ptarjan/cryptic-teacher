/* A square covered only by an unclued light is a white square, not a block.

     node tools/test_unclued_squares.js

   Each property is asserted on a square only an unclued light covers and, as
   its mirror, on a square a clued entry covers, with the same steps.

   1. revealOnLight: with the cursor on a ring-only square the panel offers
      "Reveal one letter", and it fills the light's letter. On an entry square
      the same button fills the entry's letter.
   2. pickerNeedsRing: a save with every entry square right and the ring blank
      is not "solved"; the same save with the ring filled is. Printed letters
      are never saved, so they are not asked for. */
"use strict";
const { boot } = require("./fake_dom.js");

const ID = "cyclops-511";
const KEY = "ct:" + ID;
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

function open(storage) {
  const d = boot({ query: "?p=" + ID, storage });
  const puz = global.window.CRYPTIC_PUZZLES[ID];
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: d.registry["kbd"] });
  return { d, puz, key, reg: d.registry, cols: puz.dimensions.cols };
}
const at = (t, x, y) => t.reg["grid"].children[y * t.cols + x];
const entrySquares = (p) => {
  const s = new Set();
  p.entries.forEach((e) => { for (let i = 0; i < e.length; i++)
    s.add((e.position.x + (e.direction === "across" ? i : 0)) + "," + (e.position.y + (e.direction === "across" ? 0 : i))); });
  return s;
};

{
  const t = open({});
  const only = entrySquares(t.puz);
  const ring = t.puz.unclued[0].cells.map((c, i) => ({ ...c, ch: t.puz.unclued[0].solution[i] }))
    .find((c) => !only.has(c.x + "," + c.y));
  check(!!ring, "the puzzle has a square only an unclued light covers");
  at(t, ring.x, ring.y).listeners.mousedown[0]({ preventDefault() {} });
  const btn = () => /Reveal one letter/.test(t.reg["hint-escape"].innerHTML);
  check(!t.reg["hint-panel"].classList.contains("hidden") && btn(),
    "revealOnLight: the panel offers Reveal on a ring-only square");
  t.reg["hx-letter"].onclick();
  check(at(t, ring.x, ring.y).querySelector(".letter").textContent === ring.ch,
    "revealOnLight: Reveal puts the light's letter on the square");

  // mirror: the same on a square an entry covers
  const e = t.puz.entries.find((q) => q.solution);
  at(t, e.position.x, e.position.y).listeners.mousedown[0]({ preventDefault() {} });
  t.reg["hx-letter"].onclick();
  check(at(t, e.position.x, e.position.y).querySelector(".letter").textContent === e.solution[0],
    "revealOnLight (mirror): Reveal on an entry square puts the entry's letter there");
}

{
  const puz = open({}).puz;
  const only = entrySquares(puz);
  const letters = {};
  puz.entries.forEach((e) => { for (let i = 0; i < e.length; i++)
    letters[(e.position.x + (e.direction === "across" ? i : 0)) + "," + (e.position.y + (e.direction === "across" ? 0 : i))] = e.solution[i]; });
  const printed = new Set((puz.printed || []).map((p) => p.x + "," + p.y));
  printed.forEach((k) => delete letters[k]);
  const save = (l) => JSON.stringify({ letters: l, letterAt: {}, hintsShown: {}, hintsEarned: {}, revealsUsed: {},
    blocksAt: {}, solvedWith: {}, timing: {}, clearedAt: 0, updated: 1 });
  const says = (l) => {
    const t = open({ [KEY]: save(l) });
    t.reg["btn-picker"].onclick();
    t.reg["picker-search"].value = "cyclops 511";
    t.reg["picker-search"].listeners.input[0]();
    return t.reg["picker-list"].children.map((li) => li.children[0].innerHTML).join("");
  };
  check(!/solved ✓/.test(says(letters)), "pickerNeedsRing: entry squares right, ring blank, is not solved");
  const full = { ...letters };
  puz.unclued.forEach((u) => u.cells.forEach((c, i) => { const k = c.x + "," + c.y; if (!printed.has(k)) full[k] = u.solution[i]; }));
  check(/solved ✓/.test(says(full)), "pickerNeedsRing (mirror): with the ring filled it reads solved");
  check(only.size > 0, "sanity: the entries cover squares");
}

if (failures) { console.error(failures + " failure(s)"); process.exit(1); }
console.log("unclued squares: all checks passed");
