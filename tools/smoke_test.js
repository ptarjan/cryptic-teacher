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
  set className(v) { this.classList._set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classList._set].join(" "); }
  set innerHTML(v) { this._innerHTML = String(v); if (v === "") this.children = []; }
  get innerHTML() { return this._innerHTML; }
  appendChild(el) {
    this.children.push(el);
    if (el.tagName === "SCRIPT" && el.onload) {
      // emulate script loading synchronously
      const p = path.join(ROOT, el.src);
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
  "clear-entry","reset-puzzle","clues-across","clues-down","hint-panel","hint-clue","hint-meter",
  "hint-body","hint-next"];
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

// --- escape hatch: reveal a letter BEFORE using any ladder hints ---
assert(registry["hint-escape"].innerHTML.includes("Reveal one letter"), "escape hatch offered at level 0");
assert(registry["hx-letter"].onclick, "escape-hatch button wired");
registry["hx-letter"].onclick();
assert(/letters? revealed/.test(registry["scorebar"].innerHTML), "letter reveals counted in score: " + registry["scorebar"].innerHTML);
assert(registry["hint-meter"].innerHTML.includes("1 letter revealed"), "meter shows reveal count: " + registry["hint-meter"].innerHTML);

// --- walk the hint ladder: click the 'next hint' button 5 times ---
for (let i = 1; i <= 5; i++) {
  const btn = registry["hint-next"].children[0];
  assert(btn && btn.onclick, "hint button exists at level " + i);
  if (btn && btn.onclick) btn.onclick();
  assert(registry["hint-body"].innerHTML.includes("hint-step"), "hint body populated at level " + i);
  assert(registry["hint-escape"].innerHTML.includes("Reveal one letter") || registry["hint-meter"].innerHTML.includes("Solved"),
    "escape hatch still available at level " + i);
}
assert(registry["hint-body"].innerHTML.includes("Answer:"), "level 5 shows answer");
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
kd(ev("ArrowDown")); kd(ev("ArrowRight")); kd(ev("Backspace")); kd(ev("Enter"));
assert(registry["scorebar"].innerHTML.includes("Solved"), "scorebar renders: " + registry["scorebar"].innerHTML);
assert(registry["scorebar"].innerHTML.match(/Solved <strong>[1-9]/), "at least one clue solved after reveal+typing");

// --- check buttons ---
registry["chk-grid"].onclick();
registry["chk-entry"].onclick();
registry["chk-letter"].onclick();

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
