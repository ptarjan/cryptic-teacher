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

// Puzzle ids carry their series ("cryptic-30089"); the picker shows the plain
// number, which is what a person types and what the row says. One conversion,
// used everywhere this test drives the picker.
const numberOf = (id) => (((global.CRYPTIC_INDEX || {}).puzzles || [])
  .find((p) => p.id === id) || { number: id }).number;

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

// --- the solver's abbreviation glossary is the clue-writer's, not a copy ---
// abbreviations.js is generated from tools/data/abbreviations.json so that the
// table the hints teach and the table clueability.py builds words from cannot
// disagree. Compared as data rather than as text: the generator is free to
// change how it formats, and only a real difference in what "sailor" means
// should fail.
{
  const json = JSON.parse(
    fs.readFileSync(path.join(ROOT, "tools/data/abbreviations.json"), "utf8")).abbreviations;
  const js = fs.readFileSync(path.join(ROOT, "abbreviations.js"), "utf8");
  const table = new Function(js + "\n return ABBREVIATIONS;")();
  assert(JSON.stringify(table) === JSON.stringify(Object.fromEntries(
    Object.keys(table).sort().map((k) => [k, json[k]]))),
    "abbreviations.js matches tools/data/abbreviations.json (run tools/build_abbreviations.py)");
  assert(Object.keys(table).length === Object.keys(json).length,
    "abbreviations.js has every entry the JSON does (run tools/build_abbreviations.py)");

  // And the glossary the solver can READ is the same table again. It used to be
  // a hand-picked "starter set" of two dozen pairs, which is how the blocks rung
  // could say CH was check while the tutorial had never heard of it (Paul,
  // 2026-08-22). Generated between markers now, so a new convention reaches the
  // page the solver is sent to as well as the one the hint quotes from.
  const tut = fs.readFileSync(path.join(ROOT, "tutorial.js"), "utf8");
  assert(tut.includes('<h3 id="abbreviations">'),
    "the tutorial's glossary carries the anchor the hint links to");
  const senses = new Set();
  Object.values(json).forEach((words) => words.forEach((w) => senses.add(w)));

  // Each row has its own id, because a hint links to the one convention it just
  // named rather than to the top of four hundred rows (Paul, 2026-08-22: "it
  // should link right to that clue"). The slug is computed here the same way
  // app.js and build_abbreviations.py compute it, so a rule that drifts in one
  // of the three fails rather than silently producing dead links.
  const anchor = (w) => "abbr-" + w.toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const page = fs.readFileSync(path.join(ROOT, "abbreviations/index.html"), "utf8");
  [["the tutorial", tut], ["the /abbreviations/ page", page]].forEach(([what, src]) => {
    const missing = [...senses].filter((w) => !src.includes(`<td id="${anchor(w)}">${w}</td>`));
    assert(missing.length === 0,
      `every sense in the JSON is in ${what}, anchored (run tools/build_abbreviations.py `
        + `then tools/build_seo_pages.py) — missing ${missing.length}, e.g. `
        + missing.slice(0, 3).join(", "));
  });

  // The glossary is on one indexable URL, not two competing for the same query:
  // /learn/ links to it instead of repeating the table.
  const learn = fs.readFileSync(path.join(ROOT, "learn/index.html"), "utf8");
  assert(!learn.includes('<table class="glossary">'),
    "/learn/ points at /abbreviations/ rather than duplicating the table");
  assert(learn.includes("/cryptic-teacher/abbreviations/"),
    "/learn/ links to the standalone glossary");
}

// --- traffic measurement: one beacon, on every page ---
{
  // The app and the generated pages carry the same analytics tag, taken from
  // BEACON in tools/build_seo_pages.py. Measuring only the static pages would
  // count arrivals and miss every solve; measuring only the app would lose the
  // search traffic the static pages exist for. Once per page, because a page
  // with two beacons double-counts itself.
  const beacon = fs.readFileSync(path.join(ROOT, "tools/build_seo_pages.py"), "utf8")
    .match(/cf-beacon=.*"token": "([0-9a-f]{16,})"/);
  assert(beacon, "tools/build_seo_pages.py defines a BEACON with a cf-beacon token");
  const tag = beacon ? beacon[1] : "no-token";
  ["index.html", "learn/index.html", "abbreviations/index.html"].forEach((rel) => {
    const n = fs.readFileSync(path.join(ROOT, rel), "utf8").split(tag).length - 1;
    assert(n === 1,
      `${rel} carries the analytics beacon exactly once (found ${n}; run `
        + "tools/build_seo_pages.py, and edit index.html to match BEACON)");
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
// The title shows the NUMBER — that is what a solver reads — so the id comes
// back out of the index rather than off the screen. They stopped being the
// same string on 2026-08-19, when ids grew their series.
const openNumber = (openTitle.match(/No ([\d,]+)/) || [, ""])[1].replace(/,/g, "");
const openId = ((global.CRYPTIC_INDEX.puzzles || [])
  .find((p) => String(p.number) === openNumber) || {}).id;
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
  const want = (meta && meta.hasSolutions) ? `${home}puzzles/${meta.id}/` : home;
  assert(canonicalLink.href === want,
    `canonical should be ${want}, got ${canonicalLink.href}`);
}

// The badge marks the exception, not the norm: an annotated puzzle's title
// carries no badge at all (see STYLE.md, "Badge the exception"). So the title
// must agree with the index rather than always saying something.
{
  const idx = (global.CRYPTIC_INDEX.puzzles || []).find((p) => p.id === openId);
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
  // Counted spans once; it now wraps each word of the enumeration in one, so the
  // rule is stated as what it always meant: the only text a sighted solver reads
  // here is letters and the odd hyphen or apostrophe between words.
  assert(/^[A-Z’\-]*$/.test(patHTML().replace(/<[^>]*>/g, "")),
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

// Taking a rung is two clicks now: three of them ask you to point at the words
// before they name them, so the button poses the question and "Just tell me"
// answers it. Everything below walks the ladder the lazy way on purpose — the
// guessing itself is tested at the end, on its own.
function takeRung(btn) {
  btn.onclick();
  if (registry["hint-body"].innerHTML.includes("guess-clue")) registry["guess-tell"].onclick();
}

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
  takeRung(last);
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
  takeRung(registry["hint-next"].children[0]);
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
  // The hint buttons are the other half: they don't move the cursor, but tapping
  // anything that isn't the input blurs it, the keyboard leaving is a viewport
  // change, and the page reflows just as the new rung lands — so the hint reads
  // as flashing open and shut ("clicking hints sometimes triggers them quickly
  // open then closed", Paul, iPhone, 2026-08-16). Listed with the cursor
  // controls so a new tappable thing in the panel cannot forget it.
  ["grid", "hint-pattern", "hint-next", "hint-escape"].forEach((id) =>
    assert(registry[id].listeners.mousedown,
      `${id} keeps the keyboard on mousedown, not after its own re-render`));

  // A finger that moved across the grid is scrolling, not tapping — and the move
  // guard used to bail out BEFORE preventDefault. preventDefault on touchend is
  // the only thing stopping iOS synthesising a mousedown afterwards, and this
  // same cell listens to mousedown, so a drag skipped the tap handler and was
  // then selected by the mouse handler it had just dodged. The guard has to
  // cancel first and decide second.
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
// --- every row says which day of the week it is (Paul, 2026-08-16) ---
// A Guardian week has a shape — Monday gentle, the Saturday prize hard — so the
// weekday is a difficulty cue, not trim. Two things have to hold and neither is
// checkable by eye across 85 rows: the day must AGREE with the date next to it
// (it is derived, so a timezone slip is the way it goes wrong, and a row reading
// "Sat 2026-08-16" when that was a Sunday is worse than no day at all), and
// typing the day's name must find those rows, or the label is a filter that
// lies about being one.
{
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const seen = {};
  pickerRows().forEach((li) => {
    const m = li.children[0].innerHTML.match(/<span class="p-meta">(\w{3}) (\d{4}-\d{2}-\d{2})</);
    assert(m, "every picker row carries a weekday and a date: "
      + (li.children[0].innerHTML.match(/p-meta">[^<]*/) || ["(none)"])[0]);
    const want = DAYS[new Date(m[2] + "T00:00:00Z").getUTCDay()];
    assert(m[1] === want, `${m[2]} was a ${want}, not a ${m[1]}`);
    seen[want] = (seen[want] || 0) + 1;
  });
  const day = Object.keys(seen).sort((a, b) => seen[b] - seen[a])[0];
  const full = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    .find((d) => d.startsWith(day));
  typeInPicker(full.toLowerCase());
  const hits = pickerRows();
  assert(hits.length >= seen[day],
    `searching "${full.toLowerCase()}" finds its ${seen[day]} row(s), got ${hits.length}`);
  assert(hits.every((li) => new RegExp(`p-meta">${day} `).test(li.children[0].innerHTML)),
    `and finds nothing else: ` + hits.map((li) =>
      (li.children[0].innerHTML.match(/p-meta">[^<]*/) || [""])[0]).join(" | "));
  typeInPicker("");
}
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

// --- picking a puzzle rewrites the address bar, because that is what gets shared ---
// A link has to hand over the puzzle on the screen. Left alone, the URL still
// says whatever the page booted on: the bare site root, which drops the reader
// on last night's puzzle, or a stale ?p= from the link they followed, which is
// worse because it looks deliberate. The canonical follows, so a shared ?p=
// still credits the static write-up that says the same things without JS.
{
  const urls = global.window.history.urls;
  // The clue ref is appended once the grid settles on a clue, so what has to
  // hold is that the URL names this puzzle and nothing else — asserting the
  // whole string would break every time the address bar learns to carry one
  // more thing about what is on screen.
  assert(new RegExp(`^\\?p=${autoPuzzle.id}(&c=\\d+[AD])?$`).test(urls[urls.length - 1]),
    `opening No ${autoPuzzle.number} should leave ?p=${autoPuzzle.id} in the address bar, `
      + `got ${JSON.stringify(urls)}`);
  // And the clue really does get named, so "look at 3 down" is a link.
  assert(/&c=\d+[AD]$/.test(urls[urls.length - 1]),
    `the address bar should name the selected clue too, got ${urls[urls.length - 1]}`);
  const want = `https://paultarjan.com/cryptic-teacher/puzzles/${autoPuzzle.id}/`;
  assert(canonicalLink.href === want,
    `canonical should follow the opened puzzle to ${want}, got ${canonicalLink.href}`);
  // And the front door stays the front door. Booting on the remembered puzzle is
  // not a choice anybody made, so a bare /cryptic-teacher/ must not rewrite
  // itself — a homepage declaring a puzzle as its canonical is the 2026-08-07
  // de-indexing bug pointed the other way.
  if (!new URLSearchParams(global.location.search).get("p")) {
    assert(urls.length && urls.every((u) => u !== ""),
      "the boot open must not touch the URL when nothing asked for a puzzle");
  }
}

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
    // Searched by NUMBER, which is what the picker shows and what a person
    // types; `id` carries the series and never appears on screen.
    const num = ((global.CRYPTIC_INDEX.puzzles || [])
      .find((p) => p.id === id) || {}).number;
    registry["btn-picker"].onclick();
    typeInPicker(String(num));
    const li = registry["picker-list"].children.find((x) => x.children[0] && x.children[0].innerHTML.includes("№ " + num));
    assert(li, `picker finds puzzle ${id} when searched for`);
    li.children[0].onclick();
    const row = registry["clue-" + e.id];
    assert(row && row.listeners.click, `clue list shows ${e.number}${e.direction[0]}: ${e.clue}`);
    row.listeners.click[0]();
    // rung 1 = family, rung 2 = definition, which is where both fields hang
    takeRung(registry["hint-next"].children[0]);
    takeRung(registry["hint-next"].children[0]);
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
    takeRung(btn);
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
        takeRung(btn);
        const bare = registry["hint-body"].innerHTML.replace(/[^A-Za-z]/g, "").toUpperCase();
        assert(!bare.includes(ans),
          `${where}: a rung before the walkthrough spells the answer out — ` +
          registry["hint-body"].innerHTML);
      }
      const btn = registry["hint-next"].children[0];
      assert(btn && /walkthrough/i.test(btn.textContent || ""),
        `${where}: the ladder still ends at the walkthrough, got ` +
        ((btn && btn.textContent) || "nothing"));
      takeRung(btn);
      assert(registry["hint-body"].innerHTML.includes("Answer:"),
        `${where}: the walkthrough is where the answer finally appears`);
    }
  }

  // --- a rung's name may ask its question, never answer it ---
  // The names of the rungs you have NOT bought are on screen the whole time —
  // that is how you choose one. So a name that varies with the clue type is a
  // free hint: the &lit definition rung was called "How can the whole clue be
  // the definition?", and on a semi-&lit hidden word that button, unbought,
  // was the entire solve ("21d gives away the whole thing just by the name of
  // the hint before I reveal it" — Paul, 4096 21d, VSIGN, 2026-08-17). Same
  // for "Where does the clue split?", "What is the clue really describing?",
  // "What each half means", and the singular/plural indicator label, which
  // handed over how many indicators there were.
  //
  // Checked as an invariant rather than as five strings: across every
  // annotated clue in the corpus, a rung key has exactly ONE name. Any future
  // branch that phrases a label for its type fails here whatever it says.
  {
    // Read off the buttons themselves rather than off any internal list: what
    // is being checked is precisely what a solver can see without paying.
    const names = new Map();   // label -> first clue that showed it
    const seenTypes = new Set();

    // Riding along on the same sweep: once every rung is bought, every fragment
    // the annotation named must be VISIBLY marked in the clue, on whole words.
    // Both halves were broken and reported as one thing — a highlight that had
    // been paid for not being there ("I think it might always be the indicator
    // clue which is disappearing after click", and then on the walkthrough too,
    // Paul, 2026-08-17). The cause was indexOf(): 'in' matched inside
    // "Conclud(in)g", "island", "confusion" on 18 clues, and on 15 the wrong
    // position landed under the definition, where the old overlap rule deleted
    // whichever mark came second — always the indicator, since indicators were
    // pushed last. So buying the definition took an earlier hint off the screen.
    //
    // Checked off the rendered HTML, because that is the thing the solver looks
    // at, and over the whole corpus, because the failures were spread thin: two
    // clues a puzzle, always the small function words a validator would never
    // think to doubt.
    const unesc = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
    // The clue as (text, class) runs, adjacent runs of one class joined, with
    // the setter's italics dropped — they cut the string for their own reasons
    // and a mark split by one is still a mark.
    const runs = (html) => {
      const out = [];
      // The line starts with the entry's own tag ("12A"), which is not clue text.
      html = html.replace(/^\s*<span class="entry-tag">[\s\S]*?<\/span>/, "");
      const re = /<mark class="([a-z0-9]+)">([\s\S]*?)<\/mark>|<[^>]*>|([^<]+)/g;
      let m;
      while ((m = re.exec(html)) !== null) {
        if (m[1] === undefined && m[3] === undefined) continue;      // any other tag
        const cls = m[1] === undefined ? "" : m[1];
        const text = unesc((m[1] === undefined ? m[3] : m[2]).replace(/<\/?i>/g, ""));
        if (out.length && out[out.length - 1].cls === cls) out[out.length - 1].text += text;
        else out.push({ cls, text });
      }
      return out;
    };
    const checkMarks = (id, e) => {
      const ann = e.annotation;
      if (ann.linkedTo) return;                     // renders its holder's text
      const rs = runs(registry["hint-clue"].innerHTML);
      const plain = rs.map((r) => r.text).join("");
      assert(plain === e.clue,
        `${id} ${e.id}: the marked-up clue is no longer the clue: ${JSON.stringify(plain)}`);
      let at = 0;
      const spans = rs.map((r) => { const i = at; at += r.text.length; return { ...r, i }; });
      const isLetter = (c) => !!c && /[A-Za-z]/.test(c);
      const whole = (i, len) =>
        !(isLetter(e.clue[i]) && isLetter(e.clue[i - 1])) &&
        !(isLetter(e.clue[i + len - 1]) && isLetter(e.clue[i + len]));
      // Every character of a mark's span, in clue coordinates.
      const covered = {};
      for (const s of spans) {
        if (!s.cls) continue;
        for (let k = 0; k < s.text.length; k++) (covered[s.cls] = covered[s.cls] || new Set()).add(s.i + k);
      }
      const anyMarked = new Set([].concat(...Object.values(covered).map((v) => [...v])));
      for (const frag of ann.indicators || []) {
        if (!frag || !e.clue.includes(frag)) continue;
        // An indicator is short and specific, so shortest-first guarantees it
        // wins any overlap outright: it must appear whole, in its own colour,
        // on a whole word.
        let ok = false;
        for (let i = e.clue.indexOf(frag); i >= 0 && !ok; i = e.clue.indexOf(frag, i + 1)) {
          if (!whole(i, frag.length)) continue;
          ok = [...Array(frag.length).keys()].every((k) => (covered.ind || new Set()).has(i + k));
        }
        assert(ok,
          `${id} ${e.id}: ${JSON.stringify(frag)} was bought as an indicator but is not ` +
          `marked on a whole word of the clue — a hint that has been paid for cannot ` +
          `leave the screen: ` + registry["hint-clue"].innerHTML);
      }
      // The definition may legitimately be interrupted — an &lit's indicator sits
      // inside it — so what is required of it is that none of it goes unmarked.
      const def = ann.definition;
      if (def && e.clue.includes(def)) {
        const at = e.clue.indexOf(def);
        const gap = [...Array(def.length).keys()].filter((k) => !anyMarked.has(at + k));
        assert(!gap.length || spans.some((s) => s.cls === "def"),
          `${id} ${e.id}: the definition is not marked at all: ` + registry["hint-clue"].innerHTML);
      }
    };
    const openPuzzle = (id) => {
      registry["btn-picker"].onclick();
      typeInPicker(String(numberOf(id)));
      const li = registry["picker-list"].children.find(
        (x) => x.children[0] && x.children[0].innerHTML.includes("№ " + numberOf(id)));
      assert(li, `picker finds puzzle ${id}`);
      li.children[0].onclick();
    };
    for (const id of Object.keys(puzzles).sort()) {
      const withAnn = (puzzles[id].entries || []).filter((e) => e.annotation);
      if (!withAnn.length) continue;
      openPuzzle(id);
      for (const e of withAnn) {
        const row = registry["clue-" + e.id];
        if (!row || !row.listeners.click) continue;
        seenTypes.add(e.annotation.type);
        row.listeners.click[0]();
        for (let i = 0; i < 9; i++) {
          const btns = registry["hint-next"].children.filter((b) => b.onclick);
          if (!btns.length) break;
          for (const b of btns) {
            const m = /^(?:Show hint )?\d+ · (.*)$/.exec(b.textContent || "");
            if (m && !names.has(m[1])) names.set(m[1], `${id} ${e.id} (${e.annotation.type})`);
          }
          takeRung(btns[0]);
        }
        checkMarks(id, e);
      }
    }
    assert(seenTypes.size > 20, "the sweep saw the corpus's variety of types: " + seenTypes.size);
    // Six rungs exist, so six names exist. A seventh means a branch phrased a
    // label for its clue type, whatever the wording turned out to be.
    const LADDER = ["What kind of clue is this?", "Where is the definition?",
      "Spot the indicator words", "The building blocks", "Full walkthrough"];
    const extra = [...names].filter(([n]) => !LADDER.includes(n));
    assert(!extra.length,
      "a rung is named differently depending on the clue, so its button leaks the " +
      "type before it is bought: " +
      extra.map(([n, where]) => `${JSON.stringify(n)} — ${where}`).join("; "));
  }

  // --- the indicator rung says why THAT word indicates ---
  // "The indicator didn't explain why stable no was an indicator" (Paul, 4096
  // 20a RENOVATOR, 2026-08-17) — the rung named the words and then gave the
  // sentence it gives every anagram in the corpus. `indicatorNotes` is the part
  // that is only true of this clue, so it has to be on the screen the moment it
  // exists in the file; a field that is written and never rendered is worse than
  // no field, because the backlog says the work is done.
  {
    const noted = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const n = ((e.annotation || {}).indicatorNotes) || null;
        if (n && Object.keys(n).length) noted.push({ id, e, n });
      }
    }
    assert(noted.length, "some clue in the corpus explains its indicators");
    for (const s of noted.slice(0, 25)) {
      openClue(s);
      const btn = registry["hint-next"].children.find(
        (b) => b.onclick && /indicator/i.test(b.textContent) && !b.disabled);
      assert(btn, `${s.id} ${s.e.id}: the indicators rung is offered`);
      if (!btn) continue;
      takeRung(btn);
      const html = registry["hint-body"].innerHTML;
      for (const [ind, note] of Object.entries(s.n)) {
        assert(html.includes(note.replace(/&/g, "&amp;").replace(/'/g, "&#39;")),
          `${s.id} ${s.e.id}: the note for ${JSON.stringify(ind)} never reaches the ` +
          `indicators rung: ` + html);
      }
      // And when every indicator is explained, the explanations are the whole
      // rung. Structural rather than a list of banned phrases, so a new piece of
      // generic wording cannot slip past by not being on the list: "this is just
      // context free, never just put out text for the sake of filling space"
      // (Paul, 2026-08-17). Anything the clue type alone could have written is
      // filler beside a sentence about this clue.
      const inds = (s.e.annotation.indicators || []);
      if (inds.length && inds.every((i) => s.n[i])) {
        const rung = (html.split('<div class="hint-step">')
          .find((sec) => sec.includes("Spot the indicator words")) || "")
          .replace(/<\/div>[\s\S]*$/, "");
        const rest = rung
          .replace(/<span class="step-label">[^<]*<\/span>/, "")
          .replace(/<ul class="ind-notes">[\s\S]*?<\/ul>/, "").trim();
        assert(!rest, `${s.id} ${s.e.id}: every indicator has a note, so the rung ` +
          `should be those notes and nothing else — also found: ` + rest);
      }
    }
  }

  // --- a homophone must show you the word you say aloud ---
  // "24d in 4096 doesn't explain that the original word is hoard but it is a
  // homophone and you drop the h to it. Don't just fix one clue extrapolate"
  // (Paul, 2026-08-17). The blocks rung read “Cockney mob” → OARED and stopped:
  // HORDE, the dropped aitch and the sound itself all happened off-screen, and
  // 18 of the corpus's 48 sound clues did the same. The sounded form is now a
  // tracked field rather than a sentence somebody might remember to write, so
  // drive every sound clue there is and check it reaches the page.
  {
    const sound = [];
    for (const id of Object.keys(puzzles).sort()) {
      for (const e of puzzles[id].entries || []) {
        const t = ((e.annotation || {}).type || "");
        if (/homophone|spoonerism/.test(t)) sound.push({ id, e });
      }
    }
    assert(sound.length > 20, "the corpus still has sound clues to check: " + sound.length);
    for (const s of sound) {
      const heard = (s.e.annotation.blocks || []).filter((b) => b.soundsLike);
      assert(heard.length,
        `${s.id} ${s.e.id}: type ${s.e.annotation.type} but no block says what is said aloud`);
      openClue(s);
      // Climb until the blocks rung has been bought.
      let html = "";
      for (let i = 0; i < 8; i++) {
        const btn = registry["hint-next"].children[0];
        if (!btn || !btn.onclick || !/^Show hint/.test(btn.textContent || "")) break;
        takeRung(btn);
        html = registry["hint-body"].innerHTML;
        if (html.includes("said aloud")) break;
      }
      // Escaped the way app.js escapes it: "I'D A" reaches the page as I&#39;D A.
      const esc = (t) => String(t).replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
      for (const b of heard) {
        assert(html.includes(esc(b.soundsLike)),
          `${s.id} ${s.e.id}: the blocks rung never shows ${b.soundsLike}, ` +
          `which is the whole mechanism — ` + html);
      }
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
  typeInPicker(String(numberOf(withInd.id)));
  registry["picker-list"].children
    .find((x) => x.children[0] && x.children[0].innerHTML.includes("№ " + numberOf(withInd.id)))
    .children[0].onclick();
  registry["clue-" + withInd.e.id].listeners.click[0]();
  const indBtn = registry["hint-next"].children.find((b) => /indicator/i.test(b.textContent) && !b.disabled);
  assert(indBtn, "the indicators rung is offered from cold: " + registry["hint-next"].innerHTML);
  takeRung(indBtn);
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
      takeRung(registry["hint-next"].children[0]);
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
  const after = JSON.parse(storage[Object.keys(storage).find((k) => /^ct:[a-z]+-\d+$/.test(k))] || "{}");
  assert(after.clearedAt > 0 && Object.keys(after.letters || {}).length === 0,
    "resetting records when it happened, so the reset itself can reach the other device");
}

// --- picking a clue scrolls once, and lands in the same place every time ---
// On an iPad in portrait the grid and the hint panel cannot both be on screen,
// so picking a clue has to bring the panel to you. scrollIntoView("nearest")
// did it in two goes: one tap moved a little and the next moved the rest (Paul,
// 2026-08-16), because it measured before the panel had relaid out and because
// "least you can move from here" makes the same tap land somewhere different
// depending on where you were. The fix is an absolute target, so the property to
// hold is idempotence: after one tap the panel is fully on screen, and tapping
// again does not move the page at all.
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

  // --- and it lands above the keyboard, not behind it (Paul, iPad, 2026-08-16) ---
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

  // --- and it gets there in one move, not three (Paul, iPhone, 2026-08-16) ---
  // The real sequence: the tap is handled while the keyboard is still sliding up,
  // so a placement made then is measured against a screen that is about to lose
  // its bottom third. Placing anyway and correcting on every resize is what
  // "scrolls down then back up a bit then wiggles" was — each correction started a
  // smooth scroll over one still in flight, and on a phone Safari's URL bar
  // collapsing under that scroll fires another resize and feeds the loop. So the
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

  // --- a keyboard that has not started yet is not a viewport that has settled ---
  // "Down then up a little" (Paul, iOS, 2026-08-21). Waiting for the band to hold
  // still can only measure silence, and at the instant of the tap the band has
  // been silent forever — so the placement went ahead against the whole screen
  // and the late look below had to walk it back once the keys landed. Two moves,
  // every time, on the commonest tap there is.
  //
  // Tapping a clue focuses the typing input, and on a touch device that raises a
  // keyboard, so silence there means "nothing has happened yet", not "nothing
  // will". The wait is for the thing that is owed.
  drain();                               // drain the look left over from the tap above
  vv.height = 1000; vv.offsetTop = 0;
  win.pageYOffset = 0; win.scrolls.length = 0;
  clues[0].listeners.click[0]();
  global.flushTimers(100);
  assert(win.scrolls.length === 0,
    "nothing is placed while a keyboard is still owed: " + JSON.stringify(win.scrolls));
  vv.raiseKeyboard(400);                 // the keys, later than any settle would wait
  global.flushTimers(100);
  assert(win.scrolls.length === 1 && inBand(),
    "and when they land it is ONE move, straight above them: "
      + JSON.stringify(panel.getBoundingClientRect()) + " band 0.." + vv.height);
  drain();
  assert(win.scrolls.length === 1,
    "with nothing left to correct the late look costs nothing: " + JSON.stringify(win.scrolls));

  // --- and the late look is still there for the keyboard that never resizes ---
  // A hardware keyboard, or an iOS that says nothing at all: the wait cannot be
  // unbounded, so the deadline places anyway, and the one late look is what
  // catches keys that arrive after it. Whether it lands must not depend on
  // whether the keyboard beat us — that was "worked for some but not others".
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
  // "Clicking 3d with all the hints open scrolls down then up then down then up
  // then down" (Paul, iPad, 2026-08-17). The late look above had been allowed to
  // re-arm after it fired, on the reasoning that a keyboard arriving in stages
  // moves the band twice. It does — but so does our own smooth scroll, because
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

  // --- a tap on the clue you are already on is still a tap (Paul, 2026-08-20) ---
  // 1-across is selected before the solver has touched anything, so the very first
  // tap of a puzzle lands on the entry that is already current — and while this
  // fired only when the SELECTED ENTRY CHANGED, that one tap did nothing at all:
  // the clue stayed off the bottom of the screen with the keyboard drawn over
  // where it would have been. Every test above picks a NEW clue, which is why it
  // survived all of them. The property is about the tap, not about the change.
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
    const activeId = () =>
      (clues.find((r) => r.classList.contains("active")) || {}).id;
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
    // cursor is running across — tapping the same square again flips it.
    if (!/across/.test(activeId() || "")) tapCell(kids[i]);
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

  // --- and nothing else is allowed to scroll instead of us (Paul, iPhone) ---
  // Everything above is wasted if the browser scrolls somewhere else afterwards,
  // and it will: iOS brings the focused element into view when the keyboard
  // opens, and the app focuses a 1px invisible input to raise it. Parked in the
  // document at the top of the grid, that input dragged the page back up there
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

  // --- and reading a hint must not change the keyboard either way (Paul, iPad) ---
  // A keyboard arriving is as big a viewport change as a keyboard leaving, and
  // both of them reflow the page under the rung that has just appeared. The first
  // half of this was fixed by focusing the hidden input on mousedown so a tap
  // could not dismiss the keyboard ("clicking hints sometimes triggers them
  // quickly open then closed", iPhone, 2026-08-16) — which then SUMMONED one for
  // anyone whose keyboard was down, and produced the identical symptom from the
  // other direction: "I just clicked a hint once on my iPad and it opened then
  // quickly closed" (iPad, 2026-08-17).
  //
  // So the property is steadiness, not focus: whatever the keyboard was doing
  // when the finger landed, it is still doing after. Asserted in both states,
  // because a fix for either one alone is what caused the other. The controls
  // that DO steer the cursor (the grid, the letter strip) are the opposite case
  // and are checked to still raise it — a rule of "never focus on mousedown"
  // would pass the first two assertions and leave you typing with no keyboard.
  const kbd = registry["kbd"];
  const down = (id) => (registry[id].listeners.mousedown || []).forEach((f) => f());
  for (const id of ["hint-next", "hint-escape"]) {
    document.activeElement = null;
    down(id);
    assert(document.activeElement === null,
      `${id}: tapping a hint with the keyboard down must not summon it — the ` +
      `viewport change is what flashes the rung shut`);
    kbd.focus();
    down(id);
    assert(document.activeElement === kbd,
      `${id}: tapping a hint mid-answer must not put the keyboard away either`);
  }
  for (const id of ["grid", "hint-pattern"]) {
    document.activeElement = null;
    down(id);
    assert(document.activeElement === kbd,
      `${id}: this one moves the cursor, so it must raise the keyboard to type with`);
  }
  document.activeElement = null;
}

// --- solving a clue opens its whole ladder, for free (Paul, 2026-08-16) ---
// The tiers exist to stop a walkthrough being taken cold. Once the answer is in
// the grid there is nothing left to give away, so every rung opens — and opening
// them must not cost anything, or the unlock is a trap that quietly turns
// "solved with no hints" into "solved with five". Both halves are asserted:
// unlock without the free reading is worse than leaving it locked.
{
  const taught = allPuzzles.find((p) => p.annotated && p.hasSolutions
    && global.window.CRYPTIC_PUZZLES[p.id]);
  registry["btn-picker"].onclick();
  typeInPicker(String(taught.number));
  pickerRows().find((li) => li.children[0]
    && li.children[0].innerHTML.includes("№ " + taught.number)).children[0].onclick();
  registry["reset-puzzle"].onclick();

  // An entry that is nobody's linked leg, so solving it really does solve the
  // group the hints belong to.
  let solo = null;
  for (let i = 0; i < 40 && !solo; i++) {
    kd(ev("Tab"));
    const e = currentEntry();
    if (e && e.solution && !(e.annotation && e.annotation.linkedTo)
      && !openPuz.entries.some((g) => g.annotation && g.annotation.linkedTo === e.id)) solo = e;
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
  assert(!buttons.some((b) => /^Show hint /.test(b.textContent)),
    "a solved clue's rungs are the explanation, not hints to spend: "
      + buttons.map((b) => b.textContent).join(" | "));

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

  const files = fs.readdirSync(path.join(ROOT, "puzzles")).filter((f) => /^[a-z]+-\d+\.js$/.test(f));
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

// --- the letter strip shows where the words break ---
// The enumeration is the solver's best structural clue and the grid cannot show
// it, so the strip does (Paul, 2026-08-16). A gap in the wrong place is worse
// than no gap at all, so the parser is exercised directly and then checked
// against every answer in the corpus: wherever it claims a division, the answer
// really does break there.
{
  const src = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
  const from = src.indexOf("const ENUM_SEPS");
  const to = src.indexOf("\n  }", src.indexOf("function enumBreaks")) + 4;
  assert(from > 0 && to > from, "enumBreaks is still in app.js to be tested");
  const enumBreaks = new Function(src.slice(from, to) + "\n  return enumBreaks;")();
  // Letters per word. An apostrophe break is dropped: it is drawn in the strip
  // but it does not start a new word, so DON'T is one four-square word either way.
  const shape = (clue, n) => {
    const b = enumBreaks(clue, n);
    if (!b) return null;
    const cuts = Object.keys(b).filter((k) => b[k] !== "’").map(Number).sort((x, y) => x - y);
    if (!cuts.length) return null;
    return cuts.map((c, i) => c - (i ? cuts[i - 1] : 0)).concat(n - cuts[cuts.length - 1]);
  };
  assert(String(shape("Actor in a boat (3,6)", 9)) === "3,6", "a comma is a word break");
  assert(String(shape("Left out (3-5)", 8)) === "3,5", "a hyphen breaks too");
  assert(shape("Plain one (9)", 9) === null, "one word gets no divisions at all");
  // The whole group's enumeration sits on the first leg of a linked clue, so it
  // must not be drawn over that leg's squares alone.
  assert(shape("Split across two (5,4)", 5) === null, "a total that misses the entry is ignored");
  assert(shape("Vague (two words)", 9) === null, "prose in the brackets is not an enumeration");
  assert(String(shape("Feed typo (6.6)", 12)) === "6,6", "a period where a comma was meant");

  fs.readdirSync(path.join(ROOT, "puzzles")).filter((f) => /^[a-z]+-\d+\.js$/.test(f)).forEach((f) => {
    const text = fs.readFileSync(path.join(ROOT, "puzzles", f), "utf8");
    const puz = JSON.parse(text.slice(text.indexOf("{", text.indexOf("CRYPTIC_PUZZLES[")),
                                      text.lastIndexOf("}") + 1));
    puz.entries.forEach((e) => {
      const ans = e.annotation && e.annotation.answer;
      const drawn = shape(e.clue, e.length);
      if (!ans || !drawn) return;
      // An apostrophe occupies no square, and the Guardian counts HOW'S as four
      // — so it is taken out of both sides rather than compared. An enumeration
      // may legitimately divide an answer that is written solid, (1,1,1) for
      // I.C.I., so only answers that really are several words are compared.
      const real = ans.replace(/['’]/g, "").split(/[ \-–]/).filter(Boolean).map((w) => w.length);
      if (real.length < 2) return;
      assert(String(drawn) === String(real),
        `${puz.id} ${e.id}: strip would break ${drawn} but ${ans} breaks ${real}`);
    });
  });

  // --- and it shrinks to fit rather than stacking one word per line ---
  // Fourteen boxes at full size are wider than a phone, and flexbox moves a whole
  // word to the next line rather than shrinking anything, so (3,8,3) came out as
  // three almost-empty rows (Paul, iPhone, 2026-08-16). CSS cannot count letters,
  // so the strip publishes its own shape and the stylesheet does the arithmetic.
  // Both halves are pinned here because either alone is silently useless: markup
  // with nothing reading it, or a rule sizing off a variable nobody sets.
  const css = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  const strip = registry["hint-pattern"].innerHTML;
  const n = /--n:\s*(\d+)/.exec(strip), w = /--w:\s*(\d+)/.exec(strip);
  assert(n && w, "the letter strip publishes --n and --w for the stylesheet: " + strip.slice(0, 120));
  const words = (strip.match(/class="pat-word /g) || []).length;   // the trailing space skips the last, unbroken one
  assert(Number(w[1]) === words,
    `--w counts the word breaks actually drawn: ${w[1]} vs ${words}`);
  // Both patterns keep their trailing space: without it "pat-box" also matches
  // the "pat-boxes" wrapper and every count here is one too many.
  assert(Number(n[1]) === (strip.match(/class="pat-box /g) || []).length,
    `--n counts the boxes actually drawn: ${n[1]}`);
  assert(/\.pat-box[^{]*\{[^}]*100cqw[^}]*var\(--n/.test(css.replace(/\/\*[\s\S]*?\*\//g, "")),
    "and .pat-box sizes itself off --n against the container width");
  assert(/\.pattern[^{]*\{[^}]*container-type:\s*inline-size/.test(css),
    "which needs .pattern to be the query container, or 100cqw is the viewport");
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
// On the REAL clock, never the fake one: this timer ends the process, and a
// test further down that drains the fake clock generously would otherwise fire
// it and stop the suite mid-file — printing a pass for the tests that had run
// and saying nothing about the ones that never did.
global.realSetTimeout(() => {
  // Keyed on the puzzle actually open, not on "ct:3" — that prefix assumed the
  // boot puzzle would always be a 30xxx Guardian daily, and it stopped being one
  // the night the reindex made 1394 the newest (2026-08-12). A test that only
  // passes for one range of puzzle numbers is asserting the wrong thing.
  assert(storage["ct:" + openId], `progress persisted to localStorage under ct:${openId}, got ` +
    JSON.stringify(Object.keys(storage)));
  const saved = JSON.parse(storage[Object.keys(storage).find((k) => /^ct:[a-z]+-\d/.test(k))]);
  // Without a timestamp the merge cannot tell two devices apart, so this is
  // written whether or not sync is on — turning it on later must not find a
  // pile of undated saves.
  assert(saved && typeof saved.updated === "number" && saved.updated > 0,
    "every save is timestamped, so it can be merged later even if sync is off today");
  console.log(failures ? `\n${failures} FAILURE(S)` : "\nSMOKE TEST PASSED");
  process.exit(failures ? 1 : 0);
}, 400);

// --- finishing the grid is an event, not a number going up (Paul, 2026-08-17) ---
// "There should be some celebration when you complete." Two properties, and the
// second is what keeps it from being noise: it fires on the TRANSITION, in the
// session that earned it, so re-opening a puzzle you finished last week throws
// no paper at you. And what it says is the scoreline — clues, unaided solves,
// hints spent, minutes — because that is the part a solver cannot see anywhere
// else once the grid is full.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const id = Object.keys(puzzles).sort().find((k) =>
    (puzzles[k].entries || []).every((e) => e.solution));
  assert(id, "some puzzle in the corpus ships every solution");
  const open = () => {
    registry["btn-picker"].onclick();
    typeInPicker(String(numberOf(id)));
    registry["picker-list"].children
      .find((x) => x.children[0] && x.children[0].innerHTML.includes("\u2116 " + numberOf(id)))
      .children[0].onclick();
  };
  open();
  const box = registry["celebrate"];
  assert(box.classList.contains("hidden"), "nothing is celebrated on opening a fresh grid");

  const puz = puzzles[id];
  const cols = puz.dimensions.cols;
  const cellAt = (x, y) => registry["grid"].children[y * cols + x];
  const squares = new Set();
  const walk = (e, f) => {
    for (let i = 0; i < e.length; i++) {
      f(e.direction === "across" ? e.position.x + i : e.position.x,
        e.direction === "across" ? e.position.y : e.position.y + i, i);
    }
  };
  puz.entries.forEach((e) => walk(e, (x, y) => squares.add(x + "," + y)));

  // Filled square by square, the way a solver does it, so the moment of
  // completion is the moment the LAST light square gets its letter — which is
  // somewhere in the middle of an entry, not at the end of a loop.
  const filled = new Set();
  let fired = 0;
  for (const e of puz.entries) {
    walk(e, (x, y, i) => {
      const k = x + "," + y;
      if (filled.has(k)) return;
      cellAt(x, y).listeners.mousedown[0]({ preventDefault() {} });
      kd(ev(e.solution[i]));
      filled.add(k);
      const done = filled.size === squares.size;
      if (!box.classList.contains("hidden")) fired++;
      assert(box.classList.contains("hidden") !== done,
        done ? "the last light square in the grid is celebrated: " + box.innerHTML
             : `the grid is ${squares.size - filled.size} squares short and it celebrated anyway`);
    });
  }
  assert(fired === 1, "and celebrated once, not on every keystroke after: " + fired);
  assert(/\d+<\/strong> clues/.test(box.innerHTML) && /hint/.test(box.innerHTML),
    "and it says what was achieved, not just that something was: " + box.innerHTML);
  registry["celebrate-done"].onclick();
  assert(box.classList.contains("hidden"), "and it can be dismissed");
  // Re-opening the finished puzzle: still solved, nothing earned. The save is
  // debounced, so it has to be flushed first — without that the reopened grid
  // comes back empty and this assertion passes for the wrong reason, which is
  // exactly what it did on the first run.
  global.flushTimers(200);
  open();
  assert(/Solved <strong>(\d+)\/\1<\/strong>/.test(registry["scorebar"].innerHTML),
    "the reopened puzzle really is the finished one: " + registry["scorebar"].innerHTML);
  assert(box.classList.contains("hidden"),
    "re-opening a puzzle you already finished celebrates nothing: " + box.innerHTML);
}

// --- point at the words before the rung names them ---
// Three rungs ask first and tell second. Two things have to hold and they pull
// apart: the rung must still arrive whatever you answer (this is a lesson, not
// a gate), and answering it correctly must actually cost nothing, or the
// discount is decoration.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  // A clue whose definition is the opening words of the clue, so the test can
  // name the right buttons without owning a second copy of the matcher.
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const def = e.annotation && e.annotation.definition;
      if (!def || !e.clue.startsWith(def)) continue;
      // Whole words, and one definition: a double definition asks for both
      // halves at once and the opening words are then only part of the answer.
      if (e.annotation.definition2 || !/\s/.test(e.clue[def.length] || "")) continue;
      const words = def.trim().split(/\s+/).length;
      // Not the whole clue: guessAsk refuses a question whose answer is
      // everything, and rightly.
      if (words >= e.clue.replace(/\s*\([^()]*\)\s*$/, "").split(/\s+/).length) continue;
      found = { id, e, words };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue defines with its opening words");

  const openIt = () => {
    registry["btn-picker"].onclick();
    typeInPicker(String(puzzles[found.id].number));
    const li = registry["picker-list"].children.find(
      (x) => x.children[0] && x.children[0].innerHTML.includes("№ " + puzzles[found.id].number));
    assert(li, "picker finds the puzzle to guess on");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + found.e.id].listeners.click[0]();
  };
  const defBtn = () => registry["hint-next"].children.find(
    (b) => /definition/i.test(b.textContent || "") && !b.disabled);

  openIt();
  const btn = defBtn();
  assert(btn, "the definition rung is offered: " + registry["hint-next"].innerHTML);
  btn.onclick();
  let html = registry["hint-body"].innerHTML;
  assert(html.includes("guess-clue"), "the definition rung asks before it tells: " + html);
  assert(!html.includes("hint-step\"><span class=\"step-label\">2 ·"),
    "the rung is not handed over while the question is still open: " + html);
  assert(!registry["hint-clue"].innerHTML.includes('mark class="def"'),
    "nor is the answer given away by the highlight: " + registry["hint-clue"].innerHTML);
  assert(registry["hint-next"].innerHTML === "",
    "the other rungs are not offered as a way around the question: " + registry["hint-next"].innerHTML);

  // Right: exactly the words, nothing else.
  for (let i = 0; i < found.words; i++) registry["gw-" + i].onclick();
  registry["guess-check"].onclick();
  html = registry["hint-body"].innerHTML;
  // The verdict lands on the words as well as in a sentence: "3 of 5" never says
  // WHICH three, and which three is the lesson.
  assert(html.includes("guess-verdict right"), "a correct guess is told so: " + html);
  assert((html.match(/class="gw on hit"/g) || []).length === found.words,
    `every word of a right answer is marked right on the clue itself: ${html}`);
  assert(!/class="gw[^"]*(spare|missed)"/.test(html),
    "and nothing is marked wrong: " + html);
  // The marked clue is not an animation, and the rung is not on a delay. Both
  // arrive on the tap and both are still there afterwards: "it flashes too fast
  // for me to read" (Paul, 2026-08-21) was a reading deadline nobody asked for.
  assert(html.includes("hint-step"), "the rung opens on the same tap: " + html);
  assert(!/id="gw-\d+"/.test(html),
    "and the graded words stop being buttons rather than stopping taps: " + html);
  global.flushTimers(10000);
  assert(registry["hint-body"].innerHTML === html,
    "nothing is on a timer: the verdict and its marked clue stay put: "
      + registry["hint-body"].innerHTML);
  assert(registry["hint-clue"].innerHTML.includes('mark class="def"'),
    "the definition is highlighted once the rung is up");
  assert(/\b0<\/strong> hint levels used/.test(registry["scorebar"].innerHTML),
    "a rung you earned costs nothing: " + registry["scorebar"].innerHTML);

  // Wrong: every word in the clue is never the answer to any of these.
  openIt();
  defBtn().onclick();
  const words = (registry["hint-body"].innerHTML.match(/id="gw-\d+"/g) || []).length;
  assert(words > found.words, "the clue offers more words than the definition uses");
  for (let i = 0; i < words; i++) registry["gw-" + i].onclick();
  registry["guess-check"].onclick();
  html = registry["hint-body"].innerHTML;
  assert(html.includes("guess-verdict miss"), "a wrong guess is told so: " + html);
  assert((html.match(/class="gw on hit"/g) || []).length === found.words &&
         /class="gw on spare"/.test(html),
    `the words that were doing the job are told apart from the ones that weren't: ${html}`);
  assert(html.includes("hint-step"), "and the rung still opens — never a gate: " + html);
  global.flushTimers(10000);
  assert(registry["hint-body"].innerHTML === html,
    "a miss is left on screen to be read too: " + registry["hint-body"].innerHTML);
  assert(/\b1<\/strong> hint levels used/.test(registry["scorebar"].innerHTML),
    "a rung you did not earn still costs one: " + registry["scorebar"].innerHTML);

  // And the escape hatch out of the question itself.
  openIt();
  defBtn().onclick();
  assert(registry["hint-body"].innerHTML.includes("guess-clue"), "asked again");
  registry["guess-tell"].onclick();
  assert(registry["hint-body"].innerHTML.includes("hint-step"), "“Just tell me” tells you");
  assert(!registry["hint-body"].innerHTML.includes("guess-verdict"),
    "declining to guess is not graded");
  assert(/\b1<\/strong> hint levels used/.test(registry["scorebar"].innerHTML),
    "and costs what the rung has always cost: " + registry["scorebar"].innerHTML);
}

// --- the blocks rung walks every piece, and the panel never takes anything back ---
// "The building blocks made me only pick one of the three pieces" (Paul,
// 2026-08-22). Doing the charade is the hard part, so each piece is its own
// question; a piece placed becomes settled scaffolding for the next. The
// sequence stops of its own accord when what is left IS the last piece, which is
// answerable by elimination and therefore not worth asking.
//
// And, same screen: opening a new hint used to delete the previous verdict and
// empty the rung buttons, so the panel collapsed under the solver at the moment
// a new question appeared below — "it jumps and switches to something else".
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const escHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const tokensOf = (clue) => {
    const body = String(clue || "").replace(/\s*\([^()]*\)\s*$/, "");
    const out = [];
    const re = /\S+/g;
    let m;
    while ((m = re.exec(body))) out.push({ i: m.index, text: m[0] });
    return out;
  };
  // The test only takes on fragments it can locate WITHOUT a copy of the app's
  // matcher: exactly one occurrence, on whole-word boundaries. Anything fuzzier
  // is a candidate skipped, not a wrong answer submitted.
  const spanTokens = (clue, frag) => {
    const at = clue.indexOf(frag);
    if (at < 0 || clue.indexOf(frag, at + 1) >= 0) return null;
    const hit = tokensOf(clue).map((t, n) => ({ t, n }))
      .filter(({ t }) => t.i < at + frag.length && at < t.i + t.text.length);
    if (!hit.length) return null;
    const first = hit[0].t, last = hit[hit.length - 1].t;
    if (first.i !== at || last.i + last.text.length !== at + frag.length) return null;
    return hit.map(({ n }) => n);
  };

  const openClue = (id, e) => {
    registry["btn-picker"].onclick();
    typeInPicker(String(puzzles[id].number));
    const li = registry["picker-list"].children.find(
      (x) => x.children[0] && x.children[0].innerHTML.includes("№ " + puzzles[id].number));
    if (!li) return false;
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + e.id].listeners.click[0]();
    return true;
  };
  const rungs = () => registry["hint-next"].children;
  const rung = (re) => rungs().find((b) => re.test(b.textContent || "") && !b.disabled);
  const asking = () => registry["hint-body"].innerHTML.includes('id="guess-check"');
  // Climb to the named rung, taking whatever is offered and declining every
  // question on the way, so the blocks rung is reached with the tier-0 rungs up.
  const climbTo = (re) => {
    for (let i = 0; i < 8; i++) {
      const want = rung(re);
      if (want) return want;
      const b = rungs().find((x) => !x.disabled);
      if (!b) return null;
      b.onclick();
      if (asking()) registry["guess-tell"].onclick();
    }
    return null;
  };
  const pick = (idx) => idx.forEach((n) => registry["gw-" + n].onclick());

  let walked = null, tried = 0;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      if (walked || tried > 30) break;
      const a = e.annotation;
      const bl = ((a && a.blocks) || []).filter((b) => b.clueFragment && b.gives);
      if (bl.length < 2) continue;
      const spans = bl.map((b) => spanTokens(e.clue, b.clueFragment));
      if (spans.slice(0, 2).some((s) => !s)) continue;
      tried++;
      if (!openClue(id, e)) continue;
      const blocks = climbTo(/building blocks/i);
      if (!blocks) continue;
      // Whatever the climb cost is the baseline: the blocks rung must add
      // nothing to it while its own question is still open, and nothing to it at
      // all if every piece asked for is placed right.
      const paid = registry["scorebar"].innerHTML;
      blocks.onclick();
      if (!asking()) continue;
      pick(spans[0]);
      registry["guess-check"].onclick();
      if (!registry["hint-body"].innerHTML.includes("guess-placed")) continue;
      walked = { id, e, bl, spans, paid };
    }
    if (walked) break;
  }
  assert(walked, "somewhere in the corpus the blocks rung asks about a second piece "
    + `(tried ${tried} clues with two or more locatable pieces)`);
  if (!walked) throw new Error("blocks sequencing is broken — see the FAIL above");

  // Mid-sequence: the first piece is placed and named, its words are settled, and
  // the rung has NOT been handed over.
  let html = registry["hint-body"].innerHTML;
  assert(html.includes(escHtml(walked.bl[0].gives)),
    "the piece just placed is named, not just greyed: " + html);
  assert(html.includes(escHtml(walked.bl[1].gives)),
    "and the next piece is what is now being asked for: " + html);
  const placed = html.slice(html.indexOf("guess-placed"));
  walked.spans[0].forEach((n) => assert(!placed.includes(`id="gw-${n}"`),
    `word ${n} was this solver's answer a moment ago and is not offered again: ` + placed));
  assert((placed.match(/class="gw known"/g) || []).length >= walked.spans[0].length,
    "the placed piece is settled scaffolding for the next question: " + placed);
  assert(registry["scorebar"].innerHTML === walked.paid,
    "and nothing has been bought yet — one rung, one price: " + registry["scorebar"].innerHTML);

  // The rest of the sequence, answered right, ends with the rung earned rather
  // than bought. Whether that is after two pieces or all of them is the
  // elimination guard's call, not this test's.
  for (let n = 1; n < walked.bl.length && asking(); n++) {
    const span = walked.spans[n] || spanTokens(walked.e.clue, walked.bl[n].clueFragment);
    if (!span || span.some((i) => !registry["hint-body"].innerHTML.includes(`id="gw-${i}"`))) break;
    pick(span);
    registry["guess-check"].onclick();
  }
  assert(!asking(), "the sequence ends: " + registry["hint-body"].innerHTML);
  html = registry["hint-body"].innerHTML;
  assert(html.includes("guess-verdict right"),
    "placing every piece asked for is getting the rung right: " + html);
  assert(registry["scorebar"].innerHTML === walked.paid,
    "so the whole rung is free: " + registry["scorebar"].innerHTML);

  // --- the panel only ever grows ---
  // A graded verdict on one rung, then a different rung asked for. Both the
  // verdict and the ladder must still be there: deleting either one moves every
  // word on the screen at the moment the solver is being asked to read.
  assert(openClue(walked.id, walked.e), "reopen the clue for the growth check");
  const def = rung(/definition/i);
  assert(def, "the definition rung is offered: " + registry["hint-next"].innerHTML);
  def.onclick();
  assert(asking(), "and asks before telling: " + registry["hint-body"].innerHTML);
  // Deliberately wrong, so there is a verdict to lose. The last word of a clue is
  // never the whole definition of one that starts with it.
  const last = (registry["hint-body"].innerHTML.match(/id="gw-(\d+)"/g) || []).pop();
  registry[last.slice(4, -1)].onclick();
  registry["guess-check"].onclick();
  assert(registry["hint-body"].innerHTML.includes("guess-verdict"), "graded");
  // On to a rung that poses its own question, since that is the moment the old
  // verdict used to be swept away to make room for the new one.
  let before = "";
  for (let i = 0; i < 5 && !asking(); i++) {
    const another = rungs().find((b) => !b.disabled);
    assert(another, "another rung is still on offer: " + rungs().length);
    before = registry["hint-body"].innerHTML;
    another.onclick();
  }
  assert(asking(), "a second question gets asked: " + registry["hint-body"].innerHTML);
  const after = registry["hint-body"].innerHTML;
  assert(after.includes("guess-verdict"),
    "asking for a new hint does not delete the verdict you were reading: " + after);
  assert(after.length >= before.length,
    "the panel only ever grows: " + before.length + " -> " + after.length);
  assert(rungs().length > 0 && rungs().every((b) => b.disabled),
    "and the ladder keeps its shape while the question stands, disabled rather than gone: "
      + registry["hint-next"].innerHTML);
}

// --- a run of words is one gesture, and a settled word is not a choice ---
// Two things Paul asked for on the same screen. Dragging across the words picks
// the run under the finger, because a definition IS a run and four taps is four
// chances to be interrupted. And a word an earlier rung already named cannot be
// offered as an answer to the next one: it is on the screen as fact, so letting
// it be picked means marking someone wrong for reading.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  // Definition at the front, indicators somewhere else, so the test can name the
  // definition's buttons without a second copy of the span matcher.
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      if (!a || !a.definition || a.definition2 || !(a.indicators || []).length) continue;
      if (!e.clue.startsWith(a.definition) || !/\s/.test(e.clue[a.definition.length] || "")) continue;
      const words = a.definition.trim().split(/\s+/).length;
      const all = e.clue.replace(/\s*\([^()]*\)\s*$/, "").split(/\s+/).length;
      // Two words at least, or there is no run to drag across; and never the
      // whole clue, which guessAsk refuses to make a question of.
      if (words < 2 || words >= all) continue;
      if ((a.indicators || []).some((t) => a.definition.includes(t))) continue;
      found = { id, e, words, all };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue opens with a two-word definition and has an indicator");

  const open = () => {
    registry["btn-picker"].onclick();
    typeInPicker(String(puzzles[found.id].number));
    const li = registry["picker-list"].children.find(
      (x) => x.children[0] && x.children[0].innerHTML.includes("№ " + puzzles[found.id].number));
    assert(li, "picker finds the puzzle to drag on");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + found.e.id].listeners.click[0]();
  };
  const rung = (re) => registry["hint-next"].children.find(
    (b) => re.test(b.textContent || "") && !b.disabled);
  const fire = (type, ev) => (docListeners[type] || []).forEach((f) => f(ev));
  // The harness lays the words out one x apart on y=0 — see elementFromPoint.
  const dragAcross = (from, to) => {
    registry["gw-" + from].listeners.pointerdown[0]({});
    fire("pointermove", { clientX: to, clientY: 0 });
    fire("pointerup", {});
  };
  const onNow = () => (registry["hint-body"].innerHTML.match(/class="gw on"/g) || []).length;

  // Drag the definition's run in one gesture.
  open();
  rung(/definition/i).onclick();
  dragAcross(0, found.words - 1);
  assert(onNow() === found.words,
    `a drag picks every word it crossed and no others: ${registry["hint-body"].innerHTML}`);
  assert(!registry["guess-check"].disabled, "and arms the check button");
  registry["guess-check"].onclick();
  assert(registry["hint-body"].innerHTML.includes("guess-verdict right"),
    "so the run can be the whole answer: " + registry["hint-body"].innerHTML);

  // A tap is still a tap: pointerdown and pointerup on the same word must toggle
  // rather than be swallowed as the tail of a drag.
  open();
  rung(/definition/i).onclick();
  registry["gw-0"].listeners.pointerdown[0]({});
  fire("pointermove", { clientX: 0, clientY: 0 });
  fire("pointerup", {});
  registry["gw-0"].onclick();
  assert(onNow() === 1, "a tap that never left the word still toggles it: "
    + registry["hint-body"].innerHTML);

  // Settled words: take the definition, then be asked about the indicators.
  open();
  rung(/definition/i).onclick();
  registry["guess-tell"].onclick();
  const ind = rung(/indicator/i);
  assert(ind, "the indicators rung is offered next: " + registry["hint-next"].innerHTML);
  ind.onclick();
  const html = registry["hint-body"].innerHTML;
  if (html.includes("guess-clue")) {
    const asked = html.slice(html.indexOf("guess-clue"));
    assert((asked.match(/class="gw known"/g) || []).length === found.words,
      "every word the definition rung named is marked as already known: " + asked);
    for (let i = 0; i < found.words; i++) {
      assert(!asked.includes(`id="gw-${i}"`),
        `and word ${i} is not a button to be marked wrong for: ` + asked);
    }
    assert(/id="gw-\d+"/.test(asked), "while the rest of the clue is still in play: " + asked);
  } else {
    // Legitimate: with the definition settled, what was left may BE the answer,
    // and a question answerable by elimination is not asked at all.
    assert(html.includes("hint-step"), "or the question is dropped, not broken: " + html);
  }
}

// --- the spotting rungs spend the type rung (Paul, 2026-08-21) ---
// Once the definition and the indicator are both on screen, "what kind of clue
// is this?" has nothing left to tell anyone, so it must stop gating the assembly
// rung. BY EITHER ROUTE: this ran on earnedRungs first, which is only written by
// a PERFECT guess, so a near miss or a "just tell me" left the turnstile
// standing — hence both routes are walked below and asserted identical.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const spot = ["definition", "indicators"];
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const a = e.annotation;
      if (!a || !(a.indicators || []).length) continue;
      if (!a.definition || !(a.blocks || []).some((b) => b.clueFragment && b.gives)) continue;
      found = { id, e };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue has a definition, an indicator and a named block");

  const open = () => {
    registry["btn-picker"].onclick();
    typeInPicker(String(puzzles[found.id].number));
    const li = registry["picker-list"].children.find(
      (x) => x.children[0] && x.children[0].innerHTML.includes("№ " + puzzles[found.id].number));
    assert(li, "picker finds the puzzle to guess on");
    li.children[0].onclick();
    registry["reset-puzzle"].onclick();
    registry["clue-" + found.e.id].listeners.click[0]();
  };
  const rung = (re) => registry["hint-next"].children.find((b) => re.test(b.textContent || ""));
  // Ladder positions rather than labels: every rung button is "<n> · <label>",
  // and n is the rung's place in this clue's ladder. It is the number Paul reads
  // off the screen, and it means the test never has to know what the assembly
  // rung is called.
  const at = (pred) => registry["hint-next"].children.filter(pred)
    .map((b) => ((b.textContent || "").match(/(\d+) ·/) || [])[1]);
  const locked = () => at((b) => b.disabled);
  const offeredN = () => at(() => true);
  // appendChild does not write innerHTML in the stub, so a failure message built
  // from it says nothing at all. Read the buttons.
  const offered = () => registry["hint-next"].children.map((b) => b.textContent).join(" | ");
  // Which words answer this rung, asked of the app rather than worked out again
  // here: one wrong pick, and the marks that come back name the whole target.
  // A second copy of guessAsk's span arithmetic in the test would only ever
  // prove the copy right.
  const targetOf = (re) => {
    open();
    const b = rung(re);
    if (!b) return null;
    b.onclick();
    if (!registry["hint-body"].innerHTML.includes("guess-clue")) return null;
    registry["gw-0"].onclick();
    registry["guess-check"].onclick();
    const marks = registry["hint-body"].innerHTML.match(/class="gw([^"]*)"/g) || [];
    return marks.reduce((acc, m, i) => (/hit|missed/.test(m) ? acc.concat(i) : acc), []);
  };
  const want = { definition: targetOf(/definition/i), indicators: targetOf(/indicator/i) };
  assert(want.definition && want.indicators,
    "the clue can pose both spotting questions: " + JSON.stringify(want));

  // Cold, the ladder has two locks on it: the assembly rung and the walkthrough.
  open();
  const shut = locked();
  assert(shut.length === 2, "cold, assembly and walkthrough are both locked: " + offered());

  // Take the two spotting rungs, either by pointing at the words or by asking to
  // be told, and report what the ladder looks like afterwards.
  const bothSpotted = (earn) => {
    open();
    for (const k of spot) {
      rung(new RegExp(k.slice(0, 9), "i")).onclick();
      if (!earn) { registry["guess-tell"].onclick(); continue; }
      for (const i of want[k]) registry["gw-" + i].onclick();
      registry["guess-check"].onclick();
      assert(registry["hint-body"].innerHTML.includes("guess-verdict right"),
        `the ${k} rung is earned, not bought: ` + registry["hint-body"].innerHTML);
    }
    return { locked: locked(), offered: offeredN(), score: registry["scorebar"].innerHTML,
             text: offered() };
  };

  for (const earn of [false, true]) {
    const how = earn ? "earned" : "asked for outright";
    const r = bothSpotted(earn);
    assert(r.offered.length === 3,
      `${how}: two rungs taken leaves three on the ladder: ` + r.text);
    assert(r.locked.length === 1 && shut.indexOf(r.locked[0]) >= 0,
      `${how}: exactly one of the two locks opened — the walkthrough keeps its own: `
        + r.text);
    assert(r.offered.indexOf(r.locked[0]) >= 0 && r.offered.length - r.locked.length === 2,
      `${how}: the assembly rung and the type rung are both takeable: ` + r.text);
    assert(new RegExp(`\\b${earn ? 0 : 2}</strong> hint levels used`).test(r.score),
      `${how}: skipping the type rung is free, and changes nothing else's price: `
        + r.score);
  }
}

// --- a clue is a link ---
// ?c=3D opens on that clue, so "which one are you stuck on" is answerable with a
// URL and a first-timer can be handed one clue instead of a whole 15x15. Booted
// fresh, because the ref has to survive openPuzzle rewriting the address bar to
// ?p= on its way in — which is precisely how the first cut of this silently did
// nothing. Last in the file: boot() replaces the globals every earlier test is
// still holding.
{
  const fresh = (q) => require("./fake_dom.js").boot({ query: q });
  const clueOf = (r) => (r.registry["hint-clue"].innerHTML || "").replace(/<[^>]+>/g, "");

  const dflt = clueOf(fresh("?p=cryptic-30066"));
  const asked = fresh("?p=cryptic-30066&c=3D");
  assert(clueOf(asked).startsWith("3D"),
    `?c=3D should open on 3 down, got ${clueOf(asked).slice(0, 40)}`);
  assert(clueOf(asked) !== dflt, "and that is not just where the puzzle opens anyway");

  assert(clueOf(fresh("?p=cryptic-30066&c=17d")).startsWith("17D"),
    "a lower-case ref works, because that is how people retype a link");

  // A link outliving its puzzle must still open the puzzle.
  assert(clueOf(fresh("?p=cryptic-30066&c=nope")) === dflt,
    "an unknown clue ref falls back to the first clue rather than erroring");
}
