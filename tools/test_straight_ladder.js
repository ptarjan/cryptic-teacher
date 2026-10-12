/* A puzzle that is not a cryptic (index row `style: "straight"`,
   tools/puzzle_style.py) says so above its clues, and its hint ladder offers
   no indicator, clue-type or blocks rung: Listener No 1's clues are plain
   definitions. The mirror: a 1930 Times puzzle with wordplay keeps them.

     node tools/test_straight_ladder.js */
"use strict";
const { boot } = require("./fake_dom.js");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

function open(id) {
  const d = boot({ query: "?p=" + id, storage: { "ct:nux": "9" } });
  const puz = global.window.CRYPTIC_PUZZLES[id];
  const e = puz.entries.find((x) => x.annotation);
  d.registry["clue-" + e.number + "-" + e.direction].listeners.click[0]();
  return {
    row: global.CRYPTIC_INDEX.puzzles.find((p) => p.id === id),
    note: !d.registry["puzzle-style"].classList.contains("hidden"),
    rungs: d.registry["hint-next"].children.map((b) => b.textContent || "").filter((t) => /^\d+ · /.test(t)),
  };
}

const CRYPTIC_RUNGS = /indicator|kind of clue|building blocks/i;
{
  const s = open("listener-1");
  check(s.row && s.row.style === "straight", "listener-1's index row is straight: " + JSON.stringify(s.row && s.row.style));
  check(s.note, "listener-1 says above its clues that it is not a cryptic");
  check(s.rungs.length > 0 && !s.rungs.some((t) => CRYPTIC_RUNGS.test(t)),
    "listener-1's ladder has no indicator, type or blocks rung: " + s.rungs.join(" | "));
}
{
  const c = open("times-5");
  check(c.row && !c.row.style, "(mirror) times-5's index row has no style");
  check(!c.note, "(mirror) times-5 says nothing about style");
  check(c.rungs.some((t) => /kind of clue/i.test(t)), "(mirror) times-5's ladder keeps the type rung: " + c.rungs.join(" | "));
}
process.exit(failures ? 1 : 0);
