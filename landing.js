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
   they could not get. Nothing is hidden and nothing pops up.

   Most search clicks carry no fragment at all: Brave Search never adds one,
   and Google only does for some results. The referrer is the engine's bare
   origin, so the words searched for never reach the page. Those visitors get a
   small "find your clue" box at the top instead, which jumps to and marks the
   clue they type a few words of (or "5 down"). A visitor from our own pages,
   or one who reloaded or scrolled first, sees the page unchanged.

   iOS Safari can apply the fragment scroll after load, so the check runs again
   on any scroll the reader did not make in the first few seconds. And the
   referrer is not required for a fragment: in-app browsers and some privacy
   settings send none, and a fresh page that scrolled itself before any input
   was sent to a clue by its link.

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

  // Somewhere outside the site, or nowhere we are told of.
  function fromOutside() {
    if (!document.referrer) return true;
    try { return new URL(document.referrer).host !== location.host; } catch (e) { return true; }
  }

  var landed = false;
  function check() {
    if (landed) return;
    var a = byHash();
    if (a) { landed = true; return mark(a, "hash"); }
    if (touched || !freshNavigation() || !(fromSearch() || !document.referrer)) return;
    a = scrolledTo();
    if (a) { landed = true; mark(a, "fragment"); }
  }

  function norm(t) { return (" " + t.toLowerCase().replace(/[^a-z0-9]+/g, " ") + " "); }

  // The clues containing every word typed, else the ones containing most of
  // them; "5 down", "5d" or "5" go straight to that number.
  function matches(q) {
    var all = clues(), n = /^\s*(\d+)\s*([ad])?/i.exec(q);
    if (n && /^\s*\d+\s*(a|d|across|down)?\s*$/i.test(q))
      return all.filter(function (a) {
        return a.id.split("-")[0] === n[1] && (!n[2] || a.id.split("-")[1][0] === n[2].toLowerCase());
      });
    var words = norm(q).trim().split(" ").filter(Boolean);
    if (!words.length) return [];
    var scored = all.map(function (a) {
      var c = a.querySelector("h3 + p"), t = norm(c ? c.textContent : "");
      return { a: a, n: words.filter(function (w) { return t.indexOf(w) >= 0; }).length };
    });
    var top = Math.max.apply(null, scored.map(function (s) { return s.n; }));
    if (top < Math.max(1, Math.ceil(words.length / 2))) return [];
    return scored.filter(function (s) { return s.n === top; }).map(function (s) { return s.a; });
  }

  // The fallback for a search visit with no fragment: the page cannot know
  // which clue was searched for, so it asks, once, near the top.
  function offerFind() {
    if (landed || document.querySelector(".s-find") || !freshNavigation() || !fromOutside() ||
        !(fromSearch() || !document.referrer) || window.scrollY > 0 || !clues().length) return;
    var anchor = document.querySelector(".s-facts") || document.querySelector("main h1");
    if (!anchor) return;
    var form = document.createElement("form");
    form.className = "s-find";
    form.setAttribute("role", "search");
    var label = document.createElement("label");
    label.textContent = "Looking for one clue? ";
    var input = document.createElement("input");
    input.type = "search";
    input.placeholder = "a few words of it, or 5 down";
    input.setAttribute("enterkeyhint", "search");
    label.appendChild(input);
    var go = document.createElement("button");
    go.type = "submit";
    go.textContent = "Find";
    var said = document.createElement("span");
    said.className = "s-find-said";
    said.setAttribute("aria-live", "polite");
    form.appendChild(label);
    form.appendChild(go);
    form.appendChild(said);
    var last = "", at = 0;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var q = input.value, found = matches(q);
      if (!found.length) { said.textContent = " No clue here with those words."; return; }
      at = q === last ? (at + 1) % found.length : 0;
      last = q;
      said.textContent = found.length > 1 ? " " + (at + 1) + " of " + found.length + " (Find again for the next)" : "";
      var a = found[at];
      clues().forEach(function (c) {
        if (c !== a && c.getAttribute("data-landed") === "find") {
          c.removeAttribute("data-landed");
          c.className = c.className.replace(/\s*\bs-landed\b/, "");
          var h = c.querySelector("p.s-hint");
          if (h) h.parentNode.removeChild(h);
        }
      });
      mark(a, "find");
      landed = true;
      input.blur();
      a.scrollIntoView({ block: "start", behavior: "smooth" });
    });
    anchor.parentNode.insertBefore(form, anchor.nextSibling);
  }

  // The fragment scroll happens as the document finishes loading (later on
  // iOS Safari); look once it has had its frame, then on any scroll nobody
  // made during the next few seconds.
  function start() {
    setTimeout(function () {
      check();
      offerFind();
      var t = null, stop = Date.now() + 4000;
      function onScroll() {
        if (landed || touched || Date.now() > stop) return window.removeEventListener("scroll", onScroll);
        clearTimeout(t);
        t = setTimeout(check, 150);
      }
      window.addEventListener("scroll", onScroll, { passive: true });
    }, 150);
  }
  if (document.readyState === "complete") start();
  else window.addEventListener("load", start);
  window.addEventListener("hashchange", function () { mark(byHash(), "hash"); });
})();
