/* The service worker exists so that a push has somewhere to be delivered, and
   for nothing else.

   In particular it does not cache. The site is a static deploy whose asset URLs
   are content-stamped (tools/stamp_assets.py), so the network already returns
   the right file and a cache here could only ever hold an older one. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

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
