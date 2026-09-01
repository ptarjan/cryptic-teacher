/* Cryptic Teacher — vanilla JS, no build step. Works from file:// and any static host. */
(function () {
  "use strict";

  // ---------- tiny helpers ----------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const letterOf = (s) => (s || "").toUpperCase().replace(/[^A-Z]/g, "");

  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
      catch (e) { return fallback; }
    },
    set(key, val) {
      try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* private mode etc. */ }
    },
    del(key) { try { localStorage.removeItem(key); } catch (e) {} }
  };

  // ---------- sync across machines ----------
  // The Worker in sync/. Blank it and every path below goes inert and the Sync
  // button hides itself, so the page keeps working exactly as it did offline —
  // which is also what happens for anyone who never turns sync on.
  const SYNC_ENDPOINT = "https://cryptic-teacher-sync.curly-unit-b9e0.workers.dev";
  // Reserved localStorage names, so scanning for saves cannot pick up settings.
  // Every key this app writes is "ct:<something>"; the rest are puzzle ids.
  const SYNC_RESERVED = { last: 1, sync: 1, seen: 1 };
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
  function beacon(name) {
    if (eventsSent.has(name)) return;
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
    forEachCell((c) => { total++; if (c.letter) filled++; });
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
    forEachCell((c) => { total++; if (c.letter) filled++; });
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
    if (seen && seen.last === today) return;
    // A browser with grids already in it has plainly been here before, whatever
    // this tally says: without that, the day this shipped reports every regular
    // as a new arrival.
    const days = (seen ? seen.days : (hasAnySave() ? 1 : 0)) + 1;
    store.set("ct:seen", { last: today, days });
    beacon(days === 1 ? "visit-new" : days < 5 ? "visit-return" : "visit-regular");
  }

  // ---------- puzzles/index.js: the catalogue, not the puzzles ----------
  const INDEX = (window.CRYPTIC_INDEX && window.CRYPTIC_INDEX.puzzles) ? window.CRYPTIC_INDEX : { latest: null, puzzles: [] };
  window.CRYPTIC_PUZZLES = window.CRYPTIC_PUZZLES || {};

  // ---------- ids ----------
  // A puzzle's id is its series and its number ("cryptic-30089"), because every
  // paper numbers from its own 1 and the ranges only look far apart until a new
  // paper arrives in one of them. Until 2026-08-19 the id WAS the number, so
  // puzzles/<n>.js was the whole namespace and the second paper to reach a
  // number would have shared the first one's file.
  //
  // Numbers stay numbers everywhere a person reads one. This is a key, and the
  // bare form has to keep working forever: it is in every link already shared,
  // in every browser's saved progress, and in the envelope a phone that has not
  // reloaded is still uploading.
  const IS_ID = {}, BY_NUMBER = {}, BY_ID = {};
  INDEX.puzzles.forEach((p) => {
    IS_ID[p.id] = 1;
    BY_ID[p.id] = p;
    // First wins, and the list is newest-first, so an ambiguous number resolves
    // to the puzzle a stale link is overwhelmingly more likely to have meant.
    if (!(String(p.number) in BY_NUMBER)) BY_NUMBER[String(p.number)] = p.id;
  });
  const canonicalId = (id) => {
    const s = String(id == null ? "" : id);
    return IS_ID[s] ? s : (BY_NUMBER[s] || s);
  };

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
  // Booting used to inject a <script> for EVERY puzzle in the index and wait for
  // the last of them to land before painting anything: 230 requests and about
  // 1.4 MB to put one crossword on the screen, which is most of the "little
  // while" a phone spends on a cold open (Paul, 2026-08-28). Two things need a
  // puzzle's contents — openPuzzle, and pickerStatus for a puzzle you have
  // already put letters in — and both of them now ask for it.
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
    const s = document.createElement("script");
    // ?v=<content hash> so an updated puzzle is never served from cache
    s.src = "puzzles/" + p.file + (p.v ? "?v=" + p.v : "");
    s.onload = s.onerror = () => {
      const waiting = puzzleLoad[id];
      puzzleLoad[id] = 1;
      waiting.forEach((f) => f());
    };
    document.head.appendChild(s);
  }

  // The puzzles the picker needs the answers for: the ones with letters saved.
  // pickerStatus stops at the saved progress for anything else, so fetching the
  // rest would buy nothing. Idempotent, and called again when the picker opens,
  // because a sync pull can hand this browser progress on a puzzle it has never
  // held.
  function loadStartedPuzzles(then) {
    INDEX.puzzles.forEach((p) => {
      const prog = store.get("ct:" + p.id, null);
      if (prog && prog.letters && Object.keys(prog.letters).length) loadPuzzle(p.id, then);
    });
  }

  // ---------- state ----------
  let P = null;          // current puzzle object
  let meta = null;       // its index entry
  let cells = [];        // rows x cols of {x,y,sol,num,across,down,el,letter,wrong,revealed} | null
  let entries = [];      // puzzle entries in tab order (across by number, then down)
  let byId = {};
  let cur = { x: 0, y: 0, dir: "across" };
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
  // the model has to be able to represent it. The old integer couldn't — it
  // could only say "the first N", so every rung dragged in the ones below it.
  let hintsShown = {};
  // entryKey -> the rungs that were EARNED: the solver was asked to point at the
  // words first and got them right, so the rung opened without costing a hint.
  // Kept apart from hintsShown rather than folded into the score at the moment
  // it happens, because the score is recomputed from state on every render and
  // a discount that lives only in a running total cannot survive a reload.
  let hintsEarned = {};
  let hintLevels = {};   // legacy: entryKey -> highest level, migrated on read
  let revealsUsed = {};  // entryKey -> number of letters revealed (escape hatch)
  let solvedWith = {};   // entryKey -> how many rungs were up when first solved
  // { startedAt, lastAt, activeMs, solvedAt, solvedMs } — see sync/merge.js.
  // Nothing on the page reads this: it is recorded because a solve-time index
  // (the SNITCH divides your time by your own six-month average) can only ever
  // be built out of history that was already being kept, and there is no such
  // index for the Guardian, the Independent, Everyman or the Quiptic — see
  // tools/difficulty.py. Whether a solve was clean stays derivable from
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
  const entryKey = (e) => (e.annotation && e.annotation.linkedTo) ? e.annotation.linkedTo : e.id;
  const annOf = (e) => {
    if (!e.annotation) return null;
    return e.annotation.linkedTo ? (byId[e.annotation.linkedTo] || {}).annotation || null : e.annotation;
  };
  const tag = (e) => e.number + (e.direction === "across" ? "A" : "D");
  const hasSolutions = () => entries.every((e) => e.solution);

  // ---------- persistence ----------
  // The 150ms debounce is a write-rate limit, and nothing is allowed to read the
  // store back through it. A save still sitting in its timer is a save the store
  // cannot tell you about, and what is missing is precisely the last thing the
  // solver did — so every path that reads localStorage as if it were the truth
  // (the sync envelope, and the merge that lands on top of it) flushes first.
  function saveState() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(writeState, 150);
  }
  function flushState() {
    if (saveTimer === null) return;
    clearTimeout(saveTimer);
    writeState();
  }
  function writeState() {
    saveTimer = null;
    const now = Date.now();
    const prev = store.get(stateKey(), null) || {};
    const was = prev.letters || {};
    const letters = {};
    forEachCell((c) => { if (c.letter) letters[c.x + "," + c.y] = c.letter + (c.revealed ? "!" : ""); });
    // When each square last changed, carried forward from the previous save
    // and re-stamped only where something actually moved. Rubbing a letter
    // out leaves no letter behind, so without this the merge cannot tell a
    // square you cleared from one you never filled in — and it put the
    // letters straight back (Paul, 2026-08-10). A stamp with no letter is
    // how a deletion gets to the other device.
    const letterAt = Object.assign({}, prev.letterAt);
    forEachCell((c) => {
      const k = c.x + "," + c.y;
      if (letters[k] !== was[k]) letterAt[k] = now;
    });
    // `updated` is what lets two machines be merged without asking which one
    // to believe (see sync/merge.js). It is written even with sync switched
    // off, so turning it on later does not treat today's work as undated.
    // saveState runs on every change a solver makes — a letter, a hint, a
    // reveal — so the gaps between consecutive saves are the sitting.
    timing = Object.assign({}, prev.timing);
    const gap = now - (timing.lastAt || now);
    if (!timing.startedAt) timing.startedAt = now;
    if (gap > 0 && gap <= IDLE_MS) timing.activeMs = (timing.activeMs || 0) + gap;
    timing.lastAt = now;
    if (!timing.solvedAt && entries.length && entries.every(isEntrySolved)) {
      timing.solvedAt = now;
      timing.solvedMs = timing.activeMs || 0;
    }
    store.set(stateKey(), { letters, letterAt, hintsShown, hintsEarned, revealsUsed,
                            solvedWith, timing, clearedAt: prev.clearedAt || 0, updated: now });
    syncPushSoon();
  }
  function restoreState() {
    const s = store.get(stateKey(), null);
    hintsShown = (s && s.hintsShown) || {};
    hintsEarned = (s && s.hintsEarned) || {};
    hintLevels = (s && s.hintLevels) || {};
    revealsUsed = (s && s.revealsUsed) || {};
    solvedWith = (s && s.solvedWith) || {};
    timing = (s && s.timing) || {};
    // The save is the whole truth about the grid, so wipe it first. A merge can
    // decide a letter was deleted on another device; if that square is only ever
    // written and never cleared, the stale letter survives on screen, the next
    // save re-stamps it as new, and the deletion is undone on both devices.
    forEachCell((c) => { c.letter = ""; c.revealed = false; c.wrong = false; });
    if (s && s.letters) {
      forEachCell((c) => {
        const v = s.letters[c.x + "," + c.y];
        if (v) { c.letter = v[0]; c.revealed = v.length > 1; }
      });
    }
  }

  /* ---------- sync engine ----------
     No account, no password: the eight-character code IS the identity. There is
     nothing here worth protecting with a login — it is which squares of a
     newspaper crossword you have filled in — and a password would only add a
     thing to forget, a reset flow to maintain, and an email address of Paul's
     to store. Lose the code and nothing is lost either: the save still sits in
     localStorage on every machine you have used, so you mint a fresh code from
     one of them.

     Direction of travel is always "add": the client merges the server's copy
     into its own and the server merges the client's into its own, using the
     same rules, so an iPad that has been shut in a drawer for a week cannot
     push a stale grid over the laptop's afternoon. That is the property that
     makes this safe to run automatically in the background instead of behind a
     "sync now?" prompt nobody would press. */
  const syncOn = () => !!(SYNC_ENDPOINT && store.get("ct:sync", null));

  function newSyncCode() {
    const n = 8;
    const out = [];
    const buf = new Uint8Array(n);
    if (window.crypto && window.crypto.getRandomValues) window.crypto.getRandomValues(buf);
    else for (let i = 0; i < n; i++) buf[i] = Math.floor(Math.random() * 256);
    // Rejection-free bias is irrelevant at 30 symbols and this stake; 8 symbols
    // is ~39 bits, and there is no endpoint that lets anyone enumerate them.
    for (let i = 0; i < n; i++) out.push(CODE_ALPHABET[buf[i] % CODE_ALPHABET.length]);
    return out.join("");
  }

  // Everything this browser has saved, in the wire shape merge.js expects.
  function localEnvelope() {
    flushState();
    const puzzles = {};
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k || k.indexOf("ct:") !== 0) continue;
      const id = k.slice(3);
      if (SYNC_RESERVED[id]) continue;
      const v = store.get(k, null);
      if (v && typeof v === "object") puzzles[id] = v;
    }
    const env = { v: 1, puzzles };
    const last = store.get("ct:last", null);
    if (last) env.last = { id: String(last), updated: (puzzles[last] || {}).updated || 0 };
    return env;
  }

  // Returns true if anything about the puzzle currently on screen changed, so
  // the caller knows whether it has to redraw under the solver's hands.
  //
  // WHAT COMES BACK IS MERGED IN, NEVER WRITTEN OVER THE TOP. A reply is a
  // statement about the moment its request left — it cannot know about the
  // letter typed, or the rung opened, while it was in flight, and a request is
  // in flight for as long as a round trip takes. Writing it in as the truth
  // therefore deletes whatever the solver did during that second, in front of
  // them: "I clicked full walkthrough, it appeared then disappeared" (Paul,
  // 2026-08-24). Merging is not a precaution here, it is the only correct
  // reading of the reply, and merge.js is commutative and idempotent precisely
  // so that this side can do it without knowing what order anything happened in.
  function applyEnvelope(env) {
    if (!env || !env.puzzles) return false;
    // Same rule one step earlier: an unwritten save is not in the store, so the
    // merge would not see it either.
    flushState();
    const openId = P ? String(P.id) : null;
    let openChanged = false;
    Object.keys(env.puzzles).forEach((raw) => {
      // A phone that has not reloaded is still uploading ct:30089. Map it on the
      // way in rather than writing back a key we would only migrate again.
      const id = canonicalId(raw);
      const mine = store.get("ct:" + id, null);
      const merged = CTMerge.mergePuzzle(mine, env.puzzles[raw]);
      const before = JSON.stringify(mine);
      const after = JSON.stringify(merged);
      if (before === after) return;
      store.set("ct:" + id, merged);
      if (id === openId) openChanged = true;
    });
    if (env.last && env.last.id && !store.get("ct:last", null))
      store.set("ct:last", canonicalId(env.last.id));
    return openChanged;
  }

  function syncFetch(method, body) {
    const code = store.get("ct:sync", null);
    if (!SYNC_ENDPOINT || !code) return Promise.reject(new Error("sync off"));
    return fetch(SYNC_ENDPOINT.replace(/\/$/, "") + "/s/" + encodeURIComponent(code), {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).then((r) => {
      if (r.status === 404 && method === "GET") return null; // code not used yet
      if (!r.ok) throw new Error("sync " + r.status);
      return r.json();
    });
  }

  let syncTimer = null, syncBusy = false, syncAgain = false;
  function syncPushSoon() {
    if (!syncOn()) return;
    clearTimeout(syncTimer);
    // Typing a letter saves; pushing on every keystroke would be a request per
    // letter. Two seconds of quiet is well inside "I picked up the iPad".
    syncTimer = setTimeout(syncPush, 2000);
  }
  function syncPush() {
    if (!syncOn()) return Promise.resolve();
    if (syncBusy) { syncAgain = true; return Promise.resolve(); }
    syncBusy = true;
    return syncFetch("PUT", localEnvelope())
      .then((merged) => {
        // The response is the merged truth, including anything another machine
        // pushed while this one was typing — so a push is also a pull.
        if (applyEnvelope(merged)) { restoreState(); refreshAll(); }
        syncNote("Synced");
      })
      .catch(() => syncNote("Offline — will retry"))
      .then(() => {
        syncBusy = false;
        if (syncAgain) { syncAgain = false; syncPushSoon(); }
      });
  }
  function syncPull() {
    if (!syncOn()) return Promise.resolve();
    return syncFetch("GET", null)
      .then((remote) => {
        if (!remote) return syncPush(); // first machine on this code
        const merged = CTMerge.mergeSaves(localEnvelope(), remote);
        if (applyEnvelope(merged)) { restoreState(); refreshAll(); }
        syncNote("Synced");
        // Push back whatever the server did not have. Cheap, and it means the
        // machine you just opened is not the only one holding your morning.
        if (JSON.stringify(merged) !== JSON.stringify(remote)) return syncPush();
      })
      .catch(() => syncNote("Offline — will retry"));
  }

  // One line of state, under the code, and never a modal or a toast: syncing is
  // background work, and interrupting someone mid-clue to tell them it went
  // fine is worse than saying nothing.
  function syncNote(msg) {
    const el = $("sync-status");
    if (el) el.textContent = msg;
  }

  // Showing the code is not the job; moving it to the other device is. Eight
  // characters is exactly the length that gets mistyped, so the clipboard is
  // the happy path — it needs a secure context and a user gesture, and running
  // inside the click gives us both. Where the browser withholds it the code is
  // still one tap from selected (user-select: all), and the status line says so
  // rather than leaving a button that looks broken.
  function copySyncCode() {
    const code = store.get("ct:sync", null);
    if (!code) return;
    const clip = typeof navigator !== "undefined" && navigator.clipboard;
    if (!clip) { syncNote("Press and hold the code to copy it."); return; }
    clip.writeText(code).then(
      () => syncNote("Code copied — type or paste it on the other device."),
      () => syncNote("Press and hold the code to copy it.")
    );
  }

  function renderSyncPanel() {
    const code = store.get("ct:sync", null);
    $("sync-code").textContent = code || "—";
    $("sync-on").classList.toggle("hidden", !code);
    $("sync-off").classList.toggle("hidden", !!code);
    syncNote(code ? "" : "Not syncing — this machine only.");
  }

  function forEachCell(fn) {
    for (let y = 0; y < P.dimensions.rows; y++)
      for (let x = 0; x < P.dimensions.cols; x++)
        if (cells[y][x]) fn(cells[y][x]);
  }

  // ---------- build model ----------
  function buildModel() {
    const { rows, cols } = P.dimensions;
    cells = Array.from({ length: rows }, () => Array(cols).fill(null));
    entries = P.entries.slice().sort((a, b) =>
      (a.direction === b.direction) ? a.number - b.number : (a.direction === "across" ? -1 : 1));
    byId = {};
    entries.forEach((e) => { byId[e.id] = e; });
    entries.forEach((e) => {
      for (let i = 0; i < e.length; i++) {
        const x = e.position.x + (e.direction === "across" ? i : 0);
        const y = e.position.y + (e.direction === "down" ? i : 0);
        if (!cells[y][x]) cells[y][x] = { x, y, sol: null, num: null, across: null, down: null, letter: "", wrong: false, revealed: false };
        const c = cells[y][x];
        c[e.direction] = e.id;
        if (i === 0) c.num = c.num || e.number;
        if (e.solution) c.sol = e.solution[i];
      }
    });
  }

  // ---------- grid rendering ----------
  function renderGrid() {
    const grid = $("grid");
    grid.innerHTML = "";
    grid.style.gridTemplateColumns = `repeat(${P.dimensions.cols}, var(--cellsize))`;
    grid.style.setProperty("--cols", P.dimensions.cols);
    for (let y = 0; y < P.dimensions.rows; y++) {
      for (let x = 0; x < P.dimensions.cols; x++) {
        const div = document.createElement("div");
        const c = cells[y][x];
        if (!c) {
          div.className = "cell block";
        } else {
          div.className = "cell";
          if (c.num) div.innerHTML = `<span class="num">${c.num}</span>`;
          const span = document.createElement("span");
          span.className = "letter";
          div.appendChild(span);
          c.el = div;
          div.addEventListener("mousedown", (ev) => { ev.preventDefault(); onCellClick(c); });
          // Only treat a touch as a tap if the finger didn't move (scrolling
          // over the grid must not change the selection).
          div.addEventListener("touchstart", (ev) => {
            const t = ev.touches[0];
            touchAnchor = { x: t.clientX, y: t.clientY };
          }, { passive: true });
          div.addEventListener("touchend", (ev) => {
            const t = ev.changedTouches[0];
            // preventDefault FIRST, on both paths. It is what suppresses the
            // mouse events iOS synthesises after a touch, and the mousedown
            // above is one of them — so bailing out before it meant a finger
            // that HAD moved fell through to mousedown and selected the cell
            // anyway, which is the exact thing this guard exists to stop.
            ev.preventDefault();
            if (touchAnchor && Math.hypot(t.clientX - touchAnchor.x, t.clientY - touchAnchor.y) > 10) return;
            onCellClick(c);
          }, { passive: false });
        }
        grid.appendChild(div);
      }
    }
    // word-separator marks
    entries.forEach((e) => {
      const seps = e.separatorLocations || {};
      Object.keys(seps).forEach((ch) => {
        (seps[ch] || []).forEach((pos) => {
          if (pos <= 0 || pos >= e.length) return;
          const x = e.position.x + (e.direction === "across" ? pos - 1 : 0);
          const y = e.position.y + (e.direction === "down" ? pos - 1 : 0);
          const c = cells[y][x];
          if (!c || !c.el) return;
          const suffix = e.direction === "across" ? "r" : "b";
          c.el.classList.add((ch === "-" ? "dash-" : "sep-") + suffix);
        });
      });
    });
    refreshGrid();
  }

  function refreshGrid() {
    const e = currentEntry();
    forEachCell((c) => {
      const el = c.el;
      if (!el) return;
      el.querySelector(".letter").textContent = c.letter;
      el.classList.toggle("wrong", !!c.wrong);
      el.classList.toggle("revealed", !!c.revealed);
      const inEntry = e && ((e.direction === "across" && c.y === e.position.y && c.x >= e.position.x && c.x < e.position.x + e.length)
        || (e.direction === "down" && c.x === e.position.x && c.y >= e.position.y && c.y < e.position.y + e.length));
      el.classList.toggle("hl", !!inEntry && !(c.x === cur.x && c.y === cur.y));
      el.classList.toggle("sel", c.x === cur.x && c.y === cur.y);
    });
  }

  // ---------- clue lists ----------
  function renderClues() {
    ["across", "down"].forEach((dir) => {
      const ol = $(dir === "across" ? "clues-across" : "clues-down");
      ol.innerHTML = "";
      entries.filter((e) => e.direction === dir).forEach((e) => {
        const li = document.createElement("li");
        li.id = "clue-" + e.id;
        li.innerHTML = `<span class="clue-num">${e.number}</span><span class="clue-text"></span>` +
          `<span class="checkers"></span>`;
        // No focusKbd: picking a clue off the list is not a decision to type,
        // so it must not raise a keyboard over half the screen. See the
        // mousedown handler on these lists for the other half of that rule.
        li.addEventListener("click", () => selectEntry(e, true));
        ol.appendChild(li);
      });
    });
    refreshClues();
  }

  // Every rung marks up its OWN words, independently of the others.
  //
  // This used to be gated on the definition rung: no definition, no markup of
  // any kind. That was invisible while the ladder was strictly ordered, and
  // broke the moment tier 0 let you take the rungs in any order — ask for the
  // indicators first, which is a legitimate route because working out where the
  // definition sits is most of the skill, and the clue stayed completely
  // unmarked, so the one hint you spent showed you nothing (feedback
  // 2026-08-01: "if I choose just the indicator clue now it doesn't highlight
  // the parts of clue"). Rule: highlight exactly what has been revealed, and
  // never anything that hasn't.
  // The setter's italics and the solver's highlights are two independent lists
  // of ranges over the same plain string (tools/fetch_puzzle.flatten_clue keeps
  // the clue plain so that annotation fragments can still be found in it by
  // indexOf). They overlap freely — an italicised title can BE the definition —
  // so instead of nesting one inside the other the clue is cut at every
  // boundary either list has and each piece wrapped in whatever covers it.
  // Adjacent pieces of one italic render as one italic; nothing shows the seam.
  function markUp(text, marks, italics) {
    const cuts = [0, text.length];
    marks.forEach((m) => cuts.push(m.i, m.i + m.len));
    italics.forEach((r) => cuts.push(r[0], r[0] + r[1]));
    const pts = cuts.filter((p, i) => p >= 0 && p <= text.length && cuts.indexOf(p) === i)
                    .sort((a, b) => a - b);
    let out = "";
    for (let s = 0; s < pts.length - 1; s++) {
      const a = pts[s];
      const covers = (i, len) => i <= a && a < i + len;
      const m = marks.filter((k) => covers(k.i, k.len))[0];
      let piece = esc(text.slice(a, pts[s + 1]));
      if (italics.filter((r) => covers(r[0], r[1])).length) piece = "<i>" + piece + "</i>";
      out += m ? `<mark class="${m.cls}">${piece}</mark>` : piece;
    }
    return out;
  }
  // Italics are the setter's, so they show whether or not any hint is up.
  const italicsOf = (e) => (Array.isArray(e.clueItalics) ? e.clueItalics : []);
  const plainClueHTML = (e) => markUp(e.clue, [], italicsOf(e));

  // Where a fragment goes is a placement, not a search. indexOf() takes the
    // first substring that matches and two things went wrong with that, both
    // reported as the same thing — a highlight you had paid for not being there
    // ("I think it might always be the indicator clue which is disappearing
    // after click", Paul, 2026-08-17).
    //
    //   mid-word  the indicator 'in' matched inside "Conclud(in)g", "island",
    //             "confusion" — 18 clues in the corpus were marking a syllable
    //             of an innocent word instead of the instruction;
    //   dropped   and then, because the wrong position usually landed under the
    //             definition, the overlap rule below threw the indicator away
    //             entirely — 15 clues, and always the indicator, because
    //             indicators are pushed last and the loser was whoever came
    //             second. Buying the definition made an earlier hint vanish.
    //
  // So each fragment takes the best occurrence still going: on word
  // boundaries, and not already spoken for. Nothing is ever dropped — a rung
  // that has been bought stays on the screen, which is the whole contract.
  //
  // One spelling of "where does this fragment sit", because the highlighter and
  // the grader for a solver's guess have to agree about it exactly: marking one
  // "in" and grading a different one would tell someone they were wrong about a
  // word the clue had just underlined for them.
  const isLetter = (c) => !!c && /[A-Za-z]/.test(c);
  function bestOccurrence(clue, text, taken) {
    const len = text.length;
    // Only an edge that is itself a letter can be mid-word. Fragments routinely
    // start or end on punctuation that is welded to the neighbouring word —
    // "’s gone out of" in "Pound’s gone…", "half-" in "half-dark" — and those
    // are the setter's own joins, not accidents of spelling.
    const onBoundary = (i) =>
      !(isLetter(clue[i]) && isLetter(clue[i - 1])) &&
      !(isLetter(clue[i + len - 1]) && isLetter(clue[i + len]));
    const free = (i) => !taken.some((m) => i < m.i + m.len && m.i < i + len);
    let boundaryFree = -1, boundaryAny = -1, anyFree = -1;
    for (let i = clue.indexOf(text); i >= 0; i = clue.indexOf(text, i + 1)) {
      const b = onBoundary(i), f = free(i);
      if (b && f) { boundaryFree = i; break; }
      if (b && boundaryAny < 0) boundaryAny = i;
      if (f && anyFree < 0) anyFree = i;
    }
    // A whole word somewhere else beats a syllable of the right word: the
    // fragment is a word of the clue, so a match that is not one is a
    // coincidence of spelling.
    const i = [boundaryFree, boundaryAny, anyFree, clue.indexOf(text)]
      .filter((x) => x >= 0)[0];
    return i === undefined ? -1 : i;
  }

  function clueHTML(e) {
    const ann = annOf(e);
    if (!ann) return plainClueHTML(e);
    const shown = (key) => isShown(e, key);
    const marks = [];
    const push = (text, cls) => {
      if (!text) return;
      const i = bestOccurrence(e.clue, text, marks);
      if (i >= 0) marks.push({ i, len: text.length, cls });
    };
    if (shown("definition")) {
      push(ann.definition, "def");
      push(ann.definition2, "def2");
      // Link words ride with the definition: their whole job is to show where
      // the definition stops and the wordplay starts, which gives away the
      // definition's edge. They are not a rung of their own.
      (ann.linkWords || []).forEach((w) => push(w, "link"));
    }
    if (shown("indicators")) (ann.indicators || []).forEach((ind) => push(ind, "ind"));
    if (!marks.length) return plainClueHTML(e);
    // Where two marks still overlap — an indicator genuinely sitting inside the
    // definition — markUp gives each cut piece to the FIRST mark that covers it,
    // so shortest-first hands the overlap to the more specific of the two and
    // the longer one keeps everything either side. Both stay visible; neither is
    // thrown away.
    marks.sort((a, b) => a.len - b.len);
    return markUp(e.clue, marks, italicsOf(e));
  }

  // A CHECKING letter is the crossword term for a square this entry shares with
  // one crossing the other way — the letters another answer hands you for free.
  // They are what decides which clue to attack next, and the grid makes you hunt
  // for them: you have to find the entry, run your eye along it and count what is
  // already there. One dot per checking square, in order along the entry, filled
  // when that square has a letter, says the same thing at a glance and from the
  // list you are already reading.
  //
  // Deliberately NOT a count of every filled square: letters you typed yourself
  // are not checking letters, they are your own guess, and counting them would
  // make a half-typed answer look like a well-supported one. Unchecked squares
  // get no dot at all rather than a permanently empty one — nothing will ever
  // fill them for you, so a dot there would only ever read as a gap.
  function checkerDots(e) {
    const dots = entryCells(e)
      .filter((c) => c && c.across && c.down)
      .map((c) => `<i class="${c.letter ? "on" : ""}"></i>`);
    if (!dots.length) return "";
    const got = dots.filter((d) => d.includes("on")).length;
    const label = `${got} of ${dots.length} crossing letters filled`;
    return `<span class="dots" title="${label}" aria-label="${label}" role="img">` +
      dots.join("") + "</span>";
  }

  function refreshClues() {
    const curE = currentEntry();
    entries.forEach((e) => {
      const li = $("clue-" + e.id);
      if (!li) return;
      const holder = (e.annotation && e.annotation.linkedTo) ? byId[e.annotation.linkedTo] : e;
      li.querySelector(".clue-text").innerHTML = (holder === e) ? clueHTML(e) : plainClueHTML(e);
      const solved = isEntrySolved(e);
      // Nothing to tell you about a clue you have finished — the row greys out
      // and a full row of dots would just be noise on every solved line.
      li.querySelector(".checkers").innerHTML = solved ? "" : checkerDots(e);
      li.classList.toggle("active", !!curE && entryKey(curE) === entryKey(e));
      li.classList.toggle("solved", solved);
    });
  }

  // ---------- selection & movement ----------
  function currentEntry() {
    const c = cells[cur.y] && cells[cur.y][cur.x];
    if (!c) return null;
    const id = c[cur.dir] || c[cur.dir === "across" ? "down" : "across"];
    return id ? byId[id] : null;
  }

  // Choosing a clue should put the clue in front of you. On a phone the layout
  // is a single column — grid, toolbar, hint panel, then the clue lists — so
  // picking an entry updated a panel that was off the bottom of the screen if
  // you'd come from the grid and off the top if you'd come from the list, and
  // either way you had to go looking for it. block:"nearest" is what keeps
  // this from being annoying: it scrolls the least it can, and does nothing at
  // all when the panel is already visible, which is the desktop two-column
  // case. Only fires when the SELECTED ENTRY CHANGES — scrolling on every
  // keystroke or arrow key would be intolerable.
  // A little air above the panel when it is scrolled to the top of the screen,
  // so it reads as the top of something rather than as a cut-off.
  const HINT_SCROLL_GAP = 8;
  // scrollIntoView({block:"nearest"}) did this job and did it in two goes on an
  // iPad in portrait: one tap moved a little, the next moved the rest (Paul,
  // 2026-08-16). Two causes, both fixed here.
  //
  // It measured too early. refreshAll() has just rewritten the panel and a
  // different clue is a different height — fewer rungs up, a longer clue, a
  // wider letter strip — so the page reflows and, on iOS, the smooth scroll in
  // flight gets clamped against a document that changed under it. Measure after
  // layout, never in the same tick as the tap.
  //
  // And it was relative. "nearest" scrolls the least it can FROM WHERE YOU ARE,
  // so the same tap lands somewhere different depending on where you started,
  // which is what "a bit, then all the way" is. Computing one absolute target
  // makes the move idempotent: after it, the panel is fully on screen, so the
  // next tap takes the already-visible branch and the page holds still. That
  // branch is also what keeps the desktop's two columns from ever scrolling.
  //
  // And it measured the wrong screen. iOS does NOT shrink window.innerHeight when
  // the soft keyboard comes up: the layout viewport stays its full height and the
  // keys sit on top of the bottom third of it, so a panel this code called "fully
  // in view" was parked behind them (Paul, iPad, 2026-08-16). visualViewport is
  // the part still showing — and since tapping a clue also raises the keyboard,
  // this is the ordinary case, not an edge one.
  //
  // The band of the page you can actually see, in the same client coordinates
  // getBoundingClientRect() speaks. offsetTop is where the visible part starts
  // inside the layout viewport (the keyboard can push it down as well as cut it
  // short). innerHeight is the fallback for browsers without visualViewport.
  function visibleBand() {
    const vv = window.visualViewport;
    if (vv && vv.height) {
      const top = vv.offsetTop || 0;
      return { top, bottom: top + vv.height };
    }
    return { top: 0, bottom: window.innerHeight || 0 };
  }
  // One tap, one move. This used to scroll the moment the tap was handled and
  // then re-place on every visualViewport resize for the next 1.2 seconds, which
  // on an iPhone is a fight it cannot win — "scrolls down then back up a bit then
  // wiggles before stopping" (Paul, iPhone, 2026-08-16). Three things were going
  // wrong at once, and all three are the same mistake: SCROLLING BEFORE THE
  // VIEWPORT HAS STOPPED MOVING.
  //
  //   down    the first measurement happens with the keyboard still on its way
  //           in, so the band is the whole screen and the panel gets bottom-
  //           aligned to a floor that is about to rise;
  //   back up once the keyboard lands, the panel is taller than what is left of
  //           the band, so the branch below flips from bottom-aligning to top-
  //           aligning it and the page walks back the other way;
  //   wiggle  every re-place issues a fresh smooth scrollTo that clamps the one
  //           still in flight, and on a phone (not an iPad) Safari collapses its
  //           URL bar AS WE SCROLL, which fires resize, which re-places, which
  //           scrolls. The loop only stops because the window times out.
  //
  // So wait for the viewport to hold still and then scroll exactly once. Each
  // resize pushes the placement back another settle; the deadline stops Safari's
  // toolbar from deferring it indefinitely. When the keyboard is already up
  // nothing resizes at all and the wait is one settle, which reads as instant.
  const HINT_SETTLE_MS = 90;
  const HINT_DEADLINE_MS = 600;
  // And one more look afterwards, because the deadline can fire while the
  // keyboard is STILL coming in — a cold keyboard, a predictive bar, a slow
  // first tap — and then we have measured a band that is about to shrink and we
  // never look again. That is "worked for some but not others" (Paul, iPhone,
  // 2026-08-16): identical code, and whether it lands depends on whether the
  // keyboard beat the deadline.
  //
  // The trigger is deliberately NOT "does the panel look wrong now" — the smooth
  // scroll is very likely still in flight at this point, so the panel legitimately
  // looks wrong and re-scrolling on that is the wiggle again. It is "did the
  // visible band move after we committed to it", which is the miss itself and
  // nothing else. And exactly one, never re-armed by viewport events. The target
  // is safe to recompute mid-flight: y + r.top is the panel's position in the
  // document, which scrolling does not change.
  const HINT_CONFIRM_MS = 450;
  // The first tap of a session is the slow one: the keyboard has never been
  // raised, so iOS builds it cold — keys, then the predictive bar — and the
  // resize can land well past deadline + one confirm, which is "the first click
  // which brings up the word seems to not scroll" (Paul, iPad, 2026-08-17).
  // Every later tap finds the keyboard already up, resizes nothing, and lands on
  // the first placement, which is why only the first one misses.
  //
  // So the confirming look WAITS for the viewport to go quiet instead of firing
  // at a fixed delay: a viewport event inside the watch window pushes it further
  // out, and the window bounds how long it can be pushed.
  //
  // A TAP MOVES THE PAGE AT MOST TWICE, and that budget is the load-bearing part.
  // Letting the confirm re-arm itself after it fired was "clicking 3d with all
  // the hints open scrolls down then up then down then up then down" (Paul, iPad,
  // 2026-08-17): our own smooth scroll moves the visual viewport, which fires the
  // same events the keyboard does, so a confirm that can re-place and then watch
  // again is a loop feeding on its own output, and nothing in the measurement can
  // tell the two apart — a pan and a keyboard both just move the band. The budget
  // can, because it does not have to know why the band moved. One placement on
  // the best information available, one correction once everything has stopped,
  // and then the page belongs to the reader again.
  const HINT_WATCH_MS = 1800;
  // A keyboard that has not started coming up yet looks exactly like a viewport
  // that is never going to move: both are silence, and the settle above can only
  // measure silence. At the instant of the tap the band has been quiet forever,
  // so the placement goes ahead against the whole screen and the confirm has to
  // walk it back once the keys land — down, then up a little (Paul, iOS,
  // 2026-08-21). The confirm was doing its job; there was just no reason to have
  // needed it.
  //
  // Silence only means settled when nothing is owed. Tapping a clue focuses the
  // typing input, and on a touch device that raises a keyboard, so until the band
  // shows one there is a change outstanding and nothing worth measuring. This is
  // not a guess about how tall the keys are — that would be a number to get
  // wrong. It is the difference between "nothing will happen" and "nothing has
  // happened yet", which is knowable.
  //
  // Taller than any URL bar, shorter than any soft keyboard: the two are an order
  // of magnitude apart, so nothing hinges on where in the gap this sits.
  const KEYBOARD_MIN_PX = 100;
  function keyboardUp() {
    const vv = window.visualViewport;
    const ih = window.innerHeight || 0;
    return !!(vv && vv.height && ih && ih - vv.height >= KEYBOARD_MIN_PX);
  }
  // A keyboard is OWED only when a tap actually asked for one, which is focusKbd
  // moving focus into the input on a touch device. This used to read "the input
  // is focused and no keyboard is showing" — which is also exactly what an iPad
  // looks like once you dismiss the keyboard with the chevron, or hinge on a
  // hardware one. Every clue tap after that waited out the full cold-keyboard
  // deadline for keys that were never coming, and the page sat still for over a
  // second before it moved (Paul, iPad, 2026-08-28).
  let kbdOwed = false;
  function keyboardExpected() {
    if (keyboardUp()) kbdOwed = false;
    return kbdOwed;
  }
  // Longer than the ordinary deadline because a cold first keyboard is slow to
  // build, and the wait only ever costs anything on a device that raises one at
  // all. If the keys never come — a hardware keyboard on an iPad — the placement
  // still happens here, and the confirm is still behind it.
  const HINT_KEYBOARD_MS = 1200;
  let settleTimer = null, settleBy = 0, confirmTimer = null, placedKeys = null,
      watchUntil = 0, confirmsLeft = 0;
  function scrollToHintPanel() {
    const now = Date.now();
    settleBy = now + (keyboardExpected() ? HINT_KEYBOARD_MS : HINT_DEADLINE_MS);
    watchUntil = now + HINT_WATCH_MS;
    confirmsLeft = 1;
    if (confirmTimer) { clearTimeout(confirmTimer); confirmTimer = null; }
    armHintPlacement();
  }
  function armHintPlacement() {
    if (settleTimer) clearTimeout(settleTimer);
    // While a keyboard is owed there is nothing worth measuring, so the wait runs
    // all the way to the deadline rather than to the settle. The keys arriving is
    // a resize, which comes back through here — and by then nothing is owed, so
    // it takes the short wait and places almost at once. The deadline is only
    // reached when the keyboard never comes at all.
    const left = Math.max(0, settleBy - Date.now());
    settleTimer = setTimeout(() => {
      placeHintPanel();
      armConfirm(HINT_CONFIRM_MS);
    }, keyboardExpected() ? left : Math.min(HINT_SETTLE_MS, left));
  }
  // Re-arming only ever postpones the one confirm this tap is allowed; it never
  // buys another.
  function armConfirm(delay) {
    if (!confirmsLeft) return;
    if (confirmTimer) clearTimeout(confirmTimer);
    confirmTimer = setTimeout(confirmHintPlacement, delay);
  }
  // The correction fires on the keyboard, not on the band. "Did the band move
  // since we committed to it" sounds like the miss and isn't: OUR OWN SMOOTH
  // SCROLL moves it, because iOS pans the visual viewport under a scroll and
  // slides the URL bar away as well, so every well-placed panel then bought
  // itself a second move — down, then up a little (Paul, iOS, 2026-08-21). The
  // band cannot say who moved it.
  //
  // The keyboard can. It is the one thing we were unsure about when we measured,
  // it is the only thing that can invalidate the placement, and at a hundred
  // pixels it is out of reach of a pan or a toolbar. So: re-place only if the
  // keyboard is not in the state it was in when we placed. A tap that measured
  // the truth costs exactly one move; the correction is left for the tap that
  // guessed.
  function confirmHintPlacement() {
    confirmTimer = null;
    if (placedKeys === null || !confirmsLeft) return;
    confirmsLeft = 0;
    if (keyboardUp() === placedKeys) return;
    placeHintPanel();
  }
  // Only ever called off that timer, so layout has long since flushed and there
  // is nothing to measure a frame later for.
  function placeHintPanel() {
    settleTimer = null; settleBy = 0; kbdOwed = false;
    const p = $("hint-panel");
    if (!p || p.classList.contains("hidden") || !p.getBoundingClientRect) return;
    const r = p.getBoundingClientRect();
    const band = visibleBand();
    const vh = band.bottom - band.top;
    if (vh <= 0 || !r.height) return;
    // What we were unsure about when we measured, for confirmHintPlacement to
    // compare against. Recorded even when we decide not to scroll: "already in
    // view" measured against a band the keyboard is still eating is the same
    // wrong answer as any other.
    placedKeys = keyboardUp();
    if (r.top >= band.top && r.bottom <= band.bottom) return;   // all there already
    const y = window.pageYOffset || 0;
    // Too tall to fit, or hanging off the top: line its top up with the top of
    // the band. Otherwise it is below, so pull its bottom up to the band's floor.
    const top = (r.height > vh - HINT_SCROLL_GAP || r.top < band.top)
      ? y + r.top - band.top - HINT_SCROLL_GAP
      : y + r.bottom - band.bottom + HINT_SCROLL_GAP;
    // Smooth: the travel is how the reader keeps their place, and "the smooth
    // scroll was nice" (Paul, iPad, 2026-08-28). What read as slow was never the
    // animation, it was the wait in front of it — keyboardExpected above used to
    // claim a keyboard was coming on taps that had asked for nothing, and the
    // page held still for a second before setting off. Fix the wait, keep the
    // travel. Reduced motion gets the jump instead, as it does everywhere else.
    const still = window.matchMedia &&
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: Math.max(0, top), behavior: still ? "auto" : "smooth" });
  }
  // settleBy and watchUntil are the whole guard: a resize matters only while a tap
  // is waiting to land, or while the keyboard it asked for could still be on its
  // way in. A keyboard raised for something else, a dismissal, a rotation or the
  // URL bar sliding away under an ordinary scroll must not yank the page out from
  // under someone who is reading.
  // Both events, because the keyboard does not always resize the band: when the
  // page cannot scroll any further iOS PANS the visual viewport instead, which
  // moves offsetTop and fires scroll only. Measuring through that gap gives a
  // band starting at 0 when it really starts sixty pixels down.
  if (window.visualViewport && window.visualViewport.addEventListener) {
    const settling = () => {
      if (settleBy) armHintPlacement();
      // Confirm on the CONFIRM delay, not the shorter settle one: our own smooth
      // scroll makes a phone's URL bar slide away, which fires here, and looking
      // 90ms in means measuring mid-flight and re-scrolling on it — the wiggle.
      else if (Date.now() < watchUntil) armConfirm(HINT_CONFIRM_MS);
    };
    window.visualViewport.addEventListener("resize", settling);
    window.visualViewport.addEventListener("scroll", settling);
  }

  // Every tap on the grid brings the clue to you, including a tap on the entry
  // already selected. This used to fire only when the SELECTED ENTRY CHANGED,
  // which made the one tap nobody can avoid the one that did nothing: 1-across
  // is selected before you touch anything, so starting the puzzle by tapping its
  // first square left the clue off the bottom of the screen and the keyboard
  // over where it would have been (Paul, 2026-08-20).
  //
  // The guard was never what stopped the page moving under a reader — typing and
  // the arrow keys do not come through here, and placeHintPanel already does
  // nothing when the panel is fully in the visible band. So it only ever
  // suppressed the case where the panel is NOT in view, which is the case that
  // needs it. A tap is a deliberate act; treat every one the same.
  function onCellClick(c) {
    if (cur.x === c.x && cur.y === c.y) {
      const other = cur.dir === "across" ? "down" : "across";
      if (c[other]) cur.dir = other;
    } else {
      cur.x = c.x; cur.y = c.y;
      if (!c[cur.dir]) cur.dir = c.across ? "across" : "down";
    }
    // Picking a square picks a CLUE. It used to raise the keyboard as well, on
    // the reading that tapping a square is a decision to type — but the first
    // thing the ladder does with a clue you have just picked is ask you a
    // question you answer by tapping, and a keyboard over the bottom half of
    // the screen buries it (Paul, 2026-08-29). The letter strip under the clue
    // is where typing starts now, and it is the only thing that summons one.
    keepKbd();
    refreshAll();
    if (currentEntry()) scrollToHintPanel();
  }

  function selectEntry(e, jumpToStart) {
    cur.dir = e.direction;
    if (jumpToStart || !cellInEntry(cur.x, cur.y, e)) {
      // jump to first empty cell of the entry, else its start
      let target = null;
      for (let i = 0; i < e.length; i++) {
        const c = cellAt(e, i);
        if (!c.letter && !target) target = c;
      }
      const c0 = target || cellAt(e, 0);
      cur.x = c0.x; cur.y = c0.y;
    }
    refreshAll();
    scrollToHintPanel();
  }

  const cellAt = (e, i) => cells[e.position.y + (e.direction === "down" ? i : 0)][e.position.x + (e.direction === "across" ? i : 0)];
  const cellInEntry = (x, y, e) =>
    (e.direction === "across" && y === e.position.y && x >= e.position.x && x < e.position.x + e.length) ||
    (e.direction === "down" && x === e.position.x && y >= e.position.y && y < e.position.y + e.length);

  function moveInEntry(delta) {
    const e = currentEntry();
    if (!e) return;
    const i = e.direction === "across" ? cur.x - e.position.x : cur.y - e.position.y;
    const j = Math.min(e.length - 1, Math.max(0, i + delta));
    const c = cellAt(e, j);
    cur.x = c.x; cur.y = c.y;
  }

  function moveSpatial(dx, dy) {
    let { x, y } = cur;
    const { rows, cols } = P.dimensions;
    for (;;) {
      x += dx; y += dy;
      if (x < 0 || y < 0 || x >= cols || y >= rows) return;
      if (cells[y][x]) break;
    }
    cur.x = x; cur.y = y;
    const c = cells[y][x];
    const wantDir = dx !== 0 ? "across" : "down";
    if (c[wantDir]) cur.dir = wantDir;
    else cur.dir = c.across ? "across" : "down";
  }

  // After typing, land on the next square that still needs a letter — squares
  // already filled by a crossing entry are not worth stopping on. If everything
  // ahead is filled, fall back to a plain one-square step so the cursor still
  // moves (and typing over a letter stays possible).
  function advanceToGap() {
    const e = currentEntry();
    if (!e) return;
    const i = e.direction === "across" ? cur.x - e.position.x : cur.y - e.position.y;
    for (let j = i + 1; j < e.length; j++) {
      const c = cellAt(e, j);
      if (!c.letter) { cur.x = c.x; cur.y = c.y; return; }
    }
    moveInEntry(1);
  }

  function stepEntry(delta) {
    const e = currentEntry();
    let i = entries.indexOf(e);
    i = (i + delta + entries.length) % entries.length;
    selectEntry(entries[i], true);
  }

  // ---------- typing ----------
  function typeLetter(ch) {
    const c = cells[cur.y][cur.x];
    if (!c) return;
    beacon("letter");
    c.letter = ch; c.wrong = false; c.revealed = false;
    checkSolvedEntries();
    advanceToGap();
    refreshAll(); saveState();
  }

  function backspace() {
    const c = cells[cur.y][cur.x];
    if (c && c.letter) { c.letter = ""; c.wrong = false; }
    else { moveInEntry(-1); const c2 = cells[cur.y][cur.x]; if (c2) { c2.letter = ""; c2.wrong = false; } }
    refreshAll(); saveState();
  }

  function onKey(ev) {
    if ($("app").classList.contains("hidden")) return;
    const k = ev.key;
    if (/^[a-zA-Z]$/.test(k)) { typeLetter(k.toUpperCase()); ev.preventDefault(); }
    else if (k === "Backspace") { backspace(); ev.preventDefault(); }
    else if (k === "Delete") { const c = cells[cur.y][cur.x]; if (c) { c.letter = ""; c.wrong = false; refreshAll(); saveState(); } ev.preventDefault(); }
    else if (k === "ArrowLeft") { moveSpatial(-1, 0); refreshAll(); ev.preventDefault(); }
    else if (k === "ArrowRight") { moveSpatial(1, 0); refreshAll(); ev.preventDefault(); }
    else if (k === "ArrowUp") { moveSpatial(0, -1); refreshAll(); ev.preventDefault(); }
    else if (k === "ArrowDown") { moveSpatial(0, 1); refreshAll(); ev.preventDefault(); }
    else if (k === "Tab") { stepEntry(ev.shiftKey ? -1 : 1); ev.preventDefault(); }
    else if (k === "Enter" || k === " ") {
      const c = cells[cur.y][cur.x];
      if (c) { const other = cur.dir === "across" ? "down" : "across"; if (c[other]) { cur.dir = other; refreshAll(); } }
      ev.preventDefault();
    }
  }

  function focusKbd() {
    const kbd = $("kbd");
    // Only a focus that MOVES focus can raise a keyboard, and only a keyboard on
    // its way in is worth waiting for. Re-focusing the input that is already
    // focused — what the clue lists and the hint buttons do to keep a keyboard
    // from leaving — changes nothing about the viewport, so it must not make the
    // next tap wait for a change that is not coming.
    if (document.activeElement !== kbd && !keyboardUp() &&
        typeof navigator !== "undefined" && navigator.maxTouchPoints) kbdOwed = true;
    kbd.value = "";
    kbd.focus({ preventScroll: true });
  }

  // Decline to dismiss a keyboard that is already up, and never summon one.
  // Tapping anything that is not the input blurs it, and a keyboard leaving is a
  // viewport change that reflows the page under the finger that caused it — so
  // steady either way is the requirement, up and staying up or down and staying
  // down. It is the CHANGE that flashes.
  //
  // This is the rule for every tap on the page except one. Only the letter strip
  // summons a keyboard, because tapping the boxes you are about to fill in is
  // the only tap that says "I am going to type".
  // "Focused" is not the same question as "keyboard up", and on an iPad they come
  // apart: dismiss the keys with the chevron and the input stays focused with no
  // keyboard on screen. Re-focusing a focused input is a no-op on a desktop, but
  // inside a touch gesture iOS reads it as a fresh request and puts the keyboard
  // BACK — so on that one state this function summoned the very thing it exists
  // to avoid summoning (Paul, iPad home-screen app, 2026-09-01). There is nothing
  // to keep when nothing is up, so keep nothing.
  //
  // Losing the focus costs no typing: the document-level keydown handler feeds
  // onKey whatever a hardware keyboard sends, focused input or not. #kbd is only
  // the intake for a SOFT keyboard, and a soft keyboard that is down is not
  // typing into anything.
  function keepKbd() {
    if (document.activeElement !== $("kbd")) return;
    if (typeof navigator !== "undefined" && navigator.maxTouchPoints && !keyboardUp()) return;
    focusKbd();
  }

  // ---------- checking / revealing ----------
  function canCheck() { return hasSolutions(); }

  // A check must ALWAYS visibly answer (feedback 2026-07-29: checking a correct
  // entry changed nothing on screen, so the button read as broken). Two signals:
  // a sentence in #check-result saying what was found, and a brief pulse on the
  // squares that were examined, so you can see WHICH squares the check covered.
  function checkCells(list, scope) {
    if (!canCheck()) return;
    beacon("check");
    let wrong = 0, right = 0, blank = 0;
    list.forEach((c) => {
      if (!c.letter) { blank++; return; }
      if (c.letter !== c.sol) { c.wrong = true; wrong++; } else right++;
    });
    announceCheck(scope || "grid", wrong, right, blank);
    pulseCells(list);
    refreshAll(); saveState();
  }

  let checkMsgTimer = null;
  function announceCheck(scope, wrong, right, blank) {
    const el = $("check-result");
    if (!el) return;
    const s = (n) => (n === 1 ? "" : "s");
    let msg, cls;
    if (!wrong && !right) {
      msg = `Nothing to check yet — no letters typed in the ${scope}.`;
      cls = "idle";
    } else if (wrong) {
      msg = `${wrong} wrong letter${s(wrong)} marked in red`
          + (right ? `, ${right} correct` : "")
          + (blank ? `, ${blank} still blank` : "") + ".";
      cls = "bad";
    } else {
      msg = `All ${right} letter${s(right)} in the ${scope} correct`
          + (blank ? ` so far — ${blank} square${s(blank)} still blank` : "") + ".";
      cls = "ok";
    }
    el.className = "check-result " + cls;
    el.textContent = msg;
    clearTimeout(checkMsgTimer);
    checkMsgTimer = setTimeout(() => {
      el.textContent = ""; el.className = "check-result";
    }, 6000);
  }

  function pulseCells(list) {
    list.forEach((c) => { if (c.el) c.el.classList.add("pulse"); });
    setTimeout(() => list.forEach((c) => { if (c.el) c.el.classList.remove("pulse"); }), 600);
  }
  function entryCells(e) { const out = []; for (let i = 0; i < e.length; i++) out.push(cellAt(e, i)); return out; }

  function revealCell(c) { c.letter = c.sol; c.wrong = false; c.revealed = true; }

  // Escape hatch, available at ANY hint level: reveal one letter. It doesn't
  // advance the teaching ladder, but it does count against the score.
  function revealLetter() {
    const e = currentEntry();
    if (!e || !canCheck()) return;
    // prefer the selected cell if it's empty/wrong, else first empty/wrong cell
    const cs = entryCells(e);
    const cSel = cells[cur.y][cur.x];
    let target = (cSel && cellInEntry(cSel.x, cSel.y, e) && cSel.letter !== cSel.sol) ? cSel : null;
    if (!target) target = cs.find((c) => c.letter !== c.sol) || null;
    if (target) {
      revealCell(target);
      const key = entryKey(e);
      revealsUsed[key] = (revealsUsed[key] || 0) + 1;
    }
    checkSolvedEntries(); refreshAll(); saveState();
  }

  // Past the last rung: write the whole answer into the grid.
  function fillAnswer() {
    const e = currentEntry();
    if (!e || !canCheck()) return;
    showHint(e, ANSWER_RUNG);
    entryCells(e).forEach(revealCell);
    checkSolvedEntries(); refreshAll(); saveState();
  }

  function isEntrySolved(e) {
    if (!e.solution) return false;
    for (let i = 0; i < e.length; i++) if (cellAt(e, i).letter !== e.solution[i]) return false;
    return true;
  }

  // The whole of a linked group, not one leg of it: a linked clue's hints cover
  // both entries, so getting the first must not hand over the second.
  function groupSolved(e) {
    const key = entryKey(e);
    const group = entries.filter((g) => entryKey(g) === key);
    return group.length > 0 && group.every(isEntrySolved);
  }

  function checkSolvedEntries() {
    entries.forEach((e) => {
      if (isEntrySolved(e) && solvedWith[e.id] === undefined) {
        solvedWith[e.id] = Math.max(0, shownRungs(e).length - earnedRungs(e).length);
        beacon("entry");
      }
    });
  }

  // ---------- hint ladder ----------
  // The ladder is BUILT PER CLUE, not fixed: a rung only exists if it has
  // something to say. A double definition has no indicators, so it gets no
  // "spot the indicator" rung (which used to read "No indicator words"), and
  // its rungs are worded for two definitions rather than one. See APP.md.
  const FILL_LABEL = "Fill in answer";

  const TYPE_BLURBS = [
    ["anagram", "An anagram: some words in the clue are raw letter fodder to be rearranged. Find the indicator, then count letters against the enumeration."],
    ["charade", "A charade: the answer is built from parts placed one after another, each clued separately."],
    ["container", "A container: one part is placed inside another. Look for words like holding, in, covering, swallowing."],
    ["hidden", "A hidden word: the answer is spelled out consecutively inside the clue itself."],
    ["homophone", "A homophone: the wordplay describes something that sounds like the answer."],
    ["reversal", "A reversal: something is spelled backwards (in a down clue, 'up'-words signal this)."],
    ["deletion", "A deletion: letters are removed from a longer word — heads, tails or insides."],
    ["double definition", "A double definition: two definitions sit side by side; there is no other wordplay."],
    ["&lit", "An &lit: the whole clue is both the definition and the wordplay at once."],
    ["alternate letters", "Alternate letters: take every other letter of an indicated word."],
    ["regular letters", "Regular letters: count through an indicated phrase at a fixed step — every third letter, say — and keep the ones you land on."],
    ["first letter", "First letters: take the initial letter(s) of indicated word(s)."],
    ["last letter", "Last letters: take the final letter(s) of indicated word(s)."],
    ["middle letter", "Middle letters: take just the centre of an indicated word."],
    ["second letter", "Second letters: count into the indicated word(s) and keep only the letter in position two."],
    ["outer letters", "Outer letters: keep only the outside letters of an indicated word."],
    ["cryptic definition", "A cryptic definition: no separable wordplay — the whole clue is one sly description."],
    ["spoonerism", "A spoonerism: swap the opening sounds of two words to get the answer."],
    ["cycling", "Cycling: letters move from one end to the other without changing their order — the word rotates rather than shuffles."],
    ["substitution", "A substitution: one indicated letter or chunk stands in for another — make the swap and the answer appears."],
    ["palindrome", "A palindrome: the answer reads the same forwards and backwards, and that symmetry is the wordplay — there is nothing else to take apart."]
  ];

  // Rung 1 must not hand the mechanism over. It names the FAMILY — the shape of
  // the job — and the precise (honest, compound) type is held back until the
  // building-blocks rung. First match wins, so the list is ordered by which
  // mechanism dominates a compound type. Every part in TYPE_PARTS (validator)
  // must be claimed by exactly one family here. See APP.md.
  const FAMILIES = [
    { label: "Definitions only",
      // Says what the family IS and stops. It used to add that the work is
      // spotting which words define, which on a two-word double definition is a
      // claim the page then disproves: both words define, so the definition
      // rung has nothing to ask and there are no blocks either. A blurb that
      // promises work the clue does not contain reads as a lie (Paul).
      blurb: "No letter mechanics at all — nothing is anagrammed, hidden or spelled out. Either two plain definitions sit side by side, or one sly one describes the answer the long way round.",
      match: (t) => t.includes("double definition") || t.includes("cryptic definition") },
    { label: "&lit",
      blurb: "The whole clue does double duty: read it once as a definition, then read the very same words again as wordplay.",
      match: (t) => t.includes("&lit") },
    { label: "Rearrangement",
      blurb: "Letters handed to you in the clue get shuffled into the answer. Find the fodder and count it against the enumeration.",
      match: (t) => t.includes("anagram") || t.includes("cycling") },
    { label: "Sound",
      blurb: "The wordplay describes how the answer sounds rather than how it is spelled.",
      match: (t) => t.includes("homophone") || t.includes("spoonerism") },
    { label: "Charade",
      blurb: "The answer is built from pieces laid end to end, each clued separately — read the wordplay left to right.",
      match: (t) => t.includes("charade") },
    { label: "Alteration",
      blurb: "A piece of the wordplay is changed rather than just joined on: put inside something, turned around, or trimmed.",
      match: (t) => t.includes("container") || t.includes("reversal") || t.includes("deletion") || t.includes("substitution") || t.includes("palindrome") },
    { label: "Extraction",
      blurb: "The answer's letters are already sitting in the clue in order — the job is working out which ones to pick out.",
      match: (t) => t.includes("hidden") || t.includes("letter") }
  ];

  // Every family a compound type actually uses, dominant one first. A clue can be
  // more than one thing at once — "there was a regularly indicator but I said it
  // was a charade" (Paul, 2026-08-28) — and on a type like "charade with
  // alternate letters" both answers are the truth. The ladder still NAMES one,
  // because a headline has to pick, but marking the others wrong teaches the
  // solver that a clue has exactly one mechanism, which is the opposite of what
  // this rung is for.
  function familiesOf(type) {
    const t = (type || "").toLowerCase();
    return FAMILIES.filter((f) => f.match(t));
  }
  function familyOf(type) {
    return familiesOf(type)[0] ||
      { label: "Wordplay", blurb: "The clue has a definition at one end and wordplay at the other." };
  }

  function typeBlurb(type) {
    const t = (type || "").toLowerCase();
    const hits = TYPE_BLURBS.filter(([k]) => t.includes(k)).map(([, v]) => v);
    return hits.join(" ") || "";
  }

  // What an indicator actually INSTRUCTS, and how to recognise its family next
  // time. The rung used to read "these tell you what to do with the rest", which
  // is true of every indicator in every clue ever written — content-free, and a
  // rung the solver spends a hint on. The operation is derivable from the type we
  // already store, so this costs nothing and cannot drift from the annotation.
  //
  // Plain language, not the jargon: "rearrange the letters it points at" rather
  // than "anagram indicator". The precise mechanism is still held back for the
  // building-blocks rung (see `mechanics`), and naming the job is the teaching
  // content — naming the term would only be the label.
  const INDICATOR_OPS = [
    ["anagram", "rearrange the letters it points at",
      "Anagram indicators describe a mess rather than a meaning: disorder, drunkenness, cooking, damage, movement. If a word tells you something is broken, stirred or at sea, suspect fodder nearby."],
    ["container", "put one piece inside another",
      "Containers are clued by words for holding and swallowing — in, about, around, eating, grips, hosting. The tricky ones read as ordinary prepositions."],
    ["reversal", "write a piece backwards",
      "Reversal words say turn or go back: recalled, returning, over, about. In a DOWN clue, anything meaning upwards does it too — up, rising, climbing — which is why the same clue can work one way and not the other."],
    ["deletion", "drop letters from a word",
      "Deletion words name the part to lose: endless and short take the tail, headless and beheaded the front, gutted and heartless the middle, almost and nearly one final letter."],
    ["hidden", "find a run of letters already sitting in the clue",
      "Hidden-word markers are quiet on purpose — in, some of, part of, held by, a bit of. They point at consecutive letters spanning the gap between two words."],
    ["homophone", "take how a word sounds, not how it is spelled",
      "Sound indicators name an ear: we hear, reportedly, on the radio, said, aloud, announced."],
    ["spoonerism", "swap the opening sounds of two words",
      "Spoonerisms all but announce themselves — the Reverend Spooner is named in the clue."],
    ["alternate letters", "take every other letter",
      "Alternates are signalled by oddly, evenly, regularly, alternately, or by 'every other'."],
    ["regular letters", "count through the letters at a fixed step and keep the ones you land on",
      "These say the step out loud — 'every third letter', 'each fourth' — so read them as arithmetic, not description."],
    ["first letter", "take the opening letter of the words it points at",
      "Initials come from leading words: initially, first, leaders, heads, primarily, to start."],
    ["last letter", "take the final letter of the words it points at",
      "Finals come from trailing words: finally, last, ends, tails, ultimately."],
    ["middle letter", "take just the middle of a word",
      "Centre words: heart of, middle, centrally, core."],
    ["outer letters", "keep only the outside letters of a word",
      "Outer words: outskirts, extremes, borders, bookends, both sides."],
    ["cycling", "move letters from one end to the other, keeping their order",
      "Cycling is rarer than an anagram and looks like one until you notice the order survives: cycles, rotated, circulating."],
    ["substitution", "swap one letter or chunk for another",
      "Substitution is clued by exchange words: for, replacing, instead of, in place of, takes over from."],
    ["palindrome", "check that the answer reads the same in both directions",
      "Palindrome markers talk about symmetry rather than movement: both ways, either way, back to front, whichever end you start."]
  ];

  // The whole answer isn't a teaching rung — it's the end of the road — but it
  // shares the ladder's bookkeeping so it counts against the score like one.
  const ANSWER_RUNG = "answer";
  // Which rungs are up for this clue. Migration from the old high-water integer
  // happens lazily here rather than in restoreState(): converting "level 3" into
  // rung keys needs ladderSteps(), which needs the annotation, and at restore
  // time the model isn't built yet. Reading is the first moment both exist.
  function shownRungs(e) {
    const key = entryKey(e);
    if (!hintsShown[key]) {
      const old = hintLevels[key] || 0;
      hintsShown[key] = old > 0
        ? ladderSteps(annOf(e), e.clue).slice(0, old).map((s) => s.key).concat(
            old > ladderSteps(annOf(e), e.clue).length ? [ANSWER_RUNG] : [])
        : [];
    }
    return hintsShown[key];
  }
  const isShown = (e, rung) => shownRungs(e).indexOf(rung) >= 0;

  // Tiers, not a chain, and not a free-for-all either. Inside a tier the order
  // is the solver's business; across tiers it can't be, because a later rung
  // contains the earlier ones' answers — the building blocks name the
  // definition and the indicators on the way to spelling out the wordplay, and
  // the walkthrough hands over everything. Unrestricted choice (the first cut
  // of this, 2026-08-01) put "skip to the walkthrough" one click from cold,
  // which isn't a ladder at all. So: pick freely among the things the clue
  // asks you to SPOT, then assemble, then be told.
  const RUNG_TIER = { type: 0, definition: 0, indicators: 0, blocks: 1, walkthrough: 2 };
  // The rungs that answer "which words", derived rather than listed again: the
  // tier-0 rungs apart from the one that names no words at all. Two things read
  // it — the type-rung skip, and the greying-out of words a rung has settled —
  // and both must mean the same thing by it.
  const SPOTTING = Object.keys(RUNG_TIER).filter((k) => k !== "type" && !RUNG_TIER[k]);
  // A rung unlocks once every rung of an earlier tier THIS CLUE HAS is up.
  // Per-clue is the whole point: lots of clues have no indicators rung and no
  // blocks rung, and a rung that doesn't exist must never be a lock nobody can
  // open.
  function rungAvailable(e, steps, key) {
    // Solved: nothing left to protect, so the whole ladder opens (Paul,
    // 2026-08-16). The tiers exist so the walkthrough can't be taken before the
    // clue has been fought with; once the answer is in the grid the lock stands
    // between a solver and the explanation of a clue they already got, which is
    // the one thing this site is for. Reading it afterwards is free — see
    // hintsCharged.
    if (groupSolved(e)) return true;
    const tier = RUNG_TIER[key] || 0;
    return steps.every((s) => (RUNG_TIER[s.key] || 0) >= tier ||
                              isShown(e, s.key) || spentBy(e, steps, s.key));
  }

  // A rung nobody should have to buy twice. Knowing where the definition is and
  // which words are the indicator IS knowing what kind of clue this is — an
  // anagram indicator sitting next to a definition is an anagram — so once both
  // spotting rungs are up, "what kind of clue is this?" has nothing left to say,
  // and charging for it to reach the assembly rung is a turnstile.
  //
  // Up by any route: guessed right, guessed nearly, or asked for outright. The
  // rung is spent because its CONTENT is already on the screen, which is a fact
  // about the panel and not about how well the solver did. And read off the
  // ladder rather than a fixed list of names, so a clue with no indicators rung
  // cannot open the gate on the strength of a rung it never had.
  function spentBy(e, steps, key) {
    if (key !== "type") return false;
    const spotting = steps.filter((s) => SPOTTING.indexOf(s.key) >= 0);
    return spotting.length > 0 && spotting.every((s) => isShown(e, s.key));
  }

  function showHint(e, rung) {
    if (isShown(e, rung)) return;
    shownRungs(e).push(rung);
    // WHICH kind of help was reached for, named for the rung. Each rung teaches
    // a different thing — where the definition sits, what the indicators do, how
    // the blocks assemble — so "which one do solvers ask for" says which lesson
    // to write, which is the only question a teaching site can act on. A depth
    // would answer nothing: the ladder is built per clue, and no number on that
    // scale appears anywhere a solver can see.
    beacon("hint-" + rung);
    saveState();
  }

  // Build the rungs this particular clue deserves. Each rung: {key, label, html}.
  // Where the definition sits, and therefore where the wordplay starts. A fair
  // cryptic splits into exactly two parts and finding that seam is most of the
  // battle, so the seam is what this rung should hand over. It is computable
  // from the clue text, which means every clue gets its own sentence instead of
  // the one about definitions living at one end that used to print 25 times a
  // puzzle. Falls back to a bare full stop when the definition is not a literal
  // substring (a normalised apostrophe, an &lit) rather than guessing.
  function defPlace(clue, definition) {
    const bare = String(clue || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
    const def = String(definition || "").trim();
    if (!bare || !def) return ".";
    const at = bare.toLowerCase().indexOf(def.toLowerCase());
    if (at < 0) return ".";
    const trim = (s) => s.trim().replace(/^[,;:.—–-]+|[,;:—–-]+$/g, "").trim();
    const before = trim(bare.slice(0, at));
    const after = trim(bare.slice(at + def.length));
    if (!before && !after) return " — which is the whole clue, and that is what makes this one unusual.";
    if (!before) return `, so the clue opens with it and “${esc(after)}” is the wordplay.`;
    if (!after) return `, right at the end — so “${esc(before)}” is the wordplay.`;
    return `, sitting mid-clue, so the wordplay is “${esc(before)}” and “${esc(after)}” either side of it.`;
  }

  // ---------- doing the anagram ----------
  //
  // Spotting that a clue IS an anagram is the easy half. Rearranging eleven
  // letters in your head is the half people actually fail at, and they fail for
  // a reason the page was causing: the fodder is printed as a word, so the eye
  // keeps re-reading it in the one order that is certainly wrong.
  //
  // The letters go round a ring instead, which is what setters have always told
  // solvers to do on paper — no start, no end, nothing to re-read. Shuffle deals
  // them again, and a tile can be struck out as it is placed. There is no
  // dictionary behind it and there will not be one: a box that hands back the
  // word answers the clue, and answering the clue is what the last rung is for.
  //
  // It lives on the blocks rung and nowhere earlier, because that is the rung
  // that already hands over the fodder. The ring adds no letter the solver
  // hasn't bought; it only takes away the order.
  let ring = null;  // { key, order, struck } — one clue's worth, cleared by key

  // Deal an order that is neither the fodder as written nor the answer as
  // spelled. Landing on either would make a shuffle look broken, and landing on
  // the answer would hand over the solve by luck a rung early.
  function dealRing(letters, forbidden) {
    const bad = forbidden.map((w) => (w || "").toUpperCase().replace(/[^A-Z]/g, ""));
    let order = letters.map((_, i) => i);
    for (let attempt = 0; attempt < 20; attempt++) {
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
      }
      if (bad.indexOf(order.map((i) => letters[i]).join("")) < 0) return order;
    }
    return order;  // repeated letters can make every deal a forbidden one
  }

  function ringHTML(ann) {
    const fodder = ((ann.anagram || {}).fodder || "").toUpperCase().replace(/[^A-Z]/g, "");
    // Keyed off the annotation rather than the clue id: ladderSteps() is a pure
    // function of the annotation and is called for counting as well as drawing,
    // and threading a grid coordinate through it to remember a shuffle would
    // put board state into the thing that describes a clue.
    const key = (ann.answer || "") + "|" + fodder;
    // Three letters have six arrangements and you can see all of them at once,
    // so a ring is furniture rather than help.
    if (fodder.length < 4) return "";
    const letters = fodder.split("");
    if (!ring || ring.key !== key) {
      const forbidden = [fodder, ann.answer];
      ring = { key, letters, forbidden, order: dealRing(letters, forbidden), struck: {} };
    }
    // The ring grows with the fodder so the tiles never overlap; the disc is
    // sized off the same radius so the box is never taller than its contents.
    const radius = Math.max(46, Math.round((letters.length * 30) / (2 * Math.PI)));
    const tiles = ring.order.map((idx, pos) => {
      const a = (pos / letters.length) * 2 * Math.PI - Math.PI / 2;
      return `<button type="button" class="ana-tile${ring.struck[idx] ? " struck" : ""}"
        data-ana="${idx}" aria-pressed="${ring.struck[idx] ? "true" : "false"}"
        style="left:calc(50% + ${Math.round(Math.cos(a) * radius)}px);
               top:calc(50% + ${Math.round(Math.sin(a) * radius)}px)">${letters[idx]}</button>`;
    }).join("");
    const d = radius * 2 + 34;
    return `<div class="anagram-ring">
      <div class="ana-disc" style="width:${d}px;height:${d}px">${tiles}</div>
      <p class="muted">The same letters with no order to fall back into. Tap a letter to
        cross it off once you have placed it, and shuffle when the arrangement
        stops suggesting anything.</p>
      <button type="button" id="ana-shuffle" class="ghost small">Shuffle</button>
    </div>`;
  }

  function ladderSteps(ann, clue) {
    if (!ann) return [];
    const t = (ann.type || "").toLowerCase();
    const isDD = t.includes("double definition");
    const isCD = t.includes("cryptic definition");
    const isLit = t.includes("&lit");
    const inds = ann.indicators || [];
    const blocks = ann.blocks || [];
    const steps = [];

    // Every rung is NAMED for the question it asks, never for the answer it is
    // about to give, because the unbought rungs' names are on screen the whole
    // time — that is how you choose which to buy. The &lit definition rung used
    // to be called "How can the whole clue be the definition?", so the button
    // for a hint nobody had paid for announced that the clue was an &lit, which
    // on a semi-&lit hidden word is the entire solve ("21d gives away the whole
    // thing just by the name of the hint before I reveal it" — Paul, 4096 21d,
    // VSIGN, 2026-08-17). The same was true of "Where does the clue split?",
    // "What is the clue really describing?" and "What each half means", each of
    // which named its type, and of the singular/plural indicator label, which
    // handed over the count.
    //
    // So a label is a function of the rung's key and nothing else, and the
    // smoke test holds the corpus to exactly that: one label per key, across
    // every annotated clue there is. Type-specific wording belongs in the body,
    // which is what you are paying for.
    const LABELS = {
      type: "What kind of clue is this?",
      definition: "Where is the definition?",
      indicators: "Spot the indicator words",
      blocks: "The building blocks",
      walkthrough: "Full walkthrough"
    };
    const fam = familyOf(ann.type);
    steps.push({
      key: "type",
      label: LABELS.type,
      html: `<p><strong>${esc(fam.label)}</strong>. ${esc(fam.blurb)}</p>`
    });

    // The exact mechanism, held back until the user has already seen the family,
    // the definition and the indicators.
    const mechanics = `<p class="mechanism">Mechanism: <strong>${esc(ann.type)}</strong>.
      ${esc(typeBlurb(ann.type))}</p>`;

    // Where the definition lives. For a double definition the news isn't "there
    // are two" (rung 1 said that) — it's WHERE the clue splits.
    if (isDD && ann.definition2) {
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>It splits between <mark class="def">${esc(ann.definition)}</mark> and
          <mark class="def2">${esc(ann.definition2)}</mark> — two unrelated senses of the same
          word, which is where the surface reading misleads you.</p>`
      });
    } else if (isLit) {
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>Read <mark class="def">${esc(ann.definition)}</mark> straight through as a
          description of the answer, then read the very same words again as wordplay.</p>`
      });
    } else if (isCD) {
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>There's no separable wordplay here: <mark class="def">${esc(ann.definition)}</mark>
          is a whole-clue description that only makes sense once you see it the setter's way.</p>`
      });
    } else {
      // Not "everything else is wordplay, and definitions sit at one end" — that
      // sentence was identical on every clue in the corpus, so the rung's only
      // clue-specific content was the highlight itself. Say WHERE it sits and
      // WHERE the wordplay therefore starts: the split point is the actual
      // solving move, and it is computable from the clue text we already have.
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>The definition is <mark class="def">${esc(ann.definition)}</mark>${defPlace(clue, ann.definition)}</p>`
      });
    }

    // `linkWords` names the connective words that carry no wordplay at all,
    // which is the commonest reason a beginner keeps hunting for a mechanism
    // that was never there. It hangs off the definition rung because it is about
    // the CLUE, and a solver can act on it without knowing the answer.
    //
    // `definitionNote` used to hang here too and could not: it explains why the
    // definition does not agree with the ANSWER ("payment" for PEANUTS, singular
    // for a plural), so it is written about the answer and 16 of them in the
    // corpus named it outright — TRUMP CARDS handed over on rung 2. Rewording
    // them would only have hidden a structural mistake: a note comparing the
    // answer to the definition is not an early hint, whatever words it uses. It
    // now renders beside definitionFit on the walkthrough rung, where the answer
    // is already on the table, and the validator gates the early fields at zero.
    const defStep = steps[steps.length - 1];
    if ((ann.linkWords || []).length) {
      const lw = ann.linkWords.map((w) => `<mark class="link">${esc(w)}</mark>`).join(", ");
      defStep.html += `<p class="muted">${lw} ${ann.linkWords.length > 1 ? "are" : "is"}
        just a link — words that join the definition to the wordplay and contribute
        no letters of their own.</p>`;
    }

    // Indicators only exist for some clue types — no rung that says "none".
    if (inds.length) {
      const ops = INDICATOR_OPS.filter(([k]) => t.includes(k));
      const marks = inds.map((i) => `<mark class="ind">${esc(i)}</mark>`).join(", ");
      // The sentences below are the same on every clue of a type: an anagram
      // indicator always "tells you to shuffle", and a compound one always does
      // N things. `indicatorNotes` is the part that is only true of THIS clue,
      // and where it covers every indicator the rung is those notes and nothing
      // else — "this is just context free, never just put out text for the sake
      // of filling space" (Paul, 2026-08-17, on "this clue does two things, and
      // the indicators are what tell them apart"). The generic wording is not a
      // frame worth keeping around a real answer; it is what gets said when
      // there is no real answer, and it survives only for the puzzles that
      // predate the field (tools/annotation_backlog.json).
      //
      // The count made that plain: the ops list is derived from the clue TYPE,
      // so `container + charade + middle letters + reversal` promises four
      // things while only three of them have an indicator to point at. It never
      // described the indicators; it described the type.
      const notes = ann.indicatorNotes || {};
      const written = inds.filter((i) => notes[i]);
      const noteList = `<ul class="ind-notes">${written.map((i) =>
        `<li><mark class="ind">${esc(i)}</mark> — ${esc(notes[i])}</li>`).join("")}</ul>`;
      let html;
      if (written.length === inds.length) {
        html = noteList;
      } else if (ops.length === 1) {
        html = `<p>${marks} — ${inds.length > 1 ? "they tell" : "it tells"} you to
          ${ops[0][1]}.</p><p class="muted">${ops[0][2]}</p>`;
      } else if (ops.length > 1) {
        // A compound type has more than one operation and usually more than one
        // indicator, and nothing in the annotation maps word to job. Saying so is
        // the honest move, and pairing them up is exactly the work of this rung.
        // Counted off the list rather than written into the sentence: it said
        // "two things" and then printed three for `container + charade +
        // middle letters + reversal` (Paul, 4096 16d, 2026-08-17). A number in
        // prose beside a list it is supposed to describe will go wrong the
        // first time a clue does something the sentence never imagined.
        const HOWMANY = ["no", "one", "two", "three", "four", "five", "six"];
        html = `<p>${marks} — this clue does ${HOWMANY[ops.length] || ops.length} things, and
          the indicators are what tell them apart:</p><ul>${ops.map(([, op]) => `<li>${op}</li>`).join("")}</ul>
          <p class="muted">Which word calls for which is the step to work out here.</p>`;
      } else {
        html = `<p>${marks} — ${inds.length > 1 ? "these tell" : "this tells"} you
          what to do with the rest of the wordplay.</p>`;
      }
      // A partly-noted clue is a backlog puzzle mid-repair: the generic wording
      // above is carrying the indicators nobody has written up yet, so whatever
      // notes exist go under it rather than replacing it.
      if (written.length && written.length !== inds.length) html += noteList;
      steps.push({
        key: "indicators",
        label: LABELS.indicators,
        html
      });
    }

    // A cryptic definition has no building blocks — having none is what makes it
    // one — so `gives` is never rendered for it, and the rung is named for the
    // only honest job it has: splitting a clue that does not split into letters
    // into the two ideas the setter fused together.
    //
    // It used to print the whole clue → the whole answer, because that is the
    // only "block" a cryptic definition can have. So hint 3 of 4 read
    // “Might this keep you to time?” → WATCHSTRAP: the solver paid for a rung
    // and was handed the solve, one rung after rung 2 had told them there was no
    // separable wordplay here (Paul, 1392 22-across, 2026-08-10). The validator
    // now refuses a `gives` on a cryptic definition and demands the clue be
    // split, so this suppression is belt to that braces.
    // A block whose letters ARE the whole answer hands over the solve on the
    // rung before the walkthrough, which is the WATCHSTRAP failure again with a
    // different type on it: 488 of 2805 annotated clues did this, almost every
    // hidden word and homophone and most double definitions, because for those
    // devices one block legitimately resolves to the entire word. Suppressing it
    // here rather than in the annotation is deliberate — the annotation keeps
    // recording what the block gives, and no wording a future run picks can leak
    // it. What survives is the fragment, the sounded form and the note.
    const whole = (s) => (s || "").toUpperCase().replace(/[^A-Z]/g, "");
    const answerLetters = whole(ann.answer);
    const givesAway = (b) => answerLetters && whole(b.gives) === answerLetters;
    // The rung exists when something will RENDER in it, not when the data holds
    // a field: a clue whose every block is suppressed and carries no note would
    // otherwise charge a hint for a list of clue fragments the solver can already
    // see. No clue in the corpus does that, and this is what keeps it that way.
    const shows = (b) => b.note || b.soundsLike || (b.gives && !isCD && !givesAway(b));
    if (blocks.length && blocks.some(shows)) {
      // Which pieces were conventions rather than deductions.
      //
      // Charade is our commonest clue type, and the hard part is never spotting
      // that it IS one — it is knowing that "sailor" is AB because the
      // convention says so. No amount of staring derives that, so a rung that
      // hands over the letters without saying which were knowledge leaves the
      // solver unable to tell "think harder" from "look this up once, own it
      // forever".
      //
      // The letters themselves carry that, and nothing else does: a linked AB
      // is one the glossary can explain, an unlinked one was worked out here.
      // It used to be a sentence underneath repeating the same pairs, which is
      // a second reading of something already on the screen (Paul, 2026-08-22:
      // "you still added a sentence", "just linkify the abbreviation itself").
      const glossaryHref = (b) => {
        const letters = (b.gives || "").toUpperCase();
        const meanings = typeof ABBREVIATIONS === "undefined" ? null : ABBREVIATIONS[letters];
        if (!meanings || !b.clueFragment) return null;
        // Whole words only: "one" must not fire inside "money", nor "me" inside
        // "some". The meanings are data, so they get escaped before they are a
        // pattern.
        const frag = b.clueFragment.toLowerCase();
        const word = meanings.find((m) =>
          new RegExp(`\\b${m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(frag));
        // Kept in step with the id tools/build_abbreviations.py writes onto
        // that word's cell on /abbreviations/; tools/smoke_test.js fails if the
        // two ever disagree. Relative, because the app is only ever served from
        // the site root and an absolute path would break a local checkout.
        return word
          ? "abbreviations/#abbr-"
            + word.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
          : null;
      };
      const items = blocks.map((b) => {
        let s = "<li>";
        if (b.clueFragment) s += `“${esc(b.clueFragment)}”`;
        // A homophone's whole mechanism is the word you say aloud, and it used
        // to be nowhere: “Cockney mob” → OARED, with HORDE and the dropped
        // aitch left entirely to the reader (Paul, 4096 24d, 2026-08-17). So
        // the sounded form gets its own arrow, ahead of the letters it turns
        // into, and the validator now refuses a sound clue that has none.
        if (b.soundsLike) s += ` → <span class="gives">${esc(b.soundsLike)}</span> <span class="muted">said aloud</span>`;
        if (b.gives && !isCD && !givesAway(b)) {
          const href = glossaryHref(b);
          const gives = `<span class="gives">${esc(b.gives)}</span>`;
          s += " → " + (href
            ? `<a class="gloss" href="${href}" title="Standard abbreviation — look it up once">${gives}</a>`
            : gives);
        }
        if (b.note) s += ` <span class="muted">— ${esc(b.note)}</span>`;
        return s + "</li>";
      }).join("");
      steps.push({
        key: "blocks",
        label: LABELS.blocks,
        html: (isDD || isCD ? "" : mechanics) + `<ul>${items}</ul>` +
          (t.includes("anagram") ? ringHTML(ann) : "")
      });
    }

    // The half of the clue that isn't mechanical.
    //
    // The blocks spell the answer OUT of the wordplay and the definition rung
    // points at the words, but until now nothing ever joined the two ends:
    // why do those words mean this answer? (Feedback 2026-08-01: "in the full
    // walkthrough explain why the answer matches the definition".) That link is
    // where the actual vocabulary of cryptics lives — a definition by synonym,
    // by example, by a sense of the word nobody uses outside crosswords — and
    // it is exactly what a solver is missing when they have the right letters
    // and no confidence in them. It goes LAST, immediately before the answer,
    // because it is the step that turns a spelling into a solve.
    const fit = ann.definitionFit
      ? `<p class="def-fit"><mark class="def">${esc(ann.definition)}</mark>${
          ann.definition2 ? ` and <mark class="def2">${esc(ann.definition2)}</mark>` : ""
        } → <span class="gives">${esc(ann.answer)}</span>: ${esc(ann.definitionFit)}</p>`
      : "";
    // Why the definition may fairly disagree with the answer in number or part of
    // speech — a footnote to the fit, so it sits with it rather than two rungs above.
    const note = ann.definitionNote
      ? `<p class="def-note">${esc(ann.definitionNote)}</p>` : "";
    steps.push({
      key: "walkthrough",
      label: LABELS.walkthrough,
      html: (steps.some((s) => s.key === "blocks") || isDD || isCD ? "" : mechanics) +
        `<p>${esc(ann.walkthrough)}</p>${fit}${note}<p>Answer: <span class="gives">${esc(ann.answer)}</span></p>`
    });
    return steps;
  }

  // ---------- naming the words before the rung names them ----------
  //
  // Three rungs are questions whose answer is already written down: which words
  // are the definition, which are the indicator, which give this piece. Handing
  // that over is recognition — you nod, and nothing sticks. Being made to point
  // first is recall, which is the only part that survives to the next puzzle.
  //
  // It costs no new screen: the same rung, in the same panel, one beat before
  // the same text, with "Just tell me" beside it so nobody is ever stuck behind
  // a quiz. Guess right and the rung is free, which is the score finally saying
  // what it always meant — a hint you did not need is not a hint you took.
  //
  // Buildable at all only because the annotations already store these as
  // literal spans of the clue: 1473/1473 definitions, 1471/1471 indicators,
  // 3131/3132 fragments. Measured across the corpus, not hoped for.
  //
  // The type rung is the exception to "literal spans": its answer is a family,
  // not words in the clue, so it asks by offering the seven. It belongs here all
  // the same — it is the one thing you can be asked before reading a word of the
  // wordplay, and a ladder that asks about every other part and hands this one
  // over is a ladder that answers its own first question (Paul, 2026-08-27).
  const GUESSABLE = { type: 1, definition: 1, indicators: 1, blocks: 1 };

  // The clue split into things you can put a finger on. Whitespace-delimited, so
  // the punctuation welded to a word rides along with it, and the enumeration is
  // dropped because "(4,3)" is not a word anyone can be right or wrong about.
  function clueTokens(clue) {
    const body = String(clue || "").replace(/\s*\([^()]*\)\s*$/, "");
    const out = [];
    const re = /\S+/g;
    let m;
    while ((m = re.exec(body))) out.push({ i: m.index, text: m[0] });
    return out;
  }

  // The pieces of the charade that can be pointed at: they name a span of the
  // clue and they yield letters. In clue order, because that is the order the
  // solver reads them in and the order the assembly runs in.
  function blockAsks(e) {
    const ann = annOf(e);
    return ((ann && ann.blocks) || []).filter((b) => b.clueFragment && b.gives);
  }

  // Which words of the clue a rung names. Kept apart from guessAsk because a
  // rung can be unaskable and still have named its words — an &lit's definition
  // is the whole clue, so there is no question in it, and every word of it is
  // nonetheless settled for the rung asked next.
  //
  // The blocks rung names one PIECE at a time: step is which. Every other rung
  // has one step and ignores it.
  // One entry per span the rung names, each a list of token indices, in the
  // order the rung names them. Kept apart because where one span ends and the
  // next begins is what decides which of its words are optional, and a flat
  // list of the union cannot say.
  function rungSpans(e, rung, step) {
    const ann = annOf(e);
    if (!ann) return [];
    const tokens = clueTokens(e.clue);
    const taken = [];
    const spans = [];
    const add = (t) => {
      if (!t) return;
      const i = bestOccurrence(e.clue, t, taken);
      if (i < 0) return;
      taken.push({ i, len: t.length });
      const span = [];
      tokens.forEach((tok, n) => {
        if (tok.i < i + t.length && i < tok.i + tok.text.length) span.push(n);
      });
      if (span.length) spans.push({ text: t, tokens: span });
    };
    if (rung === "definition") {
      add(ann.definition);
      add(ann.definition2);
    } else if (rung === "indicators") {
      (ann.indicators || []).forEach(add);
    } else if (rung === "blocks") {
      const b = blockAsks(e)[step || 0];
      if (b) add(b.clueFragment);
    }
    return spans;
  }

  function rungTokens(e, rung, step) {
    return rungSpans(e, rung, step).reduce((a, s) => a.concat(s.tokens), []);
  }

  // Where a definition ends is a judgement call, not a fact. "Communication made
  // meaningless by this" and "Communication made meaningless" are the same claim
  // about the same answer; one leaves in the pointer back at it. A solver who
  // draws that line one word short of where the annotation drew it has named the
  // definition, and telling them they are wrong teaches them nothing except that
  // the app is fussy (Paul, 2026-08-30).
  //
  // Only at the ENDS of a span, and only for a DEFINITION. In wordplay every
  // word is either letters or an instruction — "a" is a letter of the fodder —
  // so there dropping one is a real mistake and stays one.
  const EDGE_WORDS = ("a an the this these those it its one such by of for from " +
                      "with in on at to and that as so s").split(" ");

  function edgeTokens(span, tokens) {
    const bare = (n) => tokens[n].text.toLowerCase().replace(/[^a-z']/g, "");
    const out = [];
    const run = (order) => {
      for (let k = 0; k < order.length; k++) {
        if (EDGE_WORDS.indexOf(bare(order[k])) < 0) return;
        out.push(order[k]);
      }
    };
    run(span);
    run(span.slice().reverse());
    return out;
  }

  // The optional words of this rung's question: the ends of every span of it
  // that is a definition. A double definition's pieces are its two definitions,
  // so the blocks rung inherits the same latitude when it asks for one of them.
  function rungEdges(e, rung, step) {
    const ann = annOf(e);
    if (!ann || rung === "indicators") return [];
    const defs = [ann.definition, ann.definition2].filter(Boolean);
    const tokens = clueTokens(e.clue);
    return rungSpans(e, rung, step)
      .filter((s) => rung === "definition" || defs.indexOf(s.text) >= 0)
      .reduce((a, s) => a.concat(edgeTokens(s.tokens, tokens)), []);
  }

  // The type rung's question. Its answer is a family rather than a run of words,
  // so what comes back has `choices` where the others have `tokens`, and every
  // reader downstream branches on that one field.
  //
  // All seven are always offered, in ladder order and never shuffled: the list
  // IS the vocabulary this site is trying to teach, and seeing the same seven
  // under every clue is most of how it gets learned. Narrowing it to plausible
  // ones would make the question easier and the lesson smaller.
  function familyAsk(ann) {
    // Empty for a type no rule claims: there would be no right answer to pick, so
    // there is no question, and the rung behaves exactly as it always did.
    const right = familiesOf(ann.type).map((f) => f.label);
    if (!right.length) return null;
    return { prompt: "Which of these is it?", choices: FAMILIES.map((f) => f.label),
             answer: right[0], answers: right, step: 0 };
  }

  // What a rung asks, which tokens answer it, and which are no longer anybody's
  // to pick. Null when this clue cannot pose the question at all — an &lit whose
  // definition is the whole clue, a type with no indicators, a block rung with
  // nothing that yields letters — and the rung then behaves exactly as it always
  // did.
  //
  // A word an earlier rung already named is not a choice. Leaving it tappable
  // invites a solver who has the definition to offer it back as the indicator,
  // and marks them wrong for a thing the screen had already told them (Paul).
  // They are shown, greyed and inert: the scaffolding is the point, since
  // knowing where the definition ends is most of knowing where the wordplay
  // starts.
  //
  // Nothing is charged for without being offered first: if a rung has anything
  // to point at, it asks, even when what is left to point at IS the whole answer
  // (Paul, 2026-08-28). An easy question is a free rung; a rung handed over
  // unasked is a rung the solver paid for and was never given the chance to
  // win. The only rung that cannot ask is one with nothing to point at at all.
  // A charade has more than one piece, and "it isn't knowing it is a charade
  // that is hard, it is DOING the charade" (Paul) — so the blocks rung asks for
  // each piece in turn rather than one and done. step says which piece; a piece
  // already placed is settled scaffolding for the next question, by the same
  // rule that settles the definition when the indicators are asked for.
  function guessAsk(e, rung, step) {
    const ann = annOf(e);
    if (!ann) return null;
    const at = step || 0;
    if (at && rung !== "blocks") return null;
    if (rung === "type") return familyAsk(ann);
    const tokens = clueTokens(e.clue);
    const target = rungTokens(e, rung, at);
    if (!target.length) return null;
    let prompt = "", gives = "";
    if (rung === "definition") {
      prompt = "Which words define the answer?";
    } else if (rung === "indicators") {
      prompt = "Which words tell you what to do to the rest?";
    } else if (rung === "blocks") {
      const asks = blockAsks(e);
      if (!asks[at]) return null;
      gives = asks[at].gives;
      const of = asks.length > 1 ? ` <span class="muted">(${at + 1} of ${asks.length})</span>` : "";
      prompt = `Which words give <span class="gives">${esc(gives)}</span>?${of}`;
    }
    // Everything already named and not part of this answer: the tier-0 rungs
    // that are up, plus the pieces of this charade already placed.
    const named = SPOTTING.filter((k) => k !== rung && isShown(e, k))
      .reduce((a, k) => a.concat(rungTokens(e, k)), []);
    for (let n = 0; n < at; n++) named.push.apply(named, rungTokens(e, rung, n));
    const known = named.filter((n) => target.indexOf(n) < 0);
    return { prompt, target, tokens, known, gives, step: at,
             edge: rungEdges(e, rung, at) };
  }

  // The piece after this one, where there is one. Only the blocks rung runs a
  // sequence; every other rung is a single question and stops on its own.
  function nextAsk(e, rung, step) {
    return rung === "blocks" ? guessAsk(e, rung, (step || 0) + 1) : null;
  }

  // A guess in progress, and the verdict on the one just made. Neither is
  // persisted: what survives a reload is hintsEarned, because that is the part
  // that changed the score. A half-made guess is not progress.
  let guessing = null;   // { key, rung, step, picked: [], placed: [] }
  let lastGuess = null;  // { key, rung, tokens, known, mk: <verdict> }

  // The clue's words, wearing whatever is known about them. Buttons while the
  // question is open, the identical markup as plain spans once it has been
  // answered — because the marked-up clue IS the answer, and it stays on screen
  // underneath the verdict for as long as the solver is on this clue.
  //
  // It used to be shown for a beat and then thrown away when the rung opened,
  // which put a reading deadline on the one part of this that teaches anything:
  // "it flashes too fast for me to read" (Paul, 2026-08-21). Nothing here is on
  // a timer now. The animations are entrances — they say a thing has arrived,
  // they do not say how long you have with it.
  function guessWordsHTML(tokens, mk, picked, known, rung) {
    const settled = known || [];
    const cls = (i) => {
      if (!mk) return picked.indexOf(i) >= 0 ? " on" : "";
      if (mk.hit.indexOf(i) >= 0) return " on hit";
      if (mk.spare.indexOf(i) >= 0) return " on spare";
      return mk.missed.indexOf(i) >= 0 ? " missed" : "";
    };
    // Each word its own id rather than a delegated handler: it is the same
    // pattern as every other button here, and it means a word can be pointed at
    // by name from a test. A settled word gets no id and no button: it cannot be
    // picked, so it must not look pickable and must not answer to a tap.
    const words = tokens.map((t, i) => (mk || settled.indexOf(i) >= 0)
      ? `<span class="gw${settled.indexOf(i) >= 0 ? " known" : cls(i)}">${esc(t.text)}</span>`
      : `<button type="button" id="gw-${i}" class="gw${cls(i)}">${esc(t.text)}</button>`);
    // "ask" while it is the question, "mk" once it has been graded. The two are
    // the same words in two places, and flipCapture/flipPlay use the pair to
    // measure the journey between them.
    //
    // The rung rides along because the colour of a picked word is the colour that
    // KIND of word wears everywhere else on the site: green for a definition,
    // pink for an indicator (Paul, 2026-08-28). Picking used to be its own
    // neutral accent, which made the solver learn one colour for "I chose this"
    // and a different one for the thing they had just correctly chosen.
    return `<p class="guess-clue ${mk ? "mk" : "ask"} pick-${rung || "indicators"}">${
      words.join(" ")}</p>`;
  }

  // ---------- dragging a run of words ----------
  //
  // A definition is a RUN of words, and pointing at a run is one gesture rather
  // than four taps (Paul). A drag ADDS its run to whatever was picked already, so
  // the indicators rung — often two separate runs — is still answerable by
  // dragging each of them, and so a drag can never silently throw away a pick.
  //
  // The panel is deliberately not re-rendered mid-drag: rebuilding the DOM under
  // a live pointer ends the gesture. The words are repainted in place and the
  // panel catches up when the finger lifts.
  let drag = null;         // { base: [...picked], from, moved, ask }
  let swallowClick = false;

  function wordAt(x, y) {
    if (!document.elementFromPoint) return -1;
    let el = document.elementFromPoint(x, y);
    for (let hops = 0; el && hops < 4; hops++, el = el.parentNode) {
      const m = /^gw-(\d+)$/.exec(el.id || "");
      if (m) return +m[1];
    }
    return -1;
  }

  function paintPicked(ask) {
    ask.tokens.forEach((t, i) => {
      if (ask.known.indexOf(i) >= 0) return;
      const el = $("gw-" + i);
      if (el) el.className = "gw" + (guessing.picked.indexOf(i) >= 0 ? " on" : "");
    });
    const check = $("guess-check");
    if (check) check.disabled = !guessing.picked.length;
  }

  function dragOver(i) {
    const ask = drag.ask;
    if (i < 0 || i >= ask.tokens.length || ask.known.indexOf(i) >= 0) return;
    // Nothing happens until the pointer reaches a DIFFERENT word. A tap is a
    // pointerdown and a pointerup with a wobble in between, and a wobble that
    // counted as a one-word drag would pick the word and then let the click
    // that follows toggle it straight back off.
    if (i === drag.from && !drag.moved) return;
    drag.moved = true;
    const lo = Math.min(drag.from, i), hi = Math.max(drag.from, i);
    const run = [];
    // Settled words inside the run are skipped rather than breaking it: a
    // definition can sit either side of a word the indicators rung already named.
    for (let n = lo; n <= hi; n++) {
      if (ask.known.indexOf(n) < 0 && drag.base.indexOf(n) < 0) run.push(n);
    }
    guessing.picked = drag.base.concat(run);
    paintPicked(ask);
  }

  if (document.addEventListener) {
    document.addEventListener("pointermove", (ev) => {
      if (drag && guessing) dragOver(wordAt(ev.clientX, ev.clientY));
    });
    document.addEventListener("pointerup", () => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      // Only a real drag swallows the click. A plain tap must still toggle, and
      // a tap is a pointerdown and a pointerup on the same word.
      swallowClick = moved;
      if (moved) renderHintPanel();
    });
    document.addEventListener("pointercancel", () => { drag = null; });
  }

  // The verdict and the marked-up clue, standing above the rung they earned.
  // Sentence first because it is the headline — right or not, and by how much —
  // then the words, which are the part a count can never give you: WHICH ones.
  //
  // A choice question has no words to mark and nothing to keep: what you picked
  // is in the sentence, and the rung below is the rest of it.
  //
  // Everything in here animates on the way in, and the panel is redrawn on every
  // keystroke and every selection — so the entrance is spent the first time it is
  // drawn and never again. Without that, "yes that's the one" pops afresh while
  // you are picking your next clue (Paul, 2026-08-28): an entrance that replays
  // is not an entrance, it is a fidget.
  function verdictHTML(g) {
    const fresh = g.fresh ? " fresh" : "";
    g.fresh = false;
    return `<div class="guess-result${fresh}"><p class="guess-verdict ${
      g.mk.right ? "right" : "miss"}">${esc(g.mk.said)}</p>${
      g.tokens ? guessWordsHTML(g.tokens, g.mk, [], g.known, g.rung) : ""}</div>`;
  }

  // Pieces of the charade already placed, kept on the screen while the next one
  // is asked for. Doing a charade IS watching it assemble; a solver who has just
  // been told "right" and handed a new question with no record of the last one
  // has to hold the assembly in their head, which is the thing the rung exists
  // to teach them not to have to do.
  function placedHTML(placed) {
    if (!(placed || []).length) return "";
    return `<ul class="guess-placed">${placed.map((p) =>
      `<li><em>${esc(p.words)}</em> → <span class="gives">${esc(p.gives)}</span></li>`
    ).join("")}</ul>`;
  }

  // One of seven, and the tap IS the answer: there is a single bit to give, so a
  // confirm step would only ask for it twice. Pointing at words keeps its check
  // button because a run of words is assembled before it is offered.
  function guessChoicesHTML(ask) {
    // How many chips and how many characters they add up to, handed to the CSS
    // so the strip can size its own type to hold one row. Measured off the
    // labels rather than written down, because a written-down 65 is a number
    // that goes stale the first time a family is renamed.
    const chars = ask.choices.reduce((n, c) => n + c.length, 0);
    return `<p class="guess-choices" style="--n:${ask.choices.length};--c:${chars}">${
      ask.choices.map((c, i) =>
        `<button type="button" id="gc-${i}" class="gc">${esc(c)}</button>`).join("")}</p>`;
  }

  function guessHTML(ask, position, label) {
    const answer = ask.choices
      ? guessChoicesHTML(ask)
      : guessWordsHTML(ask.tokens, null, guessing.picked, ask.known, guessing.rung);
    const check = ask.choices ? "" : `<button id="guess-check" class="primary"${
      guessing.picked.length ? "" : " disabled"}>Check my answer</button> `;
    return `<div class="hint-step guess"><span class="step-label">${position} · ${esc(label)}</span>
      ${placedHTML(guessing.placed)}
      <p>${ask.prompt}</p>
      ${answer}
      <p class="guess-actions">${check}<button id="guess-tell" class="ghost small">Just tell me</button></p></div>`;
  }

  // Right or not, and which one you said — never what the right one was. The
  // rung opens directly underneath and names it, with the paragraph explaining
  // what that family means, and saying it twice in two voices two lines apart
  // reads as the page arguing with itself.
  // A compound clue has every family it is made of, and each of them is a right
  // answer. The one the rung goes on to name is the dominant one, so a solver who
  // named a different true one is told that theirs is in there too — otherwise
  // the paragraph underneath reads as a correction of an answer that was correct.
  function gradeChoice(ask, picked) {
    const right = ask.answers || [ask.answer];
    if (picked === right[0]) return { choice: picked, right: true, said: "Yes — that’s the one." };
    if (right.indexOf(picked) >= 0) {
      return { choice: picked, right: true,
               said: `Yes — ${picked.toLowerCase()} is part of it. This clue is more than one thing at once.` };
    }
    return { choice: picked, right: false,
             said: `Not ${picked.toLowerCase()} — here’s what it actually is.` };
  }

  // Right is the whole set and nothing else. Anything short of that opens the
  // rung too — the point was never to withhold it — but says what was missed,
  // because "wrong" with no account of it is the least useful thing a teacher
  // can say.
  function gradeGuess(ask) {
    const picked = guessing.picked.slice().sort((a, b) => a - b);
    const target = ask.target.slice().sort((a, b) => a - b);
    // The three sets, not just their sizes: guessHTML paints them onto the words.
    const hit = picked.filter((x) => target.indexOf(x) >= 0);
    const spare = picked.filter((x) => target.indexOf(x) < 0);
    const missed = target.filter((x) => picked.indexOf(x) < 0);
    const n = target.length;
    const v = { hit, spare, missed };
    if (hit.length === n && !spare.length) {
      return { ...v, right: true, said: "Yes — that’s exactly it." };
    }
    // Short by nothing but the optional ends of a definition: right, and the
    // whole span is painted so the line the annotation drew is still shown.
    const edge = ask.edge || [];
    if (!spare.length && hit.length && missed.every((x) => edge.indexOf(x) >= 0)) {
      const words = missed.map((x) => ask.tokens[x].text).join(" ");
      return { hit: target, spare, missed: [], right: true,
               said: `Yes — whether “${words}” belongs to the definition is a matter of taste.` };
    }
    if (hit.length === n) {
      return { ...v, right: false, said: `You had all ${n}, plus ${spare.length} word${
        spare.length > 1 ? "s" : ""} that isn’t doing that job.` };
    }
    if (hit.length) {
      return { ...v, right: false, said: `Close — ${hit.length} of ${n} right${
        spare.length ? `, and ${spare.length} that aren’t` : ""}.` };
    }
    return { ...v, right: false, said: "Not those. Here’s where they actually are." };
  }

  // The marked clue is the same words in a different place. The question sits at
  // the bottom of the panel, under everything already bought; the verdict belongs
  // beside the rung it judged, which is wherever that rung falls in the ladder.
  // Re-rendering puts it there instantly, and the whole panel reads as a lurch —
  // "the words all move and it is jarring" (Paul).
  //
  // FLIP: measure where it was, let the render happen, put it back with a
  // transform and then let it travel. The eye follows the one thing that did not
  // change, which is the thing worth reading. Everything is guarded because this
  // is decoration — a DOM without getBoundingClientRect gets the same panel,
  // arriving in one step.
  // Measured as the question, replayed as the verdict: the same words, and by
  // name, because a previous rung's verdict may well still be on the screen and
  // "the first .guess-clue" would then measure the wrong one.
  function flipFind(what) {
    return document.querySelector ? document.querySelector(".guess-clue." + what) : null;
  }
  function flipCapture() {
    const el = flipFind("ask");
    return el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
  }
  function flipPlay(from) {
    const el = from && flipFind("mk");
    if (!el || !el.getBoundingClientRect || !window.requestAnimationFrame) return;
    if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const to = el.getBoundingClientRect();
    const dx = from.left - to.left, dy = from.top - to.top;
    if (!dx && !dy) return;
    el.style.transition = "none";
    el.style.transform = `translate(${dx}px, ${dy}px)`;
    requestAnimationFrame(() => {
      el.style.transition = "transform .34s cubic-bezier(.2,.7,.3,1)";
      el.style.transform = "";
    });
  }

  // Opens the rung and ends the guess, in the same tick as the tap that asked
  // for it. Nothing waits: the answer and the explanation of it arrive together
  // and both stay, so there is no moment the solver has to catch.
  function finishGuess(verdict, ask) {
    if (!guessing) return;
    const e = currentEntry();
    if (!e || entryKey(e) !== guessing.key) { guessing = null; return; }
    const from = flipCapture();
    // Right, and there is another piece to place: the rung is not handed over
    // yet. It is one rung and one price — a charade is not finished until every
    // piece of it is, and stopping after the first was Paul's report that the
    // building blocks "made me only pick one of the three pieces". A wrong
    // answer still ends it and still opens the rung: never a dead end.
    const more = verdict && verdict.right && nextAsk(e, guessing.rung, guessing.step);
    if (more) {
      guessing = { key: guessing.key, rung: guessing.rung, step: guessing.step + 1,
                   picked: [], placed: guessing.placed.concat([{
                     gives: ask.gives, words: ask.target.map((i) => ask.tokens[i].text).join(" ") }]) };
      refreshAll();
      return;
    }
    lastGuess = verdict && { key: guessing.key, rung: guessing.rung, fresh: true,
                             tokens: ask.tokens, known: ask.known, mk: verdict };
    if (verdict && verdict.right && earnedRungs(e).indexOf(guessing.rung) < 0) {
      earnedRungs(e).push(guessing.rung);
    }
    showHint(e, guessing.rung);
    guessing = null;
    refreshAll();
    flipPlay(from);
  }

  function earnedRungs(e) {
    const key = entryKey(e);
    return hintsEarned[key] || (hintsEarned[key] = []);
  }

  function hintStepHTML(step, position) {
    return `<div class="hint-step"><span class="step-label">${position} · ${esc(step.label)}</span>${step.html}</div>`;
  }

  // Where the answer's words break, read straight off the clue's own
  // enumeration: (3,6) is three boxes, a gap, then six. The grid cannot show
  // this — its squares run on regardless — so the strip is the only place a
  // solver can see that they are looking for two words rather than a nine-letter
  // one, which rules out most of what they were considering (Paul, 2026-08-16).
  //
  // Trusted only when the digits add up to the squares THIS entry has. A linked
  // clue prints the whole group's enumeration on its first leg, so applying it
  // to one leg would draw the breaks in the wrong places; a mismatch means no
  // breaks rather than wrong ones, and so does anything that isn't digits and
  // separators ("(two words)" and friends). "." is a separator because feeds do
  // print (6.6) where they mean (6,6) — 30079 18-across and 30080 10-across.
  const ENUM_SEPS = { ",": " ", " ": " ", "-": "-", "–": "-", "—": "-", "'": "’", "’": "’", ".": " " };
  function enumBreaks(clue, cells) {
    const m = /\(([^()]+)\)\s*$/.exec(clue || "");
    if (!m) return null;
    const breaks = {};
    let n = 0;
    for (const tok of m[1].match(/\d+|\S/g) || []) {
      if (/^\d+$/.test(tok)) { n += Number(tok); continue; }
      // A separator before any letters, or two in a row, is not an enumeration
      // this code understands — and a half-understood one draws a wrong gap.
      if (!ENUM_SEPS[tok] || !n || breaks[n]) return null;
      breaks[n] = ENUM_SEPS[tok];
    }
    return n === cells && Object.keys(breaks).length ? breaks : null;
  }

  // The selected entry's live letter pattern: what's already in the grid, blanks
  // for what isn't, and which squares are CHECKED (shared with a crossing entry,
  // so another clue can confirm them). Unchecked squares are the hard ones —
  // nothing will ever cross them, so they have to come out of the wordplay.
  function patternHTML(e) {
    const cs = entryCells(e);
    const breaks = enumBreaks(e.clue, cs.length);
    let filled = 0, checked = 0;
    const boxes = cs.map((c, idx) => {
      if (!c) return "";
      const isChecked = !!(c.across && c.down);
      if (isChecked) checked++;
      if (c.letter) filled++;
      const cls = ["pat-box", isChecked ? "checked" : "unchecked"];
      if (c.wrong) cls.push("wrong");
      else if (c.revealed) cls.push("revealed");
      if (c.x === cur.x && c.y === cur.y) cls.push("cur");
      const title = (c.letter ? esc(c.letter) : "blank") + (isChecked ? ", checked" : ", unchecked");
      // A button, not a span: the strip doubles as a way to move the cursor
      // without hunting for the square in the grid (data-i is the index in the
      // entry, read by the delegated handler in boot()).
      return `<button type="button" class="${cls.join(" ")}" data-i="${idx}"
        title="Jump to this square — ${title}">${c.letter ? esc(c.letter) : ""}</button>`;
    });
    // Each word is its own flex row so a long entry wraps between words before it
    // wraps inside one, and so the gap that means "new word" cannot be confused
    // with the gap that means "the line ran out". A hyphen or apostrophe is drawn
    // rather than spaced, because it is a character of the answer.
    const segs = [];
    let html = "", word = "", at = 0;
    boxes.forEach((b, i) => {
      word += b;
      const sep = breaks && breaks[i + 1];
      if (!sep) return;
      html += `<span class="pat-word ${sep === " " ? "brk-space" : "brk-tight"}">${word}</span>`
            + (sep === " " ? "" : `<span class="pat-sep" aria-hidden="true">${sep}</span>`);
      segs.push(i + 1 - at);
      at = i + 1;
      word = "";
    });
    html += `<span class="pat-word">${word}</span>`;
    if (segs.length) segs.push(cs.length - at);

    const unchecked = cs.length - checked;
    const note = `${filled} of ${cs.length} letter${cs.length > 1 ? "s" : ""} in place · `
      + (segs.length ? `in words of ${segs.join(", ")} · ` : "")
      + (unchecked ? `${checked} checked, ${unchecked} unchecked (dashed — no crossing clue)`
                   : `all ${checked} checked`);
    // The note is for screen readers only. Printed next to the boxes it restated
    // what the boxes already show — which squares have letters, and which are
    // dashed — in twenty words of prose sitting directly under the clue you are
    // trying to read (Paul, 2026-08-09). The clue is what the box is for; every
    // line that is not the clue pushes it further from being read.
    // How many boxes and how many word breaks, so the strip can size itself down
    // to fit the panel instead of stacking one word per line. CSS cannot count
    // letters and JS should not be measuring screens, so the count comes from
    // here and the arithmetic stays in the stylesheet next to the box geometry.
    const brk = segs.length ? segs.length - 1 : 0;
    return `<span class="pat-boxes" role="img" style="--n:${cs.length};--w:${brk}"`
         + ` aria-label="${esc(note)}">${html}</span>`;
  }

  // ---------- writing only what changed ----------
  //
  // The panel is rebuilt by refreshAll(), and refreshAll() runs on every
  // keystroke. Assigning innerHTML makes the browser throw the subtree away,
  // reparse it and lay the block out again, so a letter typed into the grid
  // repainted a hint panel in which nothing had changed — the block shivers
  // under the typing, worst on iOS.
  //
  // The rule for everything in this panel: never write DOM that would come out
  // the same. Each region is built into a value first — a string, or for the
  // button row a list the row is a pure function of — and written only when
  // that value differs from the one it was last built from. Compared against
  // what we wrote rather than against el.innerHTML, because a browser hands
  // back its own re-serialisation and the two would never match.
  //
  // Skipping the write means skipping the handler wiring that goes with it, and
  // that is only sound because the nodes are still there with their handlers
  // live. The other half of the bargain: NO HANDLER IN THIS PANEL MAY CLOSE
  // OVER STATE THAT THE COMPARED VALUE DOES NOT CONTAIN. Each one re-reads the
  // current entry and the current guess when it fires, so a handler that
  // outlives several renders still answers for now.
  function setHTML(el, html) {
    if (el._shown === html) return false;
    el._shown = html;
    el.innerHTML = html;
    return true;
  }

  // The rung row is data first and DOM second, for the same reason the rest of
  // the panel is a string first: a row that is a pure function of this list can
  // be compared as a list and left alone. It stays real elements rather than
  // markup because these buttons carry handlers and a label that must not be
  // re-escaped by hand.
  function setButtons(el, spec) {
    const key = JSON.stringify(spec);
    if (el._shown === key) return false;
    el._shown = key;
    el.innerHTML = "";
    spec.forEach((b) => {
      if (b.fill) {
        el.innerHTML = `<button id="hx-entry">${b.text}</button>`;
        $("hx-entry").onclick = fillAnswer;
        return;
      }
      const btn = document.createElement("button");
      if (b.cls) btn.className = b.cls;
      btn.textContent = b.text;
      if (b.title) btn.title = b.title;
      if (b.disabled) { btn.disabled = true; el.appendChild(btn); return; }
      btn.onclick = () => {
        // Ask before telling, where the clue can pose the question. Not once
        // the clue is solved: the rungs have stopped being hints by then and
        // quizzing someone on an answer they already have is a chore.
        // The previous rung's verdict stays where it is. Clearing it deleted a
        // block from the middle of the panel at the exact moment a new one
        // appeared at the bottom, so the whole thing slid under the solver's
        // eyes: "it jumps and switches to something else" (Paul). Nothing the
        // panel has said is ever taken back; it only ever grows.
        const on = currentEntry();
        if (!on) return;
        if (GUESSABLE[b.rung] && !isEntrySolved(on) && guessAsk(on, b.rung)) {
          guessing = { key: entryKey(on), rung: b.rung, step: 0, picked: [], placed: [] };
        } else {
          showHint(on, b.rung);
        }
        refreshAll();
      };
      el.appendChild(btn);
    });
    return true;
  }

  // The question currently on the table, re-derived rather than captured, so a
  // handler that survived a skipped rebuild grades what is being asked now.
  function currentAsk() {
    const e = currentEntry();
    if (!e || !guessing || guessing.key !== entryKey(e)) return null;
    return guessAsk(e, guessing.rung, guessing.step);
  }

  // Reporting a hint that is wrong, from the clue it is wrong on. It lives in the
  // strip the reveal button is already in rather than getting a page or a form:
  // a reader who has just been taught something false is two taps from saying so,
  // and there is no address to find and nothing to sign up for. What goes with it
  // is only what the site already knows — which clue, and which rung was open.
  let report = null;   // { key, phase: "open" | "sent" | "failed", msg }
  function reportHTML() {
    if (!report) return `<button id="rp-open" class="ghost small">Report a bad hint</button>`;
    if (report.phase === "sent") return `<span class="muted">Thanks — noted.</span>`;
    // The reason, not "try again later": a reader told only that it failed cannot
    // tell an outage from something they did.
    if (report.phase === "failed") {
      return `<span class="muted">Didn’t send (${esc(report.msg)}).</span> `
        + `<button id="rp-open" class="ghost small">Try again</button>`;
    }
    return `<input id="rp-note" class="rp-note" maxlength="400" `
      + `placeholder="What’s wrong with this hint?">`
      + `<button id="rp-send" class="ghost small">Send</button>`;
  }
  function sendReport(e) {
    const el = $("rp-note");
    const note = ((el && el.value) || "").trim();
    if (!note) return;
    const key = entryKey(e);
    fetch(SYNC_ENDPOINT.replace(/\/$/, "") + "/r", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ puzzle: P && P.id, clue: e.id,
                             rung: shownRungs(e).slice(-1)[0] || "", note }),
    }).then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      report = { key, phase: "sent" };
      refreshAll();
    }).catch((err) => {
      report = { key, phase: "failed", msg: (err && err.message) || String(err) };
      refreshAll();
    });
  }
  function bindReport(e) {
    const open = $("rp-open");
    if (open) open.onclick = () => { report = { key: entryKey(e), phase: "open" }; refreshAll(); };
    const send = $("rp-send");
    if (send) send.onclick = () => sendReport(e);
    const note = $("rp-note");
    if (note && note.addEventListener) {
      note.addEventListener("keydown", (ev) => { if (ev.key === "Enter") sendReport(e); });
    }
  }

  function renderHintPanel() {
    const e = currentEntry();
    const panel = $("hint-panel");
    if (!e) { panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden");

    const holder = (e.annotation && e.annotation.linkedTo) ? byId[e.annotation.linkedTo] : e;
    const ann = annOf(e);
    const key = entryKey(e);
    const level = shownRungs(e).filter((r) => r !== ANSWER_RUNG).length;

    let clueLine = `<span class="entry-tag">${tag(e)}</span>`;
    if (holder !== e) clueLine += `<span class="muted">(linked with ${tag(holder)}) </span>`;
    clueLine += clueHTML(holder);
    const clueWrote = setHTML($("hint-clue"), clueLine);
    setHTML($("hint-pattern"), patternHTML(e));

    const solved = isEntrySolved(e);
    // A report is about the clue it was started on, and moving on abandons it —
    // the same rule the guess follows, for the same reason.
    if (report && report.key !== key) report = null;
    const reveals = revealsUsed[key] || 0;
    const revealsNote = reveals ? ` · ${reveals} letter${reveals > 1 ? "s" : ""} revealed` : "";
    // The count the score charges, not the number of rungs currently on screen:
    // once solved you can open the rest for free, and the meter has to say the
    // same thing the scorebar does or one of them is lying.
    const charged = hintsCharged(e);
    const meterHTML = solved
      ? ((charged || reveals)
          ? `Solved with ${charged} hint${charged === 1 ? "" : "s"}${revealsNote}`
          : "Solved with no hints — bravo!")
      // "used on this clue" — you are looking at the clue. Just the count, and
      // no longer called hints: a rung you answered yourself was never one, and
      // the score has never charged for it. What you worked out is reported
      // beside it, because that is the number this is all for.
      : (ann ? `<strong>${level}</strong>/${ladderSteps(ann, e.clue).length} shown${
                 earnedRungs(e).length ? ` · ${earnedRungs(e).length} worked out` : ""}${revealsNote}`
             : revealsNote.replace(" · ", ""));
    // Whether there is anything left on the ladder, filled in below once the
    // steps are known: a solved clue's score is settled, so the rest of the
    // ladder costs nothing — and the only place that had ever been said was a
    // comment in this file. "It's not clear when a hint is free after I
    // finished" (Paul, 2026-08-28). The explanation of a clue you have already
    // got is the one thing this site is for; the reader has to be told they can
    // have it.
    let freeRest = false;

    const body = $("hint-body");
    const next = $("hint-next");
    const escape = $("hint-escape");
    let bodyHTML = "";
    const nextSpec = [];
    let ask = null;

    if (!ann) {
      // Two different silences, and telling them apart is the whole point.
      // "Not annotated yet" promises a ladder that is coming; a clue the paper
      // printed blank has no ladder ever, because there is no clue. Say which,
      // or the reader hunts the grid for wordplay that was never printed.
      // clueMissing is written by the fetchers off has_words — see fetch_puzzle.
      bodyHTML = e.clueMissing
        ? `<div class="hint-step"><p class="muted">The paper published this clue with no text in it —
        the space beside the number came through empty, so there’s nothing here
        to solve and no wordplay to explain. Not your eyes.
        ${canCheck() ? "You can reveal the answer below." : ""}</p></div>`
        : `<div class="hint-step"><p class="muted">This clue hasn’t been hand-annotated yet
        (<span class="badge auto">auto hints</span>), so there’s no teaching ladder for it.
        You can still check your letters${canCheck() ? " and reveal below" : ""}.</p></div>`;
      if (canCheck() && !solved) nextSpec.push({ fill: true, text: "Reveal answer" });
    } else {
      // Revealed rungs always read in ladder order and keep their ladder
      // number, whatever order they were asked for in. The numbering is the
      // teaching sequence, not a click log — a solver who took 4 before 2 has
      // still met them as steps 2 and 4, and gaps in the numbers show what
      // they skipped.
      const steps = ladderSteps(ann, e.clue);
      // A guess belongs to the clue it was asked about. Moving on abandons it —
      // carrying it would mean checking an answer against a different question.
      if (guessing && guessing.key !== key) guessing = null;
      if (lastGuess && lastGuess.key !== key) lastGuess = null;
      steps.forEach((s, i) => {
        if (!isShown(e, s.key)) return;
        // The verdict reads above the rung it judged: you find out whether you
        // were right, and then you are told, in that order. It keeps the marked
        // clue with it, so what you pointed at and what was actually there can
        // be read side by side against the explanation, for as long as you like.
        if (lastGuess && lastGuess.rung === s.key) bodyHTML += verdictHTML(lastGuess);
        bodyHTML += hintStepHTML(s, i + 1);
      });
      // The legend is built from what is actually highlighted, for the same
      // reason clueHTML is: it was keyed off the definition rung, so taking the
      // indicators alone left the marks unexplained as well as absent.
      const legend = [];
      if (isShown(e, "definition")) legend.push('<mark class="def">definition</mark>');
      if (isShown(e, "indicators") && (ann.indicators || []).length) {
        legend.push('<mark class="ind">indicator</mark>');
      }
      if (isShown(e, "definition") && (ann.linkWords || []).length) {
        legend.push('<mark class="link">link</mark>');
      }
      if (legend.length) {
        bodyHTML += `<div class="legend">${legend.join(" · ")} highlighted in the clue above</div>`;
      }

      // A rung that has been asked for but not yet handed over: the solver is
      // being asked to point at the words first. It goes last in the body, under
      // everything they have already bought, because that is where the next
      // thing to do has always been.
      ask = guessing ? guessAsk(e, guessing.rung, guessing.step) : null;
      if (guessing && !ask) guessing = null;
      if (ask) {
        const at = steps.map((s) => s.key).indexOf(guessing.rung);
        bodyHTML += guessHTML(ask, at + 1, steps[at].label);
      }

      // How the ladder works, said once and then never again: it stops the
      // moment a rung is worked out anywhere in this puzzle, because at that
      // point it has been demonstrated and repeating it is just noise on every
      // clue you open after. Only claimed when a rung on THIS clue really can
      // ask; a clue with no question in it must not be sold as one.
      if (!bodyHTML && !solved && !Object.keys(hintsEarned).some((k) => hintsEarned[k].length)
          && steps.some((s) => GUESSABLE[s.key] && guessAsk(e, s.key))) {
        bodyHTML = `<div class="hint-step"><p class="muted">Every step asks before it tells —
          answer it yourself and it’s free.</p></div>`;
      }

      // Every unlocked rung is offered at once, not just the next one: wanting
      // the indicators shouldn't mean being handed the definition on the way,
      // since working out where the definition sits is most of the skill. The
      // recommended one still leads and still says "hint N", so the taught path
      // costs one obvious click and a sideways move costs one deliberate one.
      // Rungs from a later tier are shown but disabled rather than hidden — the
      // ladder has a shape and the solver should be able to see it coming.
      // While a guess is on the table the other rungs are not offered: the
      // question is answerable by buying a different hint, and a quiz you can
      // walk around is not one. Not offered, but still THERE — emptying the row
      // collapsed the panel at the moment the question appeared below it, and
      // the page slid out from under the words the solver was being asked to
      // read (Paul). Disabled says the same thing and occupies the same room.
      const togo = steps.map((s, i) => ({ s, n: i + 1 })).filter(({ s }) => !isShown(e, s.key));
      const open = guessing ? [] : togo.filter(({ s }) => rungAvailable(e, steps, s.key));
      open.forEach(({ s, n }, j) => {
        // Every rung reads as its own question and nothing else. The lead one
        // used to say "Show hint 5 · …", which sold the ladder as a shelf of
        // answers you buy — and it hasn't been that since the rungs started
        // asking you first (Paul, 2026-08-27). What it is recommending is still
        // visible: the lead is the plain button and the sideways moves are
        // ghosts, which is where that has always been said.
        nextSpec.push({ rung: s.key, cls: j > 0 ? "ghost small" : "",
          text: `${n} · ${s.label}` });
      });
      togo.filter((t) => open.indexOf(t) < 0).forEach(({ s, n }) => {
        nextSpec.push({ cls: "ghost small locked", disabled: true, text: `${n} · ${s.label}`,
          title: guessing
            ? "Answer the question below first"
            : "Take the hints above first — this one gives them away" });
      });
      freeRest = solved && togo.length > 0;
      // Offered once the building blocks are up, not only once the whole ladder
      // is: the blocks spell the answer out piece by piece, so a solver who has
      // just assembled it is being made to copy their own work into the grid
      // square by square (Paul, 2026-08-28). Still offered last, under the rungs,
      // because it is the way out of the clue rather than a step in it.
      if (!guessing && canCheck() && !solved && (!togo.length || isShown(e, "blocks"))) {
        nextSpec.push({ fill: true, text: FILL_LABEL });
      }
    }
    setHTML($("hint-meter"), meterHTML + (freeRest ? " · the rest are free now" : ""));

    const bodyWrote = setHTML(body, bodyHTML);
    setButtons(next, nextSpec);

    // The escape hatch lives outside the ladder: available at any level.
    // No "(counts against your score)" rider. The scorebar already reports
    // revealed letters, so the warning was redundant, and a learner who is
    // stuck should be nudged toward the help rather than taxed for taking it.
    const canReveal = canCheck() && !solved;
    const escapeHTML = (canReveal
      ? `<button id="hx-letter" class="ghost small">Stuck? Reveal one letter</button> ` : "")
      + reportHTML();
    if (setHTML(escape, escapeHTML)) {
      if (canReveal) $("hx-letter").onclick = revealLetter;
      bindReport(e);
    }

    if (!bodyWrote && !clueWrote) return;

    if (ask && ask.choices) {
      ask.choices.forEach((c, i) => {
        $("gc-" + i).onclick = () => {
          const a = currentAsk();
          if (a && a.choices) finishGuess(gradeChoice(a, c), a);
        };
      });
    } else if (ask) {
      // Only the words in play have a button to bind: a settled one is a span.
      ask.tokens.forEach((t, i) => {
        if (ask.known.indexOf(i) >= 0) return;
        const el = $("gw-" + i);
        el.onclick = () => {
          // A drag ends in a click on the word it started from. That click has
          // already been answered by the drag.
          if (swallowClick) { swallowClick = false; return; }
          if (!currentAsk()) return;
          const j = guessing.picked.indexOf(i);
          if (j >= 0) guessing.picked.splice(j, 1); else guessing.picked.push(i);
          renderHintPanel();
        };
        if (el.addEventListener) {
          el.addEventListener("pointerdown", () => {
            const a = currentAsk();
            if (a) drag = { base: guessing.picked.slice(), from: i, moved: false, ask: a };
          });
        }
      });
      $("guess-check").onclick = () => {
        const a = currentAsk();
        if (!a || !guessing.picked.length) return;
        finishGuess(gradeGuess(a), a);
      };
    }
    // Never a dead end. Asking to be told is a legitimate answer to "do you know
    // this yet?", and it costs what the rung has always cost. Every question has
    // one, whether it is answered by tapping words or by picking a family.
    if (ask) {
      $("guess-tell").onclick = () => {
        const a = currentAsk();
        if (a) finishGuess(null, a);
      };
    }

    // The anagram ring. Both handlers only ever touch `ring`, so a redraw is
    // the whole update — the tiles are where the letters are, not what they are.
    panel.querySelectorAll("button.ana-tile").forEach((b) => {
      b.onclick = () => {
        const i = b.getAttribute("data-ana");
        if (ring) { ring.struck[i] = !ring.struck[i]; renderHintPanel(); }
      };
    });
    const shuffle = document.getElementById("ana-shuffle");
    // Struck letters survive a shuffle: they are the ones already on the grid,
    // and dealing again is a fresh look at what is LEFT.
    if (shuffle && ring) shuffle.onclick = () => {
      ring.order = dealRing(ring.letters, ring.forbidden);
      renderHintPanel();
    };
  }

  // ---------- score ----------
  // What this clue costs. Frozen at the moment it was solved: rungs opened after
  // that are a solver studying a clue they already got, and charging for the
  // lesson would make the unlock in rungAvailable a trap. The group's cost is the
  // count when its LAST leg went in, and rungs only ever accumulate, so that is
  // the largest of the legs' snapshots.
  function hintsCharged(e) {
    // Rungs that were earned by naming the words don't count. They are on the
    // screen because the solver asked to see whether they were right, not
    // because they needed telling.
    if (!groupSolved(e)) return Math.max(0, shownRungs(e).length - earnedRungs(e).length);
    const key = entryKey(e);
    return entries.filter((g) => entryKey(g) === key)
      .reduce((n, g) => Math.max(n, solvedWith[g.id] || 0), 0);
  }

  function renderScore() {
    const total = entries.filter((e) => !(e.annotation && e.annotation.linkedTo)).length;
    let solved = 0, noHints = 0, levelsUsed = 0, lettersRevealed = 0;
    const counted = {};
    entries.forEach((e) => {
      const key = entryKey(e);
      if (counted[key]) return;
      counted[key] = true;
      const rungs = hintsCharged(e);
      if (groupSolved(e)) {
        solved++;
        if (!rungs && !(revealsUsed[key] > 0)) noHints++;
      }
      levelsUsed += rungs;
      lettersRevealed += revealsUsed[key] || 0;
    });
    $("scorebar").innerHTML =
      `Solved <strong>${solved}/${total}</strong> clues · <strong>${noHints}</strong> with no hints · <strong>${levelsUsed}</strong> hint levels used`
      + (lettersRevealed ? ` · <strong>${lettersRevealed}</strong> letter${lettersRevealed > 1 ? "s" : ""} revealed` : "");
  }

  // ---------- picker ----------
  // Difficulty comes from tools/difficulty.py, which rates a puzzle against the
  // rest of the collection rather than in the abstract — see its header for why
  // an absolute rating is not something the data supports. The tooltip carries
  // that caveat, because a bare word like "Brutal" reads as a fact.
  function difficultyBadge(p) {
    const d = p.difficulty;
    if (!d) return "";
    const pct = d.percentile === null || d.percentile === undefined ? "" :
      ` — harder than ${d.percentile}% of the puzzles here`;
    const basis = (d.basis || []).join(", ");
    return `<span class="badge diff diff-${d.band.toLowerCase()}" title="${esc(
      d.band + pct + ". Judged on " + basis + ", relative to the other puzzles here."
    )}">${esc(d.band.toLowerCase())}</span>`;
  }

  // Badge the exception, never the norm (feedback 2026-08-01: "since it only
  // lists full hints we don't have to show it"). Once the picker stopped
  // listing un-annotated puzzles, a "full hints" badge on every row said the
  // same thing about every row, which is the same as saying nothing while
  // still costing a line of the row. So there is no full-hints badge in the
  // app at all now: annotated is what a listed puzzle IS, and the badge exists
  // only to warn you when the one in front of you isn't. The archive page
  // (tools/build_seo_pages.py) still badges both, and correctly — it lists
  // every puzzle, so there the two states are a real distinction.
  function hintsBadge(annotated) {
    return annotated ? "" : `<span class="badge auto">auto hints</span>`;
  }

  // Shares the coverage axis (neutral) with the hints badge on purpose: both
  // answer "what has this site actually got for this puzzle", and the badge
  // colour rule in style.css is one colour per axis, not per badge.
  function sourceBadge(p) {
    return p.solutionsUnofficial
      ? `<span class="badge auto" title="The paper hasn't published this one's answers yet — these are ours">our answers</span>`
      : "";
  }

  // Same principle as the hints badge: badge the exception, not the norm. The
  // Every series says what it is. There is no default: a row with no chip reads
  // as a row we forgot to label, not as "the usual one", and the smoke test
  // fails on a series in the index with no entry here — that is what keeps this
  // table complete as papers are added.
  //
  // This text is prose for a human choosing what to attempt next, which is why
  // it lives here and not in tools/series.py with the machine-readable facts.
  // [what the chip says, why]. The label used to be the series key itself,
  // which worked only while every key happened to read as a word — and then
  // "indysunday" arrived. Keep it a label; keys are storage, not English.
  const SERIES_BADGE = {
    cryptic: ["guardian", `The Guardian's daily cryptic, Monday to Saturday. A
      rotating cast of setters and no house line on difficulty, so one day is a
      gentle Vulcan and the next is a Paul full of puns.`],
    quiptic: ["quiptic", `Guardian Quiptic — their beginner crossword, published
      Mondays. Same clue types as the daily cryptic, but gentler: plainer
      definitions and fewer buried indicators.`],
    everyman: ["everyman", `Everyman — the Observer's Sunday cryptic. The gentlest
      of the broadsheet puzzles and scrupulously fair: definitions sit at one end,
      and the wordplay always spells the answer out if you can hear it.`],
    independent: ["independent", `The Independent's daily cryptic, Monday to
      Saturday. About as hard as the Guardian, with a regular cast of setters —
      Phi, Quince, Eccles, Hippogryph — so their habits are worth learning if you
      like one of them.`],
    indysunday: ["indy sunday", `The Independent on Sunday's cryptic — its own
      weekly numbering, near 1,900 while the daily is past 12,400. Same stable of
      setters as the daily, and pitched about the same.`],
  };

  function seriesBadge(p) {
    const badge = SERIES_BADGE[p.series || "cryptic"];
    if (!badge) return "";  // guarded by the smoke test; never the normal path
    return `<span class="badge series" title="${badge[1]}">${badge[0]}</span>`;
  }

  // What the picker lists, and why it isn't everything.
  //
  // This is a teaching site, so a puzzle with no hand-written annotations can't
  // do the thing the site is for: you can type letters into it and check them,
  // and that's all. Listing those alongside the taught ones (2026-08-01: "we
  // only want to only show ones that have full annotations") made the one dialog
  // whose job is "what should I do next" answer mostly with things that won't
  // teach you anything — 22 of 36 rows, and the ratio gets worse every night,
  // because fetching is daily and annotating is one puzzle per run.
  //
  // Nor is it everything that IS annotated. The dialog answers "what should I
  // do next", and at 226 taught puzzles the answer had become a catalogue you
  // scroll (Paul, 2026-08-27). So the default is the newest RECENT_ROWS, plus
  // whatever the solver has open or has left unfinished.
  //
  // Hidden is not gone. A query searches EVERY puzzle, annotated or not, so
  // typing a number you know still finds it; the archive page lists them all;
  // and ?p=<n> opens any of them. A finished grid drops out of the default list
  // rather than sitting in it forever: it is the one puzzle you have no reason
  // to open next, and "solved" is a search term for the days you do.
  const RECENT_ROWS = 12;
  function pickerProgress(p) {
    const prog = store.get("ct:" + p.id, null);
    return prog && prog.letters ? Object.keys(prog.letters).length : 0;
  }
  // "Have I finished this one?" — the question a list of 78 puzzles has to
  // answer before it can answer anything else. It is computed here rather than
  // stored: the saved letters are simply held against the solutions. A stored
  // `done` flag would be a second copy of a fact the data already knows, and
  // sync/merge.js would then have to have an opinion about merging it — see
  // make-the-wrong-version-unwritable.
  //
  // The solutions are only fetched for puzzles with letters saved, which is why
  // the `!filled` test comes first: it is also what makes loadStartedPuzzles a
  // short list rather than the whole catalogue.
  //
  // Filled-but-wrong deliberately reads as unfinished rather than as "12 wrong":
  // the check buttons are for that, and a row in the picker is not the place to
  // tell someone their grid is broken.
  function pickerStatus(p) {
    const prog = store.get("ct:" + p.id, null);
    const letters = (prog && prog.letters) || {};
    const filled = Object.keys(letters).length;
    const puz = window.CRYPTIC_PUZZLES[p.id];
    if (!filled || !puz) return { filled, total: 0, done: false };
    const want = {};   // "x,y" -> the letter that belongs there
    puz.entries.forEach((e) => {
      for (let i = 0; i < e.length; i++) {
        const x = e.position.x + (e.direction === "across" ? i : 0);
        const y = e.position.y + (e.direction === "across" ? 0 : i);
        want[x + "," + y] = e.solution ? e.solution[i] : null;
      }
    });
    const squares = Object.keys(want);
    // letters[k] is "A" or "A!" — a revealed letter still counts as done. You
    // used the escape hatch; the scorebar inside the puzzle is where that costs
    // you something.
    const done = squares.length > 0
      && squares.every((k) => want[k] && letters[k] && letters[k][0] === want[k]);
    return { filled, total: squares.length, done };
  }
  // The date and the day it fell on. A weekday is not decoration on a cryptic:
  // the Guardian's week has a shape — Monday gentle, Friday and Saturday's prize
  // hard — so "what day is this from" is a difficulty cue people read before
  // they start (Paul, 2026-08-16). Always COMPUTED from the timestamp, never
  // stored: a saved weekday is a second copy of the date, and second copies
  // disagree. getUTCDay to match the UTC the ISO string is sliced out of, or a
  // solver west of Greenwich gets a day that contradicts the date beside it.
  const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  function puzzleDate(p) {
    if (!p.date) return { iso: "", day: "", short: "" };
    const dt = new Date(p.date);
    const day = WEEKDAYS[dt.getUTCDay()] || "";
    return { iso: dt.toISOString().slice(0, 10), day, short: day.slice(0, 3) };
  }
  function pickerHaystack(p) {
    const dd = puzzleDate(p);
    const d = dd.iso;
    // Both spellings of the number: the site writes "No 30,074" everywhere, and
    // a solver copying that in shouldn't get nothing back.
    // "solved" and "started" are searchable for the same reason the row shows
    // them: with 78 puzzles listed, "which ones have I already done" is a filter,
    // not just a thing to read off one row at a time.
    const st = pickerStatus(p);
    // The weekday is searchable for that same reason — showing "Sat" in the row
    // and then not matching "saturday" would be the worse half of the feature.
    // Both the series key and the name on its chip: "cryptic" is what the file
    // is called, "guardian" is what the paper is, and the one the row shows has
    // to be the one that matches.
    const series = p.series || "cryptic";
    return [p.number, String(p.number).replace(/(\d)(\d{3})$/, "$1,$2"), p.setter, d, dd.day,
      series, (SERIES_BADGE[series] || [""])[0], p.difficulty ? p.difficulty.band : "",
      st.done ? "solved done" : st.filled ? "started unfinished" : ""].join(" ").toLowerCase();
  }
  // What the browser offers as you type. Only the terms a solver could not be
  // expected to have spelled right from memory — the setters above all, then
  // series, band and day — plus the two status filters. Numbers are deliberately
  // absent: 226 of them would bury every word in the list, and a number you can
  // remember you can already type.
  //
  // Built from the index rather than listed, so a setter cannot appear in the
  // suggestions without appearing in the rows, or the other way round.
  //
  // Nothing is offered until two letters are in. iOS opens the whole list the
  // instant the field is focused, so a datalist filled up front buries the
  // panel it is there to search (Paul, iPhone, 2026-08-27). Two letters cuts
  // seventy terms to a handful, and by then the suggestion is about a word
  // already being spelled — which is when a completion is worth anything.
  const PICKER_SUGGEST_MIN = 2;
  let pickerTerms = null;
  function pickerTermsHTML(q) {
    if (q.length < PICKER_SUGGEST_MIN) return "";
    if (pickerTerms === null) {
      const seen = { solved: 1, unfinished: 1 };
      INDEX.puzzles.forEach((p) => {
        [p.setter, (SERIES_BADGE[p.series || "cryptic"] || [""])[0],
         p.difficulty ? p.difficulty.band : "",
         puzzleDate(p).day].forEach((t) => { if (t) seen[t] = 1; });
      });
      pickerTerms = Object.keys(seen).sort((a, b) => a.localeCompare(b));
    }
    return pickerTerms.filter((t) => t.toLowerCase().includes(q))
      .map((t) => `<option value="${esc(t)}"></option>`).join("");
  }

  // The two vocabularies the search accepts and nothing else teaches: the bands
  // and the papers. A completion cannot offer a word you have never seen, and
  // the rows only wear what the visible dozen happen to be — one puzzle in the
  // whole collection is Gentle, and Everyman, the biggest series of the five,
  // starts twenty-three rows down. Scrolling would not turn either up (Paul,
  // 2026-08-27). So both are named outright, in full, next to the box.
  //
  // Bands run easiest first off the percentiles rather than being listed here,
  // so a band that gets added or renamed in tools/difficulty.py cannot land in
  // the wrong place or go missing.
  let pickerBands = null;
  function pickerBandList() {
    if (pickerBands) return pickerBands;
    const at = {};
    INDEX.puzzles.forEach((p) => {
      const d = p.difficulty;
      if (!d || !d.band || d.percentile === null || d.percentile === undefined) return;
      if (at[d.band] === undefined || d.percentile < at[d.band]) at[d.band] = d.percentile;
    });
    pickerBands = Object.keys(at).sort((a, b) => at[a] - at[b]).map((b) => b.toLowerCase());
    return pickerBands;
  }

  // Papers, biggest first: how much there is to solve is the useful order when
  // the question is which one to try. Read off SERIES_BADGE so the word offered
  // is the word the row's chip says — the series KEY is storage ("cryptic" is
  // the Guardian, "indysunday" is two words), and offering that would be
  // teaching the database's name for the paper instead of the paper's.
  let pickerPapers = null;
  function pickerPaperList() {
    if (pickerPapers) return pickerPapers;
    const n = {};
    INDEX.puzzles.forEach((p) => {
      const badge = SERIES_BADGE[p.series || "cryptic"];
      if (badge) n[badge[0]] = (n[badge[0]] || 0) + 1;
    });
    pickerPapers = Object.keys(n).sort((a, b) => n[b] - n[a] || a.localeCompare(b));
    return pickerPapers;
  }

  function pickerRows(q) {
    // Every term has to match somewhere, so "imogen 2026" narrows rather than
    // widens — the useful behaviour when the list is long enough to need a
    // filter at all.
    const terms = q.split(/\s+/).filter(Boolean);
    if (terms.length) {
      return INDEX.puzzles.filter((p) => {
        const hay = pickerHaystack(p);
        return terms.every((t) => hay.includes(t));
      });
    }
    // INDEX.puzzles is latest-first, so the cap counts down from today. The two
    // exemptions are the solver's own place and don't count against it.
    let recent = 0;
    return INDEX.puzzles.filter((p) => {
      if (P && p.id === P.id) return true;
      if (pickerProgress(p) > 0 && !pickerStatus(p).done) return true;
      if (!p.annotated) return false;
      recent += 1;
      return recent <= RECENT_ROWS;
    });
  }

  function renderPicker() {
    const ul = $("picker-list");
    ul.innerHTML = "";
    const q = (($("picker-search") || {}).value || "").trim().toLowerCase();
    setHTML($("picker-terms"), pickerTermsHTML(q));
    // Tapping one ADDS its word to the search; tapping it again takes it out, so
    // the legend is a way back out as well as in. What is selected is shown by
    // the search box filling with the words — which is also the lesson, because
    // typing them yourself does exactly the same thing.
    //
    // They combine, because the question is nearly always two things at once:
    // "I can choose Everyman brutal" (Paul, 2026-08-28). A tap used to REPLACE
    // whatever was in the box, so the paper and the difficulty were mutually
    // exclusive by accident — while the typed search had combined terms all
    // along. The chips are a way to spell the query without knowing the words;
    // they must not be able to express less than the box they fill in.
    //
    // A row each, papers then difficulty (Paul, 2026-08-28: "the difficulty
    // could be on its own line"). They shared one wrapping strip to save a line,
    // and the saving was imaginary — nine chips wrap to two rows on a phone
    // anyway, and where the wrap falls is up to the width, so "Difficulty" and
    // half its bands would trail off the end of the papers. Two named rows read
    // as two questions, which is what they are.
    const chips = [];
    // A chip's label can be more than one word ("indy sunday"), and the box is a
    // list of terms that all have to match, so a chip is ON when every word of it
    // is in the box and toggling it puts in or takes out exactly those words.
    const picked = q.split(/\s+/).filter(Boolean);
    const wordsOf = (w) => w.split(/\s+/).filter(Boolean);
    const isOn = (w) => wordsOf(w).every((x) => picked.indexOf(x) >= 0);
    const group = (label, words, cls) => words.length < 2 ? "" :
      `<span class="picker-group"><span class="muted small-note">${label}</span>`
      + words.map((w) => {
        const i = chips.push(w) - 1;
        return `<button type="button" id="pf-${i}" class="badge ${cls(w)}" aria-pressed="${
          isOn(w)}">${esc(w)}</button>`;
      }).join("") + "</span>";
    setHTML($("picker-filters"),
      group("Papers", pickerPaperList(), () => "series")
        + group("Difficulty", pickerBandList(), (b) => "diff diff-" + esc(b)));
    chips.forEach((w, i) => {
      const el = $("pf-" + i);
      if (!el) return;
      el.onclick = () => {
        const mine = wordsOf(w);
        const next = isOn(w)
          ? picked.filter((x) => mine.indexOf(x) < 0)
          : picked.concat(mine.filter((x) => picked.indexOf(x) < 0));
        $("picker-search").value = next.join(" ");
        renderPicker();
      };
    });
    const rows = pickerRows(q);
    const hidden = INDEX.puzzles.length - rows.length;
    $("picker-more").innerHTML = !hidden ? "" : q
      ? `${hidden} other puzzle${hidden > 1 ? "s" : ""} don’t match.`
      : `${hidden} more — search by number, setter, day or “solved”, or `
        + `<a href="puzzles/">browse the whole archive</a>.`;
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "picker-empty";
      li.innerHTML = `<span class="muted">Nothing matches “${esc(q)}”.</span>`;
      ul.appendChild(li);
      return;
    }
    rows.forEach((p) => {
      const li = document.createElement("li");
      if (P && p.id === P.id) li.className = "current";
      const st = pickerStatus(p);
      const dd = puzzleDate(p);
      // Abbreviated, and the weekday leads. The row is tight — see the note
      // below about the nowrap element shoving the line — and "Sat" in front is
      // read at a glance where a trailing full "Saturday" would just be length.
      const d = dd.iso ? `${dd.short} ${dd.iso}` : "";
      const btn = document.createElement("button");
      // Order here is the grid's, not the eye's: the badges are markup-last but
      // render on their own second line (see .p-tags in style.css). Progress
      // sits with them because it is a status like they are, and because
      // gluing it onto the date made the one nowrap element in the row long
      // enough to shove everything else off the line.
      btn.innerHTML = `<span class="p-num">№ ${p.number}</span>
        <span class="p-setter">${esc(p.setter)}</span>
        <span class="p-meta">${d}</span>
        <span class="p-tags">${seriesBadge(p)}${difficultyBadge(p)}${hintsBadge(p.annotated)}${sourceBadge(p)}
          ${!st.filled ? ""
            : st.done ? `<span class="p-prog done" title="Every square filled in and correct">solved ✓</span>`
            : `<span class="p-prog">${st.filled}${st.total ? "/" + st.total : ""} letters in</span>`}</span>`;
      btn.onclick = () => { openPuzzle(p.id); togglePicker(false); };
      li.appendChild(btn);
      ul.appendChild(li);
    });
  }
  function togglePicker(show) {
    const el = $("picker-panel");
    const want = (show === undefined) ? el.classList.contains("hidden") : show;
    el.classList.toggle("hidden", !want);
    // Opening always starts from a clean list. A filter left over from last time
    // would look like puzzles had gone missing.
    const box = $("picker-search");
    if (want) {
      if (box) { box.value = ""; }
      renderPicker();
      // The progress numbers need the answers, and a sync pull may have handed
      // this browser progress on a puzzle whose file it has never fetched.
      loadStartedPuzzles(() => {
        if (!el.classList.contains("hidden")) renderPicker();
      });
      if (box && box.focus) box.focus();
    }
  }

  // ---------- puzzle lifecycle ----------
  // The address bar is what gets copied. Whichever puzzle is on the screen is
  // the one a share has to hand over, so opening one rewrites the URL — before
  // this, picking from the list left the address bar saying the site root,
  // which drops the reader on last night's puzzle, or a stale ?p= from the link
  // they arrived by, which is worse because it looks deliberate.
  //
  // replaceState, not push: switching puzzles is choosing what to look at, not
  // navigating, and a back button that walked the picker backwards would make
  // leaving the site take one press per puzzle browsed.
  //
  // Only when the reader CHOSE this puzzle, though. Booting on the remembered
  // one is not a choice, and a bare `/cryptic-teacher/` that rewrites itself
  // would leave the homepage declaring a puzzle as its canonical — which is the
  // 2026-08-07 de-indexing bug again, pointed the other way. The front door
  // stays the front door until somebody picks.
  let canonicalHome = null;
  function pointUrlAtPuzzle(id) {
    const p = INDEX.puzzles.find((q) => q.id === id);
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", `?p=${encodeURIComponent(id)}`);
    }
    // ?p=30054 is one app URL among thousands, and it shipped declaring the
    // homepage as its canonical — so Google folded every share and every link to
    // a specific puzzle into the site root, and Search Console listed the puzzle
    // as "alternate page with proper canonical tag" (2026-08-07). The page that
    // deserves that credit is the write-up at /puzzles/30054/, which says the same
    // things without needing JavaScript. Point at it, but only when it exists:
    // an unannotated puzzle has no static page, and the homepage is then honest.
    const link = document.querySelector('link[rel="canonical"]');
    if (!link) return;
    // Resolved against the ORIGINAL canonical, captured once: after the first
    // switch link.href is itself a /puzzles/<n>/ URL, and resolving the next
    // puzzle against that nests one inside the other.
    if (canonicalHome === null) canonicalHome = link.href;
    link.href = p && p.hasSolutions
      ? new URL(`puzzles/${p.id}/`, canonicalHome).href : canonicalHome;
  }

  function openPuzzle(id, chosen = true) {
    const puzzle = window.CRYPTIC_PUZZLES[id];
    // Not fetched yet: fetch it and come back. Once. If it still isn't here the
    // file is gone, and every caller can go on treating this as "open it".
    if (!puzzle) {
      if (puzzleLoad[id] !== 1) loadPuzzle(id, () => openPuzzle(id, chosen));
      return;
    }
    P = puzzle;
    meta = INDEX.puzzles.find((p) => p.id === id) || { annotated: false };
    store.set("ct:last", id);
    if (chosen) pointUrlAtPuzzle(id);
    buildModel();
    hintsShown = {}; hintsEarned = {}; hintLevels = {}; revealsUsed = {}; solvedWith = {}; timing = {};
    // Forget the last puzzle's completeness, so the first render of this one
    // only records where it stands. Opening a puzzle you finished last week is
    // not something to celebrate.
    wasComplete = null;
    $("celebrate").classList.add("hidden");
    restoreState();
    sealArrivedProgress();
    beacon("open");
    reportVisit();
    // ?c=3D opens on that clue. A whole 15x15 is a lot to hand someone who has
    // never solved a cryptic, and it is also just what sharing wants: the answer
    // to "which one are you stuck on" should be a link, not a number to hunt for.
    // Unknown or absent falls back to the first clue rather than erroring — a
    // link that has outlived its puzzle should still open the puzzle.
    const asked = linkedClueSpent ? "" : linkedClue;
    linkedClueSpent = true;
    const first = entries.find((e) => tag(e) === asked) || entries[0];
    cur = { x: first.position.x, y: first.position.y, dir: first.direction };
    $("app").classList.remove("hidden");
    // The day spelled out in full here, where there is room for it, and where a
    // solver about to start wants to know whether they picked a Monday or a
    // Saturday prize before they wonder why it is fighting back.
    const when = puzzleDate(meta);
    $("puzzle-title").innerHTML =
      `${esc(P.name)} — set by <em>${esc(P.setter)}</em>` +
      (when.day ? ` <span class="muted">· ${when.day} ${when.iso}</span>` : "") +
      (meta.annotated ? "" : " " + hintsBadge(false));
    // Saturday prize puzzles publish their answers about a week late, and this
    // site solves them in the meantime rather than leaving its newest puzzle
    // hintless (tools/apply_solution.py). Every letter the checker marks wrong
    // is then measured against a machine's answer, not the paper's, and someone
    // being told they are wrong deserves to know who is telling them.
    const note = $("unofficial-note");
    note.classList.toggle("hidden", !meta.solutionsUnofficial);
    note.textContent = meta.solutionsUnofficial
      ? "Heads up: the Guardian hasn't published this prize puzzle's answers yet. "
        + "The solutions and hints here are our own solve — checked for consistency "
        + "across every crossing, but not the paper's. They get replaced by the "
        + "official ones the day they appear."
      : "";
    renderGrid();
    renderClues();
    const checkable = canCheck();
    ["chk-letter", "chk-entry", "chk-grid"].forEach((id2) => { $(id2).disabled = !checkable; });
    refreshAll();
  }

  // Finishing a puzzle used to change one number in the scorebar from 27 to 28
  // ("there should be some celebration when you complete", Paul, 2026-08-17).
  // Two rules keep it from becoming noise: it fires on the TRANSITION only, in
  // the session that earned it — reopening a finished puzzle is not an
  // achievement and must not throw paper at you — and the paper is not the
  // point, the scoreline is. Somebody who solved 28 clues, 9 of them cold, in
  // 41 minutes is owed those three numbers in one sentence.
  let wasComplete = null;      // null = not measured yet on this puzzle
  function checkComplete() {
    const complete = entries.length > 0 && entries.every(isEntrySolved);
    const earned = wasComplete === false && complete;
    wasComplete = complete;
    if (earned) { beacon("done"); celebrate(); }
  }
  function celebrate() {
    const box = $("celebrate");
    if (!box) return;
    const total = entries.filter((e) => !(e.annotation && e.annotation.linkedTo)).length;
    const counted = {};
    let noHints = 0, levels = 0;
    entries.forEach((e) => {
      const key = entryKey(e);
      if (counted[key]) return;
      counted[key] = true;
      const rungs = hintsCharged(e);
      levels += rungs;
      if (!rungs && !(revealsUsed[key] > 0)) noHints++;
    });
    const mins = Math.round((timing.solvedMs || timing.activeMs || 0) / 60000);
    const bits = [`<strong>${total}</strong> clues`];
    if (noHints) bits.push(`<strong>${noHints}</strong> of them with no hint at all`);
    bits.push(levels ? `<strong>${levels}</strong> hint${levels === 1 ? "" : "s"} spent`
                     : "not one hint spent");
    if (mins) bits.push(`<strong>${mins}</strong> minute${mins === 1 ? "" : "s"} at it`);
    // The confetti is spans with per-piece delays; prefers-reduced-motion turns
    // the animation off in style.css and leaves the sentence, which is the part
    // that was actually missing.
    const bows = Array.from({ length: 24 }, (_, i) =>
      `<span class="bit" style="left:${((i * 4.1 + (i % 5) * 2) % 100).toFixed(1)}%;` +
      `animation-delay:${(i % 8) * 0.12}s"></span>`).join("");
    box.innerHTML = `<div class="paper">${bows}</div>
      <p class="shout">Finished — the whole grid.</p>
      <p class="tally">${bits.join(" · ")}</p>
      <button id="celebrate-done">Thanks</button>`;
    box.classList.remove("hidden");
    const close = () => box.classList.add("hidden");
    $("celebrate-done").onclick = close;
    box.onclick = close;
  }

  function refreshAll() {
    refreshGrid();
    refreshClues();
    renderHintPanel();
    renderScore();
    checkComplete();
    checkHalfFilled();
    syncClueUrl();
  }

  // The address bar follows the clue, so "look at 3 down" is a link.
  //
  // Driven from refreshAll rather than from selectEntry because a clue gets
  // chosen half a dozen ways — tapping a cell, the arrow keys, tab, the clue
  // list — and only one of them goes through selectEntry. Guarded on the ref
  // actually changing, because refreshAll also runs on every keystroke and
  // Safari rate-limits replaceState hard enough that a fast solver would hit
  // the ceiling and lose the lot.
  //
  // Only ever a refinement of a URL that already names a puzzle: a bare
  // /cryptic-teacher/ has to stay the front door, for the reason spelled out
  // above pointUrlAtPuzzle.
  let urlClue = null;
  function syncClueUrl() {
    const e = currentEntry();
    const ref = e ? tag(e) : null;
    if (ref === urlClue) return;
    urlClue = ref;
    const p = new URLSearchParams(location.search).get("p");
    if (!p || !ref || !window.history || !window.history.replaceState) return;
    window.history.replaceState(null, "", `?p=${encodeURIComponent(p)}&c=${ref}`);
  }

  // ---------- boot ----------

  function boot() {
    // The lesson is /learn/ — a page, reached by a plain link in the header.
    // It is a document you read end to end, and it outgrew the collapsible
    // section it used to live in on this page (Paul, 2026-08-27).
    $("btn-picker").onclick = () => togglePicker();
    $("btn-picker-close").onclick = () => togglePicker(false);

    // ---- sync ----
    // The button is only offered if there is somewhere to sync to. A control
    // that explains it cannot work is worse than no control.
    if (!SYNC_ENDPOINT) $("btn-sync").classList.add("hidden");
    $("btn-sync").onclick = () => {
      const el = $("sync-panel");
      const want = el.classList.contains("hidden");
      el.classList.toggle("hidden", !want);
      if (want) { renderSyncPanel(); if (syncOn()) syncPull(); }
    };
    $("btn-sync-close").onclick = () => $("sync-panel").classList.add("hidden");
    $("sync-start").onclick = () => {
      store.set("ct:sync", newSyncCode());
      renderSyncPanel();
      syncNote("Uploading…");
      syncPush();
    };
    $("sync-copy").onclick = copySyncCode;
    $("sync-join").onclick = () => {
      const raw = ($("sync-join-code").value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
      if (raw.length !== 8) { syncNote("A code is 8 characters."); return; }
      store.set("ct:sync", raw);
      renderSyncPanel();
      syncNote("Fetching…");
      // Pull, not push: the machine you are joining *from* is the one that knows
      // things, and the merge means joining can only ever add to what is here.
      syncPull();
    };
    $("sync-stop").onclick = () => {
      // Local progress is deliberately left alone. Stopping sync means "don't
      // send my crosswords anywhere any more", not "throw away my crosswords".
      store.del("ct:sync");
      renderSyncPanel();
    };
    // Coming back to a tab is exactly when the other machine's work is waiting,
    // and it is the cheapest possible moment to ask.
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && syncOn()) syncPull();
    });
    // Typing is the whole navigation model once the list outgrows a screen, so
    // the box is focused on open and Enter takes the top row — number in, puzzle
    // open, no mouse. Escape gets you back out; the global key handler ignores
    // inputs, so it has to be handled here.
    $("picker-search").addEventListener("input", () => renderPicker());
    $("picker-search").addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { togglePicker(false); focusKbd(); return; }
      if (ev.key !== "Enter") return;
      const first = $("picker-list").children[0];
      const btn = first && first.children[0];
      if (btn && btn.onclick) btn.onclick();
    });

    $("chk-letter").onclick = () => { const c = cells[cur.y][cur.x]; if (c) checkCells([c], "square"); };
    $("chk-entry").onclick = () => { const e = currentEntry(); if (e) checkCells(entryCells(e), "entry"); };
    $("chk-grid").onclick = () => { const all = []; forEachCell((c) => all.push(c)); checkCells(all, "grid"); };
    $("clear-entry").onclick = () => {
      const e = currentEntry();
      if (!e) return;
      entryCells(e).forEach((c) => { c.letter = ""; c.wrong = false; c.revealed = false; });
      refreshAll(); saveState();
    };
    $("reset-puzzle").onclick = () => {
      if (!confirm("Clear the grid and all hint history for this puzzle?")) return;
      // Deleting the save is not enough once there is a second device: an empty
      // slot reads as "never played this", so the other machine would hand the
      // whole grid back on the next pull. The reset is recorded as a moment
      // instead, and merge.js drops everything either side knew before it.
      const now = Date.now();
      // The clock goes with it. "Clear the grid and all hint history" means a
      // fresh attempt, and an attempt that starts on a grid you have already
      // solved once is not a time anything should be averaging.
      store.set(stateKey(), { letters: {}, letterAt: {}, hintsShown: {}, hintsEarned: {},
                              revealsUsed: {}, solvedWith: {}, timing: {},
                              clearedAt: now, updated: now });
      forEachCell((c) => { c.letter = ""; c.wrong = false; c.revealed = false; });
      hintsShown = {}; hintsEarned = {}; hintLevels = {}; revealsUsed = {}; solvedWith = {}; timing = {};
      refreshAll();
      syncPushSoon();
    };

    document.addEventListener("keydown", (ev) => {
      if (ev.target && (ev.target.tagName === "INPUT" && ev.target.id !== "kbd" || ev.target.tagName === "TEXTAREA")) return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      // Tab, Enter and Space belong to whatever control has focus. onKey swallows
      // all three on behalf of the grid, so forwarding them from a focused button
      // makes the page keyboard-dead: Tab never moves on and Enter flips the
      // grid's direction instead of pressing the button under the cursor.
      const el = document.activeElement;
      const onControl = el && el.id !== "kbd" &&
        (el.tagName === "BUTTON" || el.tagName === "A" || el.tagName === "SELECT");
      if (onControl && (ev.key === "Tab" || ev.key === "Enter" || ev.key === " ")) return;
      onKey(ev);
    });
    // mobile soft keyboards often only fire `input`
    $("kbd").addEventListener("input", (ev) => {
      const v = letterOf(ev.target.value);
      if (v) typeLetter(v[v.length - 1]);
      ev.target.value = "";
    });
    // THE ONE PLACE THAT SUMMONS A KEYBOARD: the letter strip, the row of boxes
    // for the answer. Tapping the squares you are about to fill in is the only
    // tap on the page that says "I am going to type" — everything else on the
    // way to an answer is reading and choosing.
    //
    // On mousedown, because iOS only opens the keyboard for a focus() inside the
    // gesture and this strip re-renders itself on the way through: by the time a
    // click handler's focus() ran, the box that was tapped had been thrown away
    // with the rest of the strip's innerHTML, the tap had nothing left to belong
    // to, and you got a moved cursor and no keyboard (Paul, iPad, 2026-08-09).
    $("hint-pattern").addEventListener("mousedown", () => focusKbd());

    // Everything else keeps a keyboard and never raises one. The grid used to
    // raise it — tapping a square was read as a decision to type — but picking a
    // square is how you pick a CLUE, and the ladder answers a new clue with a
    // question you answer by tapping (Paul, 2026-08-27, again 2026-08-29). The
    // hint buttons and the clue lists were already on this rule; the grid joins
    // them, so the strip is the only exception and the strip is where typing
    // starts.
    //
    // Bound to the containers, not the buttons, because refreshAll() throws the
    // buttons away and rebuilds them on every render. The mousedown listener
    // runs before the default focus transfer, so activeElement still says
    // whether the keyboard was up when the finger landed.
    ["grid", "clues-across", "clues-down", "hint-next", "hint-escape"].forEach((id) =>
      $(id).addEventListener("mousedown", keepKbd));

    // The letter strip is also how you steer: tap a box to put the cursor on
    // that square of the current entry.
    $("hint-pattern").addEventListener("click", (ev) => {
      const box = ev.target && ev.target.dataset ? ev.target : null;
      const idx = box ? Number(box.dataset.i) : NaN;
      const e = currentEntry();
      if (!e || !Number.isInteger(idx)) return;
      const c = cellAt(e, Math.max(0, Math.min(e.length - 1, idx)));
      cur.x = c.x; cur.y = c.y;
      // Focus first: refreshAll() rebuilds this strip and removes the node the
      // click is still travelling through.
      focusKbd(); refreshAll();
    });

    if (!INDEX.puzzles.length) {
      $("puzzle-title").textContent = "No puzzles found — run tools/fetch_puzzle.py first.";
      $("app").classList.remove("hidden");
      return;
    }
    // ?p=30072 wins over the remembered puzzle: the static answer pages under
    // /puzzles/<n>/ link in that way, and dropping someone on last night's
    // puzzle instead of the one they clicked would be baffling.
    // Every link shared before 2026-08-19 says ?p=30080, and they must keep
    // opening the puzzle they named.
    migrateSavedIds();
    const askedRaw = new URLSearchParams(location.search).get("p");
    const asked = askedRaw ? canonicalId(askedRaw) : null;
    const last = store.get("ct:last", null);
    const firstAnnotated = (INDEX.puzzles.find((p) => p.annotated) || INDEX.puzzles[0]).id;
    // Decided off the INDEX, which is already here, rather than off the loaded
    // files, which are not: this is the id whose file we are about to go and get.
    const want = (asked && BY_ID[asked]) ? asked : (last && BY_ID[last]) ? last : firstAnnotated;
    loadPuzzle(want, () => {
      if (!window.CRYPTIC_PUZZLES[want]) {
        // Say which one and why. The alternative — falling back to some other
        // puzzle — hides a broken deploy behind a crossword nobody asked for.
        $("puzzle-title").textContent =
          `Could not load puzzle ${want}. Check your connection and reload.`;
        $("app").classList.remove("hidden");
        return;
      }
      openPuzzle(want, !!asked);
      // Everything below is after the first paint on purpose. The pull is a
      // network round trip and the solver should be looking at yesterday's
      // letters while it happens, not a blank page; if it brings anything new,
      // applyEnvelope redraws. The started puzzles are only needed by the
      // picker, which is shut.
      if (syncOn()) syncPull();
      loadStartedPuzzles(() => {
        if (!$("picker-panel").classList.contains("hidden")) renderPicker();
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
