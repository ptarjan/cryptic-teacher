/* The solve clock only runs while the puzzle is in front of the reader.

     node tools/test_solve_clock.js

   app.js keeps `timing = { startedAt, lastAt, activeMs, solvedAt, solvedMs }`
   under localStorage key "ct:"+puzzleId. Every save adds the gap since the
   last save to activeMs, but only if that gap is a plausible sitting (over
   0ms and no more than IDLE_MS); a tab left open in the background would
   otherwise bank the whole time it sat there as solving. Four things have to
   be true for that to actually work, and this file drives the real
   pauseTiming/resumeTiming/writeState in app.js — via document
   visibilitychange and window blur/focus, exactly as a browser fires them —
   rather than re-deriving the rule in the test:

   1. openingStartsNothing — opening a puzzle and switching straight away,
      with nothing ever typed, must store no timing at all. Otherwise every
      puzzle a reader so much as glances at counts as "in progress".

   2. blurFlushesImmediately — once something IS typed, a blur must write
      that state to disk right away, with timing.lastAt stamped, rather than
      waiting out the 150ms debounce. A tab can be backgrounded and killed a
      moment later; anything still sitting in the timer at that point is lost.

   3. timeAwayIsNotBanked — the gap between blur and the next focus must not
      be added to activeMs, however short. This is checked with a gap well
      under IDLE_MS (60s, against a 5 minute cutoff) specifically so the idle
      cutoff cannot be what is doing the work — only resumeTiming re-stamping
      lastAt on focus can be.

   4. withoutResumeItWouldBeBanked — the mirror of #3: run the identical
      60-second gap but never fire focus (so resumeTiming never runs), and
      confirm the full 60s DOES land in activeMs. Without this, #3 would
      still pass if resumeTiming were deleted outright, because a test that
      only ever checks "not counted" can't tell "correctly excluded" from
      "never reached the counting code at all". */
"use strict";

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

const IDLE_MS = 5 * 60 * 1000;
const KEY = "ct:cryptic-30066";

// Every scenario gets its own boot(): booting a second time reassigns the
// window/document/localStorage globals app.js reads, so an earlier boot's
// listeners would otherwise go on firing against a puzzle that is no longer
// "this" test's.
function freshPuzzle() {
  const d = require("./fake_dom.js").boot({ query: "?p=cryptic-30066" });
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: d.registry["kbd"] });
  const puz = (global.window.CRYPTIC_PUZZLES || {})["cryptic-30066"];
  const entry = (puz.entries || []).find((e) => e.solution && e.length >= 5);
  d.registry["clue-" + entry.id].listeners.click[0]();
  const blur = () => d.winListeners["blur"].forEach((f) => f());
  const focus = () => d.winListeners["focus"].forEach((f) => f());
  const typeOneLetter = () => key(entry.solution[0]);
  const stored = () => {
    const raw = d.storage[KEY];
    return raw ? JSON.parse(raw) : null;
  };
  return { d, typeOneLetter, blur, focus, stored };
}

function withStubbedClock(fn) {
  const real = Date.now;
  let now = 1700000000000;
  Date.now = () => now;
  const advance = (ms) => { now += ms; };
  try { fn(advance); } finally { Date.now = real; }
}

// --- 1. openingStartsNothing ---
{
  const { blur, stored } = freshPuzzle();
  blur();
  check(stored() === null,
    "openingStartsNothing: switching away from an untouched puzzle stores nothing: " + JSON.stringify(stored()));
}

// --- 2. blurFlushesImmediately, 3. timeAwayIsNotBanked, 4. withoutResumeItWouldBeBanked ---
withStubbedClock((advance) => {
  const { typeOneLetter, blur, focus, stored } = freshPuzzle();

  typeOneLetter();
  check(stored() === null,
    "blurFlushesImmediately: the debounced save has not fired yet, so there is nothing on disk before the blur");

  blur();
  const afterBlur = stored();
  check(!!(afterBlur && afterBlur.timing && afterBlur.timing.lastAt),
    "blurFlushesImmediately: blur flushes the pending save synchronously, without waiting out the 150ms debounce: "
      + JSON.stringify(afterBlur));
  const activeBeforeGap = (afterBlur && afterBlur.timing && afterBlur.timing.activeMs) || 0;

  // 60 seconds away — comfortably under the 5 minute IDLE_MS cutoff, so the
  // idle cutoff cannot be what keeps this out of activeMs.
  advance(60 * 1000);
  check(60 * 1000 <= IDLE_MS, "test sanity: the away gap must be well under IDLE_MS");
  focus();
  advance(1000);
  typeOneLetter();
  blur();

  const afterReturn = stored();
  const activeAfterGap = (afterReturn && afterReturn.timing && afterReturn.timing.activeMs) || 0;
  const grewByTheGap = activeAfterGap - activeBeforeGap;
  check(grewByTheGap < 60 * 1000,
    "timeAwayIsNotBanked: 60s spent away must not be added to activeMs — grew by " + grewByTheGap + "ms");
});

withStubbedClock((advance) => {
  // The same 60-second gap, driven without ever firing focus — so
  // resumeTiming never runs. This must show the gap landing in activeMs in
  // full, or property 3 above would pass just as well with resumeTiming
  // deleted.
  const { typeOneLetter, blur, stored } = freshPuzzle();

  typeOneLetter();
  blur();
  const before = stored();
  const activeBefore = (before && before.timing && before.timing.activeMs) || 0;

  advance(60 * 1000);
  advance(1000);
  typeOneLetter();   // fires while still "backgrounded": no focus, no resumeTiming
  blur();

  const after = stored();
  const activeAfter = (after && after.timing && after.timing.activeMs) || 0;
  const grew = activeAfter - activeBefore;
  check(grew >= 60 * 1000,
    "withoutResumeItWouldBeBanked: without a focus/resume step the same 61s away IS counted in full, "
      + "which is exactly what resumeTiming exists to prevent — grew by " + grew + "ms");
});

console.log(failures ? `\n${failures} FAILURE(S)` : "\nSOLVE CLOCK TEST PASSED");
process.exit(failures ? 1 : 0);
