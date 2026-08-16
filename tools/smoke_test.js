// Fake-DOM smoke test: boots app.js in Node with a minimal DOM stub and exercises
// grid typing, the hint ladder, check/reveal, picker, degradation and persistence.
// Usage: node tools/smoke_test.js
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = require("path").join(__dirname, "..");

let failures = 0;
const assert = (cond, msg) => { if (!cond) { failures++; console.error("FAIL:", msg); } };

// The DOM stub and the app boot live in tools/fake_dom.js, because
// tools/make_hint_packets.js boots the same app to walk the same hint ladder.
// One stub, so a grader can never mark a rung the app does not actually show.
const { registry, document, storage, docListeners, canonicalLink, FakeEl, appSrc } =
  require("./fake_dom.js").boot();

// --- cache busting: index.html must reference current asset hashes ---
// (mobile browsers hold GitHub Pages' 4h max-age copies otherwise — STYLE.md)
{
  const crypto = require("crypto");
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  // Enumerated off stamp_assets.py rather than retyped, so a new asset is
  // covered by this check the moment it is stamped. A hand-kept second list is
  // a list that goes stale, and the symptom is a phone serving four-hour-old
  // JavaScript against fresh HTML.
  const stamper = fs.readFileSync(path.join(ROOT, "tools/stamp_assets.py"), "utf8");
  const assetBlock = stamper.match(/ASSETS = \[([\s\S]*?)\]/);
  assert(assetBlock, "tools/stamp_assets.py still declares ASSETS = [...]");
  const stamped = (assetBlock ? assetBlock[1].match(/"([^"]+)"/g) || [] : [])
    .map((s) => s.slice(1, -1));
  assert(stamped.includes("app.js") && stamped.includes("sync/merge.js"),
    "the stamped-asset list still covers the app and the sync merge rules");
  stamped.filter((rel) => rel.endsWith(".js") || rel.endsWith(".css")).forEach((rel) => {
    const want = crypto.createHash("md5")
      .update(fs.readFileSync(path.join(ROOT, rel))).digest("hex").slice(0, 8);
    assert(html.includes(`${rel}?v=${want}`),
      `index.html has a current ?v= stamp for ${rel} (run tools/stamp_assets.py)`);
  });
}

// --- the grid measures its container, never the window ---
// Sizing cells off `100vw` ignores body's max-width and the flex column, and on
// iOS Safari resolves against a viewport that is still moving while the toolbar
// collapses: the grid drew small and jumped bigger at the first scroll (Paul,
// iPad, 2026-08-09). --cellsize must be declared once, off --gridspace, and no
// #grid rule may reach for a viewport unit again — the breakpoints tune
// --cellcap. Asserted here because it is invisible in a headless DOM and the
// only place it shows up is on a real tablet.
{
  const all = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  // The one sanctioned exception: the `@supports not (width: 1cqi)` branch that
  // keeps pre-2023 browsers from getting no grid at all.
  const css = all.replace(/@supports not \(width: 1cqi\)\s*\{[^{}]*\{[^}]*\}[^}]*\}/g, "");
  const decls = css.match(/--cellsize\s*:/g) || [];
  assert(decls.length === 1,
    `--cellsize is declared exactly once (found ${decls.length}); breakpoints ` +
    `override --cellcap, not the whole calculation`);
  (css.match(/#grid\b[^{]*\{[^}]*\}/g) || []).forEach((rule) => {
    assert(!/\b\d*\.?\d+v(w|h|min|max)\b/.test(rule),
      "no #grid rule sizes itself in viewport units — use container units " +
      "(--gridspace) so the grid tracks its column, not the browser chrome: " + rule);
  });
  assert(/--gridspace:\s*calc\(100cqi/.test(css),
    "the grid's space comes from a container query unit");
}

// --- assertions after boot ---
assert(!registry["app"].classList.contains("hidden"), "app visible after boot");
assert(Object.keys(global.window.CRYPTIC_PUZZLES || {}).length >= 25, "all puzzle scripts loaded");
// Which puzzle boots is NOT pinned here on purpose: the nightly job adds one
// every day, and a test that only ever exercises a frozen fixture stops
// covering the puzzles people actually land on. Everything below therefore
// derives its expectations (entry lengths, letters to type) from whichever
// puzzle opened, rather than hard-coding one puzzle's answers — the previous
// version typed "COLOGNE" and silently began failing the day the app stopped
// booting on No 30,067. Set CT_TEST_QUERY=?p=30067 to pin one while debugging.
const openTitle = registry["puzzle-title"].innerHTML;
assert(/No [\d,]+/.test(openTitle), "a Guardian cryptic opened: " + openTitle);
const openId = (openTitle.match(/No ([\d,]+)/) || [, ""])[1].replace(/,/g, "");
const openPuz = (global.window.CRYPTIC_PUZZLES || {})[openId];
assert(openPuz, "the opened puzzle's data is loaded: " + openId);
// A ?p= URL hands its indexing credit to the static write-up, not to the
// homepage. It shipped canonicalling to the site root, so every link to a
// specific puzzle credited the front page and Search Console filed the puzzle
// under "alternate page with proper canonical tag" (2026-08-07). With no ?p the
// URL really is the homepage, and so is the canonical.
{
  const home = "https://paultarjan.com/cryptic-teacher/";
  const asked = new URLSearchParams(global.location.search).get("p");
  const meta = (global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === asked);
  const want = (meta && meta.hasSolutions) ? `${home}puzzles/${meta.number}/` : home;
  assert(canonicalLink.href === want,
    `canonical should be ${want}, got ${canonicalLink.href}`);
}

// The badge marks the exception, not the norm: an annotated puzzle's title
// carries no badge at all (see STYLE.md, "Badge the exception"). So the title
// must agree with the index rather than always saying something.
{
  const idx = (global.CRYPTIC_INDEX.puzzles || []).find((p) => String(p.number) === openId);
  const badged = registry["puzzle-title"].innerHTML.includes("auto hints");
  assert(idx && badged === !idx.annotated,
    "title badge disagrees with the index for " + openId + ": badged=" + badged);
}

// No difficulty band without having solved the puzzle first (Paul, 2026-08-02:
// "if you can't grade without solving just leave it unknown until you solve").
// tools/difficulty.py enforces this by requiring its wordplay component, which
// only exists once a puzzle is annotated — but that is one `if` guarding a rule
// that matters, and the failure is silent and plausible-looking: the Guardian's
// beginner Quiptic came out rated BRUTAL on the shape of its grid. So check the
// shipped index rather than trusting the generator, and check every puzzle
// rather than the one the app happened to open.
{
  const graded = (global.CRYPTIC_INDEX.puzzles || [])
    .filter((p) => p.difficulty && !p.annotated)
    .map((p) => p.number);
  assert(graded.length === 0,
    "unsolved puzzles carry a difficulty band: " + graded.join(", ")
    + " — grade from the annotations or leave it unknown");
}

// The walkthrough below is the full-hints path: it climbs the hint ladder and
// reveals letters, and neither exists on a puzzle with no annotations or no
// published solutions (Saturday prize crosswords arrive bare). Both of those
// degraded paths get their own section further down. Landing here on one is a
// pinning mistake, so say it once rather than failing eight assertions and
// crashing on a button the app was right not to render.
const openMeta = (global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === openId) || {};
if (!openMeta.annotated || !openMeta.hasSolutions) {
  console.error(`SKIPPED: No ${openId} is ${openMeta.annotated ? "unsolved" : "un-annotated"}, ` +
    "and the main walkthrough needs a full-hints puzzle. Unset CT_TEST_QUERY, or pin an annotated one.");
  process.exit(2);
}

const cellCount = openPuz.dimensions.cols * openPuz.dimensions.rows;
assert(registry["grid"].children.length === cellCount,
  `grid has ${cellCount} cells, got ` + registry["grid"].children.length);
const lightCells = registry["grid"].children.filter((c) => !c.classList.contains("block"));
// Guardian blocked grids run from roughly 140 to 180 light squares; the old
// floor of 150 was one puzzle's figure, and No 30,071 (140) tripped it.
assert(lightCells.length > 120, "light cells present: " + lightCells.length);
assert(registry["clues-across"].children.length > 10, "across clues rendered");
assert(registry["clues-down"].children.length > 10, "down clues rendered");
assert(registry["hint-clue"].innerHTML.length > 10, "hint panel shows a clue");

// --- letter pattern strip: one box per cell, checked vs unchecked marked ---
const patHTML = () => registry["hint-pattern"].innerHTML;
// note the space: it must not also match the "pat-boxes" wrapper
const patBoxes = () => (patHTML().match(/class="pat-box [^"]*"/g) || []);
{
  const boxes = patBoxes();
  const m = patHTML().match(/(\d+) of (\d+) letters in place/);
  assert(boxes.length >= 3, "pattern strip renders boxes: " + boxes.length);
  assert(m && Number(m[2]) === boxes.length, "pattern box count matches the entry length: " + patHTML());
  assert(m && Number(m[1]) === 0, "pattern starts with no letters in place: " + patHTML());
  assert(boxes.some((b) => b.includes("checked") && !b.includes("unchecked")), "checked squares marked");
  assert(patHTML().includes("checked"), "pattern summary mentions checking: " + patHTML());
}

// --- the current-clue box is the clue, not a status report (Paul, 2026-08-09) ---
// The pattern strip used to print its aria-label next to the boxes: twenty words
// restating what the boxes already show, sitting between the clue and the reader.
// The summary stays for screen readers, which cannot see the boxes; it must never
// come back as visible prose, and the meter beside it must stay a count. Asserted
// at both ends so neither half can rot — the label has to still be there, and the
// strip has to still be nothing but boxes.
{
  assert(/aria-label="[^"]*letters? in place/.test(patHTML()),
    "the pattern strip still describes itself to a screen reader: " + patHTML());
  assert((patHTML().match(/<span/g) || []).length === 1,
    "the pattern strip renders the boxes and nothing else — the summary is the " +
    "aria-label, not a line of prose under the clue: " + patHTML());
  const meter = registry["hint-meter"].innerHTML.replace(/<[^>]*>/g, "");
  assert(meter.length < 40,
    `the hint meter is a count, not a sentence (${meter.length} chars): ${meter}`);
}

// --- every validator type part must be claimed by a family in app.js (STYLE.md) ---
{
  const famBlock = appSrc.slice(appSrc.indexOf("const FAMILIES"), appSrc.indexOf("function familyOf"));
  const keywords = [...famBlock.matchAll(/t\.includes\("([^"]+)"\)/g)].map((m) => m[1]);
  const py = fs.readFileSync(path.join(ROOT, "tools/validate_annotations.py"), "utf8");
  const partsBlock = py.slice(py.indexOf("TYPE_PARTS = {"), py.indexOf("}", py.indexOf("TYPE_PARTS = {")));
  const parts = [...partsBlock.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert(parts.length > 10, "TYPE_PARTS parsed from the validator: " + parts.length);
  parts.forEach((p) => assert(keywords.some((k) => p.includes(k)),
    `type part '${p}' is claimed by a clue family in app.js`));
}

// --- escape hatch: reveal a letter BEFORE using any ladder hints ---
assert(registry["hint-escape"].innerHTML.includes("Reveal one letter"), "escape hatch offered at level 0");
assert(registry["hx-letter"].onclick, "escape-hatch button wired");
registry["hx-letter"].onclick();
assert(/letters? revealed/.test(registry["scorebar"].innerHTML), "letter reveals counted in score: " + registry["scorebar"].innerHTML);
assert(registry["hint-meter"].innerHTML.includes("1 letter revealed"), "meter shows reveal count: " + registry["hint-meter"].innerHTML);

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
  assert(/^Show hint \d/.test(open[0].textContent), "recommended rung leads: " + open[0].textContent);
  assert(locked.length >= 1, "later rungs are locked from cold, not free for the taking");
  assert(/walkthrough/i.test(locked[locked.length - 1].textContent),
    "the walkthrough is never one click from cold: " + locked[locked.length - 1].textContent);
  // The load-bearing one. Checking only that SOME button is disabled is not
  // enough: an app that offers every rung AND redundantly lists the late ones
  // as disabled would satisfy that, and did. What must hold is that no late
  // rung is clickable yet.
  assert(!open.some((b) => /walkthrough|building blocks|what each half means/i.test(b.textContent)),
    "a late rung is offered from cold: " + open.map((b) => b.textContent).join(" | "));
  const last = open[open.length - 1];
  const wanted = last.textContent;                 // e.g. "3 · Spot the indicator words"
  last.onclick();
  const shown = registry["hint-body"].innerHTML;
  assert(shown.includes("hint-step"), "the chosen rung is revealed");
  const stepCount = (shown.match(/class="hint-step"/g) || []).length;
  assert(stepCount === 1, `choosing rung "${wanted}" revealed ${stepCount} rungs, not just the one`);
  // out of order without renumbering: the rung keeps its ladder number
  assert(shown.includes(wanted.split(" · ")[0] + " · "), "rung keeps its ladder number: " + shown.slice(0, 120));
  // the definition highlight is the giveaway that a rung leaked. Position 2 IS
  // the definition rung on every clue, so it should light up exactly then.
  const lit = registry["hint-clue"].innerHTML.includes('mark class="def"');
  assert(lit === wanted.startsWith("2 · "),
    `definition highlight should appear only for the definition rung (took "${wanted}", lit=${lit})`);
}
registry["reset-puzzle"].onclick();   // back to a clean slate for the in-order walk

// --- walk the hint ladder: the ladder is per-clue, so click until it runs out ---
let rungs = 0;
while (registry["hint-next"].children[0] && registry["hint-next"].children[0].onclick && rungs < 8) {
  registry["hint-next"].children[0].onclick();
  rungs++;
  if (rungs === 1) {
    // rung 1 gives the FAMILY only — never the precise (often compound) type
    const first = registry["hint-body"].innerHTML;
    assert(/Definitions only|&amp;lit|&lit|Rearrangement|Sound|Charade|Alteration|Extraction/.test(first),
      "first rung names a clue family: " + first);
    assert(!first.includes("mechanism"), "first rung withholds the precise mechanism: " + first);
  }
  assert(registry["hint-body"].innerHTML.includes("hint-step"), "hint body populated at level " + rungs);
  assert(registry["hint-escape"].innerHTML.includes("Reveal one letter") || registry["hint-meter"].innerHTML.includes("Solved"),
    "escape hatch still available at level " + rungs);
}
assert(rungs >= 3 && rungs <= 5, "ladder has a sane number of rungs, got " + rungs);
assert(registry["hint-body"].innerHTML.includes("Answer:"), "last rung shows answer");
// no rung may be a content-free filler (the old "No indicator words" step)
assert(!registry["hint-body"].innerHTML.includes("No indicator words"),
  "ladder never shows an empty 'no indicators' rung");
assert(registry["hint-clue"].innerHTML.includes('mark class="def"'), "definition highlighted");
// final ladder rung after the walkthrough is Fill in answer (not letter reveals)
assert(registry["hint-next"].innerHTML.includes("Fill in answer"), "final rung is Fill in answer: " + registry["hint-next"].innerHTML);
const hx = registry["hx-entry"];
assert(hx.onclick, "fill-in-answer button wired");
hx.onclick();
assert(registry["hint-escape"].innerHTML === "", "escape hatch hidden once solved");
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
// A letter the entry definitely doesn't want at this square. Typing a fixed "Z"
// made the wrong-letter assertions vacuous on any answer containing a Z.
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
answer.split("").forEach((ch) => kd(ev(ch)));
// the pattern strip is live: it now shows the typed letters, all in place
{
  const boxes = patBoxes();
  assert(boxes.length === len, `pattern strip follows the ${len}-letter entry: ` + boxes.length);
  assert(patHTML().includes(`${len} of ${len} letters in place`), "pattern counts typed letters: " + patHTML());
  assert(new RegExp(`data-i="${len - 1}"`).test(patHTML()), "boxes carry their index so they can be clicked: " + patHTML());
}
// --- clicking a pattern box moves the cursor; typing skips filled squares ---
{
  const bad = wrongLetter(answer[4]);
  assert(registry["hint-pattern"].listeners.click, "pattern strip has a click handler");
  // Moving the cursor is only half of it — on a tablet you then need somewhere to
  // type. iOS raises the soft keyboard only for a focus() inside the gesture, and
  // the click handler re-renders this strip out from under the tapped button, so
  // the focus has to be hooked on mousedown like the grid's (Paul, iPad,
  // 2026-08-09). Both cursor controls, asserted together: a new one that forgets
  // this is a box you can tap and then cannot type into.
  ["grid", "hint-pattern"].forEach((id) => assert(registry[id].listeners.mousedown,
    `${id} raises the keyboard on mousedown, not after its own re-render`));
  clickBox(4);
  assert(curIndex() === 4, "clicking a pattern box moves the cursor there, got " + curIndex());
  kd(ev("Delete"));                       // punch a single gap at index 4
  assert(patHTML().includes(`${len - 1} of ${len} letters in place`), "gap cleared: " + patHTML());
  clickBox(0);
  kd(ev(wrongLetter(answer[0])));         // overwrite index 0 ...
  assert(curIndex() === 4, "typing skips filled squares to the next gap, got " + curIndex());
  kd(ev(bad));                            // ... and with no gap left it just steps on
  assert(patHTML().includes(`${len} of ${len} letters in place`), "grid refilled: " + patHTML());
  // leave the entry correct again: the solved count below expects it
  clickBox(0); kd(ev(answer[0]));
  clickBox(4); kd(ev(answer[4]));
}

kd(ev("ArrowDown")); kd(ev("ArrowRight")); kd(ev("Backspace")); kd(ev("Enter"));
assert(registry["scorebar"].innerHTML.includes("Solved"), "scorebar renders: " + registry["scorebar"].innerHTML);
assert(registry["scorebar"].innerHTML.match(/Solved <strong>[1-9]/), "at least one clue solved after reveal+typing");

// --- checking letters in the clue list (Paul, 2026-08-09) ---
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

// --- check buttons: a check must ALWAYS report a result (feedback 2026-07-29) ---
// A check that silently does nothing when the letters are right reads as a broken
// button; every check writes a sentence into #check-result and pulses the squares.
{
  const box = document.getElementById("check-result");
  const msg = () => box.textContent;
  assert(fs.readFileSync(path.join(ROOT, "index.html"), "utf8").includes('id="check-result"'),
    "index.html has the #check-result live region for check feedback");

  // Mistype the entry here rather than relying on what the navigation keys above
  // happened to leave in it — that coupling is what made these three assertions
  // fail the moment the app booted on a different puzzle.
  //
  // Half a fix, as it turned out: it stopped depending on the letters left in the
  // entry but went on deriving the wrong letter from `answer`, which belongs to
  // the entry we typed into further up, not the one the arrow keys have since
  // moved to. When the boot puzzle became 1394 the cursor landed in a 14-letter
  // entry holding one crossing letter, and a letter picked to be wrong for a
  // different word happened to be right for that one — so the check honestly
  // reported no errors and these three assertions failed nightly (2026-08-12).
  // Ask the app which entry the cursor is actually in.
  const cur = currentEntry();
  assert(cur && cur.solution, "the cursor sits in an entry with a published solution");
  clickBox(0);
  kd(ev(wrongLetter(cur.solution[0])));
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

// --- picker: taught puzzles by default, everything by search ---
// The rule is two-sided and both sides are feedback (2026-08-01, "we only want
// to only show ones that have full annotations", plus "hard to navigate as we
// get more puzzles"). Default list = what can actually teach you. Search = the
// whole collection, so nothing is unreachable and a number you know still works.
const allPuzzles = global.CRYPTIC_INDEX.puzzles || [];
const pickerRows = () => registry["picker-list"].children;
const pickerHTMLNow = () => pickerRows().map((li) => li.children[0].innerHTML).join("");
const typeInPicker = (q) => {
  registry["picker-search"].value = q;
  registry["picker-search"].listeners.input[0]();
};
registry["btn-picker"].onclick();
assert(pickerRows().length >= 5, "picker lists the annotated puzzles: " + pickerRows().length);
assert(registry["picker-search"].value === "", "the filter box starts empty on open");
{
  // "current" is the row for the puzzle already open, which is listed whatever
  // its annotation state — don't hide the user's own work. Everything else in a
  // default list has to have earned its place.
  const others = pickerRows().filter((li) => !/current/.test(li.className || ""));
  const html = others.map((li) => li.children[0].innerHTML).join("");
  // No full-hints badge anywhere (feedback 2026-08-01: "since it only lists full
  // hints we don't have to show it"). A label every row carries distinguishes
  // nothing; the badge marks the exception now, not the norm.
  assert(!pickerHTMLNow().includes("full hints"),
    "picker rows carry a full-hints badge that says the same thing about every row");
  // Structural rather than textual, so deleting the badge can't quietly turn
  // this into a test of nothing: the listed numbers must BE the annotated ones.
  const annotatedNums = new Set(allPuzzles.filter((p) => p.annotated).map((p) => String(p.number)));
  const listedNums = others.map((li) => (li.children[0].innerHTML.match(/№ (\d+)/) || [])[1]);
  const strays = listedNums.filter((n) => !annotatedNums.has(n));
  assert(listedNums.length && !strays.length,
    "un-annotated puzzles are listed by default: " + strays.join(", "));
  // The badge is the visible half of the same rule.
  assert(!html.includes("auto hints"),
    "un-annotated puzzles are listed by default: " + pickerRows().length + " rows");
  assert(pickerRows().length < allPuzzles.length,
    "something is hidden, so the footer count means something");
  assert(/archive|search/i.test(registry["picker-more"].innerHTML),
    "the hidden ones are still signposted: " + registry["picker-more"].innerHTML);
}
// filtering narrows, and matches setters as well as numbers
{
  const target = allPuzzles.find((p) => p.annotated);
  typeInPicker(String(target.number));
  assert(pickerRows().length === 1 && pickerHTMLNow().includes("№ " + target.number),
    "filtering by number finds exactly that puzzle");
  typeInPicker(target.setter.toLowerCase());
  assert(pickerHTMLNow().includes("№ " + target.number),
    "filtering by setter works: " + target.setter);
  typeInPicker("zzzznotasetter");
  assert(pickerRows().length === 1 && /picker-empty/.test(pickerRows()[0].className),
    "a filter that matches nothing says so rather than showing everything");
}

// --- open an un-annotated puzzle (auto hints degradation) ---
// Reachable only by searching for it now — which is exactly the escape hatch
// that makes hiding them by default acceptable.
// hasSolutions matters: the escape hatches asserted below are the reveal
// buttons, and a puzzle whose answers the Guardian hasn't published yet has
// nothing to reveal.
const autoPuzzle = allPuzzles.find((p) => !p.annotated && p.hasSolutions && global.window.CRYPTIC_PUZZLES[p.id]);
typeInPicker(String(autoPuzzle.number));
const autoRow = pickerRows().find((li) => li.children[0] && li.children[0].innerHTML.includes("auto hints"));
assert(autoRow, `searching for ${autoPuzzle.number} surfaces the un-annotated puzzle`);
const autoBtn = autoRow.children[0];
autoBtn.onclick();
assert(registry["puzzle-title"].innerHTML.includes("auto hints"), "auto-hints puzzle opened");
assert(registry["hint-body"].innerHTML.includes("auto hints") || registry["hint-body"].innerHTML.includes("hasn"), "degraded hint panel message");
assert(registry["hint-next"].innerHTML.includes("Reveal answer"), "auto-hints puzzle offers Reveal answer");
assert(registry["hint-escape"].innerHTML.includes("Reveal one letter"), "auto-hints puzzle offers letter escape hatch");

// --- a puzzle we solved ourselves says so ---
// Prize crosswords get solved here before the paper publishes its key
// (tools/apply_solution.py), which means the app will happily tell a solver
// their letter is wrong on the authority of a machine's guess. The disclosure
// is the whole justification for shipping those answers at all, so it is
// asserted rather than trusted: it lives in one <p> that one line of app.js
// unhides, and both are easy to lose in a refactor that nothing else notices.
{
  const unofficial = allPuzzles.find((p) => p.solutionsUnofficial && global.window.CRYPTIC_PUZZLES[p.id]);
  if (unofficial) {
    registry["btn-picker"].onclick();
    typeInPicker(String(unofficial.number));
    const row = pickerRows().find((li) => li.children[0]
      && li.children[0].innerHTML.includes("№ " + unofficial.number));
    assert(row && row.children[0].innerHTML.includes("our answers"),
      `the picker badges No ${unofficial.number} as our own answers`);
    row.children[0].onclick();
    const note = registry["unofficial-note"];
    assert(note && !note.classList.contains("hidden"),
      `No ${unofficial.number} shows the unofficial-answers note`);
    assert(note.textContent && /hasn't published|not published/.test(note.textContent),
      "the note actually says the paper hasn't published these answers: " + (note && note.textContent));
    // And the note must disappear again on a puzzle with the paper's own answers.
    const official = allPuzzles.find((p) => p.hasSolutions && !p.solutionsUnofficial
      && global.window.CRYPTIC_PUZZLES[p.id]);
    registry["btn-picker"].onclick();
    typeInPicker(String(official.number));
    pickerRows().find((li) => li.children[0]
      && li.children[0].innerHTML.includes("№ " + official.number)).children[0].onclick();
    assert(registry["unofficial-note"].classList.contains("hidden"),
      `No ${official.number} has the paper's answers and shows no note`);
  }
}

// --- the picker says which puzzles you have finished (Paul, 2026-08-13) ---
// With 78 rows listed, "have I done this one?" is the first question the list
// has to answer. It is derived, not stored — from the saved letters against the
// loaded solutions — so a change to either side can silently break it without
// breaking anything else. Drive it from both directions: a complete correct
// grid must read solved, one letter short must not.
{
  const target = allPuzzles.find((p) => p.annotated && p.hasSolutions
    && global.window.CRYPTIC_PUZZLES[p.id]);
  const puz = global.window.CRYPTIC_PUZZLES[target.id];
  const letters = {};
  puz.entries.forEach((e) => {
    for (let i = 0; i < e.length; i++) {
      const x = e.position.x + (e.direction === "across" ? i : 0);
      const y = e.position.y + (e.direction === "across" ? 0 : i);
      letters[x + "," + y] = e.solution[i];
    }
  });
  const key = "ct:" + target.id;
  const kept = storage[key];
  const rowHTML = () => {
    registry["btn-picker"].onclick();
    typeInPicker(String(target.number));
    const li = pickerRows().find((x) => x.children[0]
      && x.children[0].innerHTML.includes("№ " + target.number));
    return li ? li.children[0].innerHTML : "";
  };

  storage[key] = JSON.stringify({ letters, updated: 1 });
  assert(/solved ✓/.test(rowHTML()),
    `a complete, correct grid reads as solved in the picker: ${rowHTML().slice(0, 200)}`);

  const oneShort = Object.assign({}, letters);
  delete oneShort[Object.keys(oneShort)[0]];
  storage[key] = JSON.stringify({ letters: oneShort, updated: 1 });
  const partial = rowHTML();
  assert(!/solved ✓/.test(partial) && new RegExp(Object.keys(letters).length + " letters in").test(partial),
    `one square short is not solved, and says how far along it is: ${partial.slice(0, 200)}`);

  if (kept === undefined) delete storage[key]; else storage[key] = kept;
}

// --- link words and definition notes reach the screen (feedback 2026-07-29) ---
// Both fields exist to answer a learner's question — "what does this word do?"
// and "why doesn't the definition match the answer?" — so data that never
// renders is worse than no data. Drive the real UI to a clue that has each.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const findClue = (field) => {
    for (const id of Object.keys(puzzles).sort().reverse()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation;
        if (a && (Array.isArray(a[field]) ? a[field].length : a[field])) return { id, e };
      }
    }
    return null;
  };
  const openClue = ({ id, e }) => {
    // Search by number rather than scanning the default list: the default list
    // is annotated-only, and a puzzle can carry annotated clues while its index
    // flag says otherwise (mid-annotation, or a partial hand-edit).
    registry["btn-picker"].onclick();
    typeInPicker(String(id));
    const li = registry["picker-list"].children.find((x) => x.children[0] && x.children[0].innerHTML.includes("№ " + id));
    assert(li, `picker finds puzzle ${id} when searched for`);
    li.children[0].onclick();
    const row = registry["clue-" + e.id];
    assert(row && row.listeners.click, `clue list shows ${e.number}${e.direction[0]}: ${e.clue}`);
    row.listeners.click[0]();
    // rung 1 = family, rung 2 = definition, which is where both fields hang
    registry["hint-next"].children[0].onclick();
    registry["hint-next"].children[0].onclick();
  };

  const linked = findClue("linkWords");
  assert(linked, "at least one annotation names its link words");
  openClue(linked);
  assert(registry["hint-body"].innerHTML.includes("just a link"),
    "link words are explained on the definition rung: " + registry["hint-body"].innerHTML);
  assert(registry["hint-clue"].innerHTML.includes('mark class="link"'),
    "link words are highlighted in the clue: " + registry["hint-clue"].innerHTML);

  // A definitionNote explains why the definition does not agree with the ANSWER,
  // so it is written about the answer and routinely names it — 16 in the corpus
  // did, and one of them handed TRUMP CARDS over on rung 2 (Paul, 2026-08-09).
  // It belongs beside definitionFit on the walkthrough, not on the definition
  // rung. Assert BOTH ends: absent early, present late. Only checking that it is
  // shown somewhere is what let it sit on the wrong rung for months.
  const noted = findClue("definitionNote");
  assert(noted, "at least one annotation explains a definition that disagrees with its answer");
  openClue(noted);
  assert(!registry["hint-body"].innerHTML.includes("def-note"),
    "the definition note is NOT on the definition rung — it names the answer: " +
    registry["hint-body"].innerHTML);
  for (let i = 0; i < 8; i++) {
    const btn = registry["hint-next"].children[0];
    if (!btn || !btn.onclick || !/^Show hint/.test(btn.textContent || "")) break;
    btn.onclick();
  }
  assert(registry["hint-body"].innerHTML.includes("def-note"),
    "the definition note is shown on the walkthrough rung: " + registry["hint-body"].innerHTML);

  // --- a cryptic definition must not sell the answer on the blocks rung ---
  // The type has no wordplay, so the only "block" available is the whole clue
  // giving the whole answer — and that is what four of the nine in the corpus
  // had. Rendered, hint 3 of 4 read “Might this keep you to time?” → WATCHSTRAP,
  // one rung after hint 2 had said there was nothing to take apart (Paul, 1392
  // 22-across, 2026-08-10). The validator now rejects that annotation and app.js
  // suppresses `gives` for the type; this drives the real ladder to prove it, on
  // every cryptic definition there is rather than the one that was reported.
  {
    const cds = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        if (((e.annotation || {}).type || "") === "cryptic definition") cds.push({ id, e });
      }
    }
    assert(cds.length, "the corpus still has a cryptic definition to check");
    for (const cd of cds) {
      const ans = (cd.e.annotation.answer || "").replace(/[^A-Za-z]/g, "").toUpperCase();
      const where = `${cd.id} ${cd.e.id} (${ans})`;
      openClue(cd);
      // Climb to the rung BEFORE the walkthrough: every rung a learner can buy
      // without committing to the last one must leave the answer unspoken.
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!btn || !btn.onclick || !/^Show hint/.test(btn.textContent || "")) break;
        if (/walkthrough/i.test(btn.textContent)) break;
        btn.onclick();
        const bare = registry["hint-body"].innerHTML.replace(/[^A-Za-z]/g, "").toUpperCase();
        assert(!bare.includes(ans),
          `${where}: a rung before the walkthrough spells the answer out — ` +
          registry["hint-body"].innerHTML);
      }
      const btn = registry["hint-next"].children[0];
      assert(btn && /walkthrough/i.test(btn.textContent || ""),
        `${where}: the ladder still ends at the walkthrough, got ` +
        ((btn && btn.textContent) || "nothing"));
      btn.onclick();
      assert(registry["hint-body"].innerHTML.includes("Answer:"),
        `${where}: the walkthrough is where the answer finally appears`);
    }
  }

  // --- a rung highlights its own words, on its own ---
  // Feedback 2026-08-01: "if I choose just the indicator clue now it doesn't
  // highlight the parts of clue". All clue markup used to be gated on the
  // definition rung, which was invisible while the ladder was strictly ordered
  // and broke the day tier 0 allowed any order — so the legitimate route
  // (indicators first, work the definition out yourself) spent a hint and lit
  // nothing. Drive exactly that route, and check both directions: what was
  // asked for is marked, what wasn't is not.
  const withInd = (() => {
    for (const id of Object.keys(puzzles).sort().reverse()) {
      for (const e of puzzles[id].entries || []) {
        const a = e.annotation;
        // the indicator has to literally occur in the clue or there is nothing
        // to mark, and a linked clue renders its holder's text instead
        if (a && !a.linkedTo && (a.indicators || []).some((s) => e.clue.includes(s))) return { id, e };
      }
    }
    return null;
  })();
  assert(withInd, "at least one annotation names an indicator that occurs in its clue");
  registry["btn-picker"].onclick();
  typeInPicker(String(withInd.id));
  registry["picker-list"].children
    .find((x) => x.children[0] && x.children[0].innerHTML.includes("№ " + withInd.id))
    .children[0].onclick();
  registry["clue-" + withInd.e.id].listeners.click[0]();
  const indBtn = registry["hint-next"].children.find((b) => /indicator/i.test(b.textContent) && !b.disabled);
  assert(indBtn, "the indicators rung is offered from cold: " + registry["hint-next"].innerHTML);
  indBtn.onclick();
  const marked = registry["hint-clue"].innerHTML;
  assert(marked.includes('mark class="ind"'),
    "the indicators rung highlighted nothing in the clue: " + marked);
  assert(!marked.includes('mark class="def"') && !marked.includes('mark class="link"'),
    "the indicators rung leaked definition markup: " + marked);
  const legend = (registry["hint-body"].innerHTML.match(/<div class="legend">[\s\S]*?<\/div>/) || [""])[0];
  assert(legend.includes('mark class="ind"') && !legend.includes('mark class="def"'),
    "the legend must name exactly the marks that were drawn: " + legend);

  // --- the walkthrough joins the definition to the answer ---
  // Feedback 2026-08-01: "in the full walkthrough explain why the answer matches
  // the definition". The blocks spell the answer out of the wordplay, but nothing
  // used to say why those words MEAN it. This tests the render path only — the
  // sentence is written by the annotator and policed by
  // check_definition_fit in tools/validate_annotations.py, so the field is
  // synthesised here rather than waiting on a puzzle that happens to carry one.
  {
    const e = withInd.e;
    e.annotation.definitionFit = "SMOKE-FIT: the answer is an instance of the definition.";
    registry["clue-" + e.id].listeners.click[0]();
    let guard = 0;
    while (registry["hint-next"].children[0] && registry["hint-next"].children[0].onclick && guard++ < 8) {
      registry["hint-next"].children[0].onclick();
      if (registry["hint-body"].innerHTML.includes("Answer:")) break;
    }
    const walk = registry["hint-body"].innerHTML;
    assert(walk.includes("SMOKE-FIT"),
      "the walkthrough never explains why the answer matches the definition: " + walk.slice(-400));
    const fitLine = (walk.match(/<p class="def-fit">[\s\S]*?<\/p>/) || [""])[0];
    // letters only: esc() turns an apostrophe in FERMAT'S LAST THEOREM into an
    // entity, so a raw substring match would flake on the puzzle, not the code
    const bare = (s) => s.replace(/[^A-Za-z]/g, "");
    assert(fitLine.includes('mark class="def"') && bare(fitLine).includes(bare(e.annotation.answer)),
      "the fit line must name both ends it is joining: " + fitLine);
    assert(walk.indexOf("SMOKE-FIT") < walk.lastIndexOf("Answer:"),
      "the fit comes before the answer — it is what turns a spelling into a solve");
    delete e.annotation.definitionFit;
  }
}

// --- tutorial toggle ---
registry["btn-tutorial"].onclick();
assert(!registry["tutorial"].classList.contains("hidden"), "tutorial opens");
assert(registry["tutorial"].innerHTML.includes("anagram") || registry["tutorial"].innerHTML.includes("Anagram"), "tutorial content injected");

// --- reset ---
registry["reset-puzzle"].onclick();
// Reset leaves a record rather than a hole. An absent save reads as "never
// played this puzzle", so the other device would hand the whole grid straight
// back on the next pull — the reset has to be a thing that happened, with a
// time on it, for the merge to have anything to obey.
{
  const after = JSON.parse(storage[Object.keys(storage).find((k) => /^ct:\d+$/.test(k))] || "{}");
  assert(after.clearedAt > 0 && Object.keys(after.letters || {}).length === 0,
    "resetting records when it happened, so the reset itself can reach the other device");
}

// --- cross-device sync merges, and can only ever add ---
// The whole design rests on the merge being safe to run unattended: no "which
// device wins?" prompt, no confirmation, it just happens when you open the tab.
// That is only true while merging is a union — order-independent and unable to
// remove anything. If any rule below turns into last-write-wins, an iPad left
// in a drawer starts eating the laptop's afternoon, silently, and the solver
// has no way to get it back. So the properties are asserted, not the outputs.
{
  const { mergeSaves } = require("../sync/merge.js");
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

  // Rubbing a letter out has to reach the other device. This is the bug Paul
  // hit on 2026-08-10: absence used to mean only "I never filled this in", so a
  // deletion could not win an argument it was not allowed to enter, and the
  // other device handed the letters back on every single pull.
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
  // else on the grid does not thereby win squares it never touched. The first
  // version compared whole-puzzle timestamps and got exactly this wrong.
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

// --- clue text is text, and its italics are ranges ---
// The papers ship clues as HTML. tools/fetch_puzzle.flatten_clue takes the tags
// out and keeps the italics as [start, length] ranges, because the clue string
// itself has to stay plain: every annotation fragment is located in it by
// indexOf and highlighted by character offset. Structural, not a spot-check —
// the failure mode is a tag rendering as a tag, which is what Paul saw on the
// Independent, and it comes back the moment someone escapes a clue directly.
{
  const src = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
  assert(!/esc\(\s*e\.clue\s*\)/.test(src),
    "no clue is escaped straight to the page — that path drops the setter's italics");
  assert(/clueItalics/.test(src),
    "app.js reads clueItalics, so the ranges the fetchers write are actually rendered");

  const files = fs.readdirSync(path.join(ROOT, "puzzles")).filter((f) => /^\d+\.js$/.test(f));
  let withItalics = 0;
  files.forEach((f) => {
    const text = fs.readFileSync(path.join(ROOT, "puzzles", f), "utf8");
    const puz = JSON.parse(text.slice(text.indexOf("{", text.indexOf("CRYPTIC_PUZZLES[")),
                                      text.lastIndexOf("}") + 1));
    puz.entries.forEach((e) => {
      assert(!/<\/?[a-zA-Z][^>]*>/.test(e.clue),
        `${puz.id} ${e.id}: clue still carries markup — ${e.clue.slice(0, 60)}`);
      (e.clueItalics || []).forEach((r) => {
        withItalics++;
        assert(r[0] >= 0 && r[1] > 0 && r[0] + r[1] <= e.clue.length,
          `${puz.id} ${e.id}: italic range ${r} falls outside its clue`);
      });
    });
  });
  assert(withItalics > 0,
    "the italics survived the flatten — a run that finds none has thrown them away");
}

// --- sync is opt-in, and off means off ---
// Nobody's crossword leaves their browser because they visited the page. The
// only thing that turns it on is pressing the button, and the only thing that
// identifies you afterwards is the code — no email is ever asked for, so none
// can ever leak.
{
  assert(!storage["ct:sync"],
    "sync stays off until it is switched on — no code is minted just by loading the page");
  const src = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
  const page = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  assert(/const SYNC_ENDPOINT = "http/.test(src), "the sync endpoint is configured");
  // Structural, not a search for the words: the page must never grow a field
  // that collects a credential. A password here would protect crossword letters
  // and create something worth stealing, which is the wrong trade in both
  // directions.
  assert(!/type="(password|email)"/.test(page),
    "the page asks for no password and no email — the code is the whole identity");
  assert(/syncOn\(\)/.test(src) && (src.match(/fetch\(/g) || []).length === 1,
    "there is exactly one place that talks to the network, and it is gated on sync being on");

  registry["btn-sync"].onclick();
  assert(!registry["sync-panel"].classList.contains("hidden"), "the sync panel opens");
  assert(registry["sync-off"] && !registry["sync-off"].classList.contains("hidden"),
    "with sync off the panel offers to turn it on");
  registry["sync-start"].onclick();
  const code = storage["ct:sync"] && JSON.parse(storage["ct:sync"]);
  assert(/^[2-9A-HJ-KMNP-TV-Z]{8}$/.test(code || ""),
    `the minted code is 8 characters with no 0/O/1/I/L to mistype: ${code}`);
  // Copying is the only step of sync that happens outside the app, so it is the
  // easiest one to break without noticing: the code is useless until it reaches
  // the other device, and a Copy button that quietly puts nothing on the
  // clipboard looks identical to one that works.
  assert(registry["sync-code"].textContent === code, "the panel shows the code it minted");
  registry["sync-copy"].onclick();
  assert(global.navigator.clipboard.text === code,
    "Copy puts exactly the shown code on the clipboard");

  // Seeded rather than relied on: the reset test just above deliberately clears
  // this puzzle's save, and what is being asserted is that *stopping sync* does
  // not delete grids, not what some earlier test left lying around.
  storage["ct:99999"] = JSON.stringify({ letters: { "0,0": "K" }, updated: 1 });
  registry["sync-stop"].onclick();
  assert(!storage["ct:sync"], "stopping sync forgets the code");
  assert(storage["ct:99999"],
    "stopping sync keeps your grids — it means stop sending them, not throw them away");
  delete storage["ct:99999"];
  registry["btn-sync-close"].onclick();
}

// --- localStorage persistence happened ---
setTimeout(() => {
  // Keyed on the puzzle actually open, not on "ct:3" — that prefix assumed the
  // boot puzzle would always be a 30xxx Guardian daily, and it stopped being one
  // the night the reindex made 1394 the newest (2026-08-12). A test that only
  // passes for one range of puzzle numbers is asserting the wrong thing.
  assert(storage["ct:" + openId], `progress persisted to localStorage under ct:${openId}, got ` +
    JSON.stringify(Object.keys(storage)));
  const saved = JSON.parse(storage[Object.keys(storage).find((k) => /^ct:\d/.test(k))]);
  // Without a timestamp the merge cannot tell two devices apart, so this is
  // written whether or not sync is on — turning it on later must not find a
  // pile of undated saves.
  assert(saved && typeof saved.updated === "number" && saved.updated > 0,
    "every save is timestamped, so it can be merged later even if sync is off today");
  console.log(failures ? `\n${failures} FAILURE(S)` : "\nSMOKE TEST PASSED");
  process.exit(failures ? 1 : 0);
}, 400);
