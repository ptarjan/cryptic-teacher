// Cross-device sync merging.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { assert } = T;
// --- cross-device sync merges, and can only ever add ---
// The whole design rests on the merge being safe to run unattended: no "which
// device wins?" prompt, no confirmation, it just happens when you open the tab.
// That is only true while merging is a union — order-independent and unable to
// remove anything. If any rule below turns into last-write-wins, an iPad left
// in a drawer starts eating the laptop's afternoon, silently, and the solver
// has no way to get it back. So the properties are asserted, not the outputs.
{
  const { mergeSaves } = require("../../sync/merge.js");
  const A = { v: 1, puzzles: { 30079: {
    letters: { "0,0": "A", "1,0": "S" }, hintsShown: { "1a": ["family"] },
    revealsUsed: { "1a": 2 }, solvedWith: { "1a": 3 }, updated: 100 } } };
  const B = { v: 1, puzzles: { 30079: {
    letters: { "0,0": "Z", "0,1": "B" }, hintsShown: { "1a": ["definition"] },
    revealsUsed: { "1a": 1 }, solvedWith: { "1a": 5 }, updated: 200 }, 30080: {
    letters: { "2,2": "Q" }, updated: 50 } } };

  const ab = mergeSaves(A, B), ba = mergeSaves(B, A);
  assert(JSON.stringify(ab) === JSON.stringify(ba),
    "merging is order-independent — the two devices cannot disagree about the result");

  const m = ab.puzzles["30079"];
  assert(m.letters["1,0"] === "S" && m.letters["0,1"] === "B",
    "a letter only one device knew about survives the merge");
  assert(m.letters["0,0"] === "Z", "when both typed a square, the newer save wins");
  assert(m.hintsShown["1a"].length === 2, "hint rungs union — a rung you paid for stays up");
  assert(m.revealsUsed["1a"] === 2, "reveals are spent, not returned: the merge keeps the max");
  assert(m.solvedWith["1a"] === 3, "solved-with keeps the better score, so syncing never costs points");
  assert(ab.puzzles["30080"], "a puzzle only one device has ever opened is carried across");

  // Idempotence is what makes it safe to pull on every tab focus.
  assert(JSON.stringify(mergeSaves(ab, B)) === JSON.stringify(ab),
    "re-merging changes nothing — pulling twice is the same as pulling once");

  // When two devices stamped the same square at the same instant there is no
  // "later" to appeal to, and a revealed letter is the answer rather than an
  // opinion, so it takes the tie.
  const rev = { v: 1, puzzles: { 1: { letters: { "0,0": "R!" }, letterAt: { "0,0": 5 }, updated: 5 } } };
  const gue = { v: 1, puzzles: { 1: { letters: { "0,0": "X" }, letterAt: { "0,0": 5 }, updated: 9 } } };
  assert(mergeSaves(rev, gue).puzzles["1"].letters["0,0"] === "R!" &&
         mergeSaves(gue, rev).puzzles["1"].letters["0,0"] === "R!",
    "a revealed letter takes a tied square, from either direction");

  // Rubbing a letter out has to reach the other device. If absence meant only
  // "I never filled this in", a deletion could not win an argument it was not
  // allowed to enter, and the other device would hand the letters back on every
  // single pull.
  const had = { v: 1, puzzles: { 1: {
    letters: { "0,0": "A", "1,0": "B" }, letterAt: { "0,0": 10, "1,0": 10 }, updated: 10 } } };
  const cut = { v: 1, puzzles: { 1: {
    letters: { "1,0": "B" }, letterAt: { "0,0": 20, "1,0": 10 }, updated: 20 } } };
  ["forwards", "backwards"].forEach((dir, i) => {
    const m2 = (i ? mergeSaves(cut, had) : mergeSaves(had, cut)).puzzles["1"];
    assert(!("0,0" in m2.letters), `a deleted letter stays deleted (${dir})`);
    assert(m2.letters["1,0"] === "B", `deleting one square leaves the others alone (${dir})`);
  });
  // And it must stay deleted when the stale device pushes again, which it will.
  const afterCut = mergeSaves(had, cut);
  assert(!("0,0" in mergeSaves(afterCut, had).puzzles["1"].letters),
    "the device that still has the letter cannot resurrect it by pushing");

  // Per-square, not per-puzzle: a device that saved more recently somewhere
  // else on the grid does not thereby win squares it never touched.
  const edited = { v: 1, puzzles: { 1: {
    letters: { "0,0": "Q" }, letterAt: { "0,0": 100 }, updated: 100 } } };
  const busyElsewhere = { v: 1, puzzles: { 1: {
    letters: { "0,0": "A", "9,9": "Z" }, letterAt: { "0,0": 10, "9,9": 500 }, updated: 500 } } };
  assert(mergeSaves(edited, busyElsewhere).puzzles["1"].letters["0,0"] === "Q",
    "changing a letter beats an older letter, even if that device saved later elsewhere");

  // Reset is the one edit with no square of its own, so it is recorded as a
  // moment and everything older than it goes.
  const wiped = { v: 1, puzzles: { 1: {
    letters: {}, letterAt: {}, hintsShown: {}, revealsUsed: {}, solvedWith: {},
    clearedAt: 300, updated: 300 } } };
  const stale = { v: 1, puzzles: { 1: {
    letters: { "0,0": "A" }, letterAt: { "0,0": 100 },
    hintsShown: { "1a": ["family"] }, revealsUsed: { "1a": 2 }, updated: 100 } } };
  const rw = mergeSaves(wiped, stale).puzzles["1"];
  assert(JSON.stringify(mergeSaves(stale, wiped)) === JSON.stringify(mergeSaves(wiped, stale)),
    "reset merges the same way round either way");
  assert(Object.keys(rw.letters).length === 0 && Object.keys(rw.letterAt).length === 0,
    "resetting on one device empties the grid on the other, instead of being undone by it");
  assert(!rw.hintsShown["1a"] && !rw.revealsUsed["1a"],
    "reset clears the hint history too — it said all hint history, and meant it");
  assert(JSON.stringify(mergeSaves(rw && mergeSaves(wiped, stale), stale)) ===
         JSON.stringify(mergeSaves(wiped, stale)),
    "the reset holds when the un-reset device pushes again");
  // But a reset must not eat work done after it, or picking the iPad back up
  // after resetting on the laptop would quietly throw the new grid away.
  const since = { v: 1, puzzles: { 1: {
    letters: { "5,5": "N" }, letterAt: { "5,5": 400 }, updated: 400 } } };
  assert(mergeSaves(wiped, since).puzzles["1"].letters["5,5"] === "N",
    "letters typed after the reset survive it");

  assert(JSON.stringify(mergeSaves(null, undefined)) === JSON.stringify({ v: 1, puzzles: {} }),
    "merging nothing with nothing is empty, not a crash — the Worker calls this on a fresh code");

  // The blocks rung is paced by a per-clue count of pieces handed over, kept
  // apart from hintsShown because a rung can be up with only its first piece
  // out. That count has to survive a merge like every other one here: app.js
  // reads "rung shown, no count for it" as no pieces handed over, so a merge
  // that drops the field takes back pieces the solver already paid for.
  const pacedFar = { v: 1, puzzles: { 30079: {
    hintsShown: { "1a": ["blocks"] }, blocksAt: { "1a": 2 }, updated: 100 } } };
  const pacedNear = { v: 1, puzzles: { 30079: {
    hintsShown: { "1a": ["blocks"] }, blocksAt: { "1a": 1 }, updated: 50 } } };
  // Read defensively rather than off the bare merge result: the field this
  // test exists to catch is one a broken merge drops entirely, and a crash
  // reading past it would take out every assertion after it in the file.
  const pacedEither = mergeSaves(pacedFar, pacedNear).puzzles["30079"].blocksAt || {};
  assert(JSON.stringify(mergeSaves(pacedNear, pacedFar).puzzles["30079"].blocksAt || {})
    === JSON.stringify(pacedEither), "blocksAt merges the same way round either way");
  assert(pacedEither["1a"] === 2,
    "merging keeps whichever device paid out further, not the more recent save: "
      + JSON.stringify(pacedEither));
  // The exact shape of a push: a device merges its own save with the reply to
  // its own PUT. Nothing it already had may go missing from that round trip.
  assert((mergeSaves(pacedNear, pacedNear).puzzles["30079"].blocksAt || {})["1a"] === 1,
    "a save merged with itself keeps the pacing it already had");

  // Solve times: recorded now so that an index could be built later, which
  // means the merge has to be as unable to lose them as it is to lose letters.
  const morning = { v: 1, puzzles: { 1: { timing: {
    startedAt: 100, lastAt: 400, activeMs: 300 }, updated: 400 } } };
  const evening = { v: 1, puzzles: { 1: { timing: {
    startedAt: 900, lastAt: 1500, activeMs: 500, solvedAt: 1500, solvedMs: 500 }, updated: 1500 } } };
  const day = mergeSaves(morning, evening).puzzles["1"].timing;
  assert(JSON.stringify(mergeSaves(evening, morning).puzzles["1"].timing) === JSON.stringify(day),
    "timing merges the same way round either way");
  assert(day.startedAt === 100 && day.lastAt === 1500,
    "the earliest start and the latest touch both survive, whichever device saw them");
  assert(day.activeMs === 500,
    "grid-time takes the max: a device that was asleep cannot shorten your solve");
  assert(day.solvedAt === 1500 && day.solvedMs === 500,
    "completion carries its own elapsed time, as one fact rather than two minima");

  // Two devices that each finished it: the earlier finish is the solve, and its
  // OWN elapsed time comes with it, not the other one's.
  const slowFirst = { v: 1, puzzles: { 1: { timing: {
    startedAt: 0, lastAt: 90, activeMs: 90, solvedAt: 90, solvedMs: 90 }, updated: 90 } } };
  const quickLater = { v: 1, puzzles: { 1: { timing: {
    startedAt: 50, lastAt: 60, activeMs: 10, solvedAt: 95, solvedMs: 10 }, updated: 95 } } };
  const both = mergeSaves(slowFirst, quickLater).puzzles["1"].timing;
  assert(both.solvedAt === 90 && both.solvedMs === 90,
    "the pair stays consistent — no reporting a 10ms solve that finished at 90");

  // `wiped` reset at 300, so a device untouched since then contributes nothing.
  const timedBefore = { v: 1, puzzles: { 1: { timing: {
    startedAt: 10, lastAt: 90, activeMs: 80, solvedAt: 90, solvedMs: 80 }, updated: 90 } } };
  assert(JSON.stringify(mergeSaves(wiped, timedBefore).puzzles["1"].timing) === "{}",
    "reset clears the clock too: the next attempt is not timed from the last one");
  assert(JSON.stringify(ab.puzzles["30079"].timing) === "{}",
    "a save from before timing existed merges to an empty clock, not to zeroes");
}
