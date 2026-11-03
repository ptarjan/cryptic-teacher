// Reset, scrolling to a picked clue, the keyboard and solving a clue.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, allPuzzles, assert, currentEntry, docListeners, document, entryId, ev, fs, groupsOf,
  kd, openFromPicker, openPuz, path, registry, storage, takeRung } = T;
// --- reset ---
registry["reset-puzzle"].onclick();
// Reset leaves a record rather than a hole. An absent save reads as "never
// played this puzzle", so the other device would hand the whole grid straight
// back on the next pull — the reset has to be a thing that happened, with a
// time on it, for the merge to have anything to obey.
{
  const after = JSON.parse(storage[Object.keys(storage).find((k) => /^ct:[a-z0-9]+-\d+$/.test(k))] || "{}");
  assert(after.clearedAt > 0 && Object.keys(after.letters || {}).length === 0,
    "resetting records when it happened, so the reset itself can reach the other device");
}

// --- picking a clue scrolls once, and lands in the same place every time ---
// On an iPad in portrait the grid and the hint panel cannot both be on screen,
// so picking a clue has to bring the panel to you. scrollIntoView("nearest")
// does it in two goes, because it measures before the panel has relaid out
// and because "least you can move from here" makes the same tap land somewhere
// different depending on where you were. The target is absolute, so the
// property to hold is idempotence: after one tap the panel is fully on screen,
// and tapping again does not move the page at all.
{
  const win = global.window;
  const panel = registry["hint-panel"];
  const clues = Object.keys(registry).filter((k) => /^clue-/.test(k))
    .map((k) => registry[k]).filter((r) => r.listeners && r.listeners.click);
  assert(clues.length >= 2, "found clue rows to click: " + clues.length);

  // The stacked layout: panel below the grid, clue lists below the panel, and
  // the solver reading the clue lists.
  panel.layout(1200, 400);
  // The app waits for the viewport to hold still before it scrolls, so a tap is a
  // tap plus the settle it is waiting on. On a touch device that also means
  // waiting for the keyboard a tap has just asked for, and the harness is an iPad
  // — so a tap that never raises one waits out the deadline before placing.
  // Draining every timer keeps that a property of the app rather than of how long
  // each test happens to wait, and the late look costs nothing when the band did
  // not move, so the scroll count is still the thing being asserted.
  const drain = () => global.flushTimers(10000);
  const tap = (row) => { row.listeners.click[0](); drain(); };
  const settle = () => { win.pageYOffset = 2000; win.scrolls.length = 0; };

  settle();
  tap(clues[0]);
  assert(win.scrolls.length === 1,
    "one tap moves the page once, not in instalments: " + JSON.stringify(win.scrolls));
  const landed = win.pageYOffset;
  let r = panel.getBoundingClientRect();
  assert(r.top >= 0 && r.bottom <= win.innerHeight,
    `after one tap the whole panel is on screen (top ${r.top}, bottom ${r.bottom}, viewport ${win.innerHeight})`);

  // The second tap is the bug. A different clue, the panel already in view: the
  // page must hold still rather than finish a journey the first tap started.
  win.scrolls.length = 0;
  tap(clues[1]);
  assert(win.scrolls.length === 0 && win.pageYOffset === landed,
    `picking a second clue with the panel already in view must not move the page: `
      + `${landed} -> ${win.pageYOffset} via ${JSON.stringify(win.scrolls)}`);

  // Coming the other way — up from the grid — the panel is below the fold, and
  // one tap must still be enough.
  win.pageYOffset = 0; win.scrolls.length = 0;
  tap(clues[0]);
  assert(win.scrolls.length === 1, "one move from above too: " + JSON.stringify(win.scrolls));
  r = panel.getBoundingClientRect();
  assert(r.top >= 0 && r.bottom <= win.innerHeight, "and the panel is fully in view from above");

  // A panel taller than the screen cannot be "fully visible", so the rule has to
  // be its top, every time — otherwise this is an infinite nudge upward.
  panel.layout(1200, 4000);
  win.pageYOffset = 0; win.scrolls.length = 0;
  tap(clues[1]);
  const tall = win.pageYOffset;
  tap(clues[0]);
  assert(win.pageYOffset === tall,
    `a panel taller than the screen settles at one place, not a new one per tap: ${tall} -> ${win.pageYOffset}`);
  assert(panel.getBoundingClientRect().top >= 0 && panel.getBoundingClientRect().top < 20,
    "and that place is its top, just under the top of the screen");

  // --- and taking a rung brings THE RUNG into view, not the top of the panel ---
  // The panel only ever grows, so what a tap on the ladder produced is always
  // at the bottom of it. A panel taller than the screen is placed by its top,
  // which shows a solver everything except the thing they just asked for.
  // Choosing a hint rung should scroll it into view.
  {
    panel.layout(1200, 4000);
    win.pageYOffset = 0; win.scrolls.length = 0;
    tap(clues[0]);
    const nextRung = () => registry["hint-next"].children.find((x) => !x.disabled);
    const b = nextRung();
    assert(b, "the ladder offers a rung to take");
    b.onclick();
    assert(registry["hint-body"].innerHTML.includes('id="hint-focus"'),
      "the block that tap produced is anchored for the scroll: "
        + registry["hint-body"].innerHTML.slice(0, 200));
    const focus = global.document.getElementById("hint-focus");
    focus.layout(4900, 200);            // the newest block, at the foot of the panel
    drain();
    const fr = focus.getBoundingClientRect();
    assert(fr.top >= 0 && fr.bottom <= win.innerHeight,
      `the rung just taken is on screen (top ${fr.top}, bottom ${fr.bottom}, `
        + `viewport ${win.innerHeight})`);

    // An anchor that measures nothing falls back to placing the panel rather
    // than cancelling the scroll, so a render that dropped the id cannot make
    // a tap move nothing.
    focus.layout(0, 0);
    win.pageYOffset = 3000; win.scrolls.length = 0;
    // Whatever the next tap on the ladder is — the first one may have opened a
    // question rather than a rung, and declining it is the same journey.
    const again = (registry["guess-tell"] && registry["guess-tell"].onclick)
      ? registry["guess-tell"] : nextRung();
    assert(again, "there is another tap on the ladder to make");
    again.onclick();
    drain();
    const pr = panel.getBoundingClientRect();
    assert(pr.top >= 0 && pr.top < 20,
      "an anchor with no box falls back to placing the panel: " + JSON.stringify(pr));
  }


  // --- and it lands above the keyboard, not behind it ---
  // Tapping a clue also raises the soft keyboard, and iOS does not shrink
  // innerHeight for it — the keys are drawn over the bottom of a viewport that
  // still claims to be full height. So "fully in view" has to mean the visual
  // viewport. The band here is 600 tall against an innerHeight of 1000, which is
  // roughly an iPad in portrait with the keyboard up: anything that measures
  // innerHeight parks the panel 400px behind the keys.
  const vv = win.visualViewport;
  const inBand = () => {
    const b = panel.getBoundingClientRect();
    return b.top >= vv.offsetTop && b.bottom <= vv.offsetTop + vv.height;
  };
  panel.layout(1200, 400);

  vv.height = 600;                       // keyboard already up
  win.pageYOffset = 0; win.scrolls.length = 0;
  tap(clues[0]);
  assert(inBand(), "with the keyboard up the panel lands above it, not behind it: "
    + JSON.stringify(panel.getBoundingClientRect()) + " band 0.." + vv.height);

  // --- and it gets there in one move, not three ---
  // The real sequence: the tap is handled while the keyboard is still sliding up,
  // so a placement made then is measured against a screen that is about to lose
  // its bottom third. Placing anyway and correcting on every resize wiggles:
  // each correction starts a smooth scroll over one still in flight, and on a
  // phone Safari's URL bar collapsing under that scroll fires another resize
  // and feeds the loop. So the
  // property is not just "ends up in the right place": it is ONE entry in the
  // scroll log, after the viewport stops moving.
  vv.height = 1000;
  win.pageYOffset = 0; win.scrolls.length = 0;
  clues[1].listeners.click[0]();
  assert(win.scrolls.length === 0, "nothing moves while the keyboard is still on its way in");
  vv.raiseKeyboard(200);                 // the keyboard animating in, in stages
  vv.raiseKeyboard(400);
  assert(win.scrolls.length === 0, "and each stage of it pushes the placement back, it does not scroll");
  global.flushTimers(100);
  assert(win.scrolls.length === 1 && inBand(),
    "one move once the viewport settles, straight to the right place: "
      + JSON.stringify(win.scrolls) + " -> " + JSON.stringify(panel.getBoundingClientRect())
      + " band 0.." + vv.height);

  // A keyboard that pans instead of resizing has to count as the viewport still
  // moving too, or the placement is measured against a band that has slid out
  // from under it.
  vv.height = 1000; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  clues[0].listeners.click[0]();
  vv.panKeyboard(120);
  assert(win.scrolls.length === 0, "a pan pushes the placement back as much as a resize does");
  vv.height = 700;
  drain();
  assert(win.scrolls.length === 1 && inBand(),
    "and the band it finally measures starts at the pan, not at zero: "
      + JSON.stringify(panel.getBoundingClientRect()) + " band "
      + vv.offsetTop + ".." + (vv.offsetTop + vv.height));
  vv.offsetTop = 0;

  // --- a keyboard is corrected for, never waited for ---
  // A tap cannot know whether keys are coming: an iPad with a hardware keyboard,
  // or one whose keyboard was dismissed with the chevron, looks exactly like a
  // phone about to raise one. Waiting on that guess holds the page still for a
  // second on every device where the keys never come. So the placement
  // sets off on the settle whatever the tap did, and the keys — whenever they land
  // — are what the one late look is for.
  drain();                               // drain the look left over from the tap above
  vv.height = 1000; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  registry["hint-pattern"].listeners.mousedown[0]();   // the strip: this one does raise keys
  clues[0].listeners.click[0]();
  global.flushTimers(100);
  assert(win.scrolls.length === 1,
    "the tap sets off at once, keyboard or no keyboard: " + JSON.stringify(win.scrolls));
  vv.raiseKeyboard(400);                 // the keys, later than any settle would wait
  global.flushTimers(500);
  assert(win.scrolls.length === 2 && inBand(),
    "and when they land the panel is put back above them: "
      + JSON.stringify(panel.getBoundingClientRect()) + " band 0.." + vv.height);
  drain();
  assert(win.scrolls.length === 2,
    "with nothing left to correct the late look costs nothing: " + JSON.stringify(win.scrolls));

  // And the correction is not a single allowance spent by whichever viewport
  // event fires first — our own smooth scroll slides a phone's URL bar away
  // long before a cold keyboard arrives, and the keys would then come up over
  // the clue with nothing left to move it.
  // What bounds it is the keyboard's own state: a band that moved
  // for any other reason costs nothing, and every time the keys change their
  // mind inside the watch window the panel is put back.
  vv.height = 1000; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  clues[1].listeners.click[0]();
  global.flushTimers(100);
  assert(win.scrolls.length === 1, "placed on the tap: " + JSON.stringify(win.scrolls));
  vv.panKeyboard(40);                    // a URL bar sliding away under our own scroll
  global.flushTimers(500);
  assert(win.scrolls.length === 1,
    "a band that moved for anything but the keys costs nothing: " + JSON.stringify(win.scrolls));
  vv.offsetTop = 0;
  vv.raiseKeyboard(400);                 // and NOW the keys, with the look still available
  global.flushTimers(500);
  assert(win.scrolls.length === 2 && inBand(),
    "the keys are still corrected for after it: " + JSON.stringify(win.scrolls) + " -> "
      + JSON.stringify(panel.getBoundingClientRect()) + " band 0.." + vv.height);
  drain();

  // --- the strip's tap moves the page once: when the keys land, not before ---
  // Tapping the letter strip is the tap that raises the keys, and the clue and
  // strip are on screen when it is made. Placing the whole panel on the settle
  // moves the page while the keys are still coming, and the keys then move it
  // again: twice, on an iPad in landscape, where the band left over is too
  // short for the panel. What the keys must not cover is the clue and the strip,
  // so that is what decides whether to move, and the keys are the only move.
  {
    const kbd = registry["kbd"], clue = registry["hint-clue"], strip = registry["hint-pattern"];
    kbd.blur();
    vv.height = 1000; vv.offsetTop = 0;
    win.pageYOffset = 1000; win.scrolls.length = 0;
    panel.layout(1590, 1100);           // off the foot of the screen...
    clue.layout(1600, 60);              // ...but not its clue, which the keys will cover
    strip.layout(1665, 50);             // nor its strip
    strip.listeners.mousedown[0]();
    global.flushTimers(100);
    assert(win.scrolls.length === 0,
      "the strip's tap does not move a clue and strip already on screen: " + JSON.stringify(win.scrolls));
    vv.raiseKeyboard(560);              // a landscape keyboard: 440px left
    global.flushTimers(500);
    const c = clue.getBoundingClientRect(), st = strip.getBoundingClientRect();
    assert(win.scrolls.length === 1 && c.top >= 0 && st.bottom <= vv.height,
      "the keys move it once, to the clue and strip above them: " + JSON.stringify(win.scrolls)
        + ` clue ${c.top}, strip foot ${st.bottom}, band 0..${vv.height}`);
    drain();
    assert(win.scrolls.length === 1, "and nothing moves after it: " + JSON.stringify(win.scrolls));

    // iOS scrolls the focused input clear of the keys as they come up, whatever
    // preventScroll says — so the hidden input is focused at the top of the band,
    // which no keyboard covers, and a pan moves that top.
    kbd.blur();
    vv.height = 1000; vv.offsetTop = 120;
    strip.listeners.mousedown[0]();
    assert(kbd.style.top === "120px",
      "the hidden input is focused at the top of the visible band: " + kbd.style.top);
    drain();
    vv.offsetTop = 0;
    clue.layout(0, 0); strip.layout(0, 0); panel.layout(1200, 400);
  }

  // --- another field's keyboard is not the clue's to correct for ---
  // Picking a clue leaves a watch open for keys on their way in. Opening the
  // picker inside it focuses the search box, whose keyboard is a keys-up like
  // any other, and correcting for it would drag the page back down to the clue.
  {
    vv.height = 1000; vv.offsetTop = 0;
    win.pageYOffset = 0; win.scrolls.length = 0;
    clues[0].listeners.click[0]();
    global.flushTimers(100);
    assert(win.scrolls.length === 1, "picking the clue brings it to you: " + JSON.stringify(win.scrolls));
    win.pageYOffset = 0; win.scrolls.length = 0;
    registry["btn-picker"].onclick();
    assert(document.activeElement === registry["picker-search"], "the picker focuses its search box");
    vv.raiseKeyboard(400);
    drain();
    assert(win.scrolls.length === 0,
      "the search box's keyboard does not move the page back to the clue: " + JSON.stringify(win.scrolls));
    registry["btn-picker-close"].onclick();
    vv.height = 1000;
    registry["kbd"].focus();
    drain();
    win.pageYOffset = 0; win.scrolls.length = 0;
  }

  // --- a touch device opens the picker without raising the keyboard ---
  // Focusing the search box on open put the iOS keyboard over the list before
  // anyone chose to search. A coarse pointer leaves it unfocused; a tap on the
  // box still focuses it, and a fine pointer (above) focuses it at once.
  {
    const hadMM = win.matchMedia;
    win.matchMedia = (q) => ({ matches: q === "(pointer: coarse)" });
    registry["picker-search"].blur && registry["picker-search"].blur();
    registry["btn-picker"].onclick();
    assert(document.activeElement !== registry["picker-search"],
      "on a touch device opening the picker does not focus the search box");
    registry["picker-search"].focus();
    assert(document.activeElement === registry["picker-search"],
      "tapping the search box focuses it");
    registry["btn-picker-close"].onclick();
    win.matchMedia = hadMM;
    registry["kbd"].focus();
    drain();
    win.pageYOffset = 0; win.scrolls.length = 0;
  }

  // --- but a keyboard that is GONE is not a keyboard that is coming ---
  // "Owed" is not read off the input being focused with no keys showing: that is
  // also exactly what an iPad looks like the moment you dismiss the keyboard with
  // the chevron, or dock it to a hardware one — the input keeps focus and nothing
  // is on its way in, so every clue tap would wait out the whole cold-keyboard
  // deadline for keys that never come. Only a focus that MOVES
  // focus can raise a keyboard, so only that is worth waiting for.
  assert(document.activeElement === registry["kbd"],
    "the typing input is still focused, as it is after typing or dismissing the keys");
  vv.height = 1000; vv.offsetTop = 0;      // ...and no keyboard is up
  win.pageYOffset = 0; win.scrolls.length = 0;
  // ...so there is nothing to keep, and the tap must not ask for anything either.
  // Focused-with-no-keys is the chevron-dismissed iPad, and re-focusing a focused
  // input inside a touch gesture is how iOS is asked to put the keyboard BACK.
  // activeElement cannot see this: it reads the same before and after, which is
  // why the harness counts the calls.
  registry["kbd"].focusCalls = 0;
  registry["clues-down"].listeners.mousedown[0]();   // keeps the focus, summons nothing
  assert(registry["kbd"].focusCalls === 0,
    "a tap with the keyboard dismissed does not re-focus the input and summon it back");
  clues[1].listeners.click[0]();
  global.flushTimers(100);
  assert(win.scrolls.length === 1,
    "a tap with the keyboard already dismissed sets off at once: " + JSON.stringify(win.scrolls));
  drain();

  // --- and the late look is still there for the keyboard that never resizes ---
  // A hardware keyboard, or an iOS that says nothing at all: the wait cannot be
  // unbounded, so the deadline places anyway, and the one late look is what
  // catches keys that arrive after it. Whether it lands must not depend on
  // whether the keyboard beat us.
  vv.height = 1000; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  clues[0].listeners.click[0]();
  drain();                               // the deadline runs out; place on what we have
  assert(win.scrolls.length === 1,
    "a keyboard that never comes still gets a placement: " + JSON.stringify(win.scrolls));
  vv.raiseKeyboard(400);                 // too late to have deferred anything
  assert(win.scrolls.length === 1, "a late keyboard does not scroll on the spot either");
  global.flushTimers(500);
  assert(win.scrolls.length === 2 && inBand(),
    "the one late look puts the panel back above the keys: "
      + JSON.stringify(panel.getBoundingClientRect()) + " band 0.." + vv.height);
  // One look, not a standing correction — this is the wiggle's back door.
  drain();
  assert(win.scrolls.length === 2, "and it is one look, not a permanent correction");

  // When the placement was right first time the late look must cost nothing: it
  // is idempotent, so a band that never moved means no second scroll at all.
  vv.height = 700; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  clues[1].listeners.click[0]();
  global.flushTimers(10000);
  assert(win.scrolls.length === 1,
    "a viewport that held still gets one scroll, not two: " + JSON.stringify(win.scrolls));
  vv.height = 1000;

  // --- and our own scroll must not be able to buy another one ---
  // The late look above must not re-arm after it fires. A keyboard arriving in
  // stages moves the band twice — but so does our own smooth scroll, because
  // iOS pans the visual viewport under it and fires the same event, and nothing
  // in a band measurement says which one moved it. So the guarantee cannot be
  // "re-place whenever the band is wrong"; it has to be a BUDGET. One placement,
  // one correction, and then the page belongs to the reader. Here every scroll
  // pans the viewport and the keyboard lands late on top of it, which is the loop
  // at its most tempting.
  global.flushTimers(10000);
  panel.layout(1200, 4000);              // every rung bought: taller than the screen
  vv.height = 1000; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  win.scrollPans = 40;
  clues[0].listeners.click[0]();
  global.flushTimers(100);
  vv.raiseKeyboard(400);
  // flushTimers runs one generation: it takes a snapshot, so a timer armed by a
  // timer it ran waits for the next call. A loop that feeds itself needs several
  // turns of the crank to show, and it is the turns after the second that are the
  // bug — so crank it until the page really has stopped.
  for (let i = 0; i < 8; i++) global.flushTimers(10000);
  win.scrollPans = 0; vv.offsetTop = 0; vv.height = 1000;
  assert(win.scrolls.length <= 2,
    "a tap moves the page twice at the most, even when every move moves the viewport: "
      + JSON.stringify(win.scrolls));
  panel.layout(1200, 400);

  // But only on the heels of a tap. A viewport that changes while someone is
  // reading — keyboard dismissed, rotation, a pinch, or just the URL bar sliding
  // away as they scroll — must not yank the page.
  vv.height = 1000;
  win.pageYOffset = 3000; win.scrolls.length = 0;
  vv.raiseKeyboard(400);
  global.flushTimers(100);
  assert(win.scrolls.length === 0 && win.pageYOffset === 3000,
    `a viewport change with no tap behind it must leave the page alone: 3000 -> ${win.pageYOffset}`);

  // --- a tap on the clue you are already on is still a tap ---
  // 1-across is selected before the solver has touched anything, so the very first
  // tap of a puzzle lands on the entry that is already current. Placement must
  // fire on that tap too, or the clue stays off the bottom of the screen with the
  // keyboard drawn over it. Every test above picks a NEW clue, so only this one
  // covers it. The property is about the tap, not about the change.
  {
    const kids = registry["grid"].children;
    const n = Math.round(Math.sqrt(kids.length));
    const tappable = (d) => d && d.listeners && d.listeners.mousedown;
    let i = -1;
    for (let k = 0; k + 1 < kids.length; k++) {
      if (tappable(kids[k]) && tappable(kids[k + 1]) &&
          Math.floor(k / n) === Math.floor((k + 1) / n)) { i = k; break; }
    }
    assert(i >= 0, "the grid has two neighbouring squares in one row");
    // Every row of the selected clue: a linked clue lights its continuations'
    // rows too, and those may sit in the other direction's list.
    const activeId = () =>
      clues.filter((r) => r.classList.contains("active")).map((r) => r.id).join(" + ");
    // Drained rather than timed: a tap on a touch device waits for the keyboard
    // it just asked for, and how long that takes is not what is being asserted.
    const tapCell = (d) => {
      d.listeners.mousedown[0]({ preventDefault() {} });
      global.flushTimers(10000);
    };

    panel.layout(1200, 400);
    vv.height = 1000; vv.offsetTop = 0;
    win.pageYOffset = 2000; win.scrolls.length = 0;
    tapCell(kids[i]);
    // Two squares side by side in a row are one across light, but only if the
    // cursor is running across — tapping the same square again flips it. The
    // neighbour lit is what says so: a down clue linked to an across one lights
    // an across row while the cursor runs down.
    if (!kids[i + 1].classList.contains("hl")) tapCell(kids[i]);
    assert(kids[i + 1].classList.contains("hl"), "a second tap on a square turns the cursor across");
    const same = activeId();

    win.pageYOffset = 2000; win.scrolls.length = 0;
    tapCell(kids[i + 1]);
    assert(activeId() === same,
      `the two squares are one clue between them: ${same} / ${activeId()}`);
    assert(win.scrolls.length === 1,
      "tapping a square of the clue already selected still brings the clue to you: "
        + JSON.stringify(win.scrolls));
  }

  vv.height = 1000; vv.offsetTop = 0;
  panel.layout(0, 0);   // back to unlaid-out, so nothing below here scrolls
  win.pageYOffset = 0; win.scrolls.length = 0;

  // --- and nothing else is allowed to scroll instead of us ---
  // Everything above is wasted if the browser scrolls somewhere else afterwards,
  // and it will: iOS brings the focused element into view when the keyboard
  // opens, and the app focuses a 1px invisible input to raise it. Parked in the
  // document at the top of the grid, that input would drag the page back up there
  // whenever a clue was picked from further down. Fixed, it is always in view
  // and there is nothing to scroll to — but only outside #grid-wrap, which is a
  // query container and therefore the containing block for fixed children, so
  // nesting it back in there would silently make it absolute again. Neither half
  // is visible in the rendered DOM, so both are checked in the source.
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const css = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  const wrap = /<div id="grid-wrap">([\s\S]*?)<\/div>\s*<div/.exec(html);
  assert(wrap && !/id="kbd"/.test(wrap[1]),
    "#kbd stays out of #grid-wrap, or position:fixed resolves against the container");
  assert(/#kbd\s*\{[^}]*position:\s*fixed/.test(css),
    "#kbd is fixed, so iOS has nowhere to scroll it into view from");

  // --- and reading a hint must not change the keyboard either way ---
  // A keyboard arriving is as big a viewport change as a keyboard leaving, and
  // both of them reflow the page under the rung that has just appeared, and the
  // reader sees the keyboard flash open then closed.
  //
  // So the property is steadiness, not focus: whatever the keyboard was doing
  // when the finger landed, it is still doing after. Asserted in both states,
  // because a fix for either one alone causes the other.
  //
  // THE LETTER STRIP IS THE ONLY THING THAT SUMMONS a keyboard. Not the grid:
  // a square is how you pick a CLUE, and the ladder's first move on a new clue is
  // a question you answer by tapping, which a keyboard over the bottom half of
  // the screen buries.
  // Tapping the boxes you are about to fill in is the one tap that means typing.
  //
  // Every tappable thing in the app is listed, and asserted by tapping rather
  // than by reading app.js for a focusKbd, which a source test can miss on a
  // neighbouring control. A new
  // control that is not in this list is a control with no rule.
  const kbd = registry["kbd"];
  const down = (id) => (registry[id].listeners.mousedown || []).forEach((f) => f());
  for (const id of ["grid", "clues-across", "clues-down", "hint-next", "hint-escape"]) {
    document.activeElement = null;
    down(id);
    assert(document.activeElement === null,
      `${id}: this is not a decision to type, so it must not summon the keyboard`);
    kbd.focus();
    down(id);
    assert(document.activeElement === kbd,
      `${id}: nor put away one that is up — the viewport change is what flashes`);
  }
  document.activeElement = null;
  down("hint-pattern");
  assert(document.activeElement === kbd,
    "the letter strip must raise the keyboard: it is the only way left to type");
  document.activeElement = null;
}

// --- a real scroll drops the keyboard; our own scroll must not ---
// On a phone the keys eat half the screen while an input is focused, and scrolling
// is what a reader does to get out from under them — to read the clue, the ladder or
// the grid. But placeHintPanel()'s own window.scrollTo() above must never cost the
// keyboard a hint tap is about to need again: it fires the identical 'scroll' event a
// flick does, so only knowing WE started it can tell the two apart.
//
// docListeners.scroll is the app's own handler, registered on `document` exactly as
// it is in a browser. Moving pageYOffset
// and then calling it is a genuine simulation of the browser dispatching the event,
// not a stand-in for behaviour the app does not have.
{
  const win = global.window;
  const kbd = registry["kbd"];
  const panel = registry["hint-panel"];
  const clues = Object.keys(registry).filter((k) => /^clue-/.test(k))
    .map((k) => registry[k]).filter((r) => r.listeners && r.listeners.click);
  assert(clues.length >= 1, "found a clue row to drive the scroll-blur test");
  const userScroll = (y) => { win.pageYOffset = y; (docListeners.scroll || []).forEach((f) => f()); };

  // The grid-tap block just above can leave its own guard-clearing timer still
  // pending: flushTimers runs one generation, and a timer armed by a timer it just
  // ran (markOwnScroll, fired from inside a settle callback) waits for the next
  // call. A few more generations settle anything left over so this section starts
  // from the guard being off, as a reader who has stopped tapping actually would.
  for (let i = 0; i < 4; i++) global.flushTimers(10000);

  // A real scroll past the threshold drops the keyboard.
  document.activeElement = kbd;
  userScroll(0);        // the first tick only learns where the scroll started
  assert(document.activeElement === kbd, "no blur on the tick that just records the baseline");
  userScroll(200);     // past SCROLL_BLUR_PX (120)
  assert(document.activeElement === null, "a real scroll past the threshold drops the keyboard");

  // A 1px jitter — or Safari's URL bar collapsing as a scroll gets going — must not.
  document.activeElement = kbd;
  userScroll(200);
  userScroll(201);
  assert(document.activeElement === kbd, "a 1px jitter must not drop the keyboard");

  // No touch capability, no soft keyboard to drop: a desktop wheel-scroll while
  // typing is ordinary and must not cost focus.
  const savedMTP = navigator.maxTouchPoints;
  navigator.maxTouchPoints = 0;
  document.activeElement = kbd;
  userScroll(0);
  userScroll(500);
  assert(document.activeElement === kbd, "no touch capability means no blur, however far it moves");
  navigator.maxTouchPoints = savedMTP;

  // Our own scroll — placeHintPanel() moving the page to bring the hint panel into
  // view — must never blur the input the tap is trying to keep typing into.
  panel.layout(1200, 400);
  document.activeElement = kbd;
  win.pageYOffset = 3000; win.scrolls.length = 0;
  clues[0].listeners.click[0]();
  // A big enough number to cover the settle wait, but it still only runs ONE
  // generation of timers (see fake_dom.js's own comment on flushTimers): the
  // guard markOwnScroll() arms from inside this very settle callback is a fresh
  // timer, scheduled during this call, so it is left pending for the next call
  // rather than run now. That is what keeps it alive for the simulated 'scroll'
  // event right below.
  global.flushTimers(10000);
  assert(win.scrolls.length === 1, "the tap did move the page: " + JSON.stringify(win.scrolls));
  userScroll(win.pageYOffset);   // the 'scroll' event a real scrollTo would fire
  assert(document.activeElement === kbd,
    "the app's own scroll to the hint panel must not blur the input being typed into");
  global.flushTimers(10000);   // let the confirm settle before the next test section
  panel.layout(0, 0);
  document.activeElement = null;
}

// --- solving a clue opens its whole ladder, for free ---
// The tiers exist to stop a walkthrough being taken cold. Once the answer is in
// the grid there is nothing left to give away, so every rung opens — and opening
// them must not cost anything, or the unlock is a trap that quietly turns
// "solved with no hints" into "solved with five". Both halves are asserted:
// unlock without the free reading is worse than leaving it locked.
{
  const taught = allPuzzles.find((p) => p.annotated && p.hasSolutions
    && global.window.CRYPTIC_PUZZLES[p.id]);
  openFromPicker(taught.id);
  registry["reset-puzzle"].onclick();

  // An entry that is nobody's linked leg, so solving it really does solve the
  // group the hints belong to.
  let solo = null;
  for (let i = 0; i < 40 && !solo; i++) {
    kd(ev("Tab"));
    const e = currentEntry();
    if (e && e.solution && !e.group && !e.alsoLeads
      && !openPuz.entries.some((g) => groupsOf(g).some((grp) => grp.includes(entryId(e))))) solo = e;
  }
  assert(solo, "found an unlinked entry with a published answer to solve");
  assert(registry["hint-next"].children.some((b) => b.disabled),
    "before solving, the late rungs are still locked");

  solo.solution.split("").forEach((ch) => kd(ev(ch)));
  assert(/Solved with no hints/.test(registry["hint-meter"].innerHTML),
    "typed it cold: " + registry["hint-meter"].innerHTML);
  const buttons = registry["hint-next"].children;
  assert(buttons.length && !buttons.some((b) => b.disabled),
    "solving unlocks every rung: " + buttons.map((b) => b.textContent + (b.disabled ? " [locked]" : "")).join(" | "));
  assert(!buttons.some((b) => /hint/i.test(b.textContent)),
    "rungs are questions, never hints to spend: " + buttons.map((b) => b.textContent).join(" | "));

  // Read the lot, walkthrough included, and the score must not move.
  const before = registry["scorebar"].innerHTML;
  for (let i = 0; i < 8 && registry["hint-next"].children[0]
    && registry["hint-next"].children[0].onclick; i++) {
    takeRung(registry["hint-next"].children[0]);
  }
  assert(/hint-step/.test(registry["hint-body"].innerHTML), "the rungs really did open");
  assert(/Solved with no hints/.test(registry["hint-meter"].innerHTML),
    "studying a solved clue is free: " + registry["hint-meter"].innerHTML);
  assert(registry["scorebar"].innerHTML === before,
    `the scorebar must not move when a solved clue is studied:\n  was ${before}\n  now ${registry["scorebar"].innerHTML}`);
  registry["reset-puzzle"].onclick();
}
