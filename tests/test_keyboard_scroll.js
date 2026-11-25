/* Paul 10-30: "Dropping the keyboard all the time might be wrong. Sometimes I'm
   slightly adjusting around the clue solve section." A small scroll keeps the
   soft keyboard up; a real scroll still puts it away.

     node tests/test_keyboard_scroll.js */
"use strict";
const src = require("../tools/app_src").read(__dirname + "/..");
const s = src.indexOf("  const SCROLL_BLUR_GUARD_MS"), e = src.indexOf('document.addEventListener("scroll", onPageScroll)');
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const h = src.indexOf("  const softKeyboardPossible");
const helper = src.slice(h, src.indexOf("  const isTouchPrimary"));

function run(deltas, up = true, touch = 5) {
  const el = { id: "kbd", blurred: false, blur() { this.blurred = true; } };
  const win = { pageYOffset: 0 };
  const f = new Function("navigator", "document", "window", "keyboardUp",
    helper + src.slice(s, e) + "; return { onPageScroll, markOwnScroll };");
  const api = f({ maxTouchPoints: touch }, { activeElement: el }, win, () => up);
  api.onPageScroll();                       // baseline
  for (const y of deltas) { win.pageYOffset = y; api.onPageScroll(); }
  return el.blurred;
}
check(!run([10, 30, 60, 90]), "a small adjustment (90px in ticks) keeps the keyboard");
check(!run([40, 0, 50]), "a bounce keeps the keyboard");
check(run([50, 100, 150, 200]), "a real scroll (200px) still drops the keyboard");
// A touchscreen laptop has touch points but no soft keyboard: the wheel must not blur.
check(!run([50, 100, 150, 200], false), "touch points but no keyboard up (touchscreen laptop): a real scroll keeps focus");
check(!run([50, 100, 150, 200], true, 0), "no touch screen at all: a real scroll keeps focus");

// movePage: every app-initiated scroll is marked as the app's own, honours
// reduced motion, and the guard ends on scrollend where the browser has it.
function move(reduced, hasScrollend) {
  const el = { id: "kbd", blurred: false, blur() { this.blurred = true; } };
  const calls = [], handlers = [], timers = [];
  const win = { pageYOffset: 0, scrollTo: (o) => calls.push(o), addEventListener: (t, f) => handlers.push([t, f]), removeEventListener() {} };
  if (hasScrollend) win.onscrollend = null;
  const target = { scrollIntoView: (o) => calls.push(o) };
  win.matchMedia = () => ({ matches: reduced });
  const f = new Function("navigator", "document", "window", "keyboardUp", "reduceMotion", "setTimeout", "clearTimeout",
    helper + src.slice(s, e) + "; return { onPageScroll, movePage };");
  const api = f({ maxTouchPoints: 5 }, { activeElement: el }, win, () => true,
    () => reduced, (fn) => timers.push(fn), () => {});
  api.onPageScroll();
  api.movePage(target, { block: "center" });
  win.pageYOffset = 500; api.onPageScroll();
  return { el, calls, handlers, win, api };
}
let m = move(false, false);
check(m.calls[0].behavior === "smooth" && m.calls[0].block === "center", "movePage scrolls smoothly");
check(!m.el.blurred, "an app scroll never drops the keyboard");
check(m.handlers.length === 0, "no scrollend listener where the browser lacks it (the timer is the guard)");
m = move(true, true);
check(m.calls[0].behavior === "auto", "reduced motion gets an instant jump");
check(m.handlers.some((h) => h[0] === "scrollend"), "scrollend ends the guard where it exists");
m.handlers[0][1]();
m.api.onPageScroll();
m.win.pageYOffset = 900; m.api.onPageScroll();
check(m.el.blurred, "after scrollend a real scroll drops the keyboard again");
process.exit(failures ? 1 : 0);
