// Fake-DOM smoke test: boots app.js in Node with a minimal DOM stub and exercises
// grid typing, the hint ladder, check/reveal, picker, degradation and persistence.
// Usage: node tools/smoke_test.js
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = require("path").join(__dirname, "..");

let failures = 0;
const assert = (cond, msg) => { if (!cond) { failures++; console.error("FAIL:", msg); } };

class FakeEl {
  constructor(tag, id) {
    this.tagName = (tag || "div").toUpperCase();
    this.id = id || "";
    this.children = [];
    this._innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.style = { setProperty(k, v) { this[k] = String(v); } };
    this.listeners = {};
    this.disabled = false;
    const self = this;
    this.classList = {
      _set: new Set(),
      add(...cs) { cs.forEach((c) => this._set.add(c)); },
      remove(...cs) { cs.forEach((c) => this._set.delete(c)); },
      toggle(c, force) {
        const want = force === undefined ? !this._set.has(c) : !!force;
        want ? this._set.add(c) : this._set.delete(c);
        return want;
      },
      contains(c) { return this._set.has(c); }
    };
  }
  // Setting an id must publish the element, exactly as a real DOM does. Without
  // this, an element built by createElement() was invisible to getElementById(),
  // which then minted a SECOND, empty element under the same id — so app code and
  // test code silently held different objects and every assertion about a
  // dynamically-created element (clue rows, hint buttons) was vacuous.
  set id(v) { this._id = String(v || ""); if (this._id) registry[this._id] = this; }
  get id() { return this._id; }
  set className(v) { this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classList._set].join(" "); }
  set innerHTML(v) { this._innerHTML = String(v); if (v === "") this.children = []; }
  get innerHTML() { return this._innerHTML; }
  appendChild(el) {
    this.children.push(el);
    if (el.tagName === "SCRIPT" && el.onload) {
      // emulate script loading synchronously
      const p = path.join(ROOT, el.src.split("?")[0]); // strip ?v= cache-buster
      new Function("window", fs.readFileSync(p, "utf8"))(global.window);
      el.onload();
    }
    return el;
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  querySelector(sel) {
    const cls = sel.replace(/^\./, "");
    const find = (el) => {
      for (const c of el.children) {
        if (c.classList.contains(cls)) return c;
        const r = find(c);
        if (r) return r;
      }
      return null;
    };
    return find(this) || new FakeEl("span");
  }
  focus() {}
  scrollIntoView() {}
}

const registry = {};
const ids = ["picker-panel","picker-list","picker-search","picker-more","btn-picker","btn-picker-close","btn-tutorial",
  "tutorial","app","puzzle-title","scorebar","grid","kbd","chk-letter","chk-entry","chk-grid",
  "clear-entry","reset-puzzle","clues-across","clues-down","hint-panel","hint-clue","hint-pattern",
  "hint-meter","hint-body","hint-next"];
const inputIds = new Set(["kbd", "picker-search"]);
ids.forEach((id) => { registry[id] = new FakeEl(inputIds.has(id) ? "input" : "div", id); });
registry["app"].classList.add("hidden");
registry["tutorial"].classList.add("hidden");
registry["picker-panel"].classList.add("hidden");

const storage = {};
const docListeners = {};
const document = {
  readyState: "complete",
  head: new FakeEl("head"),
  createElement(tag) {
    const el = new FakeEl(tag);
    Object.defineProperty(el, "onclickCapture", { value: null, writable: true });
    return el;
  },
  getElementById(id) {
    if (!registry[id]) registry[id] = new FakeEl("div", id); // dynamic ids (clue-*, hx-*)
    return registry[id];
  },
  addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); }
};

global.window = {
  localStorage: {
    getItem: (k) => (k in storage ? storage[k] : null),
    setItem: (k, v) => { storage[k] = String(v); },
    removeItem: (k) => { delete storage[k]; }
  }
};
global.document = document;
global.localStorage = global.window.localStorage;
global.confirm = () => true;
// app.js reads ?p=<number> so the static answer pages can hand off into the app.
// Override CT_TEST_QUERY to boot the harness on a specific puzzle.
global.location = { search: process.env.CT_TEST_QUERY || "", href: "", hash: "" };
global.URLSearchParams = URLSearchParams;

// load index + tutorial + app
new Function("window", fs.readFileSync(path.join(ROOT, "puzzles/index.js"), "utf8"))(global.window);
new Function("window", fs.readFileSync(path.join(ROOT, "tutorial.js"), "utf8"))(global.window);
global.CRYPTIC_INDEX = global.window.CRYPTIC_INDEX;

// app.js references bare identifiers window/document/localStorage/confirm via globals above
const appSrc = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
new Function("window", "document", "localStorage", "confirm",
  appSrc)(global.window, document, global.window.localStorage, global.confirm);

// --- cache busting: index.html must reference current asset hashes ---
// (mobile browsers hold GitHub Pages' 4h max-age copies otherwise — STYLE.md)
{
  const crypto = require("crypto");
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  ["style.css", "tutorial.js", "app.js", "puzzles/index.js"].forEach((rel) => {
    const want = crypto.createHash("md5")
      .update(fs.readFileSync(path.join(ROOT, rel))).digest("hex").slice(0, 8);
    assert(html.includes(`${rel}?v=${want}`),
      `index.html has a current ?v= stamp for ${rel} (run tools/stamp_assets.py)`);
  });
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
// The badge marks the exception, not the norm: an annotated puzzle's title
// carries no badge at all (see STYLE.md, "Badge the exception"). So the title
// must agree with the index rather than always saying something.
{
  const idx = (global.CRYPTIC_INDEX.puzzles || []).find((p) => String(p.number) === openId);
  const badged = registry["puzzle-title"].innerHTML.includes("auto hints");
  assert(idx && badged === !idx.annotated,
    "title badge disagrees with the index for " + openId + ": badged=" + badged);
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
  clickBox(0);
  kd(ev(wrongLetter(answer[0])));
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

  const noted = findClue("definitionNote");
  assert(noted, "at least one annotation explains a definition that disagrees with its answer");
  openClue(noted);
  assert(registry["hint-body"].innerHTML.includes("def-note"),
    "the definition note is shown to the learner: " + registry["hint-body"].innerHTML);
}

// --- tutorial toggle ---
registry["btn-tutorial"].onclick();
assert(!registry["tutorial"].classList.contains("hidden"), "tutorial opens");
assert(registry["tutorial"].innerHTML.includes("anagram") || registry["tutorial"].innerHTML.includes("Anagram"), "tutorial content injected");

// --- reset ---
registry["reset-puzzle"].onclick();

// --- localStorage persistence happened ---
setTimeout(() => {
  assert(Object.keys(storage).some((k) => k.startsWith("ct:3")), "progress persisted to localStorage");
  console.log(failures ? `\n${failures} FAILURE(S)` : "\nSMOKE TEST PASSED");
  process.exit(failures ? 1 : 0);
}, 400);
