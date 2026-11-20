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
assert(!registry["nux"].classList.contains("hidden") && /written up/.test(nuxLine(registry)),
  "and hands over to the line about the buttons: " + nuxLine(registry));
assert(storage["ct:nux"] === "1", "cursor moved to the ladder line: " + storage["ct:nux"]);
assert(registry["hint-next"].children.filter((c) => /rung-point/.test(c.className || "")).length === 1,
  "exactly one rung is pointed at, and it is the one the line means: "
  + registry["hint-next"].children.map((c) => c.className).join("|"));
// And the page goes dark around it. The sentence says "take one"; the scrim is
// what makes it a button rather than a paragraph, so it is asserted against the
// SAME rung the pulse is on and against a box measured off that rung — a hole
// somewhere else on the page is worse than no hole.
{
  const pointed = registry["hint-next"].children.filter((c) => /rung-point/.test(c.className || ""))[0];
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
  assert(/written up/.test(registry["spot-say"].textContent)
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
assert(registry["hint-escape"].innerHTML.includes("Reveal one letter"), "escape hatch offered at level 0");
assert(registry["hx-letter"].onclick, "escape-hatch button wired");
registry["hx-letter"].onclick();
assert(/letters? revealed/.test(registry["scorebar"].innerHTML), "letter reveals counted in score: " + registry["scorebar"].innerHTML);
assert(registry["hint-meter"].innerHTML.includes("1 letter revealed"), "meter shows reveal count: " + registry["hint-meter"].innerHTML);

// A question that is still open, in either of its two forms — words to point at
// or families to choose between. Keyed off the block that wraps a live question
// and nothing inside it: a graded verdict keeps the marked-up clue on the screen
// for as long as the solver stays on the clue, so "are there words here" cannot
// tell a question from an answer.
function isAsking(body) {
  return body.innerHTML.includes('class="hint-step guess"');
}

// Taking a rung is two clicks: three of them ask you to point at the words
// before they name them, so the button poses the question and "Just tell me"
// answers it. Everything below walks the ladder the lazy way on purpose — the
// guessing itself is tested at the end, on its own.
function takeRung(btn) {
  btn.onclick();
  confirmArmed();
  if (isAsking(registry["hint-body"])) { registry["guess-tell"].onclick(); confirmArmed(); }
}
// A building block that costs a hint takes a second tap (app.js blocksCost):
// the first only arms the button and relabels it. This makes the second tap,
// on whichever button is armed, so the lazy climbs below still buy their rung.
const ARMED = /^Tap again to reveal · costs a hint$/;
function confirmArmed() {
  const row = registry["hint-next"].children.find((b) => ARMED.test(b.textContent || ""));
  if (row) return row.onclick(), true;
  if (/data-arm="blocks-tell" class="[^"]*arm-cost/.test(registry["hint-body"].innerHTML))
    return registry["guess-tell"].onclick(), true;
  return false;
}

// A button that moves the ladder on: a numbered rung, or the rest of a rung
// already open. The building blocks come out one piece at a time, so a climb
// that only recognises "N · label" stops halfway up that rung and then reads a
// body it never finished buying. One predicate, used by every climb here, so
// no copy of it can disagree.
const CLIMBABLE = (btn) => !!(btn && btn.onclick && !btn.disabled
  && (/^\d+ · /.test(btn.textContent || "") || /^Next building block · /.test(btn.textContent || "")));

// Every button in the ladder row, by label. The row is real elements, so its
// innerHTML says nothing about what is on screen — an assertion against that
// string passes on a row that shows something else.
const btnNames = () => registry["hint-next"].children.map((b) => b.textContent).join(" | ");

// --- pick a rung out of order, but not out of tier ---
// Two rules pull against each other and both have to hold. Free choice WITHIN a
// tier: taking any offered rung reveals that rung and nothing else, so wanting
// the indicators doesn't hand you the definition on the way. No choice ACROSS
// tiers: the building blocks and the walkthrough restate the early rungs while
// giving away the answer, so they stay disabled until the early ones are up.
// Lose either half and this is no longer a teaching ladder.
{
  const buttons = registry["hint-next"].children;
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
  const stepCount = (shown.match(/class="hint-step"/g) || []).length;
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
assert(!/written up/.test(nuxLine(registry))
       && /a bit more/.test(nuxLine(registry)),
  "one rung rewords the ladder line rather than spending it: " + nuxLine(registry));
assert(storage["ct:nux"] === "1",
  "and the cursor stays on it for the rest of the walk: " + storage["ct:nux"]);

registry["reset-puzzle"].onclick();   // back to a clean slate for the in-order walk

Object.assign(T, { ARMED, CLIMBABLE, btnNames, confirmArmed, isAsking, takeRung });
