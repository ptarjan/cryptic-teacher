/* The site as an iOS home-screen app: a tab bar, and a way back.

   Added to the home screen, the site runs with no browser around it
   (site.webmanifest's "display": "standalone"): no back button, no address
   bar, and swipe-back that iOS honours only sometimes. Following "More in the
   lesson" from a hint then left a solver on /learn/ with no way back to the
   crossword they were in the middle of. So, in that mode only:

   - a bottom tab bar on every page: Solve (the one in progress, as left:
     the grid is saved in localStorage and the app reopens ct:last), Library
     (the app's picker), Stats (the app's stats panel) and Learn (/learn/);
   - a "‹ Back" (or "‹ Puzzle") at the top of any page reached from another
     page of this site, which is history.back(): the page you came from, as
     you left it.

   In a browser tab neither appears: the browser has its own back and its own
   bottom toolbar, and a second bar under Safari's would eat a phone's screen
   for controls the header already has.

   Loaded in <head>, not deferred, by index.html (data-app) and every page
   tools/build_seo_pages.py templates, so html.standalone and the room the bar
   needs are set before the first paint and nothing moves when it arrives.
   tools/test_app_nav.js runs it. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement, win = window;
  var standalone = false;
  try {
    standalone = !!(win.navigator.standalone ||
      (win.matchMedia && win.matchMedia("(display-mode: standalone)").matches));
  } catch (e) { /* no matchMedia: a browser tab */ }
  if (!standalone || !root.classList) return;
  root.classList.add("standalone");

  var script = doc.currentScript;
  var isApp = !!(script && script.hasAttribute("data-app"));
  // The site root on this host: the script sits at the root (absolute, or
  // ../../ from a puzzle page), and the page's own origin keeps a local
  // preview local.
  var rootPath = "/";
  try { rootPath = new URL("./", script.src).pathname; } catch (e) { /* stays "/" */ }
  var home = location.origin + rootPath;

  function lastPuzzle() {
    try { var v = localStorage.getItem("ct:last"); return v ? JSON.parse(v) : null; }
    catch (e) { return null; }
  }
  function puzzleHref() {
    var id = lastPuzzle();
    return id ? home + "?p=" + encodeURIComponent(id) : home;
  }
  function referrer() {
    try { var r = new URL(doc.referrer); return r.origin === location.origin ? r : null; }
    catch (e) { return null; }
  }
  // Whether the page before this one was the app. Its address is the root
  // (?p=) or, once a puzzle is chosen, /puzzles/<id>/ with the flag app.js
  // sets for app_return in tools/build_seo_pages.py, which also sends a back
  // to that address into the app rather than to the write-up.
  function fromApp() {
    var r = referrer();
    if (!r) return false;
    if (r.pathname === rootPath) return true;
    var m = r.pathname.slice(rootPath.length).match(/^puzzles\/([^/]+)\/$/);
    try { return !!(m && sessionStorage.getItem("ct:app:" + decodeURIComponent(m[1]))); }
    catch (e) { return false; }
  }
  function canGoBack() { return !!referrer() && win.history && win.history.length > 1; }

  function section() {
    if (isApp) return "puzzle";
    var p = location.pathname.slice(rootPath.length);
    if (/^(puzzles|showcase)\//.test(p)) return "puzzles";
    if (/^(learn|abbreviations|indicators|difficulty)\//.test(p)) return "learn";
    return "";
  }

  var ICON = {
    puzzle: '<rect x="3.5" y="3.5" width="17" height="17" rx="1.5"/><path d="M9.2 3.5v17M14.8 3.5v17M3.5 9.2h17M3.5 14.8h17"/>'
      + '<rect x="9.2" y="9.2" width="5.6" height="5.6" fill="currentColor"/>',
    puzzles: '<path d="M12 3.5l9 4.5-9 4.5L3 8z"/><path d="M3 12.2l9 4.5 9-4.5M3 16.4l9 4.5 9-4.5"/>',
    stats: '<path d="M5 20V12M12 20V5M19 20v-9"/>',
    learn: '<path d="M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5C17 4.5 14 5 12 6.5zM12 6.5v13"/>',
  };
  // panel/btn: the app's own control for it, pressed when the bar is on the app.
  var TABS = [
    { key: "puzzle", label: "Solve", href: puzzleHref },
    { key: "puzzles", label: "Library", href: function () { return home + "#picker"; }, panel: "picker-panel", btn: "btn-picker" },
    { key: "stats", label: "Stats", href: function () { return home + "#stats"; }, panel: "stats-panel", btn: "btn-stats" },
    { key: "learn", label: "Learn", href: function () { return home + "learn/"; } },
  ];

  function el(id) { return doc.getElementById(id); }
  function open(panel) { var p = el(panel); return !!(p && !p.classList.contains("hidden")); }

  function mark(bar, key) {
    var links = bar.querySelectorAll("a");
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute("data-tab") === key) links[i].setAttribute("aria-current", "page");
      else links[i].removeAttribute("aria-current");
    }
  }
  // On the app, the tab lit is whichever panel is open, else Puzzle.
  function appSection() {
    for (var i = 0; i < TABS.length; i++) if (TABS[i].panel && open(TABS[i].panel)) return TABS[i].key;
    return "puzzle";
  }

  function onTab(tab, e) {
    if (isApp) {
      if (tab.panel) {
        e.preventDefault();
        if (!open(tab.panel) && el(tab.btn)) el(tab.btn).click();
        win.scrollTo(0, 0);
      } else if (tab.key === "puzzle") {
        e.preventDefault();
        TABS.forEach(function (t) {
          if (t.panel && open(t.panel) && el(t.btn)) el(t.btn).click();
        });
      }
      return;
    }
    // Straight back into the app, as it was left, when that is where this
    // page was opened from; otherwise the link reopens the saved puzzle.
    if (tab.key === "puzzle" && fromApp() && canGoBack()) {
      e.preventDefault();
      win.history.back();
    }
  }

  // The tabs that are other documents (Learn, and the app from a static page)
  // are fetched before they are tapped, so a switch is a render, not a round
  // trip. Speculation Rules where the browser has them (a prerender is a
  // finished page), link prefetch elsewhere. The app's own panels are already
  // in the page and need nothing.
  function warm() {
    var urls = [];
    if (section() !== "learn") urls.push(home + "learn/");
    if (!isApp) urls.push(home);
    var rules = false;
    try { rules = !!(win.HTMLScriptElement && win.HTMLScriptElement.supports && win.HTMLScriptElement.supports("speculationrules")); }
    catch (e) { /* no supports() */ }
    if (rules) {
      var s = doc.createElement("script");
      s.type = "speculationrules";
      s.textContent = JSON.stringify({ prerender: [{ source: "list", urls: urls, eagerness: "eager" }] });
      doc.head.appendChild(s);
      return;
    }
    urls.forEach(function (u) {
      var l = doc.createElement("link");
      l.rel = "prefetch"; l.href = u;
      doc.head.appendChild(l);
    });
  }

  function tabBar() {
    var bar = doc.createElement("nav");
    bar.className = "tabbar";
    bar.setAttribute("aria-label", "Sections");
    TABS.forEach(function (tab) {
      var a = doc.createElement("a");
      a.setAttribute("data-tab", tab.key);
      a.href = tab.href();
      a.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + ICON[tab.key] + "</svg><span>" + tab.label + "</span>";
      // Like a UITabBar the switch happens on the finger going down, not on the
      // click after the lift. Only the tabs that are panels of this page do:
      // a tab that is another document still navigates on click. The click that
      // follows is swallowed, and the lit tab moves before the panel's work.
      var fired = false;
      a.addEventListener("pointerdown", function (e) {
        if (!isApp || (e.button || 0) !== 0 || !(tab.panel || tab.key === "puzzle")) return;
        fired = true;
        mark(bar, tab.key);
        onTab(tab, e);
      });
      a.addEventListener("click", function (e) {
        if (fired) { fired = false; e.preventDefault(); return; }
        a.href = tab.href();   // ct:last moves while the page is open
        onTab(tab, e);
      });
      bar.appendChild(a);
    });
    doc.body.appendChild(bar);
    warm();
    mark(bar, isApp ? appSection() : section());
    if (isApp && win.MutationObserver) {
      var watch = new win.MutationObserver(function () { mark(bar, appSection()); });
      TABS.forEach(function (t) { if (t.panel && el(t.panel)) watch.observe(el(t.panel), { attributes: true, attributeFilter: ["class"] }); });
    }
    return bar;
  }

  function backLink() {
    var header = doc.querySelector("header");
    if (isApp || !header || !canGoBack()) return null;
    var a = doc.createElement("a");
    a.className = "app-back";
    a.href = fromApp() ? puzzleHref() : referrer().href;
    a.textContent = fromApp() ? "‹ Puzzle" : "‹ Back";
    a.addEventListener("click", function (e) { e.preventDefault(); win.history.back(); });
    header.insertBefore(a, header.firstChild);
    return a;
  }

  // A soft keyboard covers the bottom of the layout viewport, and a fixed bar
  // rides up into the visible part as iOS pans it, so the bar steps aside
  // while one is up (the gap app.js's keyboardUp() measures).
  function keyboard() {
    var vv = win.visualViewport;
    root.classList.toggle("kbd-up", !!(vv && vv.height && win.innerHeight - vv.height >= 100));
  }

  function build() {
    tabBar();
    backLink();
    keyboard();
    if (win.visualViewport) win.visualViewport.addEventListener("resize", keyboard);
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", build);
  else build();
})();
