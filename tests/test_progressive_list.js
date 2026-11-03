/* The full puzzle list arrives on demand, not up front (phase 3 of
   DESIGN-progressive-index.md; Paul 11-02: "It should be progressive.
   Download what we show").

     node tests/test_progressive_list.js

   The page is booted with the head only: the newest real rows, INDEX.partial,
   and INDEX.idx = head-live + head-static written by tools/index_idx.py from a
   small synthetic catalogue (two genius years, a penguin book, an old cryptic,
   one unlisted row). fetch serves puzzles/idx/ out of that folder and records
   every URL asked for.

   1. seriesFirst: searching "281 genius" fetches the two genius shards and
      nothing else (no head, no bundle, no other series), and the result appears.
   2. restFollows: a moment later (the focus timer) the remaining shards
      stream in, the list is whole (INDEX.partial false) and "N other puzzles
      don't match" is said.
   3. memosReset: after a merge, the memos built from the shorter list are
      gone: the setter suggestions and the paper menu show the new rows. A
      stale pickerTerms / paperMenu would still answer from the recent rows.
   4. fallback: when a shard will not load, the page asks for puzzles/index.js
      (the way it worked before puzzles/idx) instead of staying half a list.
   5. noIdx: with no INDEX.idx a partial index waits for index.js and the
      triggers fetch nothing from puzzles/idx (today's boot). */
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const vm = require("vm");
const { spawnSync } = require("child_process");
const { boot, ROOT } = require("../tools/fake_dom.js");

function row(series, number, o) {
  const r = { id: `${series}-${number}`, number, series,
    name: `${series[0].toUpperCase() + series.slice(1)} cryptic No ${number}` };
  if (o.date) r.date = o.date;
  if (o.year) r.year = o.year;
  Object.assign(r, { file: `${series}-${number}.js`, v: "89abcdef", annotated: true,
    hasSolutions: true, solutionsUnofficial: false, difficulty: null });
  return Object.assign(r, o.extra || {});
}

function catalogue() {
  const rows = [
    row("genius", 281, { date: "2026-10-01", extra: { setter: "Zzyzx" } }),
    row("genius", 280, { date: "2026-09-01", extra: { setter: "Hob" } }),
    row("genius", 270, { date: "2025-03-01", extra: { setter: "Hob" } }),
    row("penguin", 5, { year: 1998, extra: { name: "Penguin book 5" } }),
    row("cryptic", 30001, { date: "2019-01-01" }),
  ];
  const unlisted = [Object.assign(row("secret", 1, { date: "2019-05-05" }), { unlisted: true })];
  return { latest: "genius-281", build: { commit: "abc" }, snitchRanges: {},
    papers: {}, groups: {}, tags: {}, puzzles: rows, reprints: [], unlisted };
}

function writeIdx() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ct-prog-"));
  fs.writeFileSync(path.join(dir, "index.json"), JSON.stringify(catalogue()));
  const code = "import sys; sys.path.insert(0, 'tools'); import json, index_idx; " +
    "index_idx.write(json.load(open(sys.argv[1], encoding='utf-8')), sys.argv[2])";
  const r = spawnSync("python3", ["-c", code, path.join(dir, "index.json"), dir], { cwd: ROOT, encoding: "utf8" });
  assert.strictEqual(r.status, 0, r.stderr);
  return path.join(dir, "idx");
}

const tick = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

// A page with the head only. `broken` names a shard-file substring whose fetch fails.
function page(root, broken) {
  const asked = [];
  global.fetch = (url) => {
    const m = /puzzles\/idx\/([^?]+)$/.exec(String(url));
    if (!m) return new Promise(() => {});   // everything else never answers, as in the harness
    asked.push(m[1]);
    if (broken && m[1].includes(broken)) return Promise.resolve({ ok: false, status: 404 });
    const file = path.join(root, m[1]);
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(fs.readFileSync(file, "utf8"))) });
  };
  const live = JSON.parse(fs.readFileSync(path.join(root, "head-live.json"), "utf8"));
  const stat = {};
  vm.runInNewContext(fs.readFileSync(path.join(root, live.static), "utf8"), { window: stat });
  const d = boot({ storage: { "ct:nux": "9" }, index: (ix) => {
    // The real newest rows, minus the series the synthetic catalogue stands in
    // for: the corpus has genius rows of its own (even a genius 281, which would
    // win the id dedupe against the synthetic one and hide its setter).
    ix.puzzles = ix.puzzles.filter((p) => !["genius", "penguin", "secret"].includes(p.series)).slice(0, 12);
    ix.partial = true;
    ix.idx = { live, stat: stat.CRYPTIC_INDEX_STATIC };
  } });
  // The fake head runs an appended script at once; hold puzzles/index.js back so
  // the test decides when it "answers" (script.onload below).
  const head = d.document.head, append = head.appendChild;
  head.appendChild = function (el) {
    if (el.tagName === "SCRIPT" && /puzzles\/index\.js/.test(el.src || "")) { this.children.push(el); return el; }
    return append.call(this, el);
  };
  d.reg = d.registry;
  d.asked = asked;
  d.reg["btn-picker"].onclick();
  d.search = (q) => {
    d.reg["picker-search"].value = q;
    d.reg["picker-search"].listeners.input.forEach((f) => f());
  };
  d.rows = () => d.reg["picker-list"].children.map((li) => li.children[0] && li.children[0].innerHTML).join("");
  return d;
}

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

(async () => {
  const root = writeIdx();
  const shards = (d) => d.asked.filter((f) => /^[a-z]+-[a-z0-9]+\.[0-9a-f]{8}\.json$/.test(f));

  // 1 + 2
  let d = page(root);
  check(d.asked.length === 0, "booting with the head asks puzzles/idx for nothing");
  check(!/data-number="281"/.test(d.rows()), "genius 281 is not in the recent rows");
  d.search("281 genius");
  await tick();
  check(d.asked.length === 2 && d.asked.every((f) => /^genius-20(25|26)\.[0-9a-f]{8}\.json$/.test(f)),
    "'281 genius' fetched only the two genius shards: " + d.asked.join(", "));
  check(/data-number="281"/.test(d.rows()), "the genius 281 result appears");
  check(!/data-number="280"/.test(d.rows()), "and only the puzzle searched for");
  check(d.window.CRYPTIC_INDEX.partial === true, "the list is still partial: the other series are not in");
  global.flushTimers(1600);
  await tick();
  check(shards(d).length === 5, "the rest streamed in after the pause: " + shards(d).length + " shards");
  check(d.window.CRYPTIC_INDEX.partial === false, "the list is whole once every shard is in");
  check(/don’t match/.test(d.reg["picker-more"].innerHTML), "'N other puzzles don't match' is said once whole");
  check((d.window.CRYPTIC_INDEX.unlisted || []).some((p) => p.id === "secret-1"), "the unlisted row went to INDEX.unlisted");
  check(!d.window.CRYPTIC_INDEX.puzzles.some((p) => p.id === "secret-1"), "and not into the listed rows");
  const ids = d.window.CRYPTIC_INDEX.puzzles.map((p) => p.id);
  check(new Set(ids).size === ids.length, "no row is in the list twice");
  d.stop();

  // 3
  d = page(root);
  const menu = () => d.reg["picker-paper"].innerHTML;
  const chips = () => d.reg["picker-filters"].innerHTML;
  check(/value="genius"/.test(menu()), "before the merge the paper menu already lists genius, counted from the head");
  d.search("zzy");
  check(!/Zzyzx/.test(chips()), "before the merge nobody suggests the setter Zzyzx");
  await tick();
  check(/Zzyzx/.test(chips()), "after the merge the setter suggestions are rebuilt and offer Zzyzx");
  d.reg["btn-picker"].onclick();
  d.reg["btn-picker"].onclick();
  check(/value="genius"/.test(menu()), "after the merge the paper menu is rebuilt and has genius");
  d.stop();

  // 4
  d = page(root, "genius-2025");
  d.search("281 genius");
  await tick();
  const script = d.document.head.children.find((c) => c.tagName === "SCRIPT" && /puzzles\/index\.js$/.test(c.src || ""));
  check(!!script, "a shard that will not load makes the page ask for puzzles/index.js");
  check(d.window.CRYPTIC_INDEX.partial === true, "and the list stays partial until that file answers");
  if (script) {
    // index.js runs: it replaces window.CRYPTIC_INDEX with the whole index.
    const whole = { puzzles: catalogue().puzzles.concat(d.window.CRYPTIC_INDEX.puzzles) };
    const INDEX = d.window.CRYPTIC_INDEX;
    d.window.CRYPTIC_INDEX = whole;
    script.onload();
    check(INDEX.partial === false && INDEX.puzzles.length === whole.puzzles.length && d.window.CRYPTIC_INDEX === INDEX,
      "the whole index is adopted as it was before puzzles/idx");
    check(/data-number="281"/.test(d.rows()), "and the search is answered from it");
  }
  d.stop();

  // 5
  global.fetch = (url) => { asked5.push(String(url)); return new Promise(() => {}); };
  const asked5 = [];
  d = boot({ storage: { "ct:nux": "9" }, index: (ix) => { ix.puzzles = ix.puzzles.slice(0, 12); ix.partial = true; } });
  d.registry["btn-picker"].onclick();
  d.registry["picker-search"].value = "zzy";
  d.registry["picker-search"].listeners.input.forEach((f) => f());
  await tick();
  check(!asked5.some((u) => /puzzles\/idx\//.test(u)) && d.window.CRYPTIC_INDEX.partial === true,
    "with no INDEX.idx a search fetches nothing from puzzles/idx and waits for index.js");
  d.stop();

  console.log(failures ? failures + " FAILED" : "all passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
