/* Typing over a filled word keeps going through its filled squares.

     node tools/test_overtype.js [path/to/app.js]

   Paul: "If I'm typing over a letter I should keep typing over letters that
   aren't locked in." Typing into a square that already holds a letter moves the
   cursor to the very next square, filled or not, skipping only locked ones
   (here: a crossing entry that was solved). 9 across THEOREM is crossed at its
   fifth square by 2 down RERUN, which gets solved first so that square is locked.
   The cursor is read back from the `sel` class, as a solver sees it. */
"use strict";
const path = require("path");
const { boot } = require("./fake_dom.js");

const ID = "cryptic-30066";
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const d = boot({ query: "?p=" + ID, storage: { "ct:nux": "9" }, appPath: process.argv[2] && path.resolve(process.argv[2]) });
const reg = d.registry;
const puz = global.window.CRYPTIC_PUZZLES[ID];
const cols = puz.dimensions.cols;
const kd = d.docListeners["keydown"][0];
const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
const select = (id) => reg["clue-" + id].listeners.click[0]();
const sel = () => { const i = reg["grid"].children.findIndex((el) => el.classList.contains("sel")); return { x: i % cols, y: Math.floor(i / cols) }; };
const letterAt = (x, y) => reg["grid"].children[y * cols + x].querySelector(".letter").textContent;
const row = () => Array.from({ length: 7 }, (_, i) => letterAt(i, 2)).join("");

// Lock the crossing: solve 2 down by typing it.
select("2-down");
for (const ch of "RERUN") key(ch);
check(letterAt(4, 2) === "R", "2 down typed in, so its square in 9 across holds R");

// Fill 9 across with junk, then overtype it and watch the cursor.
select("9-across");
for (let i = 0; i < 7; i++) key("X");
check(row() === "XXXXRXX", "9 across filled with X around the locked R: " + row());

select("9-across");
const stops = [];
for (let i = 0; i < 6; i++) { key("Y"); stops.push(sel().x); }
check(stops.join() === "1,2,3,5,6,6", "overtyping steps one square at a time, skipping the locked one: " + stops);
check(row() === "YYYYRYY", "locked R untouched, the rest overwritten: " + row());

// The soft-keyboard path (answer tiles / mobile input) is the same rule.
select("9-across");
const soft = [];
for (let i = 0; i < 4; i++) { reg["kbd"].value = "Z"; reg["kbd"].listeners.input[0]({ target: reg["kbd"] }); soft.push(sel().x); }
check(soft.join() === "1,2,3,5", "the input-event path overtypes the same way: " + soft);

// Typing into an empty square still lands on the next gap.
select("21-across");
key("M"); check(sel().x === 1, "an empty square still advances normally");

process.exit(failures ? 1 : 0);
