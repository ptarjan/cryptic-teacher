// Does idx.js, the browser's decoder for the progressive index, rebuild the
// rows of index.json from what tools/index_idx.py writes? Builds puzzles/idx
// into a temp folder (python writes it, from a synthetic index and from the
// puzzles/index.json a reindex built, when this checkout has one), decodes
// head-static + head-live + every shard + the bundle with idx.js, and
// deep-compares each row with index.json's: `v` to its first 5 chars, and
// `percentile` within 1 (the head's cut points).
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const vm = require("vm");
const { spawnSync } = require("child_process");
const idx = require("../idx.js");

const ROOT = path.join(__dirname, "..");

function row(series, number, o) {
  const r = {
    id: `${series}-${number}`, number, series,
    name: `${series[0].toUpperCase() + series.slice(1)} cryptic No ${number.toLocaleString("en-US")}`,
  };
  if (o.date) r.date = o.date;
  if (o.year) r.year = o.year;
  Object.assign(r, { file: `${series}-${number}.js`, v: "89abcdef", annotated: true,
    hasSolutions: true, solutionsUnofficial: false, difficulty: o.df || null });
  return Object.assign(r, o.extra || {});
}
const df = (band, index, percentile, basis) => ({ band, index, percentile, basis });

function synthetic() {
  const rows = [
    row("cryptic", 30105, { date: "2026-10-31", df: df("hard", 2.5, 100, ["clue length", "rarity"]) }),
    row("cryptic", 30104, { date: "2026-10-30", df: df("easy", 0.5, 0, ["rarity"]), extra: { annotated: false } }),
    row("cryptic", 30103, { date: "2026-10-29", df: df("medium", 1.5, 50, ["rarity", "blog comments"]) }),
    row("genius", 281, { date: "2026-10-01", extra: { name: "Genius 281 special", setter: "Hob",
      hasSolutions: false, solutionsUnofficial: true, tags: ["big-grid"] } }),
    row("genius", 280, { date: "2026-09-01", df: df("medium", 1.6, 75, ["blog comments", "rarity"]) }),
    row("penguin", 5, { year: 1998, extra: { name: "Penguin book 5", clues: { present: 1, total: 2 } } }),
    row("odd", 7, { date: "2020-01-01", extra: { id: "odd-seven", file: "odd.js" } }),
  ];
  const unlisted = [Object.assign(row("secret", 1, { date: "2019-05-05" }), { unlisted: true })];
  return { latest: "cryptic-30105", build: { commit: "abc" }, snitchRanges: { hard: [1, 2] },
    papers: { cryptic: "Guardian" }, groups: { cryptic: "Guardian" }, tags: { "big-grid": "x" },
    puzzles: rows, reprints: [{ id: "r-1" }], unlisted };
}

function writeIdx(indexPath, outDir) {
  const code = "import sys; sys.path.insert(0, 'tools'); import json, index_idx; " +
    "index_idx.write(json.load(open(sys.argv[1], encoding='utf-8')), sys.argv[2])";
  const r = spawnSync("python3", ["-c", code, indexPath, outDir], { cwd: ROOT, encoding: "utf8" });
  assert.strictEqual(r.status, 0, r.stderr);
  return path.join(outDir, "idx");
}

function loadStatic(file) {
  const win = {};
  vm.runInNewContext(fs.readFileSync(file, "utf8"), { window: win });
  return win.CRYPTIC_INDEX_STATIC;
}

function sameRow(want, got, label) {
  want = Object.assign({}, want);
  got = Object.assign({}, got);
  assert.strictEqual(got.v, want.v.slice(0, 5), label + ": v");
  delete want.v; delete got.v;
  const wd = want.difficulty, gd = got.difficulty;
  if (wd && gd) {
    assert(Math.abs(wd.percentile - gd.percentile) <= 1,
      `${label}: percentile ${gd.percentile} vs ${wd.percentile}`);
    want.difficulty = Object.assign({}, wd, { percentile: 0 });
    got.difficulty = Object.assign({}, gd, { percentile: 0 });
  }
  // The stored index.json has difficulty.index -0 where the decoder gives 0;
  // JSON writes both as 0 and the page can't tell them apart, but
  // deepStrictEqual can, so compare what survives a JSON round trip.
  assert.deepStrictEqual(JSON.parse(JSON.stringify(got)), JSON.parse(JSON.stringify(want)), label);
}

function check(index, label, tmp) {
  const indexPath = path.join(tmp, label + ".json");
  fs.writeFileSync(indexPath, JSON.stringify(index));
  const root = writeIdx(indexPath, path.join(tmp, label));
  const live = JSON.parse(fs.readFileSync(path.join(root, "head-live.json"), "utf8"));
  const stat = loadStatic(path.join(root, live.static));
  const cuts = live.percentileCuts;
  const want = new Map(index.puzzles.concat(index.unlisted || []).map((r) => [r.id, r]));

  // the bundle
  const bundleName = fs.readdirSync(root).find((f) => /^bundle\..*\.json$/.test(f));
  const bundle = JSON.parse(fs.readFileSync(path.join(root, bundleName), "utf8"));
  const fromBundle = idx.expandBundle(bundle, stat, cuts);
  assert.strictEqual(fromBundle.length, want.size, label + ": bundle row count");
  const seen = new Set();
  for (const r of fromBundle) {
    assert(want.has(r.id), `${label}: unexpected ${r.id}`);
    seen.add(r.id);
    sameRow(want.get(r.id), r, `${label} bundle ${r.id}`);
  }
  assert.strictEqual(seen.size, want.size, label + ": duplicate ids in bundle");

  // every shard on disk, by the manifest's hashed name
  let n = 0;
  for (const [key, h] of Object.entries(live.manifest)) {
    const compact = JSON.parse(fs.readFileSync(path.join(root, `${key.replace("/", "-")}.${h}.json`), "utf8"));
    assert.deepStrictEqual(compact, bundle[key], `${label}: shard ${key} differs from the bundle`);
    for (const r of idx.expandShard(key, compact, stat, cuts)) {
      sameRow(want.get(r.id), r, `${label} shard ${r.id}`);
      n++;
    }
  }
  assert.strictEqual(n, want.size, label + ": shard row count");

  // head-live's newest rows
  const recent = idx.expandRecent(live, stat);
  const listed = index.puzzles.slice(0, recent.length);
  assert.strictEqual(recent.length, Math.min(300, index.puzzles.length), label + ": recent count");
  recent.forEach((r, i) => sameRow(listed[i], r, `${label} recent ${r.id}`));
  return n;
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "idx-decoder-"));
try {
  check(synthetic(), "synthetic", tmp);
  assert.deepStrictEqual([0.5, 1.5, 1.6, 2.5, -1, 9].map((i) => idx.percentile([0.5, 1.5, 1.6, 2.5, null], i)),
    [0, 1, 2, 3, null, 3]);
  assert.strictEqual(idx.percentile(null, 1), null);
  assert.strictEqual(idx.percentile([0], null), null);
  const real = path.join(ROOT, "puzzles", "index.json");
  let msg = "synthetic only (no puzzles/index.json)";
  if (fs.existsSync(real)) {
    const index = JSON.parse(fs.readFileSync(real, "utf8"));
    msg = `${check(index, "real", tmp)} real rows`;
  }
  console.log("ok: " + msg);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
