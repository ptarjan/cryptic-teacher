/* Google Analytics, in one file because two pages load it.

   index.html and the 437 pages tools/build_seo_pages.py writes both point at
   this, so there is exactly one measurement id on the site. A second copy of a
   gtag snippet drifts silently: the page with the stale id keeps reporting, to
   a property nobody reads.

   This measures PAGES — arrivals, where they came from, which puzzles get
   opened. It cannot measure solving, and is not meant to: the solve happens in
   localStorage and never leaves the browser, which is the whole reason
   sync/events.js exists. Nothing about a clue, a hint or an answer is sent
   here. The two are separate on purpose, and the anonymous counters are the
   ones that answer whether the teaching works.

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
