/* The clue a search visitor came for, on a /puzzles/<id>/ answers page.

   Most people who reach an answers page from Google typed one clue, not the
   puzzle's number (tools/build_seo_pages.py, puzzle_page). Google sends them
   with a text fragment (#:~:text=<the clue>), the browser scrolls to and paints
   those words before any script runs, and then strips the fragment from
   location, so the only trace a page can read is where it has been scrolled to.
   A visitor arriving at #12-across (a per-clue anchor: every clue is an
   <article id="<number>-<direction>">) is the other way in.

   Either way the clue gets marked, and under it one quiet line offering the
   rest of the crossword in the solver, opened on this clue: the hint ladder is
   what the site is for, and this is the moment the reader is looking at a clue
   they could not get. Nothing is hidden and nothing pops up; a reader who came
   from anywhere else, or reloaded, or scrolled first, sees the page unchanged.

   Two events, both on sync/events.js's list (tools/smoke_test.js checks it):
   "clue-landed" when a clue was found and marked, "clue-hint" when its line was
   followed. Sent the way app.js's beacon() sends, to GA and the sync Worker,
   and not at all from the site owner's own browsers (localStorage ct-internal). */
(function () {
  "use strict";
  var script = document.currentScript;
  var pid = script && script.getAttribute("data-p");
  if (!pid || !window.addEventListener) return;
  // app.js's SYNC_ENDPOINT; tools/smoke_test.js keeps the two the same.
  var SYNC_ENDPOINT = "https://cryptic-teacher-sync.curly-unit-b9e0.workers.dev";
  var SEARCH = /(^|\.)(google|bing|duckduckgo|ecosia|yahoo|qwant|startpage|brave|yandex|baidu|kagi)\.[a-z.]+$/;

  function beacon(name) {
    try { if (localStorage.getItem("ct-internal")) return; } catch (e) { /* counted */ }
    try { if (window.gtag) window.gtag("event", name.replace(/-/g, "_")); } catch (e) { /* never worth throwing */ }
    try {
      if (navigator.sendBeacon)
        navigator.sendBeacon(SYNC_ENDPOINT + "/e", new Blob([name], { type: "text/plain" }));
    } catch (e) { /* never worth throwing */ }
  }

  function clues() {
    return Array.prototype.slice.call(document.querySelectorAll(".s-list article[id]"));
  }

  // A real arrival, not a reload or back/forward: those restore a scroll the
  // reader made themselves.
  function freshNavigation() {
    try {
      var n = performance.getEntriesByType("navigation")[0];
      return !n || n.type === "navigate";
    } catch (e) { return true; }
  }

  function fromSearch() {
    try { return SEARCH.test(new URL(document.referrer).hostname); } catch (e) { return false; }
  }

  // The clue the browser scrolled a text fragment to: the one across the
  // middle of the viewport, where the browser centres the matched words.
  function scrolledTo() {
    if (!(window.scrollY > 0)) return null;
    var mid = window.innerHeight / 2, best = null, dist = Infinity;
    clues().forEach(function (a) {
      var r = a.getBoundingClientRect();
      var d = r.top <= mid && r.bottom >= mid ? 0 : Math.min(Math.abs(r.top - mid), Math.abs(r.bottom - mid));
      if (d < dist) { dist = d; best = a; }
    });
    return dist <= mid ? best : null;
  }

  function byHash() {
    var id = "";
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (e) { return null; }
    if (!/^\d+-(across|down)$/.test(id)) return null;
    var a = document.getElementById(id);
    return a && a.tagName === "ARTICLE" ? a : null;
  }

  function mark(a, how) {
    if (!a || a.getAttribute("data-landed")) return;
    a.setAttribute("data-landed", how);
    a.className = (a.className ? a.className + " " : "") + "s-landed";
    var m = /^(\d+)-(a|d)/.exec(a.id);
    var p = document.createElement("p");
    p.className = "s-hint";
    var link = document.createElement("a");
    link.href = "../../?p=" + encodeURIComponent(pid) + "&c=" + m[1] + m[2].toUpperCase();
    link.textContent = "Solve the rest with hints";
    link.addEventListener("click", function () { beacon("clue-hint"); });
    p.appendChild(document.createTextNode("Stuck on another clue? "));
    p.appendChild(link);
    p.appendChild(document.createTextNode(" · a nudge at a time, the answer only if you ask"));
    // Under the clue itself, above its explanation.
    var clue = a.querySelector("h3 + p");
    a.insertBefore(p, clue ? clue.nextSibling : a.firstChild.nextSibling);
    beacon("clue-landed");
  }

  // Input before the check means the scroll position is the reader's own.
  var touched = false;
  ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (t) {
    window.addEventListener(t, function () { touched = true; }, { once: true, passive: true });
  });

  function land() {
    var a = byHash();
    if (a) return mark(a, "hash");
    if (touched || !freshNavigation() || !fromSearch()) return;
    mark(scrolledTo(), "fragment");
  }

  // The fragment scroll happens as the document finishes loading; look once it
  // has had its frame.
  function later() { setTimeout(land, 150); }
  if (document.readyState === "complete") later();
  else window.addEventListener("load", later);
  window.addEventListener("hashchange", function () { mark(byHash(), "hash"); });
})();
