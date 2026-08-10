// The fake DOM that boots app.js under Node, shared by every harness that needs
// to see what a learner sees.
//
// This lived inside smoke_test.js until tools/make_hint_packets.js needed the same
// thing. Copying it would have been the obvious move and the wrong one: the point
// of booting the real app.js is that the harness cannot drift from the app, and
// two stubs drift from EACH OTHER as well. The hint ladder is built per clue by
// ladderSteps() in app.js and nowhere else — any re-derivation in Python or in a
// second stub is a guess about what the app shows, and a grader marking a guess
// is worse than no grader.
//
//   const { boot } = require("./fake_dom.js");
//   const dom = boot({ query: "?p=30078" });
//   dom.registry["hint-body"].innerHTML
//
// Each boot() is independent: its own registry, its own localStorage, its own
// FakeEl class closing over that registry. Call it once per puzzle. It does reassign
// the Node globals app.js reads (window/document/localStorage/confirm/location),
// so booting a second time invalidates the first — hold one at a time.
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..");

function boot(opts) {
  const options = opts || {};
  const registry = {};

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
      const hit = find(this);
      if (hit) return hit;
      // This DOM does not build children out of innerHTML, so a span written by
      // the page's own markup string is never found above. Hand back a stable
      // stand-in per selector rather than a fresh throwaway: the app writes into
      // these (clue text, checking dots), and a test can only assert on what was
      // written if the same object comes back on the next lookup.
      this._qs = this._qs || {};
      return (this._qs[sel] = this._qs[sel] || new FakeEl("span"));
    }
    focus() {}
    scrollIntoView() {}
  }

  // The stub's elements are read out of index.html rather than retyped here.
  // The hand-kept version of this list was three lists really — which ids
  // exist, which are inputs, and which start hidden — and all three had to be
  // updated by hand whenever the page grew a control. Miss the third and the
  // symptom is baffling: a panel the page ships closed is open in the harness,
  // so the first click closes it and every assertion after that is upside down
  // (Paul, sync panel, 2026-08-10). Parsed, a new control is simply present,
  // in the state the page actually ships it in.
  {
    const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
    const tags = /<([a-zA-Z]+)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;
    let m;
    while ((m = tags.exec(html)) !== null) {
      const attrs = m[2];
      const id = attrs.match(/\sid="([^"]+)"/);
      if (!id) continue;
      const el = new FakeEl(m[1].toLowerCase(), id[1]);
      const cls = attrs.match(/\sclass="([^"]*)"/);
      if (cls) el.className = cls[1];
      registry[id[1]] = el;
    }
  }

  const storage = {};
  const docListeners = {};
  // index.html's <link rel="canonical">, stood up so the ?p= rewrite is testable.
  // Read out of the shipped file rather than retyped, so the harness cannot be
  // testing a canonical the site does not actually have.
  const canonicalLink = new FakeEl("link");
  canonicalLink.href = (fs.readFileSync(path.join(ROOT, "index.html"), "utf8")
    .match(/<link rel="canonical" href="([^"]+)"/) || [])[1] || "";
  const document = {
    readyState: "complete",
    head: new FakeEl("head"),
    querySelector(sel) {
      return sel === 'link[rel="canonical"]' ? canonicalLink : null;
    },
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
      removeItem: (k) => { delete storage[k]; },
      // Sync has to enumerate every saved puzzle to build the envelope it
      // uploads, so the stub needs the iteration half of the Storage API too —
      // without it the whole sync path is unreachable from the smoke test,
      // which is exactly the path that must not break silently.
      get length() { return Object.keys(storage).length; },
      key(i) { const ks = Object.keys(storage); return i < ks.length ? ks[i] : null; }
    }
  };
  global.document = document;
  // The sync panel's Copy button is the only way most people will move the code
  // to their other device. Without a clipboard here the harness can only reach
  // the "your browser won't let me" branch, which is the branch nobody uses.
  const clipboard = {
    text: null,
    writeText(v) { clipboard.text = String(v); return Promise.resolve(); }
  };
  // defineProperty, not assignment: Node 22 ships its own read-only global
  // navigator, and a plain `global.navigator = …` throws.
  Object.defineProperty(global, "navigator", {
    value: { clipboard }, writable: true, configurable: true
  });
  global.localStorage = global.window.localStorage;
  global.confirm = () => true;
  // app.js reads ?p=<number> so the static answer pages can hand off into the app.
  // Override CT_TEST_QUERY to boot the harness on a specific puzzle.
  global.location = { search: options.query || process.env.CT_TEST_QUERY || "", href: "", hash: "" };
  global.URLSearchParams = URLSearchParams;

  // load index + tutorial + app
  new Function("window", fs.readFileSync(path.join(ROOT, "puzzles/index.js"), "utf8"))(global.window);
  new Function("window", fs.readFileSync(path.join(ROOT, "tutorial.js"), "utf8"))(global.window);
  global.CRYPTIC_INDEX = global.window.CRYPTIC_INDEX;

  // app.js references bare identifiers window/document/localStorage/confirm via globals above
  const appSrc = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
  new Function("window", "document", "localStorage", "confirm",
    appSrc)(global.window, document, global.window.localStorage, global.confirm);

  // appSrc goes back out because the smoke test greps app.js's own source for the
  // FAMILIES table — an assertion about the code, not about the rendered DOM.
  return { registry, document, storage, docListeners, canonicalLink, FakeEl, appSrc, window: global.window };
}

module.exports = { boot, ROOT };
