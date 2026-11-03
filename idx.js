// idx.js, the browser side of the progressive puzzle index (phase 2 of
// DESIGN-progressive-index.md). It turns what tools/index_idx.py writes into
// puzzles/idx/ (head-static, head-live, the series-year shards, the bundle)
// back into the exact row objects index.json holds, so nothing downstream of
// the index has to know the rows were ever compact. index.html loads it ahead of the boot loader, which composes the first index from the heads.
//
// Two losses by design, both the writer's: `v` is the row's first 5 hex chars
// (it only tells versions of one file apart), and `percentile` is not shipped
// but read off the head's 101 cut points (percentile(), same rank +-1).
(function (root) {
  "use strict";

  // Keys a compact row spells differently; every other key is copied as it is.
  const OWN = new Set(["n", "d", "v", "s", "id", "file", "name", "a", "h", "u", "df", "nodf", "k"]);

  // A name template with its number put back: "{n}" plain, "{n:,}" with commas.
  function render(template, number) {
    return template
      .split("{n}").join(String(number))
      .split("{n:,}").join(typeof number === "number" && Number.isInteger(number)
        ? number.toLocaleString("en-US") : String(number));
  }

  // The percentile of a difficulty index: the highest k whose cut point is at
  // or below it. cuts[k] is the lowest index that ranks k or more (null where
  // nothing does); the list is null when fewer than two puzzles are rated.
  function percentile(cuts, index) {
    if (!cuts || index === null || index === undefined) return null;
    let best = null;
    for (let k = 0; k < cuts.length; k++) {
      if (cuts[k] !== null && cuts[k] <= index) best = k;
    }
    return best;
  }

  // 0 stands for false in the flag fields; anything else is itself.
  const flag = (v) => (v === 0 ? false : v);

  // The index.json row a compact row stands for. series: the shard's series
  // (a head-live "recent" row carries it as `k`). static: window.CRYPTIC_INDEX_STATIC.
  function expandRow(c, series, stat, cuts) {
    const number = c.n;
    const id = "id" in c ? c.id : series + "-" + number;
    const row = { id: id, number: number, series: series };
    row.name = "name" in c ? c.name : render(stat.templates[series], number);
    if ("s" in c) row.setter = c.s;
    const d = c.d;
    if (typeof d === "string") row.date = d.slice(0, 4) + "-" + d.slice(4, 6) + "-" + d.slice(6);
    else if (d !== undefined && d !== null) row.year = d;
    row.file = "file" in c ? c.file : id + ".js";
    row.v = c.v;
    row.annotated = "a" in c ? flag(c.a) : true;
    row.hasSolutions = "h" in c ? flag(c.h) : true;
    row.solutionsUnofficial = "u" in c ? (c.u === 1 ? true : c.u) : false;
    let df = c.df;
    if (Array.isArray(df)) {
      const basis = [];
      stat.basis.forEach((f, i) => { if ((df[2] >> i) & 1) basis.push(f); });
      df = { band: stat.bands[df[0]], index: df[1], percentile: percentile(cuts, df[1]), basis: basis };
    }
    if (!("nodf" in c)) row.difficulty = df === undefined ? null : df;
    for (const k of Object.keys(c)) if (!OWN.has(k)) row[k] = c[k];
    return row;
  }

  // The rows of one shard, key "series/year" and its list of compact rows.
  function expandShard(key, compact, stat, cuts) {
    const series = key.split("/")[0];
    return compact.map((c) => expandRow(c, series, stat, cuts));
  }

  // The rows of head-live's `recent` list, newest first (each carries its series).
  function expandRecent(live, stat) {
    return live.recent.map((c) => expandRow(c, c.k, stat, live.percentileCuts));
  }

  // Every row of a bundle ({"series/year": [compact rows]}), in key order.
  function expandBundle(bundle, stat, cuts) {
    const out = [];
    for (const key of Object.keys(bundle)) {
      for (const r of expandShard(key, bundle[key], stat, cuts)) out.push(r);
    }
    return out;
  }

  // The partial window.CRYPTIC_INDEX a boot from the heads starts with: the
  // static head's tables, head-live's latest/build/snitchRanges, and the newest
  // rows (expanded) as the list, flagged partial. INDEX.idx keeps both heads so
  // app.js's loadShards can fetch and decode the rest.
  function compose(stat, live) {
    const index = {};
    for (const k of Object.keys(stat)) index[k] = stat[k];
    for (const k of ["latest", "build", "snitchRanges"]) if (k in live) index[k] = live[k];
    index.puzzles = expandRecent(live, stat);
    index.partial = true;
    index.idx = { live: live, stat: stat };
    return index;
  }

  // The complete index a test or tool can build from the files alone: compose()
  // with every shard of the bundle merged in the order index.json holds them.
  function full(stat, live, bundle) {
    const index = compose(stat, live);
    const seen = new Set(index.puzzles.map((p) => p.id));
    const unlisted = [];
    for (const r of expandBundle(bundle, stat, live.percentileCuts)) {
      if (r.unlisted) unlisted.push(r);
      else if (!seen.has(r.id)) { seen.add(r.id); index.puzzles.push(r); }
    }
    const day = (p) => (p.year !== undefined ? p.year + "-01-01" : (p.date || ""));
    index.puzzles.sort((a, b) => {
      const da = day(a), db = day(b);
      if (da !== db) return da < db ? 1 : -1;
      const ca = a.series === "cryptic", cb = b.series === "cryptic";
      if (ca !== cb) return ca ? -1 : 1;
      return (Number(b.number) || 0) - (Number(a.number) || 0);
    });
    if (unlisted.length) index.unlisted = unlisted;
    index.partial = false;
    delete index.idx;
    return index;
  }

  const api = { compose, full, expandRow, expandShard, expandRecent, expandBundle, percentile };
  root.ctIdx = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : this);
