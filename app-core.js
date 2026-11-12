"use strict"; // app part 1 of 7 (helpers, cross-device sync, catalogue, the list, state). Classic script sharing the page scope with its siblings; see tools/app_src.js.

  // ---------- tiny helpers ----------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Words of a clue, as shown: stored straight, curled for the page (quotes.js).
  const escClue = (s) => esc(CTQuotes.curl(s));
  const letterOf = (s) => (s || "").toUpperCase().replace(/[^A-Z]/g, "");
  // What a square of the open puzzle takes: A-Z, or 0-9 in a numerical puzzle
  // (`numeric: true`, Listener No 111: every light is a number). Letters are
  // refused there and digits elsewhere, so a stray key is never a wrong square.
  const isNumeric = () => !!(P && P.numeric);
  const squareKey = (k) => (isNumeric() ? /^[0-9]$/ : /^[a-zA-Z]$/).test(k);
  const squareChars = (s) => (s || "").toUpperCase().replace(isNumeric() ? /[^0-9]/g : /[^A-Z]/g, "");

  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
      catch (e) { return fallback; }
    },
    set(key, val) {
      try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* private mode etc. */ }
      forgetSavedProgress(key);
    },
    del(key) { try { localStorage.removeItem(key); } catch (e) {} forgetSavedProgress(key); }
  };

  /* ---------- what solvers thought of it ----------

     One tap, and only once the clue is out: before the answer is on the grid
     "was that a good clue" is a question about how stuck you are, not about the
     clue. The puzzle gets the same question when the last square goes in.

     The Worker stores a key per vote plus one running tally per puzzle (see /v
     in sync/worker.js), and nothing about who voted. The cost of that is the
     honest one: a ballot box that cannot identify a voter cannot spot a second
     ballot either, so one-vote-per-clue is this device remembering, and
     clearing the browser buys another vote. That is a fair price for keeping the votes anonymous.

     The whole puzzle's tally arrives in ONE request, not one per clue, and only
     when the first vote row is drawn: a grid opened and left, or loaded by a
     crawler, never shows a row, and fetching on open cost a KV read per page
     view (100k a day once a headless crawler walked the clue pages). Everything here is best-effort: no tally is a row with no numbers
     in it, never an error in front of somebody solving.  */
  const VOTES_KEY = "ct:votes";
  let myVotes = store.get(VOTES_KEY, {}) || {};
  let voteTally = {};

  const voteTarget = (e) => (e ? `c:${P.id}:${entryKey(e)}` : `p:${P.id}`);

  let votesAsked = null;   // the puzzle id whose tally has been asked for
  const BOT_UA = /bot|crawl|spider|slurp|headless|lightpanda|phantom|puppeteer|playwright/i;

  function forgetVotes() { voteTally = {}; votesAsked = null; }

  function fetchVotes(id) {
    if (votesAsked === id) return;
    votesAsked = id;
    if (!SYNC_ENDPOINT || typeof fetch !== "function") return;
    if (navigator.webdriver || BOT_UA.test(navigator.userAgent || "")) return;
    fetch(`${SYNC_ENDPOINT}/v?p=${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((t) => {
        // The grid may have moved on while this was in the air; a tally is
        // about one puzzle and must never be shown against another.
        if (!t || !P || P.id !== id) return;
        voteTally = t;
        renderHintPanel();
        // The finish panel draws once and then holds still, so the arrival of
        // the numbers is the one thing allowed to make it draw again.
        tallyDrawn = false;
        celebrate(wasComplete === true, false);
      })
      .catch(() => {});
  }

  function castVote(target, verdict) {
    if (myVotes[target]) return;
    myVotes[target] = verdict;
    store.set(VOTES_KEY, myVotes);
    // Counted here as well as at the Worker, so the row answers the tap rather
    // than waiting for a round trip it is not going to look at.
    const t = (voteTally[target] = voteTally[target] || { up: 0, down: 0 });
    t[verdict]++;
    tallyDrawn = false;
    const body = `${target}|${verdict}`;
    try {
      if (!SYNC_ENDPOINT) return;
      if (navigator.sendBeacon)
        navigator.sendBeacon(SYNC_ENDPOINT + "/v", new Blob([body], { type: "text/plain" }));
      else if (typeof fetch === "function")
        fetch(SYNC_ENDPOINT + "/v", { method: "POST", body, keepalive: true }).catch(() => {});
    } catch (e) { /* a vote is never worth an exception in the middle of a solve */ }
  }

  // The row reads as a sentence once it has been answered: what you said, and
  // what everyone else said, in that order. Before that it is the question and
  // two buttons. Numbers only when there are any — "0 of 0 liked it" is a way
  // of saying nobody has been here, which is not a thing to tell a solver.
  function voteRowHTML(target, ask, yes, no) {
    if (P) fetchVotes(P.id);
    const mine = myVotes[target];
    const t = voteTally[target] || { up: 0, down: 0 };
    const said = t.up + t.down;
    const others = said - (mine ? 1 : 0);
    const crowd = others > 0
      ? `<span class="vote-said">${t.up} of ${said} liked it</span>` : "";
    if (mine) {
      return `<div class="vote-row"><span class="vote-mine">${
        mine === "up" ? "You liked it" : "You didn’t like it"}</span>${crowd}</div>`;
    }
    return `<div class="vote-row"><span class="vote-ask">${ask}</span>` +
      `<button type="button" class="ghost small vote-btn" data-vote="${esc(target)}|up">${yes}</button>` +
      `<button type="button" class="ghost small vote-btn" data-vote="${esc(target)}|down">${no}</button>` +
      `${crowd}</div>`;
  }

  // Wires whatever vote buttons a freshly drawn container holds, and redraws it
  // through the same path that drew it: a vote changes the row it was cast in.
  function wireVotes(el, redraw) {
    if (!el || !el.querySelectorAll) return;
    el.querySelectorAll("button.vote-btn").forEach((b) => {
      b.onclick = () => {
        const [target, verdict] = (b.getAttribute("data-vote") || "").split("|");
        if (!target || !verdict) return;
        castVote(target, verdict);
        redraw();
      };
    });
  }

  // ---------- sync across machines ----------
  // The Worker in sync/. Blank it and every path below goes inert and the Sync
  // button hides itself, so the page keeps working exactly as it did offline —
  // which is also what happens for anyone who never turns sync on.
  const SYNC_ENDPOINT = "https://cryptic-teacher-sync.curly-unit-b9e0.workers.dev";
  // Reserved localStorage names, so scanning for saves cannot pick up settings.
  // Every key this app writes is "ct:<something>"; the rest are puzzle ids.
  const SYNC_RESERVED = { last: 1, sync: 1, seen: 1, nux: 1, notify: 1, "notify-after": 1, votes: 1, paper: 1, picker: 1 };
  const CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"; // no 0/O/1/I/L to mistype

  /* ---------- counting solves, not solvers ----------
     Solving happens in localStorage, so the only thing anybody outside this
     browser can see is that the page loaded. Whether a visitor typed a letter,
     took a hint or finished the grid was unknowable, and every question about
     whether the teaching works starts there.

     What is sent is one name from sync/events.js and nothing else — no puzzle,
     no clue, no identifier, no time. sync/worker.js stores it as a key name.

     AT MOST ONCE PER NAME PER PUZZLE PER SESSION. A solver climbing six rungs on
     thirty clues owes six beacons, not a hundred and eighty; the set below is
     what makes the difference, and openPuzzle empties it.

     Fire and forget. sendBeacon hands the request to the browser to send when it
     likes, there is no reply and nothing to await, and a browser without it — or
     with sync/events.js blocked — simply reports nothing. Nothing on this path
     may delay a keystroke or throw into one.

     Unrelated to sync. Sync moves a solver's own grids between their own
     devices; this is a counter. Someone who has never opened the sync panel is
     counted the same as someone who has. */
  let eventsSent = new Set();
  // Not "ct:"-prefixed, so localEnvelope() never mistakes it for a puzzle.
  // analytics.js reads the same key by name.
  const INTERNAL_KEY = "ct-internal";
  // Automation announces itself (webdriver) or names itself (UA). Such a page
  // is not a visitor, so it counts nothing; the Worker drops the same UAs.
  const BOT_UA = /bot|crawl|spider|slurp|headless|phantom|lighthouse|puppeteer|playwright|selenium|python|curl|wget|httpclient|facebookexternalhit|preview|monitor/i;
  function looksAutomated() {
    try {
      return !!(navigator.webdriver || BOT_UA.test(navigator.userAgent || "") ||
                (navigator.languages && navigator.languages.length === 0));
    } catch (e) { return false; }
  }
  function beacon(name) {
    if (eventsSent.has(name)) return;
    if (looksAutomated()) return;
    try { if (localStorage.getItem(INTERNAL_KEY)) return; } catch (e) { /* counted */ }
    eventsSent.add(name);
    // The list is the contract with the Worker and is checked at both ends, so a
    // name that is not on it is a bug in this file and stops here.
    if (typeof CTEvents === "undefined" || CTEvents.indexOf(name) < 0) return;
    // The same milestone goes to GA, which otherwise sees the arrival and
    // nothing after it — the two would be one story told in two places, and the
    // interesting half only exists here. GA4 event names take letters and
    // underscores, so the hyphen goes and "hint-type" reads as "hint_type".
    try {
      if (window.gtag) window.gtag("event", name.replace(/-/g, "_"));
    } catch (e) { /* a counter is never worth an exception in the middle of a solve */ }
    try {
      if (SYNC_ENDPOINT && navigator.sendBeacon)
        navigator.sendBeacon(SYNC_ENDPOINT.replace(/\/$/, "") + "/e",
                             new Blob([name], { type: "text/plain" }));
    } catch (e) { /* a counter is never worth an exception in the middle of a solve */ }
  }

  // An event says what THIS session did. A grid that opens with letters already
  // in it was filled on some other day, so the state it arrives in counts as
  // already reported and only movement from here is sent.
  function sealArrivedProgress() {
    eventsSent = new Set();
    let filled = 0, total = 0;
    forEachCell((c) => { if (c.printed) return; total++; if (c.letter) filled++; });
    if (filled) eventsSent.add("letter");
    if (total && filled * 2 >= total) eventsSent.add("half");
    if (entries.some(isEntrySolved)) eventsSent.add("entry");
    if (entries.length && entries.every(isEntrySolved)) eventsSent.add("done");
  }

  // Halfway is where sampling has turned into solving, which is why it is the
  // one grid-fill mark worth a beacon. Driven from refreshAll because letters
  // arrive half a dozen ways and only some of them are typing.
  function checkHalfFilled() {
    if (!entries.length || eventsSent.has("half")) return;
    let filled = 0, total = 0;
    forEachCell((c) => { if (c.printed) return; total++; if (c.letter) filled++; });
    if (total && filled * 2 >= total) beacon("half");
  }

  /* ---------- new faces, or the same ones ----------
     A count of openings cannot tell a hundred visitors from one visitor who came
     a hundred times, and the two ask for opposite work: a site people return to
     needs more puzzles, a site they see once needs a better first five minutes.

     The tally is kept in this browser and only a bucket ever leaves it, once a
     day. So the device remembers that it has been here and the server does not:
     two visit events still cannot be put back together into a visitor, which is
     the same line every other event holds. It counts BROWSERS, not people — a
     second device or a cleared store starts again at new, and that is the honest
     limit of a report that keeps no identifier. */
  function hasAnySave() {
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.indexOf("ct:") === 0 && !SYNC_RESERVED[k.slice(3)]) return true;
      }
    } catch (e) { /* private mode: treated as a browser with nothing in it */ }
    return false;
  }

  function reportVisit() {
    // UTC, because the Worker dates the key in UTC and a visit that counted
    // itself on one day and was filed under another would double on the seam.
    const today = new Date().toISOString().slice(0, 10);
    const seen = store.get("ct:seen", null);
    // Decided ABOVE the once-a-day gate, and from the tally rather than from
    // reaching this line: the gate exists to send one beacon a day, so a browser
    // that has already loaded the site today would never be offered the
    // first-visit lines if they hung off it — including on the reload that
    // is how anyone checks. A tally of one is a browser on its first ever day,
    // however many times it opens the grid; a browser with grids already in it
    // has plainly been here before, whatever the tally says.
    nuxSeed(seen ? seen.days === 1 : !hasAnySave());
    if (seen && seen.last === today) return;
    const days = (seen ? seen.days : (hasAnySave() ? 1 : 0)) + 1;
    store.set("ct:seen", { last: today, days });
    beacon(days === 1 ? "visit-new" : days < 5 ? "visit-return" : "visit-regular");
  }

  /* ---------- the first grid ----------
     A new arrival lands on a full 15x15 and nothing on it says that every clue
     is written up: the ladder is the point of the site and it is a row of
     buttons under a grid, which is what a crossword with a "reveal" looks like.
     These are the sentences that say otherwise. One at a time, in the hint
     panel, beside the buttons they are about.

     Not a tour and not a panel to dismiss before you may start. A tour is read
     in the wrong order, out of reach of the thing it describes, and forgotten
     before that thing comes up; a line sitting on the control at the moment you
     reach it is read while it is still true. Each is spent by the solver doing
     the thing it asked for, so the site teaches itself and then shuts up.

     Only for a browser whose FIRST EVER visit this is — the same fact reportVisit
     just worked out, taken from it rather than asked again, because a browser
     with grids already in it has plainly been here before and must not be
     taught the site.

     A cursor, not a set of flags: the lines are strictly ordered, exactly one is
     on screen, and everything that spends one advances the same integer. Nothing
     can show two, show them out of order, or bring one back. */
  const NUX_KEY = "ct:nux";
  const NUX_LINES = [
    // Step one is a dialog, not a line, and it is the only modal on the site.
    // The lines below it are read beside the control they are about, which is
    // the right place for everything EXCEPT the sentence that has to arrive
    // before the grid does: on a phone the hint panel they live in starts two
    // screens down, so a newcomer met the crossword and nothing else. Its text
    // is in index.html (#welcome) because it is a worked example with markup in
    // it, not a sentence.
    { id: "welcome", modal: true },
    { id: "ladder",
      text: "Stuck? These buttons are hints, and every clue here is written up in them. Each one shows a bit more of how the clue works. Press one, and stop as soon as you can see the answer.",
      // The one line that outlives its first press. A newcomer who takes a rung
      // has learned what one button does, not what the row is for, so the light
      // moves down the ladder with them and the sentence changes to the thing
      // that is still worth saying. Spent by the last rung or by solving.
      again: "That was one hint. Each one below gives away a bit more than the one before \u2014 keep going, and stop as soon as you can see the answer." },
    { id: "free",
      text: "Once you solve a clue, the rest of its hints costs nothing and your score stays the same. Open them anyway to see how the clue was built." },
    { id: "score",
      text: "Your score counts hints, not time \u2014 so solving a clue with two hints beats solving it with six." },
    // The walk ends by saying it has ended. Without this the last line simply
    // stops appearing, which reads as the site having lost its place rather
    // than as a tour that finished. Nothing is pointed at: there is nothing
    // left to be shown, so the scrim stays down and the page is handed back.
    { id: "done",
      text: "That is the tour: the hints, how to answer them for free, and what the score counts. There are no more tips after this one." },
  ];
  // An integer index into NUX_LINES, or null for a browser that is owed none of
  // them. undefined until the first visit this code has seen, which is the only
  // time the question can still be asked.
  let nux = store.get(NUX_KEY, undefined);
  let nuxDrawn = null;   // the id currently on screen, so a keystroke redraws nothing
  // The sentence the walk is saying right now, "" for none. It is held here
  // rather than in the element because there are two places it can be said —
  // the line in the panel, or the caption beside the spotlight — and the node
  // that is not saying it has to be EMPTY. Left in both and hidden in CSS, one
  // stale stylesheet is all it takes for the solver to read the same
  // instruction twice.
  let nuxSaid = "";
  // Whether this browser has taken a rung since the ladder line went up, which
  // is the difference between the two wordings of that line.
  let nuxWalked = false;
  // The intro is opt-in now: a link opens it. typedYet hides the hint line once a letter is typed.
  let introOpen = false, typedYet = false;

  function nuxSeed(first) {
    if (nux !== undefined) return;
    nux = first ? 0 : null;
    store.set(NUX_KEY, nux);
  }

  // Spends the current line, whichever it is. One rule for every line: taking a
  // hint or solving a clue is the solver doing the thing the site was trying to
  // get them to do, so the sentence asking for it has done its job.
  function nuxAdvance() {
    if (typeof nux !== "number" || nux >= NUX_LINES.length) return;
    nux += 1;
    store.set(NUX_KEY, nux);
    nuxDraw();
  }


  // What taking a rung does to the cursor. Every line but the ladder one is
  // spent by the first thing that answers it; the ladder line is about a row of
  // buttons and is spent by the last of them, so until then the press only
  // clears the scrim, which the next row build puts back over the next rung.
  function nuxRungTaken(e) {
    if (!nuxPointsAtRung()) { nuxAdvance(); return; }
    nuxWalked = true;
    const steps = ladderSteps(annOf(e), clueText(e));
    if (steps.every((st) => isShown(e, st.key))) { nuxAdvance(); return; }
    nuxDraw();
  }

  // Whether the rung the welcome dialog just promised should be pointed at. Read
  // by renderHintPanel as it builds the row: "take the first one" is no use to
  // someone looking at five identical buttons for the first time.
  function nuxPointsAtRung() {
    return typeof nux === "number" && NUX_LINES[nux] && NUX_LINES[nux].id === "ladder";
  }

  // Which rung the lesson is allowed to light. A rung that simply hands its
  // hint over costs score, and marching a newcomer into that teaches them the
  // ladder is a shop. A rung that asks before it tells is free to anyone who
  // answers it, and every rung is free once the clue is solved; those are the
  // ones worth walking someone through. When the lead rung is not one of them
  // the light goes out and the walk waits, rather than spending their score
  // for them.
  function nuxFreeRung(e, key, solved) {
    if (!nuxPointsAtRung()) return false;
    if (solved) return true;
    return !!(GUESSABLE[key] && guessAsk(e, key, 0));
  }

  // The last move of the walk. Once the pieces are on the table, the thing
  // still worth teaching is not another rung: it is that you work the answer
  // out and type it in yourself, which is the one way of finishing a clue that
  // charges nothing. What is left in the row by then is the full walkthrough,
  // which charges, so the light leaves the ladder and the grid takes it.
  function nuxTypeIt(e) {
    if (jigsaw || !nuxPointsAtRung() || !e || isEntrySolved(e)) return false;
    const steps = ladderSteps(annOf(e), clueText(e));
    if (!steps.length) return false;
    // A rung taken in pieces is not finished until its last piece is out.
    if (isShown(e, "blocks") && piecesLeft(e)) return false;
    // Not before they have been taught anything: a clue with no askable rung at
    // all would otherwise open the walk by demanding the answer.
    if (!shownRungs(e).some((r) => r !== ANSWER_RUNG)) return false;
    return steps.every((st) => isShown(e, st.key) || !nuxFreeRung(e, st.key, false));
  }

  // The one thing about this site a newcomer cannot get by pressing buttons:
  // that pointing at the right words yourself opens the rung for nothing. So
  // while the walk has a question on the table, the thing that would answer it
  // takes the same pulse the rung itself wore — the tour points, it does not
  // read the answer out, because what has to be learned is the gesture and a
  // sentence naming the words teaches only this one clue.
  function nuxPointing() { return nuxPointsAtRung() && !!guessing; }

  // The question the walk is pointing inside, if there is anything in it to
  // point at. A question with nothing pointable is left alone and the line goes
  // on saying what it was saying.
  function nuxAsk() {
    if (!nuxPointing()) return null;
    const e = currentEntry();
    if (!e || entryKey(e) !== guessing.key) return null;
    const ask = guessAsk(e, guessing.rung, guessing.step);
    if (!ask) return null;
    if (ask.choices) return ask.answer ? ask : null;
    if (ask.pairs) return ask;
    return (ask.target || []).length ? ask : null;
  }

  // Whether word `i` of the clue is what the walk is pointing at. A word
  // already picked stops pulsing: the pulse is an instruction, and an
  // instruction that has been carried out is noise.
  function nuxPointsWord(ask, i, picked) {
    return !!(ask && nuxPointing() && (ask.target || []).indexOf(i) >= 0
              && (picked || []).indexOf(i) < 0);
  }

  // Whether the walk has moved on to the check button: the question is one the
  // button grades, and everything it pointed at inside the question is done —
  // every pointed word picked, or every pair slot filled. Selecting the words
  // is half the gesture; a light that stays on the question block leaves the
  // newcomer looking for what to press next.
  function nuxPointsCheck(ask) {
    if (!ask || ask.choices || !nuxPointing()) return false;
    if (ask.pairs) return (guessing.slots || []).every((n) => n >= 0);
    const picked = guessing.picked || [];
    return picked.length > 0 && (ask.target || []).every((i) => picked.indexOf(i) >= 0);
  }

  // The dialog is spent by starting, like every line is spent by doing. Going on
  // leaves the cursor on the ladder line, which is the sentence the dialog just
  // promised and the rung it points at; saying you have solved cryptics before
  // spends the lot, because everything left is the same lesson.
  function bindWelcome() {
    const go = $("welcome-go"), skip = $("welcome-skip"), open = $("intro-open");
    if (!go) return;
    if (open) open.onclick = () => { introOpen = true; beacon("intro-open"); nuxDraw(); };
    document.addEventListener("keydown", (ev) => {
      if (!typedYet && /^[a-zA-Z]$/.test(ev.key) && !ev.metaKey && !ev.ctrlKey) { typedYet = true; nuxDraw(); }
    });
    go.onclick = () => {
      introOpen = false;
      nuxAdvance();
      // The rung row was built while the dialog was still up, so it carries no
      // mark: the thing the dialog promised to point at only becomes pointable
      // the moment the cursor moves off it.
      refreshAll();
      beacon("nux-start");
      // The panel it just sent them to is below the fold on a phone, which is
      // the whole reason this dialog exists; landing them back at the top of the
      // grid would rebuild the problem one step later.
      const panel = $("hint-panel");
      if (panel && panel.scrollIntoView) panel.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    if (skip) skip.onclick = () => { introOpen = false; nux = NUX_LINES.length; store.set(NUX_KEY, nux); nuxDraw(); beacon("nux-skip"); };
  }

  // Named, because the walk both says it and acts on it: saying it is what
  // sends the eye to the grid, so the two cannot be allowed to drift apart.
  // The tour hands over the answer itself: the lesson at this step is where the
  // answer goes and that typing it costs nothing, not whether a newcomer can
  // assemble their first clue unaided.
  function typeItLine(e) {
    const ann = annOf(e) || {};
    const answer = String(ann.answer || "").trim();
    return (answer ? "You have every piece now, and they make " + answer
                     + (ann.entered ? ", entered as " + ann.entered : "") + ". Type it"
                   : "You have every piece now. Put them together and type the answer")
      + " into the highlighted squares — typing it in yourself finishes a clue without using a hint.";
  }

  // Drawn from refreshAll, after the panel it sits in. Every line is about the
  // row of rung buttons, so every one waits for that row to exist: a clue with no
  // annotation has no ladder to explain, and an unannotated puzzle must not
  // start the lesson.
  function nuxDraw() {
    const el = $("nux");
    if (!el) return;
    const line = (typeof nux === "number") ? NUX_LINES[nux] : null;
    const modal = $("welcome");
    // Toggled above the redraw guard below: the dialog and the line are two
    // states of one cursor, and whichever is not current has to be gone.
    if (modal) modal.classList.toggle("hidden", !(line && line.modal && introOpen));
    // First visit: no dialog in the way, just one line beside the grid.
    const tap = $("tap-hint");
    if (tap) tap.classList.toggle("hidden", !(line && line.modal && !introOpen && !typedYet));
    const live = !!line && !line.modal
                 && !$("hint-panel").classList.contains("hidden")
                 && $("hint-next").childElementCount > 0;
    const typeIt = !nuxAsk() && nuxTypeIt(currentEntry());
    const telling = nuxAsk()
      ? "Answer this question yourself and the hint costs you nothing \u2014 tap what is lit up."
      : typeIt
      ? typeItLine(currentEntry())
      : "";
    const text = telling || ((line && line.again && nuxWalked) ? line.again : (line ? line.text : ""));
    // The id alone is not the identity of what is on screen: the ladder line
    // stays current across the whole walk and rewords itself twice under it,
    // once per question it answers and once for the rest of the climb.
    const want = live ? line.id + "/" + text : null;
    // Outside the guard, and before the draw below: the words are the same on
    // a redraw that changes nothing, and spotlightDraw is what puts them on
    // screen either way.
    nuxSaid = live ? text : "";
    // The funnel: one name per tour line, the first time it is actually on screen.
    if (live) beacon("nux-" + line.id);
    if (nuxDrawn !== want) {
      nuxDrawn = want;
      el.classList.toggle("hidden", !live);
      // The step that needs a different part of the panel in view: the strip
      // is at the top of it, while the last rung press left the eye at the
      // bottom of the row.
      const strip = live && typeIt ? $("hint-pattern") : null;
      if (strip && strip.scrollIntoView) {
        strip.scrollIntoView({ behavior: "smooth", block: "center" });
        // The hole is in page coordinates, so the scroll carries it along and
        // there is nothing to redraw as the page moves. Only the caption needs
        // a second look: which side of the hole it goes on is a question about
        // the window, and the window is still moving.
        [200, 500, 900].forEach((ms) => setTimeout(spotlightDraw, ms));
      }
    }
    // Outside the redraw guard: the sentence does not change while it is up, but
    // the button it is about moves under every scroll.
    spotlightDraw();
  }

  /* The spotlight. A sentence beside five identical buttons still leaves a
     newcomer choosing, so for every step of the walk the rest of the page goes
     behind a scrim and the thing the line is talking about keeps the light:
     the rung to press, the question to answer, or the squares to type into.
     The scrim never goes down mid-walk — a lightbox that comes and goes reads
     as a bug, and the step it skipped is the step with nothing pointing at it.

     The hole is put over whatever already carries the pulse, rather than over
     "the first rung": one answer to "which thing", read by both, so they
     cannot come apart. It is measured in viewport space and re-measured on
     every scroll and resize, because the dialog hands off with a smooth scroll
     and the rect is stale before the page has stopped moving. Nothing here is
     clickable — the scrim lets taps through — so a solver who wants to ignore
     it is not trapped by it. */
  function nuxRung() {
    const row = $("hint-next");
    if (!row || !nuxPointsAtRung()) return null;
    for (let i = 0; i < row.children.length; i += 1) {
      if (/\brung-point\b/.test(row.children[i].className || "")) return row.children[i];
    }
    return null;
  }

  // What the walk is pointing at, in the order the page has it. One hole covers
  // all of it, and one hole is enough for every step because #nux sits between
  // the hint body and the rungs: whatever is being pointed at, the sentence
  // asking for it is inside the same block. The row of rungs is below the line,
  // so a step that is not about a rung leaves the whole ladder dark — nothing
  // that charges is ever inside the light.
  function walkTargets() {
    const on = currentEntry();
    const body = $("hint-body");
    const out = [];
    // Branched in the same order as the sentence beside it, off the same two
    // tests: the hole and the line are one instruction, so a hole that decided
    // for itself would sooner or later point at something the line is not
    // talking about. The panel's own markup says whether a question is up:
    // `guessing` outlives the question it asked, so it cannot be the test.
    const open = !!(body && /guess-tell/.test(body.innerHTML || ""));
    const ask = nuxAsk();
    if (ask || (open && !nuxTypeIt(on))) {
      // The words being pointed at, and nothing else. A hole around the whole
      // clue lights every word in it, which is the opposite of pointing at one
      // — and the clue stretches the hole across the question below it too, so the light
      // ends up over most of the panel. Picked off the same predicate that
      // painted the pulse, so the hole and the pulse cannot name different
      // words, and the light moves to the question below the moment the last
      // pointed word is taken.
      const lit = (ask && ask.target ? ask.target : [])
        .filter((i) => nuxPointsWord(ask, i, (guessing && guessing.picked) || []))
        .map((i) => $("gw-" + i)).filter((el) => !!el);
      if (lit.length) return lit;
      // Then the button that grades it, off the class it is wearing, so the
      // hole and the pulse cannot disagree about whether it is time to press.
      const check = $("guess-check");
      if (check && /\bwalk-point\b/.test(check.className || "")) return [check];
      // The question itself, not the whole panel. Everything already bought sits
      // in the same box above it, and a hole big enough to hold that lights the
      // part of the lesson that is over. The question is written last into the
      // body, so it is the body's last child.
      const kids = (body && body.children) || [];
      if (body) out.push(kids[kids.length - 1] || body);
      // A question that says "Tap them in the clue above" has to light the clue
      // words it is talking about, not only itself: a hole that stops at the
      // question leaves the words it asks for dimmed behind the scrim. Reached
      // whenever the walk is not pointing at specific words (a later tour line
      // over a question that is still open, or a question with nothing pointable),
      // so it is the question's own wording that decides, off the same markup.
      if (body && /\btap-hint\b/.test(body.innerHTML || "")) {
        const row = $("hint-clue") && $("hint-clue").querySelector
          ? $("hint-clue").querySelector(".guess-clue.ask") : null;
        if (row) out.unshift(row);
      }
    } else if (nuxTypeIt(on)) {
      // Type it in: the letter strip in the panel and nothing else. The line
      // gives the answer, so the pieces it was worked out from need no light,
      // and the strip types into the same entry the grid does.
      const strip = $("hint-pattern");
      if (!strip) return [];
      out.push(strip);
    } else {
      const rung = nuxRung();
      if (!rung) return [];
      // The rung and nothing else: the step being pointed at is the one thing
      // to act on, and the rungs already climbed are behind the scrim with the
      // rest of the page.
      out.push(rung);
    }
    return out;
  }

  // Puts the walk's current sentence in ONE of the two places it can be said,
  // and empties the other. `say` is the caption beside the hole when there is a
  // hole; `lit` is false when there is no hole and the line in the panel has to
  // say it, which empties the caption rather than leaving last step's words in
  // a node that is only hidden. Also
  // the write guard: this runs on every scroll event, and rewriting text that
  // has not changed is a layout on every frame of a phone scroll.
  function sayIt(line, say, lit) {
    const inSpot = !!(lit && nuxSaid && say);
    const words = { line: inSpot ? "" : nuxSaid, say: inSpot ? nuxSaid : "" };
    if (line) {
      line.classList.toggle("in-spot", inSpot);
      if (line.textContent !== words.line) line.textContent = words.line;
    }
    if (say && say.textContent !== words.say) say.textContent = words.say;
  }

  function spotlightDraw() {
    const spot = $("spotlight");
    if (!spot) return;
    // nuxDrawn, not nux: the line and the light are the same instruction, so the
    // scrim is up exactly when the sentence explaining it is on screen.
    const els = nuxDrawn ? walkTargets() : [];
    if (!els.length) {
      spot.classList.add("hidden");
      sayIt($("nux"), $("spot-say"), false);
      return;
    }
    const boxes = els.map((e) => e.getBoundingClientRect());
    const pad = 6;
    const top = Math.min.apply(null, boxes.map((b) => b.top)) - pad;
    const left = Math.min.apply(null, boxes.map((b) => b.left)) - pad;
    // Page coordinates: the rects come back in viewport space, and the hole is
    // placed in the page so that scrolling moves the two together.
    const sy = window.pageYOffset || 0;
    const sx = window.pageXOffset || 0;
    spot.style.setProperty("top", Math.round(top + sy) + "px");
    spot.style.setProperty("left", Math.round(left + sx) + "px");
    spot.style.setProperty("width",
      Math.round(Math.max.apply(null, boxes.map((b) => b.right)) - left + pad) + "px");
    const bottom = Math.max.apply(null, boxes.map((b) => b.bottom)) + pad;
    spot.style.setProperty("height", Math.round(bottom - top) + "px");
    // The sentence rides the spotlight instead of sitting inside the hole. The
    // hole is then only ever the thing to tap, which is the point of darkening
    // the page at all: a hole stretched to reach the line in the panel is most
    // of a phone screen, and lights nothing.
    // Below the hole, unless the hole is near the foot of the window.
    spot.classList.toggle("say-above", bottom + 96 > (window.innerHeight || 800));
    sayIt($("nux"), $("spot-say"), true);
    spot.classList.remove("hidden");
  }

  if (window.addEventListener) {
    window.addEventListener("scroll", spotlightDraw);
    window.addEventListener("resize", spotlightDraw);
  }

  // ---------- the catalogue, not the puzzles ----------
  // index.html loads it before this file. Without it there is no catalogue and
  // no clue types, so the app stops here rather than drawing itself empty.
  if (!window.CRYPTIC_INDEX || !window.CRYPTIC_INDEX.clueTypes) {
    throw new Error("app.js: the index must be composed first (window.CRYPTIC_INDEX.clueTypes is missing); " +
                    "index.html's boot builds it from puzzles/idx/head-live.json");
  }
  const INDEX = window.CRYPTIC_INDEX;
  window.CRYPTIC_PUZZLES = window.CRYPTIC_PUZZLES || {};

  // ---------- ids ----------
  // A puzzle's id is its series and its number ("cryptic-30089"), because every
  // paper numbers from its own 1 and the ranges only look far apart until a new
  // paper arrives in one of them. A bare number would be one namespace for
  // every paper, and the second paper to reach a number would share the first
  // one's puzzle file.
  //
  // Numbers stay numbers everywhere a person reads one. This is a key, and the
  // bare form has to keep working forever: it is in every link already shared,
  // in every browser's saved progress, and in the envelope a phone that has not
  // reloaded is still uploading.
  // ---------- books ----------
  // THE WHOLE SHELF IS ONE SERIES. Every scanned printed book here is `book`,
  // one chip and one colour however many books arrive, and WHICH book a
  // puzzle came out of lives in its number: book_index * 1000 + position, so
  // book-3018 is the eighteenth puzzle of the book registered as index 3.
  //
  // THE SHELF IS NOT SPELLED HERE. tools/data/books.json is the registry —
  // one row per physical book — and tools/fetch_puzzle.py --reindex copies the
  // browser's half of it into puzzles/index.json, which is what this reads. A
  // second copy of that table here, hand-mirrored from tools/series.py, is how
  // a shelf comes to be spelled two ways — one of them on the page a reader is
  // looking at.
  //
  // The index a number carries is NOT the volume the book prints on itself:
  // two publishers' volume 2 are different books, so the index is this repo's
  // and permanent, and the volume comes off the row. A reader is shown the
  // volume, because that is what is on the cover they might go and find.
  const BOOKS = INDEX.books || {};
  // tools/series.py's BOOK_SERIES. A feed's number is its publisher's and
  // holds no book, so a row is only read as a book when its series says so —
  // everyman-3018 would otherwise print as "Penguin book 5 No 18".
  const BOOK_SERIES = "book";

  // The registry row for a puzzle, or null if it is not out of a book. Null
  // for a book the index does not describe too, which is the right failure for
  // an index with no books table: the number prints raw and no
  // legacy id is built, rather than a made-up book being named.
  function bookOf(series, number) {
    if (series !== BOOK_SERIES) return null;
    const n = Number(number), position = n % 1000;
    const row = BOOKS[String(Math.floor(n / 1000))];
    return row && position ? { row, position } : null;
  }

  // The series whose stored number is the print date (tools/series.py
  // numberIsDate), each with its row name ("Canberra Times", series.py
  // date_numbered()): the number is shown as the day it names, and the picker
  // row's title slot names the paper. The kind alone ("Cryptic") made every
  // such row look like the same unnamed puzzle.
  const DATE_NUMBERED = INDEX.dateNumbered || {};
  const isDateNumbered = (p) => Object.hasOwn(DATE_NUMBERED, p.series) && !!p.date;

  // What a solver reads instead of the stored number: display_number() in
  // tools/series.py, which writes the same row on the archive pages, so the two
  // must agree character for character (tests/test_date_numbers.py). "No 3,018"
  // names a puzzle no book prints, and with one chip for the whole shelf a bare
  // "No 18" would name thirty different puzzles.
  function displayNumber(p) {
    const b = bookOf(p.series, p.number);
    if (b) return `${b.row.shelf} ${b.row.volume} No ${b.position}`;
    if (isDateNumbered(p)) return puzzleDate(p).shortWords;
    return `No ${Number(p.number).toLocaleString("en-GB")}`;
  }

  // Every id this puzzle has ever had, from the days when a book was its own
  // series: "penguin-5018" while each BOOK was a key, "penguin5-18" before
  // that while each VOLUME was one. Mirrors legacy_ids() in tools/series.py.
  // A rule rather than a list, so a book acquired later keeps working without
  // anyone remembering to add it. A series that was date-numbered (Metro
  // until 2026-10-11, index dateIdsUntil) also answers to <series>-YYYYMMDD.
  const DATE_IDS_UNTIL = INDEX.dateIdsUntil || {};
  function legacyIds(p) {
    const until = DATE_IDS_UNTIL[p.series];
    if (until && p.date && p.date <= until) return [`${p.series}-${p.date.replace(/-/g, "")}`];
    const b = bookOf(p.series, p.number);
    if (!b) return [];
    return [`${b.row.was}-${b.row.volume * 1000 + b.position}`,
            `${b.row.was}${b.row.volume}-${b.position}`];
  }

  // INDEX.partial: only the newest rows are here. The page draws the puzzle it
  // names from the puzzle's own file (fastOpen, below) while the shards fill in.
  const IS_ID = {}, BY_NUMBER = {}, BY_ID = {}, ALIAS = {};
  const REPRINTS_OF = {};
  function buildTables() {
  // Run again whenever rows arrive (loadShards), so the tables that depend on
  // the order of the list, or that push, start empty: BY_ID and IS_ID only ever
  // gain an id, and a row is replaced by its own id.
  [BY_NUMBER, ALIAS, REPRINTS_OF].forEach((t) => { Object.keys(t).forEach((k) => { delete t[k]; }); });
  INDEX.puzzles.forEach((p) => {
    IS_ID[p.id] = 1;
    BY_ID[p.id] = p;
    // First wins, and the list is newest-first, so an ambiguous number resolves
    // to the puzzle a stale link is overwhelmingly more likely to have meant.
    if (!(String(p.number) in BY_NUMBER)) BY_NUMBER[String(p.number)] = p.id;
    // Saved progress, shared links and one browser's sync envelope all hold the
    // id a puzzle had when they were written. An id that stopped resolving
    // would orphan a grid somebody is halfway through.
    legacyIds(p).forEach((was) => { ALIAS[was] = p.id; });
  });
  // Opened only by ?p=<id>: resolvable here, in INDEX.puzzles nowhere.
  (INDEX.unlisted || []).forEach((p) => { IS_ID[p.id] = 1; BY_ID[p.id] = p; });
  // A reprint is the original under another paper's number and date, so its id
  // opens the original, and progress saved under it moves there. REPRINTS_OF
  // holds each original's reprints, newest first, for the line saying so.
  (INDEX.reprints || []).forEach((r) => {
    if (!BY_ID[r.reprintOf]) return;
    ALIAS[r.id] = r.reprintOf;
    (REPRINTS_OF[r.reprintOf] = REPRINTS_OF[r.reprintOf] || []).push(r);
  });
  }
  buildTables();
  // Whether /puzzles/<id>/ exists: build_seo_pages.py writes one for every
  // listed puzzle with answers.
  const hasPage = (p) => !!(p && p.hasSolutions && !p.unlisted);
  const canonicalId = (id) => {
    const s = String(id == null ? "" : id);
    return IS_ID[s] ? s : (ALIAS[s] || BY_NUMBER[s] || s);
  };

  // ---------- the list, on demand ----------
  // Paul 11-02: "It should be progressive. Download what we show."
  // (DESIGN-progressive-index.md.) A progressive boot hands this file a PARTIAL
  // index: INDEX.puzzles is only the newest rows, INDEX.partial is true and
  // INDEX.idx = {live, stat} is head-live.json and head-static's table. The
  // rest of the list comes from puzzles/idx/ when something needs it, a series
  // and year at a time (loadShards), and each arrival is merged in the order
  // fetch_puzzle.py sorts the index in.
  //
  // index.html's loader sets INDEX.idx (ctIdx.compose of head-live and
  // head-static). If a shard will not load, loadShards calls back false.
  const IDX_ALL_MS = 1500;        // a focus waits this long for a typed series before loading the rest
  const IDX_BUNDLE_MIN = 12;      // more shards than this come as the one bundle
  const idxHave = new Set();      // "series/year" keys merged so far
  const idxFlight = {};           // key -> true while its fetch is out
  let idxWaiters = [];            // callbacks for the list being whole
  let idxBundleOut = false;
  let idxAllTimer = null;
  const idxManifest = () => (INDEX.idx && INDEX.idx.live && INDEX.idx.live.manifest) || {};
  const idxDay = (p) => (p.year !== undefined ? p.year + "-01-01" : (p.date || ""));
  // fetch_puzzle.py: newest day first, the daily cryptic first on a tie, then the larger number.
  function idxOrder(a, b) {
    const da = idxDay(a), db = idxDay(b);
    if (da !== db) return da < db ? 1 : -1;
    const ca = a.series === "cryptic", cb = b.series === "cryptic";
    if (ca !== cb) return ca ? -1 : 1;
    return (Number(b.number) || 0) - (Number(a.number) || 0);
  }
  // Whether INDEX.puzzles is every listed puzzle.
  function listFull() { return !INDEX.partial; }
  function idxFinish(ok) {
    const w = idxWaiters;
    idxWaiters = [];
    w.forEach((f) => f(ok));
  }
  // New rows in; everything computed from the old list is stale, so rebuild and redraw.
  function idxMerge(rows, unlisted) {
    const seen = new Set(INDEX.puzzles.map((p) => p.id));
    rows.forEach((r) => { if (!seen.has(r.id)) { seen.add(r.id); INDEX.puzzles.push(r); } });
    if (unlisted && unlisted.length) {
      INDEX.unlisted = INDEX.unlisted || [];
      const have = new Set(INDEX.unlisted.map((p) => p.id));
      unlisted.forEach((r) => { if (!have.has(r.id)) INDEX.unlisted.push(r); });
    }
    INDEX.puzzles.sort(idxOrder);
    if (Object.keys(idxManifest()).every((k) => idxHave.has(k))) INDEX.partial = false;
    idxRefresh();
  }
  function idxRefresh() {
    buildTables();
    resetListCaches();
    migrateSavedIds();
    const panel = $("picker-panel");
    if (panel && !panel.classList.contains("hidden")) renderPicker();
  }
  // The shards named (keys: "series/year" strings; all when omitted) are
  // fetched, merged, and cb(true) called; cb(false) if the list could not be
  // completed at all. Safe to call again before an answer: a shard already in
  // flight is not asked for twice.
  function loadShards(keys, cb) {
    cb = cb || function () {};
    if (listFull()) return cb(true);
    if (!INDEX.idx || !window.ctIdx || typeof fetch !== "function") { idxWaiters.push(cb); return undefined; }
    const manifest = idxManifest();
    const want = (keys || Object.keys(manifest)).filter((k) => k in manifest && !idxHave.has(k));
    if (!want.length) return cb(true);
    const live = INDEX.idx.live, stat = INDEX.idx.stat, cuts = live.percentileCuts;
    const rows = [], unlisted = [];
    const take = (key, compact) => {
      idxHave.add(key);
      window.ctIdx.expandShard(key, compact, stat, cuts).forEach((r) => { (r.unlisted ? unlisted : rows).push(r); });
    };
    const json = (name) => fetch(at("puzzles/idx/" + name))
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
    const settle = (ok) => {
      if (ok) { idxMerge(rows, unlisted); cb(true); return; }
      // puzzles/idx is not whole: keep what did arrive and say the list is not complete.
      if (rows.length) idxMerge(rows, unlisted);
      cb(false);
    };
    if (want.length > IDX_BUNDLE_MIN && live.bundle) {
      if (idxBundleOut) { idxWaiters.push(cb); return undefined; }
      idxBundleOut = true;
      json(live.bundle).then((b) => {
        Object.keys(manifest).forEach((k) => { if (!idxHave.has(k) && b[k]) take(k, b[k]); });
        idxBundleOut = false;
        settle(true);
        idxFinish(true);
      }).catch(() => { idxBundleOut = false; settle(false); });
      return undefined;
    }
    let left = want.length, bad = false;
    want.forEach((key) => {
      if (idxFlight[key]) { left -= 1; return; }
      idxFlight[key] = true;
      json(key.replace("/", "-") + "." + manifest[key] + ".json")
        .then((c) => { take(key, c); }, () => { bad = true; })
        .then(() => {
          delete idxFlight[key];
          if (--left === 0) settle(!bad);
        });
    });
    if (left === 0) { settle(!bad); }
    return undefined;
  }
  // Everything, in a moment: a focus on the search box says a search may be
  // coming, but a series typed first should be answered by its own shards.
  function loadAllSoon() {
    if (listFull() || idxAllTimer !== null) return;
    idxAllTimer = setTimeout(() => { idxAllTimer = null; loadShards(); }, IDX_ALL_MS);
  }
  function loadAllNow() {
    if (idxAllTimer !== null) { clearTimeout(idxAllTimer); idxAllTimer = null; }
    loadShards();
  }
  // The series a search term or the paper menu names.
  function idxSeriesNamed(term) {
    const out = [];
    Object.keys(idxManifest()).forEach((k) => {
      const s = k.split("/")[0];
      if (out.indexOf(s) < 0 && (s === term || (SERIES_BADGE[s] || [""])[0].toLowerCase() === term)) out.push(s);
    });
    return out;
  }
  // What a query needs from the shards not here yet. A term that names a
  // series ("281 genius") asks for that series' shards first and the rest
  // follow in a moment; any other query or menu needs every row now.
  function loadForQuery(q) {
    if (listFull()) return;
    const terms = q.split(/\s+/).filter(Boolean);
    const paper = (($("picker-paper") || {}).value || "");
    const narrowed = terms.length || paper || (($("picker-band") || {}).value) || (($("picker-tag") || {}).value);
    if (!narrowed) return;
    const series = paper ? paper.split(",") : [];
    terms.forEach((t) => { idxSeriesNamed(t).forEach((s) => { if (series.indexOf(s) < 0) series.push(s); }); });
    const others = (($("picker-band") || {}).value) || (($("picker-tag") || {}).value) ||
      terms.some((t) => !idxSeriesNamed(t).length && !/^\d+$/.test(t));
    if (!series.length || others) { loadAllNow(); return; }
    // Only a number beside the series: its shards answer it.
    const keys = Object.keys(idxManifest()).filter((k) => series.indexOf(k.split("/")[0]) >= 0);
    loadShards(keys, () => { loadAllSoon(); });
  }
  // A shared link whose id is not one this list knows: a series-date alias
  // ("metro-20260105") needs that series' shards, and if they do not name it
  // either, or the link is a bare number, every row is fetched.
  function loadForLink(raw, cb) {
    if (listFull() || IS_ID[raw] || BY_ID[raw]) return cb();
    const series = Object.keys(idxManifest()).map((k) => k.split("/")[0])
      .filter((s, i, a) => a.indexOf(s) === i && raw.indexOf(s + "-") === 0);
    const keys = series.length ? Object.keys(idxManifest()).filter((k) => series.indexOf(k.split("/")[0]) >= 0) : null;
    loadShards(keys, () => {
      if (!IS_ID[raw] && !ALIAS[raw] && !BY_NUMBER[raw] && keys) loadShards(null, cb); else cb();
    });
  }

  // Saved progress moves with the id, once. Anyone mid-grid keeps their grid.
  function migrateSavedIds() {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf("ct:") === 0) keys.push(k);
    }
    keys.forEach((k) => {
      const old = k.slice(3);
      if (SYNC_RESERVED[old]) return;
      const id = canonicalId(old);
      if (id === old) return;
      const v = store.get(k, null);
      // Never clobber: if this browser has already played the namespaced one,
      // that save is the newer of the two and the old key is just debris.
      if (v && !store.get("ct:" + id, null)) store.set("ct:" + id, v);
      store.del(k);
    });
    const last = store.get("ct:last", null);
    if (last) store.set("ct:last", canonicalId(last));
  }

  // A puzzle file is fetched when something needs it, and not before.
  //
  // Loading every puzzle in the index before painting would be hundreds of
  // requests and over a megabyte to put one crossword on the screen. Two things
  // need a puzzle's contents — openPuzzle, and pickerStatus for a puzzle you
  // have already put letters in — and both of them ask for it.
  //
  // puzzleLoad[id] is the queue of callbacks while the file is in flight, and 1
  // once it has settled. Settled, not loaded: a file that 404s answers everyone
  // waiting and is never asked for again, because a loader that retries on
  // missing is a loader that spins.
  const puzzleLoad = {};
  function loadPuzzle(id, done) {
    const q = puzzleLoad[id];
    if (q === 1 || window.CRYPTIC_PUZZLES[id]) return done();
    if (q) { q.push(done); return; }
    const p = BY_ID[id];
    if (!p) return done();
    puzzleLoad[id] = [done];
    const settle = () => {
      const waiting = puzzleLoad[id];
      puzzleLoad[id] = 1;
      waiting.forEach((f) => f());
    };
    // ?v=<content hash> so an updated puzzle is never served from cache
    const v = p.v ? "?v=" + p.v : "";
    const script = () => {
      const s = document.createElement("script");
      s.src = at("puzzles/" + p.file + v);
      s.onload = s.onerror = settle;
      document.head.appendChild(s);
    };
    // The site ships puzzles/<id>.js.gz, not the .js (tools/stage_site.py:
    // Pages counts the artifact uncompressed, and cannot serve a .gz with
    // Content-Encoding), so it is fetched and inflated here and run the way
    // the script tag would run it. The .js script tag is the way in wherever
    // that fails: file:// (no fetch), a checkout served as it stands (no .gz
    // built), and the Node harnesses, whose window has no fetch.
    if (!window.fetch) return script();
    window.fetch(at("puzzles/" + p.file + ".gz" + v))
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
      .then(unzipText)
      .then((text) => { new Function("window", text)(window); settle(); })
      .catch(() => (window.CRYPTIC_PUZZLES[id] ? settle() : script()));
  }

  // The text in a .gz's bytes. DecompressionStream where the browser has it;
  // inflate.js, loaded on first need, where it does not (Safari before 16.4,
  // Firefox before 113). Bytes that are not gzip are taken as the text itself,
  // for a server that sent the .gz with Content-Encoding and so had the
  // browser inflate it already.
  let inflateLoad = null;
  function unzipText(buf) {
    const bytes = new Uint8Array(buf);
    if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
    if (window.DecompressionStream) {
      return new Response(new Blob([bytes]).stream()
        .pipeThrough(new window.DecompressionStream("gzip"))).text();
    }
    inflateLoad = inflateLoad || new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = at("inflate.js");
      s.onload = () => (window.ctGunzip ? ok(window.ctGunzip) : fail(new Error("no inflate")));
      s.onerror = () => { inflateLoad = null; fail(new Error("no inflate")); };
      document.head.appendChild(s);
    });
    return inflateLoad.then((gunzip) => new TextDecoder().decode(gunzip(bytes)));
  }

  // Every puzzle this browser has letters saved for, id -> progress. Built by
  // walking localStorage, which holds one key per STARTED puzzle — a handful —
  // rather than by asking it about each indexed puzzle, which the picker would
  // otherwise do on every keystroke.
  //
  // Kept until something writes a ct: key, which store.set and store.del below
  // are the only ways to do: a letter typed, a sync merge landing, a reset, the
  // id migration. The next reader rebuilds it. Invalidating from the writer
  // rather than from each caller is what stops a new save path shipping with a
  // picker that shows yesterday's progress.
  let savedCache = null;
  function forgetSavedProgress(key) {
    if (savedCache && String(key).indexOf("ct:") === 0) savedCache = null;
  }
  // The other writer, and the one store.set cannot see: another tab of this
  // site, where the same solver is typing into the same localStorage. A browser
  // announces exactly that, so listen for it — without this, a picker opened in
  // this tab would go on reporting the progress as it stood when THIS tab last
  // wrote, which is the whole failure mode a cache of what was read has.
  //
  // key is null when a tab cleared the store, which is every key at once.
  if (window.addEventListener) window.addEventListener("storage", (ev) => {
    if (!ev || !ev.key || String(ev.key).indexOf("ct:") === 0) savedCache = null;
  });
  function savedProgress() {
    if (savedCache) return savedCache;
    const found = {};
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k || k.indexOf("ct:") !== 0) continue;
        // ct:last, ct:sync and ct:votes live under the same prefix and have no
        // letters, so "has letters saved" is the whole test — no list of
        // reserved names to keep in step with.
        const prog = store.get(k, null);
        if (prog && prog.letters && Object.keys(prog.letters).length) found[k.slice(3)] = prog;
      }
    } catch (e) { /* no enumeration: treat it as nothing started */ }
    savedCache = found;
    return savedCache;
  }

  // The puzzles the picker needs the answers for: the ones with letters saved.
  // pickerStatus stops at the saved progress for anything else, so fetching the
  // rest would buy nothing. Idempotent, and called again when the picker opens,
  // because a sync pull can hand this browser progress on a puzzle it has never
  // held.
  function loadStartedPuzzles(then) {
    // Driven off the SAVES, which are a handful, rather than off the whole
    // catalogue filtered down to that handful — the picker calls this every
    // time it opens. The two are the same set from opposite sides:
    // savedProgress() holds only ids with letters, and BY_ID is the membership
    // test the filter was making.
    Object.keys(savedProgress()).forEach((id) => { if (BY_ID[id]) loadPuzzle(id, then); });
  }

  // ---------- state ----------
  let P = null;          // current puzzle object
  let meta = null;       // its index entry
  let cells = [];        // rows x cols of {x,y,sol,num,across,down,el,letter,wrong,revealed} | null
  let entries = [];      // puzzle entries in tab order (across by number, then down)
  let byId = {};
  let unclued = [];      // per P.unclued light, its cells in reading order
  let leaderOf = {};     // continuation id -> its linked group's leader id (buildLeaderOf)
  let cur = { x: 0, y: 0, dir: "across" };
  let leadPick = null;   // a virtual lead's id picked off the list (expandEntries)
  // A jigsaw (tools/puzzle_tags.is_jigsaw) withholds where each answer goes, so
  // the clue chosen off the list is held apart from the cursor: `pick` is the
  // clue the hint panel teaches, `cur` the square being typed into, and nothing
  // on screen ties one to the other until a reveal writes the answer in.
  let jigsaw = false;
  const isJigsaw = (m) => ((m && m.tags) || []).some((t) => t === "jigsaw" || t === "numbered-jigsaw");
  let gridNumbers = true;  // false where the paper printed the grid unnumbered
  let pick = null;
  // The clue the LINK asked for, read once and spent once.
  //
  // Read at load because opening a puzzle rewrites the address bar before it
  // picks a clue, so by the time the grid is built the ?c= that brought the
  // reader here is already gone. Spent once because it belongs to the puzzle it
  // arrived with: carrying it forward would drop you on 3 down of every puzzle
  // you opened afterwards.
  const linkedClue = (new URLSearchParams(location.search).get("c") || "").toUpperCase();
  let linkedClueSpent = false;
  // entryKey -> array of rung keys revealed ("definition", "blocks", …), in the
  // order the solver asked for them. A SET, not a high-water mark: the ladder
  // has a recommended order but no required one, so wanting the indicators
  // without being told the definition first is a legitimate way to solve and
  // the model has to be able to represent it. A high-water integer could only
  // say "the first N", so every rung would drag in the ones below it.
  let hintsShown = {};
  // entryKey -> the rungs that were EARNED: the solver was asked to point at the
  // words first and got them right, so the rung opened without costing a hint.
  // Kept apart from hintsShown rather than folded into the score at the moment
  // it happens, because the score is recomputed from state on every render and
  // a discount that lives only in a running total cannot survive a reload.
  let hintsEarned = {};
  let hintLevels = {};   // legacy: entryKey -> highest level, migrated on read
  // entryKey -> how many pieces of the building-blocks rung are on screen.
  //
  // A scalar, and allowed to be one where hintsShown is not, because these come
  // out in a fixed order and only ever forwards: piece 3 cannot arrive before
  // piece 2, so "how many" says everything "which ones" would. The rungs are the
  // opposite — the solver picks among them — which is why that one is a set.
  //
  // Why it exists at all: a rung that hands over every piece at once is not a
  // hint for a clue built from more than one piece, it is the answer. A charade's assembly is "read them in order", so the letters
  // ARE the solve; an anagram's is not, which is why the same rung felt like
  // work on one clue and like cheating on the next.
  let blocksAt = {};
  // Pieces taken out of turn, from the formula under the type rung (formulaHTML):
  // entryKey -> a bitmask over the blocks rung's pieces. blocksAt is a prefix
  // count and cannot say "piece 3 but not 1 and 2", so those pieces live here.
  // A mask, not a list, so a sync merge can OR two devices' picks together.
  let piecesPicked = {};
  let revealsUsed = {};  // entryKey -> number of letters revealed (escape hatch)
  let solvedWith = {};   // entryKey -> how many rungs were up when first solved
  // { startedAt, lastAt, activeMs, solvedAt, solvedMs } — see sync/merge.js.
  // The page reads only the dates (solvedAt, lastAt), for the stats ledger and
  // the streak. The durations are recorded because a solve-time index (the
  // SNITCH divides your time by your own six-month average) can only ever be
  // built out of history that was already being kept, and there is no such
  // index for the Guardian, the Independent, the Observer or the Telegraph —
  // see tools/difficulty.py. Whether a solve was clean stays derivable from
  // hintsShown and revealsUsed rather than being copied in here.
  let timing = {};
  // Elapsed time is not solving time: a crossword is done on a bus, then in an
  // evening, and the wall clock counts the day in between. Only gaps short
  // enough to be one sitting are added up. Long is deliberate — staring at a
  // clue for four minutes IS solving it.
  const IDLE_MS = 5 * 60 * 1000;
  let saveTimer = null;
  let touchAnchor = null; // touchstart position, to distinguish taps from scrolls

  const stateKey = () => "ct:" + P.id;
  // A linked answer is one clue: only its leader carries `group` (itself first)
  // and the annotation, and each continuation belongs to the first leader in
  // the puzzle's entry order whose group lists it.
  // An entry's id, "<number>-<direction>": what `group` lists. Derived; the
  // puzzle file stores none.
  // A virtual lead (expandEntries) carries its own id, "22-across~2".
  const entryId = (e) => e.vid || (e.number + "-" + e.direction);
  // A light that starts more than one linked answer (`alsoLeads`) leads each
  // further one as a virtual entry: the light's geometry and solution, that
  // answer's clue, group and annotation, and an id of its own that heads its
  // group, so its continuations' holder is it. It owns no square: the grid's
  // squares belong to the real entry (`base`).
  const expandEntries = (list) => (list || []).flatMap((e) => [e, ...(e.alsoLeads || []).map((l, k) => {
    const vid = entryId(e) + "~" + (k + 2);
    const v = { number: e.number, direction: e.direction, position: e.position, length: e.length,
                solution: e.solution, clue: l.clue, vid, base: entryId(e),
                group: [vid, ...(l.group || []).slice(1)] };
    if (l.annotation) v.annotation = l.annotation;
    if (l.selfClued) v.selfClued = l.selfClued;
    return v;
  })]);
  // An off-grid clue (`offGrid`) is an answer the preamble has entered
  // somewhere other than a light. Item k (1-based) is the virtual entry
  // "<k>-offgrid": it owns no square, its length is its solution's or else its
  // enumeration's, and the letters typed for it are its own (`typed`).
  const offGridEntries = (puz) => (puz.offGrid || []).map((o, k) => {
    const v = { number: k + 1, direction: "offgrid", offGrid: true, clue: o.clue, typed: "", revealed: false,
                length: o.solution ? o.solution.length
                  : (String(o.clue.enumeration || "").match(/\d+/g) || []).reduce((n, d) => n + Number(d), 0) };
    if (o.solution) v.solution = o.solution;
    if (o.annotation) v.annotation = o.annotation;
    return v;
  });
  const buildLeaderOf = (list) => {
    const out = {};
    // A light named in `selfClued` is an answer of its own that this one also
    // runs through (cryptic-21893's THERE): it keeps its own clue.
    // A leader may print its clue on a later light of its answer, so every
    // light of the group but its own is a continuation (tools/groups.py).
    list.forEach((e) => (e.group || []).forEach((id) => {
      if (id !== entryId(e) && !(id in out) && !(e.selfClued || []).includes(id)) out[id] = entryId(e);
    }));
    return out;
  };
  const holderOf = (e) => byId[leaderOf[entryId(e)]] || e;
  const entryKey = (e) => entryId(holderOf(e));
  // An annotation explains the clue's own word; an entry the preamble or clue
  // alters before entry (`alteration`) holds other letters in the grid, so the
  // annotation carries the alteration and those letters for the last rung.
  const annOf = (e) => {
    const h = holderOf(e);
    const ann = h.annotation || blogAnn(h);
    return ann && h.alteration ? { ...ann, alteration: h.alteration, entered: h.solution } : ann;
  };
  // What the clue itself solves to: `alteration.from` where the grid holds
  // something else, else the solution.
  const clueAnswer = (e) => (e.alteration && e.alteration.from) || e.solution || "";
  // A clue we have not annotated may still carry what a blog's write-up marks
  // about it (tools/blog_facts.py, merged into the shim by fetch_puzzle): the
  // underlined definition, a clue type the blogger named outright or spelled
  // out in letters that check, marked indicators, and the building blocks it
  // writes as WORD (clue words). Held in the annotation's own shape
  // (definitions [{text, at}], blocks [{clueFragment, gives, soundsLike}]),
  // so the ladder, the highlights and the questions all read it the way they
  // read ours. Two spans are a definition pair only when the type says so;
  // the extractor ships no other multi-span definition.
  // A field named in `inferred` (definitions, type, indicators) is not the blog's
  // but tools/letter_facts.py's, read off the letters; `typeCore` makes its type a lower bound, the clue
  // that and perhaps a cut or a letter selection besides. A block with
  // `inferred` is one of the pieces letter_facts.py split the answer into.
  // The answer is the solution, so blockLetters holds back a block that is the
  // whole of it exactly as it does for ours; a hidden word's carrier then shows
  // the note ours write, the run capitalised in its words (carrierNote).
  // A definition's `at` counts code points (a Python str index); a JS string
  // index counts UTF-16 units. This converts one to the other.
  const cpToIdx = (s, at) => [...s].slice(0, at).join("").length;

  function blogAnn(e) {
    const b = e.blog;
    if (!b) return null;
    const defs = b.definitions || [];
    // A linked answer is built from all its lights, joined in group order.
    const lights = (e.group || []).map((id) => (id === entryId(e) ? e : byId[id]));
    const answer = lights.length > 1 && lights.every((l) => l && l.solution)
      ? lights.map((l) => (l === e ? clueAnswer(l) : l.solution)).join("") : clueAnswer(e);
    const ann = { fromBlog: true, answer, type: b.type || [], indicators: b.indicators || [],
                  blocks: (b.blocks || []).map((block) => {
                    if (block.soundsLike) return block;
                    const note = wholeWord(block.gives) === wholeWord(answer) ? carrierNote(answer, block.clueFragment) : "";
                    return note ? { ...block, note } : block;
                  }),
                  inferred: b.inferred || [], typeCore: !!b.typeCore };
    const texts = defs.length === 2 && ann.type.includes("double_definition") ? defs : defs.slice(0, 1);
    if (texts.length) ann.definitions = texts;
    return ann;
  }
  // "hidden in saW HIZbollah": the words that carry `answer`, its run in
  // capitals; "hidden backwards in" where the run spells it reversed; "" where
  // the words do not carry it or are nothing else. tools/fetch_puzzle.py's
  // carrier_note is the same rule for the static pages.
  function carrierNote(answer, frag) {
    const want = wholeWord(answer);
    const at = [];
    for (let i = 0; i < (frag || "").length; i++) if (/[A-Za-z]/.test(frag[i])) at.push(i);
    const got = at.map((i) => frag[i].toUpperCase()).join("");
    if (want.length < 3 || got === want) return "";
    let from = got.indexOf(want);
    const back = from < 0;
    if (back) from = got.indexOf([...want].reverse().join(""));
    if (from < 0) return "";
    const lo = at[from], hi = at[from + want.length - 1] + 1;
    return (back ? "hidden backwards in " : "hidden in ")
      + frag.slice(0, lo) + frag.slice(lo, hi).toUpperCase() + frag.slice(hi);
  }
  // An off-grid clue has no grid reference, so no tag.
  const tag = (e) => (e.offGrid ? null : e.number + (e.direction === "across" ? "A" : "D"));
  // The key a save's `letters` and `letterAt` hold square i of an entry under.
  const squareOf = (e, i) => (e.position.x + (e.direction === "across" ? i : 0)) + ","
    + (e.position.y + (e.direction === "across" ? 0 : i));
  // Every square a solver can fill, as save keys: the lights, clued or not.
  function lightSquares(puz) {
    const sq = {};
    (puz.entries || []).forEach((e) => { for (let i = 0; i < e.length; i++) sq[squareOf(e, i)] = 1; });
    (puz.unclued || []).forEach((u) => u.cells.forEach(({ x, y }) => { sq[x + "," + y] = 1; }));
    return sq;
  }
  // A save is keyed by puzzle id, and an id can come to name a different grid
  // (a book renumbered, a grid rebuilt). Each save carries the fingerprint of
  // the grid it was typed into, and loads only into that grid.
  function gridPrint(puz) {
    const d = puz.dimensions || {};
    const s = d.cols + "x" + d.rows + "|" + Object.keys(lightSquares(puz)).sort().join(";");
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
    return (h >>> 0).toString(36);
  }
  // A save from before fingerprints has only its squares to go on: every one
  // of them must be a light of this grid.
  function fitsGrid(save, puz) {
    if (!save || typeof save !== "object") return true;
    if (save.grid) return save.grid === gridPrint(puz);
    const sq = lightSquares(puz);
    return Object.keys(Object.assign({}, save.letters, save.letterAt)).every((k) => sq[k] || k.endsWith("-offgrid"));
  }
  const hasSolutions = () => entries.every((e) => e.solution);

  /* ---------- paper mode ----------
     Solving the way the paper is solved: no tick when a clue goes in, no
     ladder, no letter or word checks, no reveal, until the solver says they are
     done. "I'm done" checks the grid, ends paper mode for that puzzle and
     hands everything back.

     A solve on paper is a solve with nothing bought, so it scores clean. Hidden
     means unknown: while a puzzle is on paper, isEntrySolved answers false, and
     every mark, lock, freeze and beacon that hangs off it waits with it. The
     saves-derived views (the picker's "solved ✓", the stats ledger) ask
     onPaper of the id for the same reason, so nothing anywhere says solved
     before the solver asked. The end-check is then an ordinary
     checkSolvedEntries: each correct clue is frozen at the rungs it had up,
     which on paper is none.

     The setting and the set of puzzles on paper are this DEVICE's, held under
     a reserved name and never synced: paper on the phone and the ladder on the
     laptop is a reasonable way to solve, and the letters still move between
     them as usual. The switch sits in the puzzle's toolbar and shows whether
     the puzzle on screen is on paper. Ticking it puts that puzzle on paper
     and turns the setting on, so every puzzle started (or reset) after it
     starts on paper too; one already under way elsewhere stays as it was.
     Unticking it turns the setting off and takes every puzzle off paper. */
  const PAPER_KEY = "ct:paper";
  let paper = store.get(PAPER_KEY, null) || {};
  const onPaper = (id) => !!(paper.open && paper.open[id]);
  const paperHides = () => !!P && onPaper(P.id);
  function writePaper(on, open) {
    // A puzzle opened on paper and left without a letter is not being solved;
    // dropping it here keeps the set to the grids actually under way.
    const saves = savedProgress();
    const kept = {};
    Object.keys(open).forEach((id) => { if (saves[id] || (P && id === P.id)) kept[id] = 1; });
    paper = { on: !!on, open: kept };
    store.set(PAPER_KEY, paper);
  }
  const setOnPaper = (id, yes) => {
    const open = Object.assign({}, paper.open);
    if (yes) open[id] = 1; else delete open[id];
    writePaper(paper.on, open);
  };
  // Anything to hide: a grid with no answers cannot be checked at the end, and
  // a finished one has nothing left to hide.
  const paperable = () => hasSolutions() && !entries.every(lettersRight);
  // The reader pressed "I'm done". A grid that is all right ends paper mode
  // and is checked exactly as Check grid checks it, every correct clue
  // credited first so the finish is scored. A grid that is not gets a verdict
  // only, the way a paper's answers next day say "not quite" without a red
  // pen: nothing is marked, and the puzzle stays on paper. Pressing again
  // (the button now says so) is the ordinary end: paper off, wrong squares
  // marked. paperVerdict holds the id the verdict was given for, so it is
  // never carried to another puzzle.
  let paperVerdict = null;
  const paperAsked = () => !!P && paperVerdict === P.id;
  // Is it right? Verify only: solved finishes as below, anything else is
  // a verdict that marks nothing and counts no wrong letters. endPaper is the
  // other button, "Show what's wrong", which ends paper mode regardless.
  function verifyPaper() {
    if (entries.every(lettersRight) && uncluedSolved()) { endPaper(); return; }
    let blank = 0;
    forEachCell((c) => { if (!c.letter) blank++; });
    paperVerdict = P.id;
    announceVerdict(blank);
    refreshAll();
  }
  function endPaper() {
    paperVerdict = null;
    setOnPaper(P.id, false);
    const credited = entries.filter((e) => isEntrySolved(e) && solvedWith[entryId(e)] === undefined).length;
    checkSolvedEntries();
    if (credited) noteMilestone(true);
    const all = [];
    forEachCell((c) => all.push(c));
    checkCells(all, "grid");
  }
  function togglePaper(on) {
    if (on) {
      writePaper(true, Object.assign({}, paper.open, P && paperable() ? { [P.id]: 1 } : {}));
    } else {
      // Off means feedback back on everywhere, not only here: a puzzle left on
      // paper with the setting off would hide its ticks with no switch on
      // screen to say why. Whatever was right is credited as it is seen.
      const was = paperHides();
      writePaper(false, {});
      if (was) { checkSolvedEntries(); saveState(); }
    }
    if (P) refreshAll();
  }

