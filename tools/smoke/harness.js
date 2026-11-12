// The shared ground every section stands on: the DOM stub and booted app, the
// assertion counter, and the small helpers (and the app helpers read out of
// the app) that the sections use.
// Part of tools/smoke_test.js (the entry point); see tools/smoke/ for the sections.
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = require("path").join(__dirname, "..", "..");
// Strip tags until nothing changes, so "<scr<b>ipt" cannot reassemble.
function stripTags(s, rep) {
  let prev;
  s = String(s);
  do { prev = s; s = s.replace(/<[^>]*>/g, rep); } while (s !== prev);
  return s;
}
const pp = require("../puzzle_paths");

const T = module.exports = {};
T.failures = 0;
const CTQuotes = require("../../quotes.js");
// Every linked group an entry leads: its own `group`, then one per further
// answer that starts on the same light (`alsoLeads`).
const groupsOf = (e) => [e.group, ...(e.alsoLeads || []).map((l) => l.group)].filter(Boolean);
// Returns the condition, so a check whose failure would crash the checks after it
// can guard them: a stack trace stops the suite dead and hides every other result.
const assert = (cond, msg) => { if (!cond) { T.failures++; console.error("FAIL:", msg); } return !!cond; };
// The walk says its sentence in exactly ONE node: the caption beside the
// spotlight while there is a hole, the line down in the panel when there is
// not, and the other one is emptied (sayIt in app.js). Read whichever is
// saying it — an assertion pinned to one of the two nodes passes or fails on
// where the sentence happens to be, which is not what any of them are about.
const nuxLine = (reg) => reg["spot-say"].textContent || reg["nux"].textContent;

// The crawlable pages this test reads are generated and not committed, so a
// checkout that has not built them cannot be smoke-tested at all. Stop with the
// command to run rather than an ENOENT stack trace from readFileSync: the path
// alone does not tell anyone that the file is meant to be built, or by what.
const readBuilt = (rel) => {
  const file = path.join(ROOT, rel);
  if (!fs.existsSync(file)) {
    console.error(`FAIL: ${rel} has not been built — run: python3 tools/build_seo_pages.py`);
    process.exit(1);
  }
  return fs.readFileSync(file, "utf8");
};

// The DOM stub and the app boot live in tools/fake_dom.js, because
// tools/make_hint_packets.js boots the same app to walk the same hint ladder.
// One stub, so a grader can never mark a rung the app does not actually show.
const { registry, document, storage, docListeners, winListeners, canonicalLink, FakeEl,
        appSrc, beacons } = require("../fake_dom.js").boot();
// What this file needs of the app's own helpers, cut out of the source it just
// booted rather than retyped: a copy is how this file and the page came to
// disagree about what an entry's id or a clue's printed line is. Each is a
// one-statement definition at the IIFE's top level; a rename or a move is a
// failure here, not a silent fork.
const APP_HELPERS = (() => {
  const names = ["esc", "cpToIdx", "entryId", "clueText", "reconstructedHTML", "enumHTML"];
  const lines = appSrc.split("\n");
  let code = "";
  for (const name of names) {
    const at = lines.findIndex((l) => new RegExp(`^  (const|function) ${name}\\b`).test(l));
    if (at < 0) { console.error(`FAIL: ${name} is no longer a top-level helper in the app to be read`); process.exit(1); }
    // The definition ends at the first line, at or after its own, where the
    // text so far parses and the next line starts back at the IIFE's margin.
    for (let end = at; end < lines.length; end++) {
      const text = lines.slice(at, end + 1).join("\n");
      try { new Function(text); } catch (e) { continue; }
      if (/^  \S/.test(lines[end + 1] || "") || /^\s*$/.test(lines[end + 1] || "")) { code += text + "\n"; break; }
    }
  }
  return new Function(code + `return { ${names.join(", ")} };`)();
})();
const { esc: htmlEsc, cpToIdx, entryId, clueText } = APP_HELPERS;
// The line a solver reads: the words curled, then "(enumeration)" — the app's
// enumHTML with its markup taken off, minus the "reconstructed" tag it appends.
const printedClue = (e) => CTQuotes.curl(clueText(e)) + stripTags(
  APP_HELPERS.enumHTML({ clue: Object.assign({}, e.clue, { reconstructed: false }) }), "")
  .replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
// Another tab of this site saving progress. Several tests plant a save rather
// than typing two hundred letters into a grid, and a plant written straight
// into `storage` is a write no browser can perform: the page it happened in
// would have gone through app.js, and a page it did NOT happen in is told by
// the storage event. Writing the value without the event models neither, and
// what it silently tests is whether the app re-reads localStorage on every
// render — which the picker deliberately does not.
const saveFromAnotherTab = (key, value) => {
  if (value === undefined) delete storage[key]; else storage[key] = value;
  (winListeners.storage || []).forEach((fn) => fn({ key, newValue: value === undefined ? null : value }));
};
const EVENTS = require("../../sync/events.js");
// A guess is asked of the clue at the top of the panel and answered in the body
// under it, so "what the panel is showing" spans both elements. Tests that care
// which of the two still name the element; the rest ask the panel.
const panelHTML = () => registry["hint-clue"].innerHTML + registry["hint-body"].innerHTML;
// A right answer now goes straight on to the ladder's next question (Paul
// 10-30: "When you finish a hint ring it should go to the next"). The checks that
// read the finished rung's own state skip that question first, as a solver
// pressing "Skip for now" would, so they see the rung they just answered.
const dismissNext = () => {
  if (registry["hint-body"].innerHTML.includes('id="guess-later"') && registry["guess-later"]
    && registry["guess-later"].onclick) registry["guess-later"].onclick();
};
// What the page reported since a mark, in order. Sliced rather than read whole:
// the harness opens a great many puzzles over a run, and the rule under test is
// "at most once per puzzle per session", not "at most once ever".
const reported = (mark) => beacons.slice(mark).map((b) => b.body.parts);

// Puzzle ids carry their series ("cryptic-30089"); the picker shows the plain
// number, which is what a person types and what the row says. One conversion,
// used everywhere this test drives the picker.
const numberOf = (id) => (((global.CRYPTIC_INDEX || {}).puzzles || [])
  .find((p) => p.id === id) || { number: id }).number;
// The literal text of each `html:` template in app.js, cut at every ${…}
// placeholder (nested templates inside a placeholder are skipped whole).
function rungTemplateProse(src) {
  const out = [];
  for (const m of src.matchAll(/html:\s*`/g)) {
    let i = m.index + m[0].length, lit = "";
    while (i < src.length && src[i] !== "`") {
      if (src[i] === "$" && src[i + 1] === "{") {
        out.push(lit);
        lit = "";
        let depth = 1;
        i += 2;
        while (i < src.length && depth) {
          if (src[i] === "`") { i++; while (i < src.length && src[i] !== "`") i++; }
          else if (src[i] === "{") depth++;
          else if (src[i] === "}") depth--;
          i++;
        }
      } else lit += src[i++];
    }
    out.push(lit);
  }
  return out;
}

// The ladder, read off app.js's ordered LABELS map rather than copied here. The
// map's key order is the ladder's order — app.js sorts by Object.keys(LABELS)
// and tools/build_readme.py numbers README.md off the same map — so this file
// cannot hold an order that disagrees with the app.
const LADDER = (() => {
  const block = /const LABELS = \{([\s\S]*?)\n    \};/.exec(appSrc);
  if (!assert(block, "app.js still declares the ladder as `const LABELS = { … };`")) return [];
  if (!assert(/const RUNG_ORDER = Object\.keys\(LABELS\);/.test(appSrc),
      "the ladder's order is Object.keys(LABELS), not a second list beside it — "
      + "a copy is what let the README publish an order the app had abandoned")) return [];
  return [...block[1].matchAll(/(\w+):\s*"([^"]+)"/g)].map((m) => ({ key: m[1], label: m[2] }));
})();
assert(LADDER.length === 5, "the ladder has five rungs: " + LADDER.map((r) => r.key).join(", "));

// An annotation's definitions, as clue text; `at` counts code points, so
// cpToIdx turns it into a JS string index.
const defTexts = (a) => ((a && a.definitions) || []).map((d) => d.text);
// A row's number span carries the stored number as data-number, read here
// rather than the printed "No 1,183", which a book or a date-keyed paper prints
// as something else. Quoted, so 1183 cannot match the row of 11830.
const rowHasNumber = (html, num) => html.includes(`data-number="${num}"`);

Object.assign(T, { CTQuotes, EVENTS, LADDER, ROOT, appSrc, assert, beacons, canonicalLink, clueText,
  cpToIdx, defTexts, dismissNext, docListeners, document, entryId, fs, groupsOf, htmlEsc, numberOf,
  nuxLine, panelHTML, path, pp, printedClue, readBuilt, registry, reported, rowHasNumber,
  rungTemplateProse, saveFromAnotherTab, storage, stripTags });
