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
      const letters = {};
      forEachCell((c) => { if (c.letter) letters[c.x + "," + c.y] = c.letter + (c.revealed ? "!" : ""); });
      store.set(stateKey(), { letters, hintsShown, revealsUsed, solvedWith });
    }, 150);
  }
  function restoreState() {
    const s = store.get(stateKey(), null);
    hintsShown = (s && s.hintsShown) || {};
    hintLevels = (s && s.hintLevels) || {};
    revealsUsed = (s && s.revealsUsed) || {};
    solvedWith = (s && s.solvedWith) || {};
    if (s && s.letters) {
      forEachCell((c) => {
        const v = s.letters[c.x + "," + c.y];
        if (v) { c.letter = v[0]; c.revealed = v.length > 1; }
      });
    }
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
        li.innerHTML = `<span class="clue-num">${e.number}</span><span class="clue-text"></span>`;
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
  function clueHTML(e) {
    const ann = annOf(e);
    if (!ann) return esc(e.clue);
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
    if (!marks.length) return esc(e.clue);
    marks.sort((a, b) => a.i - b.i);
    // drop overlaps
    const keep = [];
    let end = -1;
    marks.forEach((m) => { if (m.i >= end) { keep.push(m); end = m.i + m.len; } });
    let out = "", pos = 0;
    keep.forEach((m) => {
      out += esc(e.clue.slice(pos, m.i));
      out += `<mark class="${m.cls}">` + esc(e.clue.slice(m.i, m.i + m.len)) + "</mark>";
      pos = m.i + m.len;
    });
    out += esc(e.clue.slice(pos));
    return out;
  }

  function refreshClues() {
    const curE = currentEntry();
    entries.forEach((e) => {
      const li = $("clue-" + e.id);
      if (!li) return;
      const holder = (e.annotation && e.annotation.linkedTo) ? byId[e.annotation.linkedTo] : e;
      li.querySelector(".clue-text").innerHTML = (holder === e) ? clueHTML(e) : esc(e.clue);
      li.classList.toggle("active", !!curE && entryKey(curE) === entryKey(e));
      li.classList.toggle("solved", isEntrySolved(e));
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
  function scrollToHintPanel() {
    const p = $("hint-panel");
    if (p && !p.classList.contains("hidden") && p.scrollIntoView) {
      p.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
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
    ["spoonerism", "A spoonerism: swap the opening sounds of two words to get the answer."]
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
      match: (t) => t.includes("anagram") },
    { label: "Sound",
      blurb: "The wordplay describes how the answer sounds rather than how it is spelled.",
      match: (t) => t.includes("homophone") || t.includes("spoonerism") },
    { label: "Charade",
      blurb: "The answer is built from pieces laid end to end, each clued separately — read the wordplay left to right.",
      match: (t) => t.includes("charade") },
    { label: "Alteration",
      blurb: "A piece of the wordplay is changed rather than just joined on: put inside something, turned around, or trimmed.",
      match: (t) => t.includes("container") || t.includes("reversal") || t.includes("deletion") },
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
        ? ladderSteps(annOf(e)).slice(0, old).map((s) => s.key).concat(
            old > ladderSteps(annOf(e)).length ? [ANSWER_RUNG] : [])
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
    const tier = RUNG_TIER[key] || 0;
    return steps.every((s) => (RUNG_TIER[s.key] || 0) >= tier || isShown(e, s.key));
  }

  function showHint(e, rung) {
    if (isShown(e, rung)) return;
    shownRungs(e).push(rung);
    saveState();
  }

  // Build the rungs this particular clue deserves. Each rung: {key, label, html}.
  function ladderSteps(ann) {
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
      steps.push({
        key: "definition",
        label: "Where is the definition?",
        html: `<p>The definition is <mark class="def">${esc(ann.definition)}</mark>. Everything
          else is wordplay — in a fair cryptic the definition always sits at one end of the clue.</p>`
      });
    }

    // Two footnotes hang off the definition rung, both of them things a learner
    // would otherwise be left puzzling over. `definitionNote` explains a
    // definition that deliberately does NOT agree with the answer ("Lousy
    // payment" = PEANUTS); `linkWords` names the connective words that carry no
    // wordplay at all, which is the commonest reason a beginner keeps hunting
    // for a mechanism that was never there.
    const defStep = steps[steps.length - 1];
    if (ann.definitionNote) {
      defStep.html += `<p class="def-note">${esc(ann.definitionNote)}</p>`;
    }
    if ((ann.linkWords || []).length) {
      const lw = ann.linkWords.map((w) => `<mark class="link">${esc(w)}</mark>`).join(", ");
      defStep.html += `<p class="muted">${lw} ${ann.linkWords.length > 1 ? "are" : "is"}
        just a link — words that join the definition to the wordplay and contribute
        no letters of their own.</p>`;
    }

    // Indicators only exist for some clue types — no rung that says "none".
    if (inds.length) {
      steps.push({
        key: "indicators",
        label: inds.length > 1 ? "Spot the indicator words" : "Spot the indicator word",
        html: `<p>${inds.map((i) => `<mark class="ind">${esc(i)}</mark>`).join(", ")} —
          ${inds.length > 1 ? "these tell you" : "this tells you"} what to do with the rest.</p>`
      });
    }

    if (blocks.length && blocks.some((b) => b.gives || b.note)) {
      const items = blocks.map((b) => {
        let s = "<li>";
        if (b.clueFragment) s += `“${esc(b.clueFragment)}”`;
        if (b.gives) s += ` → <span class="gives">${esc(b.gives)}</span>`;
        if (b.note) s += ` <span class="muted">— ${esc(b.note)}</span>`;
        return s + "</li>";
      }).join("");
      steps.push({
        key: "blocks",
        label: isDD ? "What each half means" : "The building blocks",
        html: (isDD || isCD ? "" : mechanics) + `<ul>${items}</ul>`
      });
    }

    steps.push({
      key: "walkthrough",
      label: "Full walkthrough",
      html: (steps.some((s) => s.key === "blocks") || isDD || isCD ? "" : mechanics) +
        `<p>${esc(ann.walkthrough)}</p><p>Answer: <span class="gives">${esc(ann.answer)}</span></p>`
    });
    return steps;
  }

  function hintStepHTML(step, position) {
    return `<div class="hint-step"><span class="step-label">${position} · ${esc(step.label)}</span>${step.html}</div>`;
  }

  // The selected entry's live letter pattern: what's already in the grid, blanks
  // for what isn't, and which squares are CHECKED (shared with a crossing entry,
  // so another clue can confirm them). Unchecked squares are the hard ones —
  // nothing will ever cross them, so they have to come out of the wordplay.
  function patternHTML(e) {
    const cs = entryCells(e);
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
    }).join("");
    const unchecked = cs.length - checked;
    const note = `${filled} of ${cs.length} letter${cs.length > 1 ? "s" : ""} in place · `
      + (unchecked ? `${checked} checked, ${unchecked} unchecked (dashed — no crossing clue)`
                   : `all ${checked} checked`);
    return `<span class="pat-boxes" role="img" aria-label="${esc(note)}">${boxes}</span>`
      + `<span class="pat-note muted">${esc(note)}</span>`;
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
    $("hint-meter").innerHTML = solved
      ? ((solvedWith[e.id] || reveals)
          ? `Solved with ${solvedWith[e.id] || 0} hint${solvedWith[e.id] === 1 ? "" : "s"}${revealsNote}`
          : "Solved with no hints — bravo!")
      : (ann ? `Hints: <strong>${level}</strong>/${ladderSteps(ann).length} used on this clue${revealsNote}`
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
      const steps = ladderSteps(ann);
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
        btn.textContent = j === 0 ? `Show hint ${n} · ${s.label}` : `${n} · ${s.label}`;
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
      escape.innerHTML = `<button id="hx-letter" class="ghost small">Stuck? Reveal one letter</button>
        <span class="muted">(counts against your score)</span>`;
      $("hx-letter").onclick = revealLetter;
    }
  }

  // ---------- score ----------
  function renderScore() {
    const total = entries.filter((e) => !(e.annotation && e.annotation.linkedTo)).length;
    let solved = 0, noHints = 0, levelsUsed = 0, lettersRevealed = 0;
    const counted = {};
    entries.forEach((e) => {
      const key = entryKey(e);
      if (counted[key]) return;
      counted[key] = true;
      const rungs = shownRungs(e).length;
      const group = entries.filter((g) => entryKey(g) === key);
      if (group.every(isEntrySolved) && group.length) {
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
      d.band + pct + ". Judged on " + basis + ", relative to other Guardian cryptics."
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
  function pickerHaystack(p) {
    const d = p.date ? new Date(p.date).toISOString().slice(0, 10) : "";
    // Both spellings of the number: the site writes "No 30,074" everywhere, and
    // a solver copying that in shouldn't get nothing back.
    return [p.number, String(p.number).replace(/(\d)(\d{3})$/, "$1,$2"), p.setter, d,
      p.difficulty ? p.difficulty.band : ""].join(" ").toLowerCase();
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
      const filled = pickerProgress(p);
      const d = p.date ? new Date(p.date).toISOString().slice(0, 10) : "";
      const btn = document.createElement("button");
      // Order here is the grid's, not the eye's: the badges are markup-last but
      // render on their own second line (see .p-tags in style.css). Progress
      // sits with them because it is a status like they are, and because
      // gluing it onto the date made the one nowrap element in the row long
      // enough to shove everything else off the line.
      btn.innerHTML = `<span class="p-num">№ ${p.number}</span>
        <span class="p-setter">${esc(p.setter)}</span>
        <span class="p-meta">${d}</span>
        <span class="p-tags">${difficultyBadge(p)}${hintsBadge(p.annotated)}
          ${filled ? `<span class="p-prog">${filled} letters in</span>` : ""}</span>`;
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
    hintsShown = {}; hintLevels = {}; revealsUsed = {}; solvedWith = {};
    restoreState();
    const first = entries[0];
    cur = { x: first.position.x, y: first.position.y, dir: first.direction };
    $("app").classList.remove("hidden");
    $("puzzle-title").innerHTML =
      `${esc(P.name)} — set by <em>${esc(P.setter)}</em>` +
      (meta.annotated ? "" : " " + hintsBadge(false));
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
  function boot() {
    $("tutorial").innerHTML = window.TUTORIAL_HTML || "<p>Tutorial unavailable.</p>";
    $("btn-tutorial").onclick = () => {
      const t = $("tutorial");
      t.classList.toggle("hidden");
      if (!t.classList.contains("hidden")) t.scrollIntoView({ behavior: "smooth" });
    };
    $("btn-picker").onclick = () => togglePicker();
    $("btn-picker-close").onclick = () => togglePicker(false);
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
      store.del(stateKey());
      forEachCell((c) => { c.letter = ""; c.wrong = false; c.revealed = false; });
      hintsShown = {}; hintLevels = {}; revealsUsed = {}; solvedWith = {};
      refreshAll();
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
    $("grid").addEventListener("mousedown", () => focusKbd());

    // The letter-pattern strip is a second way to steer: click a box to put the
    // cursor on that square of the current entry.
    $("hint-pattern").addEventListener("click", (ev) => {
      const box = ev.target && ev.target.dataset ? ev.target : null;
      const idx = box ? Number(box.dataset.i) : NaN;
      const e = currentEntry();
      if (!e || !Number.isInteger(idx)) return;
      const c = cellAt(e, Math.max(0, Math.min(e.length - 1, idx)));
      cur.x = c.x; cur.y = c.y;
      refreshAll(); focusKbd();
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
      const last = store.get("ct:last", null);
      const firstAnnotated = (INDEX.puzzles.find((p) => p.annotated) || INDEX.puzzles[0]).id;
      const want = (asked && window.CRYPTIC_PUZZLES[asked]) ? asked
        : (last && window.CRYPTIC_PUZZLES[last]) ? last : firstAnnotated;
      openPuzzle(want);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
