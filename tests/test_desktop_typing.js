/* With a mouse and a keyboard, picking a light leaves the page and focus alone.

     node tests/test_desktop_typing.js [path/to/app.js]

   A solver: "each time I click on an empty answer to enter it, I'm taken to the
   inset to type it in there. Ideally I would click the grid space and type."
   Clicking a square or a clue used to scroll the page down to the hint panel
   and its letter strip. On a fine pointer the pick now stays put, nothing takes
   focus, and typed letters land in the grid squares. */
"use strict";
const path = require("path");
const { boot } = require("../tools/fake_dom.js");

const ID = "cryptic-30066";
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const d = boot({ query: "?p=" + ID, storage: { "ct:nux": "9" }, fine: true,
                 appPath: process.argv[2] && path.resolve(process.argv[2]) });
const reg = d.registry;
const win = global.window;
const cols = win.CRYPTIC_PUZZLES[ID].dimensions.cols;
const kd = d.docListeners["keydown"][0];
const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["grid"] });
const cell = (x, y) => reg["grid"].children[y * cols + x];
const letterAt = (x, y) => cell(x, y).querySelector(".letter").textContent;

win.scrolls.length = 0;
reg["clue-9-across"].listeners.click[0]();
global.flushTimers && global.flushTimers(500);
check(win.scrolls.length === 0, "picking a clue does not scroll to the hint panel: " + JSON.stringify(win.scrolls));
check(global.document.activeElement !== reg["kbd"], "picking a clue does not focus the answer input");

const target = cell(2, 2);
check(!!(target.listeners.mousedown || [])[0], "a square listens for the mouse going down");
target.listeners.mousedown[0]({ preventDefault() {}, stopPropagation() {} });
global.flushTimers && global.flushTimers(500);
check(win.scrolls.length === 0, "clicking a square does not scroll to the hint panel: " + JSON.stringify(win.scrolls));
check(global.document.activeElement !== reg["kbd"], "clicking a square does not focus the answer input");

key("Q");
check(letterAt(2, 2) === "Q", "a typed letter goes straight into the clicked square: " + letterAt(2, 2));

process.exit(failures ? 1 : 0);
