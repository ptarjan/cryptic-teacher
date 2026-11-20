/* The free letter wheel: the anagram ring, opened empty on any clue.

     node tests/test_free_wheel.js

   1. The button is on a clue that is NOT an anagram as well as on one that is,
      or its presence would give the clue type away.
   2. Opening it changes neither the hint meter nor the scorebar, and the wheel
      starts empty (no tiles, no fodder).
   3. Letters typed into it appear as tiles, and Backspace takes one off. */
"use strict";
const { boot } = require("../tools/fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const entryId = (e) => e.number + "-" + e.direction;

const id = "quiptic-1396";
const d = boot({ query: "?p=" + id });
const reg = d.registry;
const entries = global.window.CRYPTIC_PUZZLES[id].entries;
const isAna = (e) => ((e.annotation || {}).type || []).includes("anagram");
const plain = entries.find((e) => e.annotation && e.solution && !isAna(e));
const ana = entries.find((e) => e.annotation && e.solution && isAna(e));
const tiles = () => [...reg["hint-body"].innerHTML.matchAll(/class="ana-tile[^"]*"[\s\S]*?>([A-Z])<\/button>/g)].map((m) => m[1]);

for (const [name, e] of [["non-anagram", plain], ["anagram", ana]]) {
  check(!!e, `${name} clue found: ${e && e.solution}`);
  reg["clue-" + entryId(e)].listeners.click[0]();
  check(reg["hint-escape"].innerHTML.includes('id="hx-wheel"'), `the wheel button is on the ${name} clue`);
}

reg["clue-" + entryId(plain)].listeners.click[0]();
const meter = reg["hint-meter"].innerHTML, score = reg["scorebar"].innerHTML;
reg["hx-wheel"].onclick();
check(reg["hint-body"].innerHTML.includes("anagram-ring"), "opening it draws the ring");
check(tiles().length === 0, "which starts empty");
check(reg["hint-clue"].innerHTML.includes("data-aw=") && !reg["hint-body"].innerHTML.includes("ana-word"),
  "the clue's own words are the picker, with no second row of chips");
check(reg["hint-meter"].innerHTML === meter, "the hint count is unchanged: " + reg["hint-meter"].innerHTML);
check(reg["scorebar"].innerHTML === score, "and so is the score");

const word = "TEARS";
const type = (k) => reg["ana-kbd"].listeners.keydown[0]({ key: k, preventDefault() {} });
word.split("").forEach(type);
check(tiles().sort().join("") === word.split("").sort().join(""),
  "typed letters appear in the ring: " + tiles().join(""));
check(reg["hint-meter"].innerHTML === meter, "still no hint charged");
type("Backspace");
check(tiles().length === word.length - 1, "Backspace takes one off");

if (failures) { console.error(failures + " failed"); process.exit(1); }
console.log("all passed");
