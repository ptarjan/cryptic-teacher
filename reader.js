/* Is a person reading this page? The one gate every count on the site waits on.

   GA (analytics.js: its page_view, session and every event), the KV counters
   app.js sends to sync/worker.js, and the answers-page beacons in landing.js
   all go through CTReader.when(fn). Nothing on the site reports anything
   before it passes, and nothing else decides it, so "what counts as a
   visitor" has one answer in one place.

   What a page has to show, all of it observable without identifying anyone:

   1. No automation tell. navigator.webdriver is the standard flag a driven
      browser must raise; a user agent that names itself (headless, a crawler,
      a scripting library) and an empty navigator.languages are the other
      cheap tells. A page with any of them never passes. A stealth browser
      hides all three, so they only stop the honest ones.

   2. The reader's attention: the page is visible AND the document has focus.
      A person's page has focus while they read it (it is the window they
      clicked into, the tab in front, the app on screen). A headless browser's
      page normally does not: document.hasFocus() is false unless the driver
      goes out of its way to emulate focus. It is the same signal GA itself
      measures engagement time by, and a page that can be pressed, scrolled or
      typed into but never focused is a script driving it.

   3. One of two things while attentive:
      - a trusted gesture (pointerdown, keydown, touchstart, wheel). isTrusted
        only says the browser, not page script, made the event; a driver that
        injects input through the devtools protocol makes trusted events too,
        which is why the gesture alone is not enough and must land on a
        focused page. Focus is checked again after the gesture's default
        action has run, because a click is what focuses the page;
      - or DWELL_MS of continuous attention, for the reader who reads without
        touching anything (a short answer page on a desktop, a dialog they
        look at and leave). Losing focus or visibility restarts the clock.

   Not a fingerprint and not a blocklist: no IP, no named fleet, no window
   size. A driver that emulates focus and sends input gets through, and so be
   it; the gate is set where a real reader always is and a farm of unattended
   headless pages is not.

   Loaded by every page before analytics.js, as its own file: it must not
   share a name a blocker drops, because the KV counters are the copy meant to
   survive one. If it fails to load, CTReader is missing and every caller
   counts nothing. */
(function () {
  "use strict";
  var DWELL_MS = 3000;
  var GESTURES = ["pointerdown", "keydown", "touchstart", "wheel"];
  var AUTOMATION_UA = /bot|crawl|spider|slurp|headless|phantom|lighthouse|puppeteer|playwright|selenium|python|curl|wget|httpclient|facebookexternalhit|preview|monitor/i;

  function automated() {
    try {
      return !!(navigator.webdriver || AUTOMATION_UA.test(navigator.userAgent || "") ||
                (navigator.languages && navigator.languages.length === 0));
    } catch (e) { return true; }
  }

  function attentive() {
    try { return document.visibilityState === "visible" && document.hasFocus(); }
    catch (e) { return false; }
  }

  var passed = false;
  var waiting = [];
  var dwell = null;
  var gone = automated();

  function run(fn) { try { fn(); } catch (e) { /* a count is never worth an exception */ } }

  function pass() {
    if (passed || gone) return;
    passed = true;
    stopDwell();
    GESTURES.forEach(function (t) { window.removeEventListener(t, onGesture, true); });
    window.removeEventListener("focus", watch);
    window.removeEventListener("blur", watch);
    document.removeEventListener("visibilitychange", watch);
    waiting.splice(0).forEach(run);
  }

  function stopDwell() { if (dwell) { clearTimeout(dwell); dwell = null; } }

  // Attention lost stops the clock; attention (re)gained starts a fresh one.
  function watch() {
    if (!attentive()) { stopDwell(); return; }
    if (dwell) return;
    dwell = setTimeout(function () {
      dwell = null;
      if (attentive()) pass(); else watch();
    }, DWELL_MS);
  }

  function onGesture(e) {
    if (passed || !e || e.isTrusted !== true) return;
    if (attentive()) { pass(); return; }
    setTimeout(function () { if (attentive()) pass(); }, 0);
  }

  if (!gone) {
    GESTURES.forEach(function (t) { window.addEventListener(t, onGesture, true); });
    window.addEventListener("focus", watch);
    window.addEventListener("blur", watch);
    document.addEventListener("visibilitychange", watch);
    watch();
  }

  window.CTReader = {
    // fn runs once, as soon as the page is known to have a reader (at once if
    // it already has); never, for a page that does not get one.
    when: function (fn) {
      if (gone) return;
      if (passed) run(fn); else waiting.push(fn);
    },
    passed: function () { return passed; },
  };
})();
