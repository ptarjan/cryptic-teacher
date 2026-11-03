/* The page boots from the progressive index's heads (phase 4 of
   DESIGN-progressive-index.md; Paul 11-02: "It should be progressive.
   Download what we show").

     node tests/test_boot_from_head.js

   The index is written by tools/index_idx.py from a small synthetic catalogue
   (three genius rows in two years, a penguin book, an old cryptic, an old metro
   puzzle with a dated id, one unlisted row).

   1. loaderUsesHeads: index.html's boot loader fetches head-live.json, then the
      head-static file it names, composes the partial index, and only after the
      parser has reached the end of the page injects app.js.
   2. loaderFails: a head-live that 404s, a head-static that will not load,
      and a compose that throws are each retried, then shown as an error with a
      Retry button; app.js is never injected and no other index file is tried.
   3. compose: ctIdx.compose is the head's partial index (newest rows expanded,
      partial, INDEX.idx = both heads); ctIdx.full adds every shard and equals
      what the bundle holds, with the unlisted row kept apart.
   4. menuCounts: with only the head's rows, the paper menu counts each paper
      from head-live's counts, not from the rows it holds.
   5. shareLinks: an id already in the recent rows opens with no request to
      puzzles/idx; a legacy series-date alias (metro-20260105) fetches only
      that series' shards and resolves; a bare number and an unknown id fetch
      every shard (the bare number resolves, the unknown id boots on the
      newest puzzle). */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const vm = require("vm");
const { spawnSync } = require("child_process");
const { boot, ROOT } = require("../tools/fake_dom.js");
const ctIdx = require("../idx.js");

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
    row("metro", 10001, { date: "2026-01-05" }),
    row("genius", 270, { date: "2025-03-01", extra: { setter: "Hob" } }),
    row("cryptic", 30001, { date: "2019-01-01" }),
    row("penguin", 5, { year: 1998, extra: { name: "Penguin book 5" } }),
  ];
  const unlisted = [Object.assign(row("secret", 1, { date: "2019-05-05" }), { unlisted: true })];
  return { latest: "genius-281", build: { commit: "abc" }, snitchRanges: {}, clueTypes: { types: [] },
    papers: {}, groups: {}, tags: {}, puzzles: rows, reprints: [], unlisted };
}

function writeIdx() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ct-head-"));
  fs.writeFileSync(path.join(dir, "index.json"), JSON.stringify(catalogue()));
  const code = "import sys; sys.path.insert(0, 'tools'); import json, index_idx; " +
    "index_idx.write(json.load(open(sys.argv[1], encoding='utf-8')), sys.argv[2])";
  const r = spawnSync("python3", ["-c", code, path.join(dir, "index.json"), dir], { cwd: ROOT, encoding: "utf8" });
  if (r.status !== 0) throw new Error(r.stderr);
  return path.join(dir, "idx");
}

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};
const tick = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

// index.html's boot loader, run against a stub page. `files` maps a URL to
// its text (a missing one answers 404).
function loader(root, files) {
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  const m = /<script id="ct-boot"[^>]*>([\s\S]*?)<\/script>/.exec(html);
  const attr = () => undefined;
  const added = [], asked = [];
  const ctx = { Promise, Error };
  const timers = [], shown = [];
  ctx.setTimeout = (f) => { timers.push(f); };
  ctx.window = ctx;
  ctx.ctIdx = ctIdx;
  ctx.fetch = (url) => {
    asked.push(String(url));
    const text = files(String(url));
    return Promise.resolve(text === null || text === undefined
      ? { ok: false, status: 404 }
      : { ok: true, status: 200, json: () => Promise.resolve(JSON.parse(text)) });
  };
  ctx.document = {
    getElementById: () => ({ getAttribute: attr }),
    querySelectorAll: () => ["app-core.js?v=1", "app-boot.js?v=1"].map((h) => ({ getAttribute: () => h })),
    createElement: () => ({ appendChild() {}, style: {}, setAttribute() {} }),
    createTextNode: (t) => ({ t }),
    body: { firstChild: null, insertBefore: (el) => { shown.push(el); } },
    head: { appendChild: (el) => { added.push(el); } },
  };
  vm.runInNewContext(m[1], ctx);
  return { ctx, added, asked, timers, shown, srcs: () => added.map((e) => e.src) };
}

(async () => {
  const root = writeIdx();
  const liveText = fs.readFileSync(path.join(root, "head-live.json"), "utf8");
  const live = JSON.parse(liveText);
  const statText = fs.readFileSync(path.join(root, live.static), "utf8");
  const stat = {};
  vm.runInNewContext(statText, { window: stat });
  const STAT = stat.CRYPTIC_INDEX_STATIC;
  const serve = (url) => (/head-live\.json/.test(url) ? liveText : null);

  // 1
  const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
  check(!/index(-core)?\.js(?!on)/.test(html) && /puzzles\/idx\/head-live\.json/.test(html),
    "index.html does not mention index-core.js or index.js and names head-live.json");
  let L = loader(root, serve);
  await tick();
  check(L.srcs().length === 1 && L.srcs()[0] === "puzzles/idx/" + live.static,
    "the loader asks head-live.json, then the head-static file it names: " + L.srcs().join(", "));
  L.ctx.CRYPTIC_INDEX_STATIC = STAT;
  L.added[0].onload();
  check(!!L.ctx.CRYPTIC_INDEX && L.ctx.CRYPTIC_INDEX.partial === true && !!L.ctx.CRYPTIC_INDEX.idx,
    "the partial index is composed from the two heads");
  check(L.srcs().length === 1, "app.js is held back until the parser has reached the end of the page");
  L.ctx.ctBootParsed();
  check(L.srcs().length === 3 && L.srcs()[1] === "app-core.js?v=1" && L.srcs()[2] === "app-boot.js?v=1",
    "then the app's scripts are injected, in order: " + L.srcs().join(", "));
  check(L.added.slice(1).every((e) => e.async === false), "and they are not async, so they run in the order added");
  check(!L.srcs().concat(L.asked).some((u) => /index(-core)?\.js/.test(u)),
    "neither index-core.js nor index.js is asked for");
  check(L.ctx.CRYPTIC_INDEX.puzzles.length === catalogue().puzzles.length,
    "the recent rows are the whole (small) head list: " + L.ctx.CRYPTIC_INDEX.puzzles.length);

  // 2: each failure is retried (the timers), then the error box is shown
  const exhaust = async (L, again) => {
    for (let i = 0; i < 6 && L.timers.length; i++) { L.timers.shift()(); await tick(); if (again) again(L); }
  };
  L = loader(root, () => null);
  await tick();
  await exhaust(L);
  L.ctx.ctBootParsed();
  check(L.shown.length === 1 && L.srcs().length === 0 && L.asked.length === 3,
    "head-live.json missing: three tries, then an error box and nothing injected: " + L.asked.length + " asks, " + L.shown.length + " boxes");

  L = loader(root, serve);
  await tick();
  L.added[0].onerror();
  L.ctx.ctBootParsed();
  check(L.srcs().length === 1 && L.timers.length === 1, "head-static that will not load: retried, app.js not injected: " + L.srcs().join(", "));

  L = loader(root, serve);
  await tick();
  L.ctx.CRYPTIC_INDEX_STATIC = null;      // compose throws on it
  L.added[0].onload();
  L.ctx.ctBootParsed();
  check(!L.srcs().some((u) => /app-/.test(u)) && L.timers.length === 1, "a compose that throws: retried, app.js not injected");
  check(![].concat(L.srcs(), L.asked).some((u) => /index(-core)?\.js/.test(u)), "no legacy index file is ever asked for");

  // 3
  const c = ctIdx.compose(STAT, live);
  check(c.partial === true && c.idx.live === live && c.idx.stat === STAT && c.latest === live.latest &&
    c.puzzles.length === live.recent.length && c.puzzles[0].id === "genius-281",
    "compose: newest rows expanded, partial, INDEX.idx holds both heads");
  const bundle = JSON.parse(fs.readFileSync(path.join(root, live.bundle), "utf8"));
  const f = ctIdx.full(STAT, live, bundle);
  const want = catalogue();
  check(f.partial === false && f.puzzles.map((p) => p.id).join() === want.puzzles.map((p) => p.id).join(),
    "full: every listed row in index.json's order: " + f.puzzles.map((p) => p.id).join());
  check((f.unlisted || []).map((p) => p.id).join() === "secret-1", "full: the unlisted row is kept apart");

  // 4 and 5: the page, booted with the head only
  function page(query) {
    const asked = [];
    global.fetch = (url) => {
      const m = /puzzles\/idx\/([^?]+)$/.exec(String(url));
      if (!m) {
        if (/\.js\.gz/.test(String(url))) return Promise.resolve({ ok: false, status: 404 });
        return new Promise(() => {});
      }
      asked.push(m[1]);
      const file = path.join(root, m[1]);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(JSON.parse(fs.readFileSync(file, "utf8"))) });
    };
    let real = null;
    const d = boot({ query, storage: { "ct:nux": "9" }, index: (ix) => {
      // A real annotated puzzle (its file exists, so the page can open it) and
      // two synthetic genius rows are "recent"; the rest are in the shards.
      real = ix.puzzles.find((p) => p.annotated && !/^(genius|metro|penguin|cryptic|secret)$/.test(p.series)) ||
        ix.puzzles.find((p) => p.annotated);
      ix.puzzles = [real].concat(catalogue().puzzles.slice(0, 2));
      ix.reprints = [];
      ix.partial = true;
      ix.idx = { live, stat: STAT };
    } });
    d.asked = asked;
    d.real = real;
    return d;
  }
  const shardsOf = (d) => d.asked.filter((n) => /\.[0-9a-f]{8}\.json$/.test(n) && !/^bundle/.test(n));
  const total = Object.keys(live.manifest).length;

  let d = page("");
  d.registry["btn-picker"].onclick();
  const menu = d.registry["picker-paper"].innerHTML;
  const nCryptic = (live.counts.series.cryptic || 0);
  check(/value="cryptic"/.test(menu) && /value="metro"/.test(menu) && /value="penguin"/.test(menu),
    "the paper menu lists the papers the head counts, though their rows are not here yet");
  check(nCryptic === 1 && d.window.CRYPTIC_INDEX.puzzles.length === 3 && !d.window.CRYPTIC_INDEX.puzzles.some((p) => p.series === "metro"),
    "(and only three rows are held, none of them metro)");
  d.stop();

  d = page("");
  const realId = d.real.id;
  d.stop();
  d = page("?p=" + realId);
  await tick();
  check(d.asked.length === 0, "a canonical id in the recent rows opens with no request to puzzles/idx");
  d.stop();

  d = page("?p=metro-20260105");
  await tick();
  check(shardsOf(d).length >= 1 && shardsOf(d).every((n) => /^metro-/.test(n)),
    "a series-date alias fetches only that series' shards: " + d.asked.join(", "));
  check(/metro-10001/.test(String(global.location.replaced || "")) && d.window.CRYPTIC_INDEX.partial === true,
    "and resolves to metro-10001 while the rest of the list stays unfetched: " + global.location.replaced);
  d.stop();

  d = page("?p=270");
  await tick();
  check(shardsOf(d).length === total, "a bare number loads every shard: " + shardsOf(d).length + " of " + total);
  check(/genius-270/.test(String(global.location.replaced || "")), "and resolves to genius-270: " + global.location.replaced);
  d.stop();

  d = page("?p=nonesuch-9");
  await tick();
  check(shardsOf(d).length === total && d.window.CRYPTIC_INDEX.partial === false,
    "an unknown id loads every shard, then boots on the newest puzzle");
  d.stop();

  console.log(failures ? failures + " FAILED" : "all passed");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
