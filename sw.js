/* The service worker does two jobs: it delivers pushes, and it lets the app
   open with no network (a puzzle on a plane).

   Offline caching, by kind of request (same-origin GETs only; the sync Worker
   is another origin and is never touched here):
   - A STAMPED asset (a URL with ?v=<content hash>, tools/stamp_assets.py: the
     JS, CSS, icons, puzzles/index.js, and each puzzle's .gz) is CACHE-FIRST. Its
     URL changes whenever its bytes do, so a cached copy can never be stale.
   - The home page (HTML), and anything unstamped (puzzles/index.json, the
     manifest), is NETWORK-FIRST with the cache as the fallback, so an online
     visit always gets the newest deploy and an offline one gets the last copy.
     If the network has not answered in 4 seconds and a copy is held, the copy
     is used (a plane's wifi that is up but dead).
   - Puzzle files live in their own cache, capped at MAX_PUZZLES, oldest out
     first. Every puzzle the solver opens lands there, and the page sends a
     batch of URLs in a "save" message by itself: once idle after an online
     load (at most every 6h) and after a solve, with no tap needed. A new
     worker skips waiting and claims the page, so the first load is covered.
     One puzzle file holds the grid, the annotations and the hints.
   - sw.js itself is never cached here, so a new worker is always picked up.
   Old stamped copies of a file are dropped when the page announces its current
   set of assets in a "precache" message (the first visit has no worker yet to
   see the page's own requests, so the page tells it what it loaded).

   What is not kept: the /learn/ and archive pages, and anything the sync Worker
   serves. Those fail quietly offline. */

const SHELL = "ct-shell-1";
const PUZZLES = "ct-puzzles-1";
const MAX_PUZZLES = 250;        // above the page's batch of 100
const MAX_FILE_BYTES = 300 * 1024;   // a single puzzle file bigger than this is skipped
const NETWORK_WAIT_MS = 4000;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

const SCOPE = new URL("./", self.location).href;
const isPuzzleFile = (url) => /\/puzzles\/.+\.js(\.gz)?$/.test(url.pathname) && !/\/index\.js$/.test(url.pathname);
// The home page however it was opened (?p=<id>, a Home Screen start URL).
const isHome = (url) => {
  const at = url.origin + url.pathname;
  return at === SCOPE || at === SCOPE + "index.html";
};

async function trimPuzzles(cache) {
  const keys = await cache.keys();            // oldest first
  for (let i = 0; i < keys.length - MAX_PUZZLES; i++) await cache.delete(keys[i]);
}

async function cacheFirst(req, name) {
  const cache = await caches.open(name);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok && !res.redirected) {
    await cache.put(req, res.clone());
    if (name === PUZZLES) await trimPuzzles(cache);
  }
  return res;
}

// `key` is what the copy is filed under: the home page is one entry however
// many ?p=<id> addresses it was opened as.
async function networkFirst(req, name, key) {
  const cache = await caches.open(name);
  const held = await cache.match(key);
  const net = fetch(req).then((res) => {
    if (res.ok && !res.redirected) cache.put(key, res.clone());
    return res;
  });
  if (!held) return net;
  return Promise.race([
    net.catch(() => held),
    new Promise((ok) => setTimeout(() => ok(held), NETWORK_WAIT_MS)),
  ]);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || req.headers.has("range")) return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.endsWith("/sw.js")) return;
  // The page's update check asks for the home HTML with cache "no-store": it
  // wants the server's copy now, not the held one, so the worker stays out.
  if (req.cache === "no-store") return;

  if (req.mode === "navigate") {
    if (isHome(url)) {
      event.respondWith(networkFirst(req, SHELL, new Request(SCOPE)).catch(() =>
        caches.match(new Request(SCOPE)).then((r) => r || Response.error())));
    } else {
      // Another page (archive, /learn/): live when online; offline, the app.
      event.respondWith(fetch(req).catch(() =>
        caches.match(new Request(SCOPE)).then((r) => r || Response.error())));
    }
    return;
  }
  const name = isPuzzleFile(url) ? PUZZLES : SHELL;
  if (url.searchParams.has("v")) {
    event.respondWith(cacheFirst(req, name));
  } else {
    const key = new Request(url.origin + url.pathname);
    event.respondWith(networkFirst(req, name, key).catch(() =>
      caches.match(key).then((r) => r || Response.error())));
  }
});

// The page's messages. "precache": the assets it was loaded with. "save": a
// batch of puzzle files, answered on the port with {done, total, failed}.
self.addEventListener("message", (event) => {
  const d = event.data || {};
  const port = event.ports && event.ports[0];
  if (d.type === "precache") event.waitUntil(precache(d.urls || []));
  if (d.type === "save") event.waitUntil(savePuzzles(d.urls || [], port, d.drop || []));
});

async function precache(urls) {
  const cache = await caches.open(SHELL);
  const keep = new Set();
  for (const u of urls) {
    try {
      const url = new URL(u, SCOPE);
      if (url.origin !== self.location.origin || url.pathname.endsWith("/sw.js")) continue;
      keep.add(url.href);
      if (!(await cache.match(url.href))) await cache.add(new Request(url.href));
    } catch (e) { /* offline or a bad URL: the next load tries again */ }
  }
  try {
    if (!(await cache.match(new Request(SCOPE)))) await cache.add(new Request(SCOPE));
  } catch (e) { /* same */ }
  // A stamped URL this page no longer uses, for a path it still does.
  const paths = new Set([...keep].map((h) => h.split("?")[0]));
  for (const k of await cache.keys()) {
    if (k.url.includes("?v=") && paths.has(k.url.split("?")[0]) && !keep.has(k.url)) await cache.delete(k);
  }
}

async function savePuzzles(urls, port, drop) {
  const cache = await caches.open(PUZZLES);
  // Recycling: files the page says are solved or out of the batch (any ?v=).
  for (const u of drop) {
    try { await cache.delete(new Request(new URL(u, SCOPE).href), { ignoreSearch: true }); } catch (e) { /* skip */ }
  }
  let done = 0, failed = 0;
  for (const u of urls) {
    try {
      const req = new Request(new URL(u, SCOPE).href);
      if (!(await cache.match(req))) {
        const res = await fetch(req);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const buf = await res.arrayBuffer();
        // Oversize: not saved, not an error (the puzzle still opens online).
        if (buf.byteLength <= MAX_FILE_BYTES) await cache.put(req, new Response(buf, { headers: res.headers }));
      }
      done++;
    } catch (e) { failed++; }
    if (port) port.postMessage({ done, failed, total: urls.length });
  }
  await trimPuzzles(cache);
  if (port) port.postMessage({ done, failed, total: urls.length, finished: true });
}

/* A push MUST result in a visible notification. A browser that sees one pass
   silently substitutes its own "this site was updated in the background", and
   revokes the permission if it keeps happening — so a payload that will not
   parse still shows something rather than nothing. */
self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = {}; }
  event.waitUntil(self.registration.showNotification(d.title || "A new puzzle is up", {
    body: d.body || "",
    icon: "icon-192.png",
    badge: "icon-192.png",
    // One notification per puzzle: a second push for the same one replaces it
    // rather than stacking, which is what happens if a run is retried.
    tag: d.tag || "cryptic-teacher",
    data: { url: d.url || "./" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "./";
  const scope = new URL("./", self.location).href;
  // A tab already on the site is the one with the solver's grid in it, so the
  // notification steers that tab instead of opening a second copy of the app.
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true })
    .then((wins) => {
      for (const w of wins) {
        if (!w.url.startsWith(scope)) continue;
        if (w.navigate) return w.navigate(url).then((c) => (c || w).focus());
        return w.focus();
      }
      return self.clients.openWindow(url);
    }));
});
