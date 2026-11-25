// reader.js, the one gate every count on the site waits on: a page passes on a
// trusted gesture or a few seconds of attention, but only while it is visible
// and focused, and never with an automation tell. And every path that counts
// goes through it: GA's own page_view, app.js's counters and votes, and
// landing.js's beacons, on every page that loads analytics.js.
//
//     node tests/test_reader_gate.js
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "reader.js"), "utf8");
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

// A page with a controllable clock, focus and visibility.
function page({ webdriver = false, ua = "Mozilla/5.0 (Windows NT 10.0) Chrome/131.0", languages = ["en-GB"],
                focused = true, visible = true } = {}) {
  const win = {}, doc = {};
  const on = (o) => (t, f) => { (o[t] = o[t] || []).push(f); };
  const off = (o) => (t, f) => { o[t] = (o[t] || []).filter((g) => g !== f); };
  const state = { focused, visible, now: 0 };
  let timers = [], seq = 0;
  const window = { addEventListener: on(win), removeEventListener: off(win) };
  const document = {
    get visibilityState() { return state.visible ? "visible" : "hidden"; },
    hasFocus: () => state.focused,
    addEventListener: on(doc), removeEventListener: off(doc),
  };
  const setTimeout = (fn, ms) => { const id = ++seq; timers.push({ id, fn, at: state.now + (ms || 0) }); return id; };
  const clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
  new Function("window", "document", "navigator", "setTimeout", "clearTimeout", SRC)(
    window, document, { webdriver, userAgent: ua, languages }, setTimeout, clearTimeout);
  const P = {
    gate: window.CTReader,
    ran: [],
    advance(ms) {
      const end = state.now + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at);
        const t = timers[0];
        if (!t || t.at > end) break;
        timers.shift(); state.now = t.at; t.fn();
      }
      state.now = end;
    },
    fire(type, e) { (win[type] || []).slice().forEach((f) => f(e)); },
    gesture(type = "pointerdown", trusted = true) { P.fire(type, { isTrusted: trusted }); },
    blur() { state.focused = false; P.fire("blur", {}); },
    focus() { state.focused = true; P.fire("focus", {}); },
    hide() { state.visible = false; (doc.visibilitychange || []).slice().forEach((f) => f()); },
    state,
  };
  P.gate.when(() => P.ran.push("a"));
  P.gate.when(() => P.ran.push("b"));
  return P;
}

// A trusted gesture on a focused page passes at once, and the waiting callbacks
// run once each, in the order they asked.
{
  const p = page();
  assert(!p.gate.passed() && p.ran.length === 0, "nothing runs before the page has a reader");
  p.gesture("touchstart");
  assert(p.gate.passed() && p.ran.join() === "a,b", "a trusted touch on a focused page passes: " + p.ran);
  p.gesture("keydown"); p.advance(10000);
  assert(p.ran.join() === "a,b", "and the callbacks run once: " + p.ran);
  p.gate.when(() => p.ran.push("c"));
  assert(p.ran.join() === "a,b,c", "a callback after the gate has passed runs at once");
}
// Script-made events do not count.
{
  const p = page({ focused: false, visible: false });
  p.gesture("pointerdown", false); p.advance(0);
  p.state.focused = true; p.state.visible = true;
  p.gesture("pointerdown", false); p.advance(0);
  assert(!p.gate.passed(), "an untrusted event never passes the gate");
}
// A headless page: trusted input from the driver, but the page never has focus.
{
  const p = page({ focused: false });
  ["pointerdown", "keydown", "wheel", "touchstart"].forEach((t) => p.gesture(t));
  p.advance(60000);
  assert(!p.gate.passed() && p.ran.length === 0, "trusted input on a page that never has focus counts nothing");
}
// A click is what focuses the page: focus that arrives with the gesture counts.
{
  const p = page({ focused: false });
  p.gesture("pointerdown"); p.state.focused = true; p.advance(0);
  assert(p.gate.passed(), "a gesture that focuses the page passes once its default action has run");
}
// Hidden pages do not count either.
{
  const p = page({ visible: false });
  p.gesture(); p.advance(60000);
  assert(!p.gate.passed(), "a hidden page never passes");
}
// The reader who reads without touching: continuous attention for the dwell.
{
  const p = page();
  p.advance(2999);
  assert(!p.gate.passed(), "under three seconds of attention is not yet a reader");
  p.advance(1);
  assert(p.gate.passed() && p.ran.join() === "a,b", "three seconds of focused, visible attention passes");
}
{
  const p = page();
  p.advance(2000); p.blur(); p.advance(5000);
  assert(!p.gate.passed(), "losing focus stops the clock");
  p.focus(); p.advance(2000);
  assert(!p.gate.passed(), "and regaining it starts a fresh one, not the old one");
  p.advance(1000);
  assert(p.gate.passed(), "which passes after its own three seconds");
}
{
  const p = page();
  p.advance(2000); p.hide(); p.advance(5000);
  assert(!p.gate.passed(), "going hidden stops the clock");
}
// The automation tells: never passes, whatever the page does.
for (const [why, opts] of [
  ["navigator.webdriver", { webdriver: true }],
  ["a headless user agent", { ua: "Mozilla/5.0 HeadlessChrome/131.0" }],
  ["a crawler's user agent", { ua: "Googlebot/2.1" }],
  ["no languages", { languages: [] }],
]) {
  const p = page(opts);
  p.gesture(); p.advance(60000);
  assert(!p.gate.passed() && p.ran.length === 0, `${why} never passes the gate`);
}

// --- every path that counts goes through it ---
const read = (f) => fs.readFileSync(path.join(ROOT, f), "utf8");
const analytics = read("analytics.js");
const landing = read("landing.js");
const app = require("../tools/app_src").read(ROOT);
// GA's automatic page_view and session start come from "config"; it and the
// script fetch must sit inside the gate's callback, not at load.
{
  const body = (analytics.match(/CTReader\.when\(function \(\) \{([\s\S]*?)\n  \}\);/) || [])[1] || "";
  assert(/gtag\("config"/.test(body) && /googletagmanager/.test(body),
    "analytics.js configures GA and loads gtag.js only inside CTReader.when");
  assert((analytics.match(/gtag\("config"/g) || []).length === 1, "analytics.js configures GA in one place");
  assert(/if \(!window\.CTReader\) return;/.test(analytics), "without reader.js, analytics.js sends nothing");
}
// Every send to GA or the Worker is reached only through the gate.
for (const [name, src] of [["app.js", app], ["landing.js", landing]]) {
  assert(!/skipGate|isTrusted|webdriver|hasFocus/.test(src), `${name} keeps no gate of its own: reader.js is the one`);
}
{
  const beacon = (app.match(/function beacon\(name\) \{([\s\S]*?)\n  \}/) || [])[1] || "";
  assert(/CTReader\.when\(\(\) => sendEvent\(name\)\)/.test(beacon), "app.js's beacon() sends only through CTReader.when");
  assert((app.match(/sendEvent\(/g) || []).length === 2, "and sendEvent has no other caller");
  assert(!/beacon\("[^"]+", /.test(app), "no beacon() call carries a second argument to step around the gate");
  const vote = (app.match(/function castVote\([\s\S]*?\n  \}/) || [""])[0];
  assert(/CTReader\.when\(\(\) => \{[\s\S]*sendBeacon\(SYNC_ENDPOINT \+ "\/v"/.test(vote), "a vote is sent through the gate");
  const votes = (app.match(/function fetchVotes\([\s\S]*?\n  \}/) || [""])[0];
  assert(/CTReader\.when\(\(\) => fetch\(/.test(votes), "the vote tally is read through the gate");
}
{
  const beacon = (landing.match(/function beacon\(name\) \{([\s\S]*?)\n  \}/) || [])[1] || "";
  assert(/CTReader\.when\(function \(\) \{ send\(name\); \}\)/.test(beacon), "landing.js's beacon() sends only through CTReader.when");
  assert((landing.match(/\bsend\(/g) || []).length === 1 + 1, "and send() has no other caller");
}
// Every page that loads analytics.js loads reader.js first.
{
  const html = read("index.html");
  const r = html.indexOf('<script src="reader.js"></script>'), a = html.indexOf('<script src="analytics.js"></script>');
  assert(r >= 0 && a > r, "index.html loads reader.js before analytics.js");
  const seo = read("tools/build_seo_pages.py");
  const loads = seo.split('asset("analytics.js")').length - 1;
  const pairs = (seo.match(/asset\("reader\.js"\)\}"><\/script>(\\n'\n\s*\+ f'|\n)<script src="\{asset\("analytics\.js"\)/g) || []).length;
  assert(loads > 0 && pairs === loads, `every page tools/build_seo_pages.py writes loads reader.js just before analytics.js (${pairs} of ${loads})`);
}

if (fails.length) { console.error(fails.join("\n")); process.exit(1); }
console.log("ok");
