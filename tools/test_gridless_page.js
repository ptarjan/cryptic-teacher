/* A gridless puzzle is played from its clue list: no grid is drawn, and each
   clue carries its own letter boxes.

     node tools/test_gridless_page.js

   A real puzzle is stripped of its grid in the page's own copy and opened
   through the picker, so the test does not depend on any filed puzzle staying
   gridless. Each property has its mirror on the same puzzle with its grid. */
"use strict";
const fs = require("fs");
const path = require("path");
const { boot, ROOT } = require("./fake_dom.js");

const HOME = "cryptic-30066";
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

function shimPuzzle(row) {
  const w = { CRYPTIC_PUZZLES: {} };
  new Function("window", fs.readFileSync(path.join(ROOT, "puzzles", row.file), "utf8"))(w);
  return w.CRYPTIC_PUZZLES[row.id];
}

function openThrough(strip) {
  const d = boot({ query: "?p=" + HOME });
  const reg = d.registry;
  const row = global.window.CRYPTIC_INDEX.puzzles.find((p) => p.id !== HOME && p.hasSolutions && p.series === "cryptic");
  const puz = shimPuzzle(row);
  if (strip) {
    delete puz.dimensions;
    delete puz.bars;
    puz.entries.forEach((e) => { delete e.position; });
  }
  global.window.CRYPTIC_PUZZLES[row.id] = puz;
  reg["btn-picker"].onclick();
  reg["picker-search"].value = `${row.series} ${row.number}`;
  reg["picker-search"].listeners.input[0]();
  const btn = reg["picker-list"].children.map((li) => li.children[0])
    .find((b) => b.innerHTML.includes(row.number.toLocaleString("en-GB")) || b.innerHTML.includes(String(row.number)));
  btn.onclick({});
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  return { reg, puz, key };
}

for (const strip of [true, false]) {
  const t = openThrough(strip);
  const name = strip ? "" : " (mirror, with its grid)";
  const li = t.reg["clues-across"].children[0];
  // This DOM builds no children out of innerHTML: the row's markup says
  // whether the box holder is there, and querySelector hands back what the
  // app wrote into it.
  const pat = li && /class="clue-pat/.test(li.innerHTML) ? li.querySelector(".clue-pat") : null;
  check(t.reg["grid-wrap"].classList.contains("hidden") === strip,
    strip ? "no grid is drawn" : "mirror: the grid is drawn");
  check(t.reg["app"].classList.contains("gridless") === strip,
    "the page is marked gridless exactly when the puzzle is" + name);
  check(!!pat === strip, strip ? "each clue carries its own letter boxes"
                               : "mirror: a gridded clue carries no boxes of its own");
  if (!strip) continue;
  const first = t.puz.entries.filter((e) => e.direction === "across").sort((a, b) => a.number - b.number)[0];
  const boxes = (pat.innerHTML.match(/class="pat-box /g) || []).length;
  check(boxes === first.length, `1-across's boxes number its length (${boxes} of ${first.length})`);
  check(t.puz.entries.every((e) => e.position && e.position.y >= 100),
    "the page's own squares sit below any real grid, so a later grid inherits no saved letters");
  li.listeners.click[0]({ target: { dataset: { i: "0" } } });
  t.key(first.solution[0]);
  check(pat.innerHTML.includes(`>${first.solution[0]}</button>`),
    "a letter typed after tapping a clue's first box lands in that clue's boxes");
}

if (failures) { console.error(failures + " failure(s)"); process.exit(1); }
console.log("gridless page: all checks passed");
