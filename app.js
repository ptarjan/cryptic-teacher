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
  const SYNC_RESERVED = { last: 1, sync: 1 };
  const CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"; // no 0/O/1/I/L to mistype

  // ---------- load all puzzle files listed in puzzles/index.js ----------
  const INDEX = (window.CRYPTIC_INDEX && window.CRYPTIC_INDEX.puzzles) ? window.CRYPTIC_INDEX : { latest: null, puzzles: [] };
  window.CRYPTIC_PUZZLES = window.CRYPTIC_PUZZLES || {};

  function loadPuzzleScripts(done) {
    let pending = INDEX.puzzles.length;
    if (!pending) return done();
    INDEX.puzzles.forEach((p) => {
      const s = document.createElement("script");
      // ?v=<content hash> so an updated puzzle is never served from cache
      s.src = "puzzles/" + p.file + (p.v ? "?v=" + p.v : "");
      s.onload = s.onerror = () => { if (--pending === 0) done(); };
      document.head.appendChild(s);
    });
  }

  // ---------- state ----------
  let P = null;          // current puzzle object
  let meta = null;       // its index entry
  let cells = [];        // rows x cols of {x,y,sol,num,across,down,el,letter,wrong,revealed} | null
  let entries = [];      // puzzle entries in tab order (across by number, then down)
  let byId = {};
  let cur = { x: 0, y: 0, dir: "across" };
  // entryKey -> array of rung keys revealed ("definition", "blocks", …), in the
  // order the solver asked for them. A SET, not a high-water mark: the ladder
  // has a recommended order but no required one, so wanting the indicators
  // without being told the definition first is a legitimate way to solve and
  // the model has to be able to represent it. The old integer couldn't — it
  // could only say "the first N", so every rung dragged in the ones below it.
  let hintsShown = {};
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
  function saveState() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
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
      store.set(stateKey(), { letters, letterAt, hintsShown, revealsUsed, solvedWith,
                              timing, clearedAt: prev.clearedAt || 0, updated: now });
      syncPushSoon();
    }, 150);
  }
  function restoreState() {
    const s = store.get(stateKey(), null);
    hintsShown = (s && s.hintsShown) || {};
    hintLevels = (s && s.hintLevels) || {};
    revealsUsed = (s && s.revealsUsed) || {};
    solvedWith = (s && s.solvedWith) || {};
    timing = (s && s.timing) || {};
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
  function applyEnvelope(env) {
    if (!env || !env.puzzles) return false;
    const openId = P ? String(P.id) : null;
    let openChanged = false;
    Object.keys(env.puzzles).forEach((id) => {
      const merged = env.puzzles[id];
      const before = JSON.stringify(store.get("ct:" + id, null));
      const after = JSON.stringify(merged);
      if (before === after) return;
      store.set("ct:" + id, merged);
      if (id === openId) openChanged = true;
    });
    if (env.last && env.last.id && !store.get("ct:last", null)) store.set("ct:last", env.last.id);
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
            if (touchAnchor && Math.hypot(t.clientX - touchAnchor.x, t.clientY - touchAnchor.y) > 10) return;
            ev.preventDefault(); onCellClick(c);
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
        li.addEventListener("click", () => { selectEntry(e, true); focusKbd(); });
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

  function clueHTML(e) {
    const ann = annOf(e);
    if (!ann) return plainClueHTML(e);
    const shown = (key) => isShown(e, key);
    const marks = [];
    const push = (text, cls) => {
      if (!text) return;
      const i = e.clue.indexOf(text);
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
    marks.sort((a, b) => a.i - b.i);
    // drop overlaps
    const keep = [];
    let end = -1;
    marks.forEach((m) => { if (m.i >= end) { keep.push(m); end = m.i + m.len; } });
    return markUp(e.clue, keep, italicsOf(e));
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
  let settleTimer = null, settleBy = 0;
  function scrollToHintPanel() {
    settleBy = Date.now() + HINT_DEADLINE_MS;
    armHintPlacement();
  }
  function armHintPlacement() {
    if (settleTimer) clearTimeout(settleTimer);
    settleTimer = setTimeout(placeHintPanel, Math.max(0, Math.min(HINT_SETTLE_MS, settleBy - Date.now())));
  }
  // Only ever called off that timer, so layout has long since flushed and there
  // is nothing to measure a frame later for.
  function placeHintPanel() {
    settleTimer = null; settleBy = 0;
    const p = $("hint-panel");
    if (!p || p.classList.contains("hidden") || !p.getBoundingClientRect) return;
    const r = p.getBoundingClientRect();
    const band = visibleBand();
    const vh = band.bottom - band.top;
    if (vh <= 0 || !r.height) return;
    if (r.top >= band.top && r.bottom <= band.bottom) return;   // all there already
    const y = window.pageYOffset || 0;
    // Too tall to fit, or hanging off the top: line its top up with the top of
    // the band. Otherwise it is below, so pull its bottom up to the band's floor.
    const top = (r.height > vh - HINT_SCROLL_GAP || r.top < band.top)
      ? y + r.top - band.top - HINT_SCROLL_GAP
      : y + r.bottom - band.bottom + HINT_SCROLL_GAP;
    window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }
  // settleBy is the whole guard: a resize matters only while a tap is waiting to
  // land. A keyboard raised for something else, a dismissal, a rotation or the
  // URL bar sliding away under an ordinary scroll must not yank the page out from
  // under someone who is reading.
  if (window.visualViewport && window.visualViewport.addEventListener) {
    window.visualViewport.addEventListener("resize", () => {
      if (settleBy) armHintPlacement();
    });
  }

  function onCellClick(c) {
    const before = currentEntry();
    if (cur.x === c.x && cur.y === c.y) {
      const other = cur.dir === "across" ? "down" : "across";
      if (c[other]) cur.dir = other;
    } else {
      cur.x = c.x; cur.y = c.y;
      if (!c[cur.dir]) cur.dir = c.across ? "across" : "down";
    }
    focusKbd();
    refreshAll();
    const after = currentEntry();
    if (after && (!before || entryKey(before) !== entryKey(after))) scrollToHintPanel();
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
    kbd.value = "";
    kbd.focus({ preventScroll: true });
  }

  // ---------- checking / revealing ----------
  function canCheck() { return hasSolutions(); }

  // A check must ALWAYS visibly answer (feedback 2026-07-29: checking a correct
  // entry changed nothing on screen, so the button read as broken). Two signals:
  // a sentence in #check-result saying what was found, and a brief pulse on the
  // squares that were examined, so you can see WHICH squares the check covered.
  function checkCells(list, scope) {
    if (!canCheck()) return;
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
        solvedWith[e.id] = shownRungs(e).length;
      }
    });
  }

  // ---------- hint ladder ----------
  // The ladder is BUILT PER CLUE, not fixed: a rung only exists if it has
  // something to say. A double definition has no indicators, so it gets no
  // "spot the indicator" rung (which used to read "No indicator words"), and
  // its rungs are worded for two definitions rather than one. See STYLE.md.
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
    ["first letter", "First letters: take the initial letter(s) of indicated word(s)."],
    ["last letter", "Last letters: take the final letter(s) of indicated word(s)."],
    ["middle letter", "Middle letters: take just the centre of an indicated word."],
    ["outer letters", "Outer letters: keep only the outside letters of an indicated word."],
    ["cryptic definition", "A cryptic definition: no separable wordplay — the whole clue is one sly description."],
    ["spoonerism", "A spoonerism: swap the opening sounds of two words to get the answer."],
    ["cycling", "Cycling: letters move from one end to the other without changing their order — the word rotates rather than shuffles."],
    ["substitution", "A substitution: one indicated letter or chunk stands in for another — make the swap and the answer appears."]
  ];

  // Rung 1 must not hand the mechanism over. It names the FAMILY — the shape of
  // the job — and the precise (honest, compound) type is held back until the
  // building-blocks rung. First match wins, so the list is ordered by which
  // mechanism dominates a compound type. Every part in TYPE_PARTS (validator)
  // must be claimed by exactly one family here. See STYLE.md.
  const FAMILIES = [
    { label: "Definitions only",
      blurb: "No letter mechanics at all — the clue works by definition alone. The work is spotting which words are doing the defining.",
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
      match: (t) => t.includes("container") || t.includes("reversal") || t.includes("deletion") || t.includes("substitution") },
    { label: "Extraction",
      blurb: "The answer's letters are already sitting in the clue in order — the job is working out which ones to pick out.",
      match: (t) => t.includes("hidden") || t.includes("letter") }
  ];

  function familyOf(type) {
    const t = (type || "").toLowerCase();
    return FAMILIES.find((f) => f.match(t)) ||
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
      "Substitution is clued by exchange words: for, replacing, instead of, in place of, takes over from."]
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
    return steps.every((s) => (RUNG_TIER[s.key] || 0) >= tier || isShown(e, s.key));
  }

  function showHint(e, rung) {
    if (isShown(e, rung)) return;
    shownRungs(e).push(rung);
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

  function ladderSteps(ann, clue) {
    if (!ann) return [];
    const t = (ann.type || "").toLowerCase();
    const isDD = t.includes("double definition");
    const isCD = t.includes("cryptic definition");
    const isLit = t.includes("&lit");
    const inds = ann.indicators || [];
    const blocks = ann.blocks || [];
    const steps = [];

    const fam = familyOf(ann.type);
    steps.push({
      key: "type",
      label: "What kind of clue is this?",
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
        label: "Where does the clue split?",
        html: `<p>It splits between <mark class="def">${esc(ann.definition)}</mark> and
          <mark class="def2">${esc(ann.definition2)}</mark> — two unrelated senses of the same
          word, which is where the surface reading misleads you.</p>`
      });
    } else if (isLit) {
      steps.push({
        key: "definition",
        label: "How can the whole clue be the definition?",
        html: `<p>Read <mark class="def">${esc(ann.definition)}</mark> straight through as a
          description of the answer, then read the very same words again as wordplay.</p>`
      });
    } else if (isCD) {
      steps.push({
        key: "definition",
        label: "What is the clue really describing?",
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
        label: "Where is the definition?",
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
      let html;
      if (ops.length === 1) {
        html = `<p>${marks} — ${inds.length > 1 ? "they tell" : "it tells"} you to
          ${ops[0][1]}.</p><p class="muted">${ops[0][2]}</p>`;
      } else if (ops.length > 1) {
        // A compound type has more than one operation and usually more than one
        // indicator, and nothing in the annotation maps word to job. Saying so is
        // the honest move, and pairing them up is exactly the work of this rung.
        html = `<p>${marks} — this clue does two things, and the indicators are
          what tell them apart:</p><ul>${ops.map(([, op]) => `<li>${op}</li>`).join("")}</ul>
          <p class="muted">Which word calls for which is the step to work out here.</p>`;
      } else {
        html = `<p>${marks} — ${inds.length > 1 ? "these tell" : "this tells"} you
          what to do with the rest of the wordplay.</p>`;
      }
      steps.push({
        key: "indicators",
        label: inds.length > 1 ? "Spot the indicator words" : "Spot the indicator word",
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
    if (blocks.length && blocks.some((b) => b.gives || b.note)) {
      const items = blocks.map((b) => {
        let s = "<li>";
        if (b.clueFragment) s += `“${esc(b.clueFragment)}”`;
        if (b.gives && !isCD) s += ` → <span class="gives">${esc(b.gives)}</span>`;
        if (b.note) s += ` <span class="muted">— ${esc(b.note)}</span>`;
        return s + "</li>";
      }).join("");
      steps.push({
        key: "blocks",
        label: isDD ? "What each half means"
             : isCD ? "Which words are doing the work?"
             : "The building blocks",
        html: (isDD || isCD ? "" : mechanics) + `<ul>${items}</ul>`
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
      label: "Full walkthrough",
      html: (steps.some((s) => s.key === "blocks") || isDD || isCD ? "" : mechanics) +
        `<p>${esc(ann.walkthrough)}</p>${fit}${note}<p>Answer: <span class="gives">${esc(ann.answer)}</span></p>`
    });
    return steps;
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
    $("hint-clue").innerHTML = clueLine;
    $("hint-pattern").innerHTML = patternHTML(e);

    const solved = isEntrySolved(e);
    const reveals = revealsUsed[key] || 0;
    const revealsNote = reveals ? ` · ${reveals} letter${reveals > 1 ? "s" : ""} revealed` : "";
    // The count the score charges, not the number of rungs currently on screen:
    // once solved you can open the rest for free, and the meter has to say the
    // same thing the scorebar does or one of them is lying.
    const charged = hintsCharged(e);
    $("hint-meter").innerHTML = solved
      ? ((charged || reveals)
          ? `Solved with ${charged} hint${charged === 1 ? "" : "s"}${revealsNote}`
          : "Solved with no hints — bravo!")
      // "used on this clue" — you are looking at the clue. Just the count.
      : (ann ? `Hints <strong>${level}</strong>/${ladderSteps(ann, e.clue).length}${revealsNote}`
             : revealsNote.replace(" · ", ""));

    const body = $("hint-body");
    const next = $("hint-next");
    const escape = $("hint-escape");
    body.innerHTML = ""; next.innerHTML = ""; escape.innerHTML = "";

    if (!ann) {
      body.innerHTML = `<div class="hint-step"><p class="muted">This puzzle hasn’t been hand-annotated yet
        (<span class="badge auto">auto hints</span>), so there’s no teaching ladder for this clue.
        You can still check your letters${canCheck() ? " and reveal below" : ""}.</p></div>`;
      if (canCheck() && !solved) {
        next.innerHTML = `<button id="hx-entry">Reveal answer</button>`;
        $("hx-entry").onclick = fillAnswer;
      }
    } else {
      // Revealed rungs always read in ladder order and keep their ladder
      // number, whatever order they were asked for in. The numbering is the
      // teaching sequence, not a click log — a solver who took 4 before 2 has
      // still met them as steps 2 and 4, and gaps in the numbers show what
      // they skipped.
      const steps = ladderSteps(ann, e.clue);
      steps.forEach((s, i) => {
        if (isShown(e, s.key)) body.innerHTML += hintStepHTML(s, i + 1);
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
        body.innerHTML += `<div class="legend">${legend.join(" · ")} highlighted in the clue above</div>`;
      }

      // Every unlocked rung is offered at once, not just the next one: wanting
      // the indicators shouldn't mean being handed the definition on the way,
      // since working out where the definition sits is most of the skill. The
      // recommended one still leads and still says "hint N", so the taught path
      // costs one obvious click and a sideways move costs one deliberate one.
      // Rungs from a later tier are shown but disabled rather than hidden — the
      // ladder has a shape and the solver should be able to see it coming.
      const togo = steps.map((s, i) => ({ s, n: i + 1 })).filter(({ s }) => !isShown(e, s.key));
      const open = togo.filter(({ s }) => rungAvailable(e, steps, s.key));
      open.forEach(({ s, n }, j) => {
        const btn = document.createElement("button");
        if (j > 0) btn.className = "ghost small";
        // No "Show hint 5" on a clue that is already in: the rungs stopped being
        // hints to spend the moment it was solved, and a price hintsCharged no
        // longer charges shouldn't be advertised.
        btn.textContent = (j === 0 && !solved) ? `Show hint ${n} · ${s.label}` : `${n} · ${s.label}`;
        btn.onclick = () => { showHint(e, s.key); refreshAll(); };
        next.appendChild(btn);
      });
      togo.filter(({ s }) => !rungAvailable(e, steps, s.key)).forEach(({ s, n }) => {
        const btn = document.createElement("button");
        btn.className = "ghost small locked";
        btn.disabled = true;
        btn.textContent = `${n} · ${s.label}`;
        btn.title = "Take the hints above first — this one gives them away";
        next.appendChild(btn);
      });
      if (!togo.length && canCheck() && !solved) {
        next.innerHTML = `<button id="hx-entry">${FILL_LABEL}</button>`;
        $("hx-entry").onclick = fillAnswer;
      }
    }

    // The escape hatch lives outside the ladder: available at any level.
    if (canCheck() && !solved) {
      // No "(counts against your score)" rider. The scorebar already reports
      // revealed letters, so the warning was redundant, and a learner who is
      // stuck should be nudged toward the help rather than taxed for taking it.
      escape.innerHTML = `<button id="hx-letter" class="ghost small">Stuck? Reveal one letter</button>`;
      $("hx-letter").onclick = revealLetter;
    }
  }

  // ---------- score ----------
  // What this clue costs. Frozen at the moment it was solved: rungs opened after
  // that are a solver studying a clue they already got, and charging for the
  // lesson would make the unlock in rungAvailable a trap. The group's cost is the
  // count when its LAST leg went in, and rungs only ever accumulate, so that is
  // the largest of the legs' snapshots.
  function hintsCharged(e) {
    if (!groupSolved(e)) return shownRungs(e).length;
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
  // Guardian daily is the norm here and gets no badge; everything else says what
  // it is, either because it is gentler — the thing a struggling solver most
  // wants to find in this list — or because it is a different paper with a
  // different house style. A table rather than a chain of ifs, so a new series
  // is one entry; an unlisted one simply goes unbadged, same as the cryptic.
  //
  // This text is prose for a human choosing what to attempt next, which is why
  // it lives here and not in tools/series.py with the machine-readable facts.
  const SERIES_BADGE = {
    quiptic: `Guardian Quiptic — their beginner crossword, published Mondays.
      Same clue types as the daily cryptic, but gentler: plainer definitions and
      fewer buried indicators.`,
    everyman: `Everyman — the Observer's Sunday cryptic. The gentlest of the
      broadsheet puzzles and scrupulously fair: definitions sit at one end, and
      the wordplay always spells the answer out if you can hear it.`,
    independent: `The Independent's daily cryptic, Monday to Saturday. About as
      hard as the Guardian, with a regular cast of setters — Phi, Quince, Eccles,
      Hippogryph — so their habits are worth learning if you like one of them.`,
  };

  function seriesBadge(p) {
    const why = SERIES_BADGE[p.series || "cryptic"];
    if (!why) return "";
    return `<span class="badge series" title="${why}">${p.series}</span>`;
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
  // Hidden is not gone. A query searches EVERY puzzle, annotated or not, so
  // typing a number you know still finds it; the archive page lists them all;
  // and ?p=<n> opens any of them. Two rows are also never hidden, both the same
  // rule — don't hide the user's own work: the puzzle currently open (so the
  // highlighted row can't vanish out from under them) and any puzzle they have
  // letters saved against.
  function pickerProgress(p) {
    const prog = store.get("ct:" + p.id, null);
    return prog && prog.letters ? Object.keys(prog.letters).length : 0;
  }
  // "Have I finished this one?" — the question a list of 78 puzzles has to
  // answer before it can answer anything else. It is computed here rather than
  // stored: every puzzle file is already in memory (loadPuzzleScripts pulls the
  // lot at startup), so the saved letters can simply be held against the
  // solutions. A stored `done` flag would be a second copy of a fact the data
  // already knows, and sync/merge.js would then have to have an opinion about
  // merging it — see make-the-wrong-version-unwritable.
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
    return [p.number, String(p.number).replace(/(\d)(\d{3})$/, "$1,$2"), p.setter, d, dd.day,
      p.series || "cryptic", p.difficulty ? p.difficulty.band : "",
      st.done ? "solved done" : st.filled ? "started unfinished" : ""].join(" ").toLowerCase();
  }
  function pickerRows(q) {
    // Every term has to match somewhere, so "imogen 2026" narrows rather than
    // widens — the useful behaviour when the list is long enough to need a
    // filter at all.
    const terms = q.split(/\s+/).filter(Boolean);
    return INDEX.puzzles.filter((p) => {
      if (terms.length) {
        const hay = pickerHaystack(p);
        return terms.every((t) => hay.includes(t));
      }
      return p.annotated || (P && p.id === P.id) || pickerProgress(p) > 0;
    });
  }

  function renderPicker() {
    const ul = $("picker-list");
    ul.innerHTML = "";
    const q = (($("picker-search") || {}).value || "").trim().toLowerCase();
    const rows = pickerRows(q);
    const hidden = INDEX.puzzles.length - rows.length;
    $("picker-more").innerHTML = !hidden ? "" : q
      ? `${hidden} other puzzle${hidden > 1 ? "s" : ""} don’t match.`
      : `${hidden} more without hand-written hints — search by number, or `
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
      if (box && box.focus) box.focus();
    }
  }

  // ---------- puzzle lifecycle ----------
  function openPuzzle(id) {
    const puzzle = window.CRYPTIC_PUZZLES[id];
    if (!puzzle) return;
    P = puzzle;
    meta = INDEX.puzzles.find((p) => p.id === id) || { annotated: false };
    store.set("ct:last", id);
    buildModel();
    hintsShown = {}; hintLevels = {}; revealsUsed = {}; solvedWith = {}; timing = {};
    restoreState();
    const first = entries[0];
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

  function refreshAll() {
    refreshGrid();
    refreshClues();
    renderHintPanel();
    renderScore();
  }

  // ---------- boot ----------

  // ?p=30054 is one app URL among thousands, and it shipped declaring the
  // homepage as its canonical — so Google folded every share and every link to
  // a specific puzzle into the site root, and Search Console listed the puzzle
  // as "alternate page with proper canonical tag" (2026-08-07). The page that
  // deserves that credit is the write-up at /puzzles/30054/, which says the same
  // things without needing JavaScript. Point at it, but only when it exists:
  // an unannotated puzzle has no static page, and the homepage is then honest.
  function pointCanonicalAtStaticPage(asked) {
    const link = document.querySelector('link[rel="canonical"]');
    if (!link || !asked) return;
    const p = INDEX.puzzles.find((q) => q.id === asked);
    if (!p || !p.hasSolutions) return;
    link.href = new URL(`puzzles/${p.number}/`, link.href).href;
  }

  function boot() {
    $("tutorial").innerHTML = window.TUTORIAL_HTML || "<p>Tutorial unavailable.</p>";
    $("btn-tutorial").onclick = () => {
      const t = $("tutorial");
      t.classList.toggle("hidden");
      if (!t.classList.contains("hidden")) t.scrollIntoView({ behavior: "smooth" });
    };
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
      store.set(stateKey(), { letters: {}, letterAt: {}, hintsShown: {}, revealsUsed: {},
                              solvedWith: {}, timing: {}, clearedAt: now, updated: now });
      forEachCell((c) => { c.letter = ""; c.wrong = false; c.revealed = false; });
      hintsShown = {}; hintLevels = {}; revealsUsed = {}; solvedWith = {}; timing = {};
      refreshAll();
      syncPushSoon();
    };

    document.addEventListener("keydown", (ev) => {
      if (ev.target && (ev.target.tagName === "INPUT" && ev.target.id !== "kbd" || ev.target.tagName === "TEXTAREA")) return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      onKey(ev);
    });
    // mobile soft keyboards often only fire `input`
    $("kbd").addEventListener("input", (ev) => {
      const v = letterOf(ev.target.value);
      if (v) typeLetter(v[v.length - 1]);
      ev.target.value = "";
    });
    // Every control that moves the cursor must also raise the soft keyboard, and
    // it has to do it on mousedown. iOS only opens the keyboard for a focus()
    // that happens inside the gesture, and the pattern strip re-renders itself on
    // the way through — by the time focus() ran, the button that was tapped had
    // been thrown away with the rest of the strip's innerHTML, and the tap had
    // nothing left to belong to, so tapping a box moved the cursor and then left
    // you with no keyboard (Paul, iPad, 2026-08-09). The grid had always done it
    // this way and worked; the strip had not. Listed together so a third way to
    // steer cannot be added without it.
    ["grid", "hint-pattern"].forEach((id) =>
      $(id).addEventListener("mousedown", () => focusKbd()));

    // The letter-pattern strip is a second way to steer: click a box to put the
    // cursor on that square of the current entry.
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
    loadPuzzleScripts(() => {
      // ?p=30072 wins over the remembered puzzle: the static answer pages under
      // /puzzles/<n>/ link in that way, and dropping someone on last night's
      // puzzle instead of the one they clicked would be baffling.
      const asked = new URLSearchParams(location.search).get("p");
      pointCanonicalAtStaticPage(asked);
      const last = store.get("ct:last", null);
      const firstAnnotated = (INDEX.puzzles.find((p) => p.annotated) || INDEX.puzzles[0]).id;
      const want = (asked && window.CRYPTIC_PUZZLES[asked]) ? asked
        : (last && window.CRYPTIC_PUZZLES[last]) ? last : firstAnnotated;
      openPuzzle(want);
      // After the grid is up, not before: the pull is a network round trip and
      // the solver should be looking at yesterday's letters while it happens,
      // not a blank page. If it brings anything new, applyEnvelope redraws.
      if (syncOn()) syncPull();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
