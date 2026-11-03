// Walking one clue's hint ladder to its end, typing into the grid, the pattern
// boxes and the check buttons.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { EVENTS, ROOT, assert, beacons, btnNames, docListeners, document, fs, lightCells, nuxLine,
  openPuz, patBoxes, patHTML, path, registry, reported, storage, takeRung } = T;
// --- walk the hint ladder: the ladder is per-clue, so click until it runs out ---
const hintMark = beacons.length;
let rungs = 0, clicks = 0;
// The lead button, unless it is the way OUT of the clue. fillAnswer() solves the
// entry outright, so a climb that presses it stops climbing and starts asserting
// about a finished clue.
const leadRung = () => {
  const b = registry["hint-next"].children[0];
  return b && b.onclick && b.id !== "hx-entry" ? b : null;
};
while (leadRung() && clicks < 12) {
  // Rungs are counted, not clicks. The building blocks come out a piece at a
  // time, so finishing that rung takes several presses of a button that is not
  // a rung of its own — it is the rest of one already bought, and counting it
  // would make the ladder look longer than it is.
  const isRung = /^\d+ · /.test(leadRung().textContent || "");
  takeRung(leadRung());
  clicks++;
  if (!isRung) continue;
  rungs++;
  if (rungs === 1) {
    // Rung 1 is the cheapest rung the clue HAS. Indicators when it has any,
    // because that rung names the mechanism and leaves the definition — most of
    // the skill — to find; the definition when it has none, since app.js builds
    // no rung that says "there are no indicators". A pure charade just stacks
    // its pieces and has nothing to point at, so what leads is read off the
    // clue rather than fixed here: whichever puzzle the nightly adds tonight is
    // the one this walk lands on.
    const ann = (currentEntry() || {}).annotation || {};
    const want = (ann.indicators || []).length
      ? "Spot the indicator words" : "Where is the definition?";
    const first = registry["hint-body"].innerHTML;
    assert(first.includes(want), `rung 1 leads with "${want}": ` + first);
    // One rung into this walk is one more hint, so the third and last line is
    // up: what the score actually charges for. Asserted here rather than after
    // the loop because the same climb spends it again a click later.
    assert(/a bit more/.test(nuxLine(registry)),
      "one rung in, the line is still walking them down the ladder: " + nuxLine(registry));
  }
  // Wherever the family rung lands, it gives the FAMILY only — never the
  // precise (often compound) type, which is the blocks rung's to give.
  {
    // That rung's own section, not everything after it: the blocks rung below
    // names the precise mechanism and is entitled to, so a match on the rest of
    // the panel would fail on exactly the ladders that are behaving.
    const fam = (registry["hint-body"].innerHTML.split('<div class="hint-step')
      .find((sec) => sec.includes("What kind of clue is this?")) || "");
    if (fam) {
    assert(/Double or cryptic definition|&amp;lit|&lit|Anagram|Homophone|Charade|Container, reversal or deletion|Hidden or letter selection/.test(fam),
      "the family rung names a clue family: " + fam);
    assert(!fam.includes("mechanism"), "the family rung withholds the precise mechanism: " + fam);
    }
  }
  assert(registry["hint-body"].innerHTML.includes("hint-step"), "hint body populated at level " + rungs);
  assert(registry["hint-escape"].innerHTML.includes("Reveal one letter") || registry["hint-meter"].innerHTML.includes("Solved"),
    "escape hatch still available at level " + rungs);
}
assert(rungs >= 3 && rungs <= 5, "ladder has a sane number of rungs, got " + rungs);
// ...and having taught the site, the site shuts up. The cursor is past the last
// line, the slot is empty, and nothing in the app moves it back: a newcomer gets
// three sentences in their life, not a banner that returns every session.
assert(!registry["nux"].classList.contains("hidden") && /costs nothing/.test(nuxLine(registry)),
  "a finished ladder hands over to the next line: " + nuxLine(registry));
assert(storage["ct:nux"] === "2",
  "and the whole walk spent exactly one line, not one per rung: " + storage["ct:nux"]);
// The site shutting up for good is checked on its own boot, below: doing it
// here means resetting the puzzle, and everything after this line is asserted
// against the ladder this walk just exhausted.
// Each rung reports itself by name. beacon() drops anything not on the shared
// list, so this is where a rung whose key never reaches the beacon shows up:
// "hint-undefined" is silently discarded and nothing is counted at all.
// beacon() reports a name once per session, and the out-of-order pick above
// already spent one of this clue's rungs, so the count is over the whole
// session: on a three-rung ladder the walk itself only has two names left.
{
  const climbed = reported(hintMark).filter((n) => /^hint/.test(n));
  const everyRung = new Set(reported(0).filter((n) => /^hint/.test(n)));
  assert(climbed.length >= 1 && everyRung.size >= rungs,
    `climbing ${rungs} rungs reports which ones were revealed, got: ` + [...everyRung].join(","));
  assert(climbed.every((n) => /^hint-[a-z]+$/.test(n) && EVENTS.indexOf(n) >= 0),
    "every rung reports its own name off the shared list: " + climbed.join(","));
}
// The walkthrough prints the answer once (02ee84cec57): in its own "Answer:" line,
// or, when the clue has a definition-fit line, as that line's "gives" span.
function answerShown(html, ans) {
  if (html.includes("Answer:")) return true;
  const fit = (html.match(/<p class="def-fit">[\s\S]*?<\/p>/) || [""])[0];
  const gives = [...fit.matchAll(/<span class="gives">([^<]*)<\/span>/g)]
    .map((m) => m[1].replace(/&[#\w]+;/g, "").replace(/[^A-Za-z]/g, "").toUpperCase());
  return gives.some((g) => g && (!ans || g === ans));
}
assert(answerShown(registry["hint-body"].innerHTML), "last rung shows answer");
// no rung may be a content-free filler such as "No indicator words"
assert(!registry["hint-body"].innerHTML.includes("No indicator words"),
  "ladder never shows an empty 'no indicators' rung");
assert(registry["hint-clue"].innerHTML.includes('mark class="def"'), "definition highlighted");
// final ladder rung after the walkthrough is Fill in answer (not letter reveals)
assert(registry["hint-next"].children.some((b) => b.textContent === "Fill in answer"),
  "final rung is Fill in answer: " + btnNames());
const hx = registry["hx-entry"];
assert(hx.onclick, "fill-in-answer button wired");
hx.onclick();
// Nothing that gives letters away survives the answer going in. The strip itself
// stays, because reporting a bad hint is most useful from a clue you have just
// finished and can see was explained wrong.
assert(!registry["hint-escape"].innerHTML.includes("hx-letter"),
  "escape hatch hidden once solved: " + registry["hint-escape"].innerHTML);
const kd = docListeners["keydown"][0];
assert(kd, "document keydown listener registered");

// --- type into the grid via keyboard events ---
const ev = (key) => ({ key, preventDefault() {}, shiftKey: false, target: registry["kbd"] });
const clickBox = (i) => registry["hint-pattern"].listeners.click[0]({ target: { dataset: { i: String(i) } } });
const curIndex = () => patBoxes().findIndex((b) => b.includes("cur"));

// Which entry the grid is on, read back the way a solver sees it: the app marks
// the current square `sel` and the rest of its entry `hl`. Going through the DOM
// keeps this test honest — app.js keeps its state closed over inside an IIFE, and
// a test that reached into that state would stop testing what the page renders.
function currentEntry() {
  const cols = openPuz.dimensions.cols;
  const lit = [];
  registry["grid"].children.forEach((el, i) => {
    if (el.classList.contains("sel") || el.classList.contains("hl")) {
      lit.push({ x: i % cols, y: Math.floor(i / cols) });
    }
  });
  return openPuz.entries.find((e) => e.length === lit.length && lit.every(({ x, y }) =>
    e.direction === "across"
      ? y === e.position.y && x >= e.position.x && x < e.position.x + e.length
      : x === e.position.x && y >= e.position.y && y < e.position.y + e.length));
}
// A letter the entry definitely doesn't want at this square. A fixed "Z" would
// make the wrong-letter assertions vacuous on any answer containing a Z.
const wrongLetter = (right) => "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").find((c) => c !== right);

// Tab to an entry long enough for the cursor tests below (they punch a gap at
// index 4) and whose answer is published — prize puzzles arrive without one.
let target = null;
for (let i = 0; i < openPuz.entries.length && !target; i++) {
  kd(ev("Tab"));
  const e = currentEntry();
  if (e && e.solution && e.length >= 6) target = e;
}
assert(target, "found an entry to type into");
const answer = target.solution;
const len = answer.length;
// All but the last letter, so the entry is not CONFIRMED while the editing below
// happens: a word the grid has confirmed is locked against being typed over or
// deleted, so an edit test that finishes the answer first would be testing the
// lock rather than the cursor. The last letter goes in at the end of the block.
answer.slice(0, len - 1).split("").forEach((ch) => kd(ev(ch)));
// the pattern strip is live: it shows the typed letters, all in place
{
  const boxes = patBoxes();
  assert(boxes.length === len, `pattern strip follows the ${len}-letter entry: ` + boxes.length);
  assert(patHTML().includes(`${len - 1} of ${len} letters in place`), "pattern counts typed letters: " + patHTML());
  assert(new RegExp(`data-i="${len - 1}"`).test(patHTML()), "boxes carry their index so they can be clicked: " + patHTML());
}
// --- clicking a pattern box moves the cursor; overtyping a letter moves to the next unlocked square ---
// (typing into a gap still skips to the next gap; typing over a filled square goes to the
// very next square that is not locked in, filled or not — see tests/test_overtype.js)
{
  const bad = wrongLetter(answer[4]);
  assert(registry["hint-pattern"].listeners.click, "pattern strip has a click handler");
  // Moving the cursor is only half of it — on a tablet you then need somewhere to
  // type. iOS raises the soft keyboard only for a focus() inside the gesture, and
  // the click handler re-renders this strip out from under the tapped button, so
  // the focus has to be hooked on mousedown like the grid's. Both cursor
  // controls, asserted together: a new one that forgets this is a box you can
  // tap and then cannot type into.
  // The hint buttons are the other half: they don't move the cursor, but tapping
  // anything that isn't the input blurs it, the keyboard leaving is a viewport
  // change, and the page reflows just as the new rung lands — so the hint reads
  // as flashing open and shut. Listed with the cursor controls so a new
  // tappable thing in the panel cannot forget it.
  ["grid", "hint-pattern", "hint-next", "hint-escape",
   "clues-across", "clues-down"].forEach((id) =>
    assert(registry[id].listeners.mousedown,
      `${id} keeps the keyboard on mousedown, not after its own re-render`));

  // Which of them may RAISE one is asserted in one place, further down — search
  // for "the letter strip is the only thing that summons". Listing it twice is
  // how the two lists come to disagree.

  // A finger that moved across the grid is scrolling, not tapping, but the move
  // guard must not bail out before preventDefault. preventDefault on touchend is
  // the only thing stopping iOS synthesising a mousedown afterwards, and this
  // same cell listens to mousedown, so a drag that skips the tap handler is
  // then selected by the mouse handler. The guard has to cancel first and
  // decide second.
  {
    const cell = registry["grid"].children.find((d) => d.listeners && d.listeners.touchend);
    assert(cell, "the grid has tappable cells");
    let prevented = 0;
    cell.listeners.touchstart[0]({ touches: [{ clientX: 0, clientY: 0 }] });
    cell.listeners.touchend[0]({
      changedTouches: [{ clientX: 0, clientY: 200 }],
      preventDefault: () => prevented++
    });
    assert(prevented === 1,
      "a moved finger still cancels the mousedown it would otherwise fall through to");
  }
  clickBox(4);
  assert(curIndex() === 4, "clicking a pattern box moves the cursor there, got " + curIndex());
  kd(ev("Delete"));                       // punch a single gap at index 4
  assert(patHTML().includes(`${len - 2} of ${len} letters in place`), "gap cleared: " + patHTML());
  clickBox(0);
  kd(ev(wrongLetter(answer[0])));         // overwrite index 0 ...
  assert(curIndex() === 1,
    "overtyping a filled square moves to the next unlocked square, got " + curIndex());
  clickBox(4);                            // put the cursor back on the gap
  kd(ev(bad));                            // ... and the gap at 4 takes it
  assert(patHTML().includes(`${len - 1} of ${len} letters in place`), "grid refilled: " + patHTML());
  // leave the entry correct and complete: the solved count below expects it
  clickBox(0); kd(ev(answer[0]));
  clickBox(4); kd(ev(answer[4]));
  clickBox(len - 1); kd(ev(answer[len - 1]));
  assert(patHTML().includes(`${len} of ${len} letters in place`),
    "the entry finishes correct: " + patHTML());

  // --- and now it is confirmed, it is not editable ---
  // Deleting a letter from a confirmed word should not be possible, nor should
  // closing a crossing entry be able to do it either. Every letter is right and
  // the grid has said so, so a keystroke on one is an accident by definition.
  clickBox(2);
  kd(ev("Delete"));
  assert(patHTML().includes(`${len} of ${len} letters in place`),
    "Delete cannot empty a square of a confirmed word: " + patHTML());
  kd(ev("Backspace"));
  assert(patHTML().includes(`${len} of ${len} letters in place`),
    "nor can Backspace, which is how a crossing entry reaches it: " + patHTML());
  // Refusing the delete is not the same as doing nothing: the cursor still goes
  // where the key was pointing it, one square back, or Backspace reads as dead
  // on a finished word.
  assert(curIndex() === 1,
    "a refused Backspace still steps the cursor back one, got " + curIndex());
  clickBox(2);
  kd(ev(wrongLetter(answer[2])));
  assert(patHTML().includes(`${len} of ${len} letters in place`),
    "nor typing over it, which is a delete with a letter on the end: " + patHTML());
  // A refusal you cannot see is a key that reads as dead, so each of the three
  // above answers on the square it was refused on.
  assert(lightCells.some((c) => c.classList.contains("pulse")),
    "a refused keystroke pulses the square it was refused on");

  // --- and once it is out, you can say what you thought of it ---
  // The question only makes sense after the answer: before it, "was that a good
  // clue" is a question about how stuck you are. The row carries what is being
  // rated and which way, and nothing else — see the privacy block further down,
  // which is where what may leave the page is settled.
  //
  // In #hint-vote and never in #hint-body. Appended to the body it would land
  // wherever the body happens to end, so the question would move up or down the
  // panel with how many rungs had been bought — a fixed slot at the foot of
  // the panel is the only thing that holds it still.
  {
    const body = registry["hint-body"].innerHTML;
    const row = registry["hint-vote"].innerHTML;
    const m = /data-vote="([^"|]+)\|up"/.exec(row);
    assert(m, "a solved clue offers the vote row: " + row.slice(-400));
    assert(m && /^c:[a-z0-9]+-\d+:\d+-(across|down)$/.test(m[1]),
      "and it names the puzzle and the clue, nothing about the solver: " + (m && m[1]));
    assert(/data-vote="[^"]+\|down"/.test(row), "both verdicts are offered: " + row.slice(-400));
    assert(!/data-vote=/.test(body),
      "and it is not in the body, where its place would depend on the ladder above it: "
        + body.slice(-400));
  }
}

kd(ev("ArrowDown")); kd(ev("ArrowRight")); kd(ev("Backspace")); kd(ev("Enter"));
assert(registry["scorebar"].innerHTML.includes("Solved"), "scorebar renders: " + registry["scorebar"].innerHTML);
assert(registry["scorebar"].innerHTML.match(/Solved <strong>[1-9]/), "at least one clue solved after reveal+typing");

// --- checking letters in the clue list ---
// One dot per crossing square, filled once that square has a letter, so you can
// see from the list which clue the grid has already half-given you. Having just
// solved an entry, every clue it crosses must show at least one filled dot, and
// the solved row itself must show none. Asserted at both ends: dots that never
// light up are useless, and dots left on finished clues are noise on every line.
{
  const rows = Object.keys(registry).filter((k) => /^clue-/.test(k)).map((k) => registry[k]);
  assert(rows.length > 10, "clue rows rendered: " + rows.length);
  const dots = (r) => ((r.querySelector(".checkers") || {}).innerHTML) || "";
  assert(rows.some((r) => dots(r).includes('<i class="on">')),
    "solving an entry lights the crossing-letter dots on the clues it crosses");
  assert(rows.some((r) => dots(r).includes('<i class="">')),
    "squares still empty show an unfilled dot");
  const done = rows.filter((r) => r.classList.contains("solved"));
  assert(done.length, "at least one clue row is marked solved");
  done.forEach((r) => assert(!dots(r).includes("<i "),
    "a solved clue shows no crossing-letter dots: " + dots(r)));
}

// --- check buttons: a check must ALWAYS report a result ---
// A check that silently does nothing when the letters are right reads as a broken
// button; every check writes a sentence into #check-result and pulses the squares.
{
  const box = document.getElementById("check-result");
  const msg = () => box.textContent;
  assert(fs.readFileSync(path.join(ROOT, "index.html"), "utf8").includes('id="check-result"'),
    "index.html has the #check-result live region for check feedback");

  // Mistype the entry here rather than relying on what the navigation keys above
  // happened to leave in it, and derive the wrong letter from the entry the
  // cursor is actually in, not from `answer`, which belongs to the entry typed
  // into further up: a letter wrong for one word can be right for another.
  // ...and into one that is still open. A full entry is a confirmed one, and a
  // confirmed word refuses the wrong letter this check needs — correctly, which
  // is what the lock above asserts. Tab walks the entries in order.
  const entryFull = () => {
    const m = patHTML().match(/(\d+) of (\d+) letters in place/);
    return !!m && m[1] === m[2];
  };
  for (let i = 0; i < 60 && entryFull(); i++) kd(ev("Tab"));
  assert(!entryFull(), "found an entry with a gap in it to put a wrong letter in: " + patHTML());
  const cur = currentEntry();
  assert(cur && cur.solution, "the cursor sits in an entry with a published solution");
  // Into a BLANK square, not square 0. A square already holding a letter can
  // belong to a confirmed crossing word, and a confirmed letter refuses to be
  // overwritten — the keystroke vanishes and the check honestly reports every
  // letter present as correct. The entry is known to have a gap (asserted just
  // above); put the wrong letter in the gap.
  const blankAt = () => {
    const m = [...patHTML().matchAll(/data-i="(\d+)"\s*title="Jump to this square — blank/g)];
    return m.length ? Number(m[0][1]) : -1;
  };
  const gap = blankAt();
  assert(gap >= 0, "found a blank square in the entry to mistype into: " + patHTML());
  clickBox(gap);
  kd(ev(wrongLetter(cur.solution[gap])));
  registry["chk-entry"].onclick();
  assert(/wrong letter/.test(msg()), "wrong letters are reported: " + JSON.stringify(msg()));
  assert(box.className.includes("bad"), "wrong result styled as bad: " + box.className);

  registry["clear-entry"].onclick();
  registry["chk-entry"].onclick();
  assert(/Nothing to check/.test(msg()), "empty entry says there is nothing to check: " + JSON.stringify(msg()));

  registry["chk-grid"].onclick();    // only correct (revealed) letters remain
  assert(/correct/.test(msg()), "an all-correct check confirms it: " + JSON.stringify(msg()));
  assert(box.className.includes("ok"), "correct result styled as ok: " + box.className);
  assert(lightCells.some((c) => c.classList.contains("pulse")),
    "checked squares pulse so the check's scope is visible");

  registry["chk-letter"].onclick();
  assert(msg().length > 0, "checking a single square reports something too");
}

Object.assign(T, { answerShown, currentEntry, ev, kd });
