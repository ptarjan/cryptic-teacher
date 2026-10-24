// appnav.js, the home-screen app's tab bar and back link. Run standalone
// (display-mode: standalone, or iOS's navigator.standalone), every page gets a
// bottom bar of Puzzle · Puzzles · Stats · Learn with its own section lit, the
// Puzzle tab reopens the puzzle in progress (localStorage ct:last), and a page
// reached from another page of the site gets a "‹ Back", or "‹ Puzzle" when
// that page was the app, which is history.back(). In a browser tab, nothing.
// Also: index.html and every templated page load it in <head>, and the hint
// panel's lesson links resolve against the front door, not the address bar.
//
//     node tools/test_app_nav.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "appnav.js"), "utf8");
const ORIGIN = "https://cryptic.paultarjan.com";
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

function run({ page = "/learn/", referrer = "", standalone = true, iosFlag = false, last = "cryptic-30135",
               appFlags = [], app = false, panels = {}, historyLength = 3 } = {}) {
  const backs = [], clicked = [];
  class ClassList {
    constructor() { this.s = new Set(); }
    add(c) { this.s.add(c); }
    remove(c) { this.s.delete(c); }
    contains(c) { return this.s.has(c); }
    toggle(c, on) { if (on === undefined ? !this.s.has(c) : on) this.s.add(c); else this.s.delete(c); }
  }
  class El {
    constructor(tag, id) {
      this.tagName = tag.toUpperCase(); this.id = id || ""; this.children = []; this.attrs = {};
      this.classList = new ClassList(); this.handlers = {}; this.className = ""; this.textContent = "";
      this.innerHTML = ""; this.href = "";
    }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
    removeAttribute(k) { delete this.attrs[k]; }
    hasAttribute(k) { return k in this.attrs; }
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
    insertBefore(c, ref) {
      const i = ref ? this.children.indexOf(ref) : -1;
      if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
      c.parentNode = this; return c;
    }
    get firstChild() { return this.children[0] || null; }
    addEventListener(t, f) { this.handlers[t] = f; }
    querySelectorAll(sel) { return sel === "a" ? this.children.filter((c) => c.tagName === "A") : []; }
    click() { clicked.push(this.id); if (this.onclick) this.onclick(); }
  }
  const html = new El("html"), body = new El("body"), header = new El("header");
  body.appendChild(header);
  const byId = {};
  Object.keys(panels).forEach((id) => {
    const p = new El("div", id); if (!panels[id]) p.classList.add("hidden"); byId[id] = p;
    const btn = new El("button", id === "picker-panel" ? "btn-picker" : "btn-stats");
    btn.onclick = () => p.classList.toggle("hidden");
    byId[btn.id] = btn;
  });
  const script = new El("script");
  script.src = ORIGIN + "/appnav.js?v=abc";
  if (app) script.setAttribute("data-app", "");
  const store = (init) => ({ data: { ...init }, getItem(k) { return k in this.data ? this.data[k] : null; },
    setItem(k, v) { this.data[k] = String(v); } });
  const observers = [];
  const window = {
    navigator: { standalone: iosFlag },
    matchMedia: (q) => ({ matches: standalone && q === "(display-mode: standalone)" }),
    history: { length: historyLength, back: () => backs.push(1) },
    innerHeight: 800, visualViewport: { height: 800, addEventListener() {} },
    scrollTo() {},
    MutationObserver: class { constructor(f) { this.f = f; observers.push(this); } observe() {} },
  };
  const document = {
    documentElement: html, body, head: new El("head"), currentScript: script, referrer, readyState: "complete",
    createElement: (t) => new El(t),
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => (sel === "header" ? header : null),
    addEventListener() {},
  };
  const ctx = {
    window, document, navigator: window.navigator, URL, location: new URL(ORIGIN + page),
    localStorage: store(last ? { "ct:last": JSON.stringify(last) } : {}),
    sessionStorage: store(Object.fromEntries(appFlags.map((id) => [`ct:app:${id}`, "1"]))),
  };
  vm.runInNewContext(SRC, ctx);
  const bar = body.children.find((c) => c.className === "tabbar");
  const tabs = bar ? bar.children : [];
  const tab = (k) => tabs.find((a) => a.getAttribute("data-tab") === k);
  const litNow = () => tabs.filter((a) => a.getAttribute("aria-current") === "page").map((a) => a.getAttribute("data-tab"));
  const back = header.children.find((c) => c.className === "app-back") || null;
  const press = (a) => { let stopped = false; a.handlers.click({ preventDefault: () => { stopped = true; } }); return stopped; };
  return { head: document.head, html, bar, tab, get lit() { return litNow(); }, back, backs, clicked, press, byId, observers };
}

// A browser tab: nothing at all.
{
  const r = run({ standalone: false, referrer: ORIGIN + "/" });
  assert(!r.bar && !r.back && !r.html.classList.contains("standalone"),
    "in a browser tab appnav.js adds no tab bar, no back link and no html.standalone");
}
// iOS's own flag counts as standalone too.
assert(run({ standalone: false, iosFlag: true }).bar, "navigator.standalone (iOS) gets the tab bar");

// The reported case: a hint's "More in the lesson" from the app, at /puzzles/<id>/.
{
  const r = run({ page: "/learn/", referrer: ORIGIN + "/puzzles/cryptic-30135/", appFlags: ["cryptic-30135"] });
  assert(r.html.classList.contains("standalone"), "standalone sets html.standalone");
  assert(r.bar, "/learn/ opened from the app has the tab bar");
  assert(["puzzle", "puzzles", "stats", "learn"].every((k) => r.tab(k)), "the bar has Solve, Library, Stats and Learn");
  assert(JSON.stringify(r.lit) === '["learn"]', `/learn/ lights Learn alone (lit ${JSON.stringify(r.lit)})`);
  assert(r.tab("puzzle").href === ORIGIN + "/?p=cryptic-30135", `the Puzzle tab opens the last puzzle (got ${r.tab("puzzle").href})`);
  assert(r.tab("puzzles").href === ORIGIN + "/#picker" && r.tab("stats").href === ORIGIN + "/#stats",
    "Puzzles and Stats open the app's picker and stats panels");
  assert(r.back && r.back.textContent === "‹ Puzzle", "/learn/ from the app has a ‹ Puzzle back link");
  assert(r.back && r.back.href === ORIGIN + "/?p=cryptic-30135", "the back link's address is the last puzzle");
  assert(r.press(r.back) && r.backs.length === 1, "the back link is history.back(), the app as it was left");
  assert(r.press(r.tab("puzzle")) && r.backs.length === 2, "from the app, the Puzzle tab goes back rather than reloading");
}
// From the app at the site root (?p=) as well.
assert(run({ referrer: ORIGIN + "/?p=times-29671" }).back.textContent === "‹ Puzzle",
  "a page opened from the app at the root has ‹ Puzzle");
// A deep page reached from another static page: ‹ Back, and Puzzle is a link.
{
  const r = run({ page: "/abbreviations/", referrer: ORIGIN + "/learn/" });
  assert(r.back && r.back.textContent === "‹ Back" && r.back.href === ORIGIN + "/learn/",
    "/abbreviations/ from /learn/ has ‹ Back to /learn/");
  assert(JSON.stringify(r.lit) === '["learn"]', "/abbreviations/ lights Learn");
  assert(!r.press(r.tab("puzzle")) && r.backs.length === 0, "not from the app, the Puzzle tab follows its link to the saved puzzle");
}
// A /puzzles/<id>/ write-up the solver did NOT come from the app to.
{
  const r = run({ page: "/puzzles/series/cryptic/", referrer: ORIGIN + "/puzzles/" });
  assert(JSON.stringify(r.lit) === '["puzzles"]', "a series listing lights Puzzles");
  assert(r.back.textContent === "‹ Back", "a listing reached from /puzzles/ says ‹ Back");
}
// Opened cold (a notification, a fresh launch): tabs, no back link.
{
  const r = run({ page: "/puzzles/cryptic-30135/", referrer: "" });
  assert(r.bar && !r.back, "a page with no referrer from this site gets the bar and no back link");
  assert(!run({ referrer: "https://www.google.com/" }).back, "a referrer from another site gets no back link");
  assert(!run({ referrer: ORIGIN + "/learn/", historyLength: 1 }).back, "no back link when there is no history to go back to");
}
// No puzzle yet: Puzzle is the front door.
assert(run({ last: null }).tab("puzzle").href === ORIGIN + "/", "with no ct:last the Puzzle tab opens the site root");

// On the app itself.
{
  const r = run({ page: "/puzzles/cryptic-30135/", app: true, referrer: ORIGIN + "/learn/",
                  panels: { "picker-panel": false, "stats-panel": false } });
  assert(JSON.stringify(r.lit) === '["puzzle"]', "the app lights Puzzle");
  assert(!r.back, "the app has no back link (it is where back leads)");
  assert(r.press(r.tab("stats")) && r.clicked.includes("btn-stats"), "the Stats tab on the app presses the Stats button");
  r.observers.forEach((o) => o.f());
  assert(JSON.stringify(r.lit) === '["stats"]', `an open stats panel lights Stats (lit ${JSON.stringify(r.lit)})`);
  assert(r.press(r.tab("puzzle")) && r.byId["stats-panel"].classList.contains("hidden"),
    "the Puzzle tab on the app closes the open panel");
}

// Every page loads it, in <head>, before the body paints.
{
  const index = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const headPart = index.slice(0, index.indexOf("</head>"));
  assert(/<script src="appnav\.js(\?v=[0-9a-f]+)?" data-app><\/script>/.test(headPart),
    "index.html loads appnav.js with data-app in its <head>");
  const seo = fs.readFileSync(path.join(ROOT, "tools/build_seo_pages.py"), "utf8");
  const n = (seo.match(/<script src="\{asset\("appnav\.js"\)\}"><\/script>/g) || []).length;
  assert(n >= 2, `tools/build_seo_pages.py loads appnav.js in head() and the which-paper page (found ${n})`);
  assert(!/defer|async/.test((seo.match(/.*asset\("appnav\.js"\).*/g) || []).join("")),
    "appnav.js is not deferred: html.standalone must be set before the first paint");
  const appJs = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");
  assert(!/href="learn\//.test(appJs),
    "app.js writes no relative learn/ link: under /puzzles/<id>/ it resolves to /puzzles/<id>/learn/");
}

// Opening as a real app, and feeling like one.
{
  const idx = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const seo = fs.readFileSync(path.join(ROOT, "tools/build_seo_pages.py"), "utf8");
  for (const [name, src] of [["index.html", idx], ["build_seo_pages.py head()", seo]]) {
    assert(/<link rel="manifest" href="[^"]*site\.webmanifest">/.test(src), `${name} links the manifest: a page without one is outside the installed app`);
    assert(/<meta name="apple-mobile-web-app-capable" content="yes">/.test(src), `${name} sets apple-mobile-web-app-capable`);
    assert(/<meta name="mobile-web-app-capable" content="yes">/.test(src), `${name} sets mobile-web-app-capable`);
  }
  const man = JSON.parse(fs.readFileSync(path.join(ROOT, "site.webmanifest"), "utf8"));
  assert(man.display === "standalone" && man.start_url === "./" && man.scope === "./", "manifest is standalone, start_url and scope the site root");
  const css = fs.readFileSync(path.join(ROOT, "style.css"), "utf8");
  assert(/\.tabbar a \{[^}]*touch-action: manipulation/.test(css), "tab links drop the tap delay");
  assert(!/\.tabbar a\.pressed/.test(css) && /\.tabbar a:active[^}]*background: none/.test(css), "tab links have no pressed pill");
  assert(/@view-transition \{ navigation: auto; \}/.test(css), "cross-document view transition is on");
  const r = run({ page: "/", app: true });
  const a = r.tab("puzzle");
  a.handlers.pointerdown({ button: 0, preventDefault() {} });
  a.handlers.click({ preventDefault() {} });
  const app = run({ page: "/learn/" }).head.children.map((c) => c.href).join(" ");
  assert(app.includes(ORIGIN + "/"), "a static page prefetches the app");
  const fromApp = run({ page: "/", app: true }).head.children.map((c) => c.href).join(" ");
  assert(fromApp.includes(ORIGIN + "/learn/"), "the app prefetches Learn");
}

if (fails.length) {
  console.error(fails.map((f) => "FAIL: " + f).join("\n"));
  process.exit(1);
}
console.log("ok: test_app_nav");
