// Two bugs Paul hit on his iPhone in the home-screen app, in a real headless
// Chromium emulating one (tools/mobile_browser.js; the fake DOM cannot scroll):
//
//   1. After opening a puzzle and coming back to Puzzles, a scroll moved the
//      page behind the list instead of the list. The panel kept its old scroll
//      (already at its end), the puzzle underneath was still scrolled, and a
//      drag that ran off the panel's end chained into the window.
//   2. Touch-scrolling the list lit up the rows: the system tap-highlight on
//      every row, and a :hover tint that sticks to touch.
//
//     node tools/test_phone_scroll.js
"use strict";
const { withPhone } = require("./mobile_browser.js");
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

(async () => {
  const ran = await withPhone(async ({ goto, ev, sleep, swipe }) => {
    await goto("/");
    const tab = (k) => ev(`document.querySelector('.tabbar a[data-tab=${k}]').click()`).then(() => sleep(800));
    const num = (js) => ev(js);
    const panelTop = () => num("document.getElementById('picker-panel').scrollTop");

    // ---- 2. touching the list highlights nothing
    await tab("puzzles");
    const row = await ev(`(() => {
      const b = document.querySelector('#picker-list button'), c = getComputedStyle(b);
      return { tap: c.webkitTapHighlightColor, us: c.webkitUserSelect || c.userSelect, n: document.querySelectorAll('#picker-list li').length };
    })()`);
    assert(row.n > 5, "the picker lists puzzles: " + row.n);
    assert(/, 0\)$|transparent/.test(row.tap), "a picker row paints no system tap-highlight: " + row.tap);
    assert(row.us === "none", "a drag over picker rows selects no text: " + row.us);
    // No :hover rule may reach a picker row (or a clue / archive row) on a
    // screen that cannot hover: every one belongs inside @media (hover: hover).
    const loose = await ev(`(() => {
      const out = [];
      for (const sh of document.styleSheets) for (const r of sh.cssRules) {
        if (r.type === 1 && /(#picker-list|\\.clue-list|\\.s-index)[^,{]*:hover/.test(r.selectorText)) out.push(r.selectorText);
      }
      return out;
    })()`);
    assert(loose.length === 0, "hover tint outside @media (hover: hover) sticks to touch: " + loose.join(" | "));

    // ---- 1. back to the list after a puzzle: the list scrolls, the page does not
    await swipe(200, 700, 100);                  // scroll the list to its end
    assert(await panelTop() > 0, "swiping the list moves the list: " + await panelTop());
    assert(await num("scrollY") === 0, "...and not the page behind it: " + await num("scrollY"));
    await ev("document.querySelector('#picker-list button').click()"); await sleep(1500);   // open a puzzle
    await swipe(200, 700, 200);                  // read down it
    const scrolledPuzzle = await num("scrollY");
    assert(scrolledPuzzle > 0, "the puzzle page scrolls: " + scrolledPuzzle);
    await tab("puzzles");
    assert(await panelTop() === 0, "the list opens at its top, not where it was left: " + await panelTop());
    const before = await num("scrollY");
    await swipe(200, 700, 100);                  // a drag up that outruns the list
    await swipe(200, 700, 100);
    await swipe(200, 700, 100);
    assert(await num("scrollY") === before, "scrolling the list never moves the page behind it: " + before + " -> " + await num("scrollY"));
    assert(await panelTop() > 0, "the list is what moved: " + await panelTop());
    const lock = await ev("getComputedStyle(document.documentElement).overflow + ' ' + getComputedStyle(document.querySelector('#picker-panel')).overscrollBehaviorY");
    assert(lock === "hidden contain", "page locked and chaining stopped while a tab is up: " + lock);

    // The tabs still work and the lock lets go: Puzzle tab closes the panel and
    // the puzzle page scrolls again.
    await tab("puzzle");
    assert(await ev("document.getElementById('picker-panel').classList.contains('hidden')"), "the Puzzle tab closes the list");
    assert(await ev("getComputedStyle(document.documentElement).overflow") === "visible", "the page unlocks when the tab closes");
    await ev("scrollTo(0,0)");
    await swipe(200, 700, 200);
    assert(await num("scrollY") > 0, "the puzzle page scrolls again: " + await num("scrollY"));
  });
  if (ran === false) return;     // no Chromium here: said so, not failed
  if (fails.length) { fails.forEach((f) => console.error("FAIL:", f)); process.exit(1); }
  console.log("ok: phone scroll");
})().catch((e) => { console.error(e); process.exit(1); });
