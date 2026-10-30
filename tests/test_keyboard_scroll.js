/* Paul 10-30: "Dropping the keyboard all the time might be wrong. Sometimes I'm
   slightly adjusting around the clue solve section." A small scroll keeps the
   soft keyboard up; a real scroll still puts it away.

     node tests/test_keyboard_scroll.js */
"use strict";
const src = require("fs").readFileSync(__dirname + "/../app.js", "utf8");
const s = src.indexOf("  const SCROLL_BLUR_GUARD_MS"), e = src.indexOf('document.addEventListener("scroll", onPageScroll)');
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

function run(deltas) {
  const el = { id: "kbd", blurred: false, blur() { this.blurred = true; } };
  const win = { pageYOffset: 0 };
  const f = new Function("navigator", "document", "window",
    src.slice(s, e) + "; return { onPageScroll, markOwnScroll };");
  const api = f({ maxTouchPoints: 5 }, { activeElement: el }, win);
  api.onPageScroll();                       // baseline
  for (const y of deltas) { win.pageYOffset = y; api.onPageScroll(); }
  return el.blurred;
}
check(!run([10, 30, 60, 90]), "a small adjustment (90px in ticks) keeps the keyboard");
check(!run([40, 0, 50]), "a bounce keeps the keyboard");
check(run([50, 100, 150, 200]), "a real scroll (200px) still drops the keyboard");
process.exit(failures ? 1 : 0);
