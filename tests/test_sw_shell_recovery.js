// The home-screen app must never boot as bare HTML (Paul 10-30: "My css seems
// broken in my app" — Times text, every panel open, no app). sw.js is run
// here in a vm against an in-memory Cache Storage and a network that can be
// switched off:
//
//   1. Offline, a navigation to /puzzles/<id>/ (the app writes that into the
//      bar) is a redirect to ./?p=<id>, never the home HTML served at that
//      address, where its relative style.css and app.js resolve to
//      /puzzles/<id>/style.css and fail.
//   2. Offline, a stamp the cache does not hold falls back to another stamp
//      of the same file, so a held home page whose stamps were dropped still
//      gets a stylesheet; a client already in that state heals.
//   3. A "precache" from an older page does not delete the stamps the held
//      (newer) home page names, and fetches them if missing.
//   4. Online, a stamped file still comes from the network and is cached.
//
//     node tests/test_sw_shell_recovery.js
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
    handlers.fetch({ request: req, respondWith: (p) => { out = p; } });
    return out;
  }
  async function message(data) {
    let p;
    handlers.message({ data, ports: [], waitUntil: (x) => { p = x; } });
    await p;
  }
  return { request, message, caches, setOnline: (v) => { online = v; } };
}

const page = (v) => `<!doctype html><link rel="stylesheet" href="style.css?v=${v}"><script src="app.js?v=${v}"></script>`;

(async () => {
  const site = {
    "/": [page("bbbb"), "text/html"],
    "/style.css": ["body{font-family:system-ui}", "text/css"],
    "/app.js": ["1", "text/javascript"],
  };

  // ---- 1. offline navigation to the bar the app writes
  {
    const h = harness(site);
    await h.message({ type: "precache", urls: [SCOPE + "style.css?v=bbbb", SCOPE + "app.js?v=bbbb"] });
    h.setOnline(false);
    const res = await h.request(SCOPE + "puzzles/times-29687/", "navigate");
    assert(res && res.status === 302, "offline /puzzles/<id>/ is a redirect, not the home HTML at that address: status " + (res && res.status));
    assert(res && res.headers.get("location") === SCOPE + "?p=times-29687", "the redirect keeps the puzzle: " + (res && res.headers.get("location")));
    const other = await h.request(SCOPE + "learn/", "navigate");
    assert(other && other.status === 302 && other.headers.get("location") === SCOPE, "offline /learn/ goes to the front door");
    const home = await h.request(SCOPE + "?p=times-29687", "navigate");
    assert(home && home.status === 200 && /style\.css\?v=bbbb/.test(await home.text()), "the front door itself is the held home page");
  }

  // ---- 2. a held page naming a stamp the cache lost: the bad state heals
  {
    const h = harness(site);
    const shell = await h.caches.open("ct-shell-1");
    await shell.put(new Request(SCOPE), new Response(page("bbbb"), { headers: { "content-type": "text/html" } }));
    await shell.put(new Request(SCOPE + "style.css?v=aaaa"), new Response("body{font-family:old}", { headers: { "content-type": "text/css" } }));
    h.setOnline(false);
    let css = null;
    try { css = await h.request(SCOPE + "style.css?v=bbbb"); } catch (e) { css = null; }
    assert(css && css.ok && (await css.text()) === "body{font-family:old}", "offline, a missing stamp falls back to the held copy of style.css");
  }

  // ---- 3. an older page's precache keeps (and fetches) the held page's stamps
  {
    const h = harness(site);
    const shell = await h.caches.open("ct-shell-1");
    await shell.put(new Request(SCOPE), new Response(page("bbbb"), { headers: { "content-type": "text/html" } }));
    await shell.put(new Request(SCOPE + "style.css?v=bbbb"), new Response("new", { headers: { "content-type": "text/css" } }));
    await h.message({ type: "precache", urls: [SCOPE + "style.css?v=aaaa", SCOPE + "app.js?v=aaaa"] });
    assert(await shell.match(SCOPE + "style.css?v=bbbb"), "precache from an older page left the held page's stylesheet");
    assert(await shell.match(SCOPE + "app.js?v=bbbb"), "precache fetched the held page's app.js it lacked");
    assert(await shell.match(SCOPE + "style.css?v=aaaa"), "and kept the sending page's own");
    h.setOnline(false);
    const css = await h.request(SCOPE + "style.css?v=bbbb");
    assert(css && (await css.text()) === "new", "offline, the held page's exact stylesheet is served");
  }

  // ---- 4. online, unchanged behaviour
  {
    const h = harness(site);
    const css = await h.request(SCOPE + "style.css?v=cccc");
    assert(css && css.ok && /system-ui/.test(await css.text()), "online, a stamped file comes from the network");
    const shell = await h.caches.open("ct-shell-1");
    assert(await shell.match(SCOPE + "style.css?v=cccc"), "and is cached under its stamp");
    assert(h.request(SCOPE + "puzzles/times-29687/", "navigate") !== undefined, "navigations are still handled");
    const live = await h.request(SCOPE + "puzzles/times-29687/", "navigate");
    assert(live.status === 404, "online, /puzzles/<id>/ is whatever the server says (here 404)");
  }

  if (fails.length) { console.log("FAIL\n  " + fails.join("\n  ")); process.exit(1); }
  console.log("PASS test_sw_shell_recovery");
})().catch((e) => { console.log("FAIL", e); process.exit(1); });
