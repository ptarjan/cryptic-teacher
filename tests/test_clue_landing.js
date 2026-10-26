// landing.js marks the clue a search visitor came for on a /puzzles/<id>/
// answers page and offers the rest of the crossword with hints under it:
// found by Google's text-fragment scroll (fresh navigation from a search
// engine, page already scrolled, no input yet) or by a #12-across anchor, and
// left alone otherwise. Its two beacons are on sync/events.js's list, its
// endpoint is app.js's, and every puzzle page loads it with its id.
//
//     node tests/test_clue_landing.js
"use strict";
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "landing.js"), "utf8");
const EVENTS = require("../sync/events.js");
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

// Three clues stacked 300px apart; the viewport is 800 tall.
function run({ referrer = "https://www.google.com/", scrollY = 0, hash = "", navType = "navigate",
               touch = false, internal = false } = {}) {
  const sent = [], gtagged = [], listeners = {};
  class El {
    constructor(tag, id, top) {
      this.tagName = tag.toUpperCase(); this.id = id || ""; this.children = []; this.attrs = {};
      this.className = ""; this.top = top; this.textContent = ""; this.handlers = {};
    }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
    insertBefore(c, ref) {
      const i = ref ? this.children.indexOf(ref) : -1;
      if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
      return c;
    }
    get firstChild() { return this.children[0]; }
    get nextSibling() { const s = this.parentNode.children; return s[s.indexOf(this) + 1] || null; }
    querySelector(sel) { return sel === "h3 + p" ? this.children[1] : null; }
    addEventListener(t, f) { this.handlers[t] = f; }
    getBoundingClientRect() { return { top: this.top - scrollY, bottom: this.top - scrollY + 250 }; }
    text() { return this.textContent + this.children.map((c) => c.text ? c.text() : c.data).join(""); }
  }
  const arts = ["1-across", "5-across", "3-down"].map((id, i) => {
    const a = new El("article", id, 600 + i * 300);
    a.appendChild(new El("h3")); a.appendChild(new El("p")); a.appendChild(new El("p"));
    a.children.forEach((c) => { c.parentNode = a; });
    return a;
  });
  const script = new El("script"); script.setAttribute("data-p", "everyman-4172");
  const window = {
    scrollY, innerHeight: 800,
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    gtag: (_e, name) => gtagged.push(name),
  };
  const document = {
    currentScript: script, referrer, readyState: "complete",
    querySelector: () => null,
    querySelectorAll: (sel) => (sel === ".s-list article[id]" ? arts : []),
    getElementById: (id) => arts.find((a) => a.id === id) || null,
    createElement: (t) => new El(t),
    createTextNode: (data) => ({ data }),
  };
  const sandbox = {
    window, document,
    location: { hash },
    navigator: { sendBeacon: (url, blob) => { sent.push([url, blob.parts.join("")]); return true; } },
    localStorage: { getItem: (k) => (internal && k === "ct-internal" ? "1" : null) },
    performance: { getEntriesByType: () => [{ type: navType }] },
    Blob: class { constructor(parts) { this.parts = parts; } },
    URL, setTimeout: (f) => f(), Infinity, Math, Array, encodeURIComponent, decodeURIComponent,
  };
  if (touch) {
    // the reader's own input arrives before the delayed check
    sandbox.setTimeout = (f) => { (listeners.wheel || []).forEach((g) => g()); f(); };
  }
  new Function(...Object.keys(sandbox), SRC)(...Object.values(sandbox));
  const landed = arts.filter((a) => a.getAttribute("data-landed"));
  const hint = landed.length && landed[0].children.find((c) => c.className === "s-hint");
  return { arts, landed, hint, sent, gtagged };
}

// Text fragment from Google: page scrolled so 5-across (900..1150) spans the middle (scrollY 600 -> mid at 1000).
{
  const r = run({ scrollY: 600 });
  assert(r.landed.length === 1 && r.landed[0].id === "5-across", "fragment scroll marks the clue across the viewport middle: " + r.landed.map((a) => a.id));
  assert(r.landed[0] && r.landed[0].className.includes("s-landed"), "the marked clue carries s-landed");
  assert(r.landed[0] && r.landed[0].children[2] === r.hint, "the hint line sits straight under the clue text");
  const link = r.hint && r.hint.children.find((c) => c.tagName === "A");
  assert(link && link.href === "../../?p=everyman-4172&c=5A", "the line opens the solver on this clue: " + (link && link.href));
  assert(r.hint && / · /.test(r.hint.text()), "the line uses the site's ' · ' separator: " + (r.hint && r.hint.text()));
  assert(r.sent.length === 1 && r.sent[0][1] === "clue-landed" && /\/e$/.test(r.sent[0][0]), "a landing sends clue-landed: " + JSON.stringify(r.sent));
  assert(r.gtagged.join() === "clue_landed", "and tells GA: " + r.gtagged);
  link && link.handlers.click();
  assert(r.sent.map((s) => s[1]).join() === "clue-landed,clue-hint", "following the line sends clue-hint: " + JSON.stringify(r.sent));
}
// A #3-down anchor marks that clue whatever the referrer.
{
  const r = run({ referrer: "", hash: "#3-down" });
  assert(r.landed.length === 1 && r.landed[0].id === "3-down", "a per-clue anchor marks its clue");
}
// Left alone: no search referrer, not scrolled, a reload, the reader's own scroll, a junk hash.
for (const [why, opts] of [
  ["arrived from elsewhere", { referrer: "https://example.com/", scrollY: 600 }],
  ["not scrolled (no fragment)", { scrollY: 0 }],
  ["a reload restoring the reader's scroll", { scrollY: 600, navType: "reload" }],
  ["the reader scrolled first", { scrollY: 600, touch: true }],
  ["a hash that is not a clue", { referrer: "", hash: "#main" }],
]) {
  const r = run(opts);
  assert(r.landed.length === 0 && r.sent.length === 0, `nothing marked or sent when ${why}`);
}
// The owner's own browser is marked but not counted.
{
  const r = run({ scrollY: 600, internal: true });
  assert(r.landed.length === 1 && r.sent.length === 0 && r.gtagged.length === 0, "ct-internal browsers send nothing");
}

// The contract: names on the shared list, the same Worker as app.js.
for (const n of [...SRC.matchAll(/beacon\("([^"]+)"\)/g)].map((m) => m[1]))
  assert(EVENTS.indexOf(n) >= 0, `landing.js reports "${n}", which is not on sync/events.js's list`);
const app = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
const ep = (s) => (s.match(/SYNC_ENDPOINT = "([^"]+)"/) || [])[1];
assert(ep(app) && ep(app) === ep(SRC), `landing.js posts to app.js's SYNC_ENDPOINT: ${ep(SRC)} vs ${ep(app)}`);

// Every puzzle page loads it, with its id.
const page = execFileSync("python3", ["-c", `
import build_seo_pages as B
puz = {"id": "everyman-4172", "series": "everyman", "number": 4172, "setter": None, "date": "2026-10-04",
       "name": "x", "entries": [], "dimensions": {"cols": 15, "rows": 15}}
print(B.puzzle_page(puz, None, None, None))
`], { env: { ...process.env, PYTHONPATH: path.join(ROOT, "tools") }, encoding: "utf8" });
assert(/<script src="[^"]*landing\.js\?v=[^"]*" data-p="everyman-4172" defer><\/script>/.test(page),
  "a puzzle page loads stamped landing.js with its id");

if (fails.length) { console.error(fails.join("\n")); process.exit(1); }
console.log("ok");
