// The newcomer's line, the reveal-a-letter escape hatch and rung order.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { assert, nuxLine, registry, storage } = T;
// --- the newcomer's line: the site teaches itself, once, then shuts up ---
// This harness boots with empty storage, which is exactly a first-ever visit —
// the only visit owed these lines. Asserted HERE, before anything below climbs a
// ladder, because the first rung taken is what spends the first line: run this
// any later and it passes on a site that never showed it at all.
assert(!registry["welcome"].classList.contains("hidden"),
  "a first-ever visit is met by the worked example, over the grid and before it");
assert(registry["nux"].classList.contains("hidden"),
  "and by nothing else: the dialog and the lines are one cursor, so only one is ever up");
assert(storage["ct:nux"] === "0",
  "the cursor is written on that first visit, not left for the next one: " + storage["ct:nux"]);
// Starting is what spends it, the way taking a hint spends every line after.
// The rung the dialog promised to point at is marked only once the dialog is
// gone, because the row was built while it was still up.
registry["welcome-go"].onclick();
assert(registry["welcome"].classList.contains("hidden"), "the dialog goes when you start");
assert(!registry["nux"].classList.contains("hidden") && /one step at a time/.test(nuxLine(registry)),
  "and hands over to the line about the buttons: " + nuxLine(registry));
assert(storage["ct:nux"] === "1", "cursor moved to the ladder line: " + storage["ct:nux"]);
assert(registry["hint-rungs"].children.filter((c) => /rung-point/.test(c.className || "")).length === 1,
  "exactly one rung is pointed at, and it is the one the line means: "
  + registry["hint-rungs"].children.map((c) => c.className).join("|"));
// And the page goes dark around it. The sentence says "take one"; the scrim is
// what makes it a button rather than a paragraph, so it is asserted against the
// SAME rung the pulse is on and against a box measured off that rung — a hole
// somewhere else on the page is worse than no hole.
{
  // The real node, not the shim's view of it: layout() must land on the element the app measures.
  const pointed = [...registry["hint-track"].children, ...registry["hint-next"].children]
    .filter((c) => /rung-point/.test(c.className || ""))[0];
  const spot = registry["spotlight"];
  registry["hint-body"].layout(560, 60);   // whatever the ladder has said so far
  registry["nux"].layout(640, 50);   // the line, sitting just above the row
  pointed.layout(700, 44);
  global.window.scrollTo({ top: 200 });
  assert(!spot.classList.contains("hidden"), "the scrim is up while the line is asking for a press");
  // The hole holds the rung and nothing else: not the other rungs, not the
  // steps already climbed above it, and not the line, which the spotlight says
  // for itself beside the hole rather than inside it.
  assert(spot.style.top === "694px" && spot.style.height === "56px",
    "the light covers the rung the line names, padded, and nothing else: "
    + spot.style.top + " / " + spot.style.height);
  // Said ONCE, by the light — and the panel's own line is left EMPTY rather than
  // merely hidden. Two nodes holding the same sentence put a stylesheet between
  // the solver and reading it twice.
  assert(/one step at a time/.test(registry["spot-say"].textContent)
         && registry["nux"].textContent === ""
         && /in-spot/.test(registry["nux"].className || ""),
    "and the sentence is said once, by the light: " + registry["spot-say"].textContent
    + " / line: " + JSON.stringify(registry["nux"].textContent));
  // Page space, not window space: the dialog hands off with a smooth scroll, and
  // a hole that has to be redrawn on every frame of it is wrong on the frame it
  // misses — which is the one where it sits over the wrong row.
  global.window.scrollTo({ top: 260 });
  assert(spot.style.top === "694px", "the hole is welded to the page: " + spot.style.top);
  pointed.layout(0, 0);
  registry["nux"].layout(0, 0);
  registry["hint-body"].layout(0, 0);
  global.window.scrollTo({ top: 0 });
  global.window.scrolls.length = 0;
}

// --- escape hatch: reveal a letter BEFORE using any ladder hints ---
assert(registry["hint-escape"].innerHTML.includes("Reveal letter"), "escape hatch offered at level 0");
assert(registry["hx-letter"].onclick, "escape-hatch button wired");
registry["hx-letter"].onclick();
assert(/<strong>1<\/strong> hint\b/.test(registry["scorebar"].innerHTML), "a revealed letter counts as a hint in the score: " + registry["scorebar"].innerHTML);
assert(/1 hint/.test(registry["scorebar"].innerHTML.replace(/<[^>]*>/g, "")), "the score bar counts the revealed letter as a hint: " + registry["scorebar"].innerHTML);

// A question that is still open, in either of its two forms — words to point at
// or families to choose between. Keyed off the block that wraps a live question
// and nothing inside it: a graded verdict keeps the marked-up clue on the screen
// for as long as the solver stays on the clue, so "are there words here" cannot
// tell a question from an answer.
function isAsking(body) {
  return body.innerHTML.includes('class="hint-step guess"');
}

// Taking a rung is two clicks: three of them ask you to point at the words
// before they name them, so the button poses the question and "Show me"
// answers it. Everything below walks the ladder the lazy way on purpose — the
// guessing itself is tested at the end, on its own.
//
// The Pieces step is the formula line: one blank chip is current and the one
// help button ("Show me", two taps when it costs) fills just that chip. There is
// no "next piece" button, so a climb that wants the walkthrough has to settle
// every chip, which is what settleOpen does after the rung is opened.
const blankChips = () => (registry["hint-body"].innerHTML.match(/data-piece="\d+"/g) || []).length;
function pressShowMe() {
  const b = registry["guess-tell"];
  if (!b || !b.onclick || !/id="guess-tell"/.test(registry["hint-escape"].innerHTML)) return false;
  b.onclick();
  confirmArmed();
  return true;
}
// Answer the question on the table with "Show me", then every blank chip of an
// open Pieces step in turn. onAsk sees each question before it is answered.
function settleOpen(onAsk) {
  for (let g = 0; g < 40; g++) {
    const asking = isAsking(registry["hint-body"]);
    if (!(blankChips() || (g === 0 && asking))) break;
    if (asking && onAsk) onAsk();
    if (!pressShowMe()) break;
  }
}
function takeRung(btn) {
  btn.onclick();
  confirmArmed();
  settleOpen();
}
// A step that costs a hint takes a second tap: the first only arms the button
// and relabels it. This makes the second tap, on whichever button is armed
// (a rung in the row, or the help button), so the lazy climbs below still buy
// their rung.
const ARMED = /^Tap again · 1 hint$/;
function confirmArmed() {
  const row = registry["hint-rungs"].children.find((b) => ARMED.test(b.textContent || ""));
  if (row) return row.onclick(), true;
  if (/id="guess-tell"[^>]*arm-cost/.test(registry["hint-escape"].innerHTML) && registry["guess-tell"])
    return registry["guess-tell"].onclick(), true;
  return false;
}

// A button that moves the ladder on: a numbered rung. One predicate, used by
// every climb here, so no copy of it can disagree.
const CLIMBABLE = (btn) => !!(btn && btn.onclick && !btn.disabled
  && /^\d+ · /.test(btn.textContent || ""));

// Every button in the ladder row, by label. The row is real elements, so its
// innerHTML says nothing about what is on screen — an assertion against that
// string passes on a row that shows something else.
const btnNames = () => registry["hint-rungs"].children.map((b) => b.textContent).join(" | ");

// --- pick a rung out of order, but not out of tier ---
// Two rules pull against each other and both have to hold. Free choice WITHIN a
// tier: taking any offered rung reveals that rung and nothing else, so wanting
// the indicators doesn't hand you the definition on the way. No choice ACROSS
// tiers: the building blocks and the walkthrough restate the early rungs while
// giving away the answer, so they stay disabled until the early ones are up.
// Lose either half and this is no longer a teaching ladder.
{
  const buttons = registry["hint-rungs"].children;
  const open = buttons.filter((b) => !b.disabled);
  const locked = buttons.filter((b) => b.disabled);
  assert(open.length >= 2, "the first tier offers a choice, not a single next step: " + open.length);
  assert(/^\d+ · /.test(open[0].textContent), "rungs read as their own question: " + open[0].textContent);
  assert(!(open[0].className || "").includes("ghost"),
    "the recommended rung leads, and says so by being the one solid button");
  assert(locked.length >= 1, "later rungs are locked from cold, not free for the taking");
  assert(/walkthrough/i.test(locked[locked.length - 1].textContent),
    "the walkthrough is never one click from cold: " + locked[locked.length - 1].textContent);
  // The load-bearing one. Checking only that SOME button is disabled is not
  // enough: an app that offers every rung AND redundantly lists the late ones
  // as disabled would satisfy that. What must hold is that no late
  // rung is clickable yet.
  assert(!open.some((b) => /walkthrough|building blocks|what each half means/i.test(b.textContent)),
    "a late rung is offered from cold: " + open.map((b) => b.textContent).join(" | "));
  const last = open[open.length - 1];
  const wanted = last.textContent;                 // e.g. "3 · Spot the indicator words"
  takeRung(last);
  const shown = registry["hint-body"].innerHTML;
  assert(shown.includes("hint-step"), "the chosen rung is revealed");
  const stepCount = (shown.match(/class="hint-step(?: foldable(?: folded)?)?"/g) || []).length;
  assert(stepCount === 1, `choosing rung "${wanted}" revealed ${stepCount} rungs, not just the one`);
  // out of order without renumbering: the rung keeps its ladder number
  assert(shown.includes(wanted.split(" · ")[0] + " · "), "rung keeps its ladder number: " + shown.slice(0, 120));
  // the definition highlight is the giveaway that a rung leaked: it lights up on
  // the definition rung and nowhere else. Keyed off the rung's LABEL, not its
  // number — where that rung lands depends on which rungs the clue has.
  const lit = registry["hint-clue"].innerHTML.includes('mark class="def"');
  assert(lit === wanted.includes("Where is the definition?"),
    `definition highlight should appear only for the definition rung (took "${wanted}", lit=${lit})`);
}
// --- ...and the newcomer's line is spent by doing what it asked ---
// The rung above was this browser's first, which is the moment the first line
// was asking for. Both halves matter: it has to GO (a nudge that outlives its
// own advice is furniture), and the next one has to arrive in its place,
// because the cursor is the only thing keeping exactly one of them on screen.
// Deliberately after the cold-ladder block rather than before it — everything
// in there is asserted against a ladder nobody has climbed.
// The ladder line is the one exception to "a line is spent by the first thing
// that answers it". It is about a ROW of buttons, and one press has taught what
// one button does, so it rewords itself and the light moves down the ladder.
assert(!/one step at a time/.test(nuxLine(registry))
       && /That step is open/.test(nuxLine(registry)),
  "one rung rewords the ladder line rather than spending it: " + nuxLine(registry));
assert(storage["ct:nux"] === "1",
  "and the cursor stays on it for the rest of the walk: " + storage["ct:nux"]);

registry["reset-puzzle"].onclick();   // back to a clean slate for the in-order walk

Object.assign(T, { ARMED, CLIMBABLE, btnNames, confirmArmed, isAsking, settleOpen, takeRung });
