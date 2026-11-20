// The service worker's rules for the progressive puzzle index (puzzles/idx/):
// head-live.json is network-first with the cache as the offline copy, the
// content-named head-static, shards and bundle are cache-first, all of them in
// the shell cache and never in ct-puzzles-1; a new head-live deletes the idx
// files it no longer names; and anything in idx/ is never
// filed as a puzzle (the "ready offline" count was off by one).
//
//     node tests/test_sw_idx_cache.js
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ORIGIN = "https://ct.test";
const SCOPE = ORIGIN + "/";
const fails = [];
const assert = (ok, msg) => { if (!ok) fails.push(msg); };

function harness(site) {
  let online = true;
  const waits = [];
  const stores = new Map();
  const keyOf = (r) => (typeof r === "string" ? r : r.url);
  const bare = (u) => u.split("?")[0];
  class FakeCache {
    constructor() { this.m = new Map(); }
    async match(r, opts) {
      const k = keyOf(r);
      if (this.m.has(k)) return this.m.get(k).clone();
      if (opts && opts.ignoreSearch) {
        for (const [u, res] of this.m) if (bare(u) === bare(k)) return res.clone();
      }
      return undefined;
    }
    async put(r, res) { this.m.delete(keyOf(r)); this.m.set(keyOf(r), res.clone()); }
    async add(r) {
      const res = await fakeFetch(r);
      if (!res.ok) throw new TypeError("bad status");
      await this.put(r, res);
    }
    async delete(r, opts) {
      let hit = false;
      for (const u of [...this.m.keys()]) {
        if (u === keyOf(r) || (opts && opts.ignoreSearch && bare(u) === bare(keyOf(r)))) { this.m.delete(u); hit = true; }
      }
      return hit;
    }
    async keys() { return [...this.m.keys()].map((u) => new Request(u)); }
  }
  const caches = {
    async open(n) { if (!stores.has(n)) stores.set(n, new FakeCache()); return stores.get(n); },
    async match(r) { for (const c of stores.values()) { const x = await c.match(r); if (x) return x; } return undefined; },
  };
  // The server, like GitHub Pages, ignores the query string.
  async function fakeFetch(r) {
    if (!online) throw new TypeError("Load failed");
    const p = new URL(keyOf(r)).pathname;
    if (!(p in site)) return new Response("nope", { status: 404 });
    const [body, type] = site[p];
    return new Response(body, { status: 200, headers: { "content-type": type } });
  }
  const handlers = {};
  const self = {
    location: new URL(ORIGIN + "/sw.js"),
    addEventListener: (t, f) => { handlers[t] = f; },
    skipWaiting() {}, clients: { claim: async () => {} }, registration: {},
  };
  const ctx = vm.createContext({ self, caches, fetch: fakeFetch, Request, Response, Headers, URL, setTimeout, console, TypeError, Promise });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "sw.js"), "utf8"), ctx);

  // Fires a fetch event. undefined: the worker left it to the network.
  function request(url, mode) {
    let out;
    const req = { url, method: "GET", mode: mode || "no-cors", cache: "default", headers: new Headers() };
    handlers.fetch({ request: req, respondWith: (p) => { out = p; }, waitUntil: (p) => { waits.push(p); } });
    return out;
  }
  async function message(data) {
    let p;
    handlers.message({ data, ports: [], waitUntil: (x) => { p = x; } });
    await p;
  }
  return { settle: () => Promise.all(waits), request, message, caches, setOnline: (v) => { online = v; }, setSite: (s) => { site = s; } };
}

const IDX = SCOPE + "puzzles/idx/";
const live = (gen) => JSON.stringify({
  static: "head-static.s1.js", bundle: "bundle." + gen + ".json",
  manifest: { "times/2026": gen, "cryptic/2025": "c1" },
});
const siteOf = (gen) => ({
  "/puzzles/idx/head-live.json": [live(gen), "application/json"],
  "/puzzles/idx/head-static.s1.js": ["window.S=1", "text/javascript"],
  ["/puzzles/idx/bundle." + gen + ".json"]: ["{}", "application/json"],
  ["/puzzles/idx/times-2026." + gen + ".json"]: ["[]", "application/json"],
  "/puzzles/idx/cryptic-2025.c1.json": ["[]", "application/json"],
});
const names = async (h, cacheName) => (await (await h.caches.open(cacheName)).keys()).map((r) => r.url.replace(ORIGIN, "")).sort();

(async () => {
  const h = harness(siteOf("g1"));
  for (const f of ["head-live.json", "head-static.s1.js", "bundle.g1.json", "times-2026.g1.json", "cryptic-2025.c1.json"]) {
    const res = await h.request(IDX + f);
    assert(res && (await res).ok, f + " is served");
  }
  await h.settle();
  const shell = await names(h, "ct-shell-1");
  assert(shell.length === 5 && shell.every((n) => n.startsWith("/puzzles/idx/")), "idx files are in the shell cache: " + shell);
  assert((await names(h, "ct-puzzles-1")).length === 0, "none went to the puzzle cache");

  // A new manifest: the old shard version and bundle go, the unchanged shard stays.
  h.setSite(siteOf("g2"));
  await h.request(IDX + "head-live.json");
  await h.settle();
  await h.request(IDX + "times-2026.g2.json");
  await h.settle();
  const after = await names(h, "ct-shell-1");
  assert(!after.includes("/puzzles/idx/times-2026.g1.json"), "old shard version deleted: " + after);
  assert(!after.includes("/puzzles/idx/bundle.g1.json"), "old bundle deleted");
  assert(after.includes("/puzzles/idx/cryptic-2025.c1.json") && after.includes("/puzzles/idx/head-static.s1.js"), "files still named are kept");
  assert(after.includes("/puzzles/idx/times-2026.g2.json"), "the new shard is held");

  // Offline: head-live and the shards come from the cache.
  h.setOnline(false);
  const lv = await h.request(IDX + "head-live.json");
  assert(lv && JSON.parse(await (await lv).text()).bundle === "bundle.g2.json", "offline head-live is the held copy");
  const sh = await h.request(IDX + "cryptic-2025.c1.json");
  assert(sh && (await sh).ok, "offline shard is the held copy");
  const st = await h.request(IDX + "head-static.s1.js");
  assert(st && (await st).ok, "offline head-static is the held copy");

  // Puzzle files still go to the puzzle cache; the list files and idx never do.
  const h2 = harness({ "/puzzles/x/times-1.js.gz": ["p", "application/gzip"] });
  await h2.request(SCOPE + "puzzles/x/times-1.js.gz?v=aa");
  assert((await names(h2, "ct-puzzles-1")).length === 1, "only the puzzle is in the puzzle cache: " + (await names(h2, "ct-puzzles-1")));

  if (fails.length) { console.error(fails.map((f) => "FAIL: " + f).join("\n")); process.exit(1); }
  console.log("ok");
})();
