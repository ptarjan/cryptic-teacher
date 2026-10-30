/* Paul 10-30: "Why do we show a cursor selection when there isnt a keyboard
   up". On a touch screen the cursor square is drawn only while the soft
   keyboard is up; with no touch (desktop, physical keyboard) it always is.

     node tests/test_cursor_needs_keyboard.js */
"use strict";
const src = require("fs").readFileSync(__dirname + "/../app.js", "utf8");
const a = src.indexOf("  function cursorVisible"), b = src.indexOf("  // Redraw only on a change");
const code = src.slice(a, b);
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const vis = (nav, up) => new Function("navigator", "keyboardUp", code + "; return cursorVisible();")(nav, () => up);

check(vis({ maxTouchPoints: 5 }, false) === false, "touch screen, keyboard down: no cursor");
check(vis({ maxTouchPoints: 5 }, true) === true, "touch screen, keyboard up: cursor");
check(vis({ maxTouchPoints: 0 }, false) === true, "desktop (no touch): cursor stays");
check(vis({}, false) === true, "no touch signal at all: cursor stays");
// refreshGrid draws the cursor off that answer, and the entry's other squares
// take its place in the highlight while it is away.
check(/showCur && c\.x === cur\.x/.test(src) && /toggle\("sel", showCur/.test(src), "refreshGrid gates .sel on cursorVisible");
check(/visualViewport\.addEventListener\("resize", syncCursor\)/.test(src), "the keyboard coming or going redraws the cursor");
process.exit(failures ? 1 : 0);
