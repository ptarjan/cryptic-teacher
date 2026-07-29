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
const ids = ["picker-panel","picker-list","btn-picker","btn-picker-close","btn-tutorial",
  "tutorial","app","puzzle-title","scorebar","grid","kbd","chk-letter","chk-entry","chk-grid",
  "clear-entry","reset-puzzle","clues-across","clues-down","hint-panel","hint-clue","hint-pattern",
  "hint-meter","hint-body","hint-next"];
ids.forEach((id) => { registry[id] = new FakeEl(id === "kbd" ? "input" : "div", id); });
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
assert(registry["puzzle-title"].innerHTML.includes("30,06"), "a flagship puzzle opened: " + registry["puzzle-title"].innerHTML);
assert(registry["grid"].children.length === 225, "grid has 225 cells, got " + registry["grid"].children.length);
const lightCells = registry["grid"].children.filter((c) => !c.classList.contains("block"));
assert(lightCells.length > 150, "light cells present: " + lightCells.length);
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
kd(ev("Tab"));          // next entry
"COLOGNE".split("").forEach((ch) => kd(ev(ch)));
// the pattern strip is live: it now shows the typed letters, all in place
{
  const boxes = patBoxes();
  assert(boxes.length === 7, "pattern strip follows the 7-letter entry: " + boxes.length);
  assert(patHTML().includes("7 of 7 letters in place"), "pattern counts typed letters: " + patHTML());
  assert(/data-i="6"/.test(patHTML()), "boxes carry their index so they can be clicked: " + patHTML());
}
// --- clicking a pattern box moves the cursor; typing skips filled squares ---
{
  const clickBox = (i) => registry["hint-pattern"].listeners.click[0]({ target: { dataset: { i: String(i) } } });
  const curIndex = () => patBoxes().findIndex((b) => b.includes("cur"));
  assert(registry["hint-pattern"].listeners.click, "pattern strip has a click handler");
  clickBox(4);
  assert(curIndex() === 4, "clicking a pattern box moves the cursor there, got " + curIndex());
  kd(ev("Delete"));                       // punch a single gap at index 4
  assert(patHTML().includes("6 of 7 letters in place"), "gap cleared: " + patHTML());
  clickBox(0);
  kd(ev("Z"));                            // overwrite index 0 ...
  assert(curIndex() === 4, "typing skips filled squares to the next gap, got " + curIndex());
  kd(ev("Z"));                            // ... and with no gap left it just steps on
  assert(patHTML().includes("7 of 7 letters in place"), "grid refilled: " + patHTML());
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

  registry["chk-entry"].onclick();   // this entry currently holds mistyped Z's
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

// --- picker ---
registry["btn-picker"].onclick();
assert(registry["picker-list"].children.length >= 25, "picker lists all puzzles");
const pickerHTML = registry["picker-list"].children.map((li) => li.children[0].innerHTML).join("");
assert(pickerHTML.includes("full hints") && pickerHTML.includes("auto hints"), "both badges present");

// --- open an un-annotated puzzle (auto hints degradation) ---
const autoBtn = registry["picker-list"].children.find((li) => li.children[0].innerHTML.includes("auto hints")).children[0];
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
    registry["btn-picker"].onclick();
    const li = registry["picker-list"].children.find((x) => x.children[0].innerHTML.includes("№ " + id));
    assert(li, `picker lists puzzle ${id}`);
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
