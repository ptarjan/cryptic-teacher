/* Google Analytics, in one file because two pages load it.

   index.html and the 437 pages tools/build_seo_pages.py writes both point at
   this, so there is exactly one measurement id on the site. A second copy of a
   gtag snippet drifts silently: the page with the stale id keeps reporting, to
   a property nobody reads.

   On its own this would measure arrivals and nothing after them, because the
   solve happens in localStorage and never leaves the browser. So app.js reports
   the same milestones it sends to sync/worker.js through gtag as well — one
   story in one place, with the hyphens in sync/events.js turned into the
   underscores GA4 accepts. The counters in KV stay: they are the copy that
   survives a blocker, and the copy with nothing in it but a name.

   Which clue, which puzzle and which answer are not sent to either.

   Fails silently from file:// and behind a blocker, like every other thing on
   this page that is not the crossword. */
(function () {
  "use strict";
  var ID = "G-JX21DWG8J5";
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag("js", new Date());
  window.gtag("config", ID);
  var s = document.createElement("script");
  s.async = true;
  s.src = "https://www.googletagmanager.com/gtag/js?id=" + ID;
  document.head.appendChild(s);
})();
