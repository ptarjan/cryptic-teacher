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
  let hintLevels = {};   // entryKey -> highest hint level revealed (0..6)
  let revealsUsed = {};  // entryKey -> number of letters revealed (escape hatch)
  let solvedWith = {};   // entryKey -> hint level in force when first solved
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
      store.set(stateKey(), { letters, hintLevels, revealsUsed, solvedWith });
    }, 150);
  }
  function restoreState() {
    const s = store.get(stateKey(), null);
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

  function clueHTML(e, level) {
    const ann = annOf(e);
    let html = esc(e.clue);
    const shown = (key) => stepShown(ann, key, level);
    if (ann && shown("definition")) {
      const marks = [];
      const push = (text, cls) => {
        if (!text) return;
        const i = e.clue.indexOf(text);
        if (i >= 0) marks.push({ i, len: text.length, cls });
      };
      push(ann.definition, "def");
      push(ann.definition2, "def2");
      if (shown("indicators")) (ann.indicators || []).forEach((ind) => push(ind, "ind"));
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
      html = out;
    }
    return html;
  }

  function refreshClues() {
    const curE = currentEntry();
    entries.forEach((e) => {
      const li = $("clue-" + e.id);
      if (!li) return;
      const holder = (e.annotation && e.annotation.linkedTo) ? byId[e.annotation.linkedTo] : e;
      const level = hintLevels[entryKey(e)] || 0;
      li.querySelector(".clue-text").innerHTML = (holder === e) ? clueHTML(e, level) : esc(e.clue);
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

  function onCellClick(c) {
    if (cur.x === c.x && cur.y === c.y) {
      const other = cur.dir === "across" ? "down" : "across";
      if (c[other]) cur.dir = other;
    } else {
      cur.x = c.x; cur.y = c.y;
      if (!c[cur.dir]) cur.dir = c.across ? "across" : "down";
    }
    focusKbd();
    refreshAll();
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
    moveInEntry(1);
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

  function checkCells(list) {
    if (!canCheck()) return;
    list.forEach((c) => { if (c.letter && c.letter !== c.sol) c.wrong = true; });
    refreshAll(); saveState();
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
    bumpHint(e, ladderSteps(annOf(e)).length + 1);
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
      const key = entryKey(e);
      if (isEntrySolved(e) && solvedWith[e.id] === undefined) {
        solvedWith[e.id] = hintLevels[key] || 0;
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
    ["outer letters", "Outer letters: keep only the outside letters of an indicated word."]
  ];

  function typeBlurb(type) {
    const t = (type || "").toLowerCase();
    const hits = TYPE_BLURBS.filter(([k]) => t.includes(k)).map(([, v]) => v);
    return hits.join(" ") || "";
  }

  function bumpHint(e, level) {
    const key = entryKey(e);
    if ((hintLevels[key] || 0) < level) { hintLevels[key] = level; saveState(); }
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

    steps.push({
      key: "type",
      label: "What kind of clue is this?",
      html: `<p><strong>${esc(ann.type)}</strong>. ${esc(typeBlurb(ann.type))}</p>`
    });

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
        html: `<ul>${items}</ul>`
      });
    }

    steps.push({
      key: "walkthrough",
      label: "Full walkthrough",
      html: `<p>${esc(ann.walkthrough)}</p><p>Answer: <span class="gives">${esc(ann.answer)}</span></p>`
    });
    return steps;
  }

  // Has the rung named `key` been revealed at this hint level?
  function stepShown(ann, key, level) {
    const i = ladderSteps(ann).findIndex((s) => s.key === key);
    return i >= 0 && level >= i + 1;
  }

  function hintStepHTML(step, position) {
    return `<div class="hint-step"><span class="step-label">${position} · ${esc(step.label)}</span>${step.html}</div>`;
  }

  function renderHintPanel() {
    const e = currentEntry();
    const panel = $("hint-panel");
    if (!e) { panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden");

    const holder = (e.annotation && e.annotation.linkedTo) ? byId[e.annotation.linkedTo] : e;
    const ann = annOf(e);
    const key = entryKey(e);
    const level = hintLevels[key] || 0;

    let clueLine = `<span class="entry-tag">${tag(e)}</span>`;
    if (holder !== e) clueLine += `<span class="muted">(linked with ${tag(holder)}) </span>`;
    clueLine += clueHTML(holder, level);
    $("hint-clue").innerHTML = clueLine;

    const solved = isEntrySolved(e);
    const reveals = revealsUsed[key] || 0;
    const revealsNote = reveals ? ` · ${reveals} letter${reveals > 1 ? "s" : ""} revealed` : "";
    $("hint-meter").innerHTML = solved
      ? ((solvedWith[e.id] || reveals)
          ? `Solved after hint level ${solvedWith[e.id] || 0}${revealsNote}`
          : "Solved with no hints — bravo!")
      : (ann ? `Hint ladder: <strong>${level}</strong>/${ladderSteps(ann).length} used on this clue${revealsNote}`
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
      const steps = ladderSteps(ann);
      steps.slice(0, level).forEach((s, i) => { body.innerHTML += hintStepHTML(s, i + 1); });
      if (stepShown(ann, "definition", level)) {
        body.innerHTML += `<div class="legend"><mark class="def">definition</mark>${
          stepShown(ann, "indicators", level) ? ' · <mark class="ind">indicator</mark>' : ""
        } highlighted in the clue above</div>`;
      }

      if (level < steps.length) {
        const btn = document.createElement("button");
        btn.textContent = `Show hint ${level + 1} · ${steps[level].label}`;
        btn.onclick = () => { bumpHint(e, level + 1); refreshAll(); };
        next.appendChild(btn);
      } else if (canCheck() && !solved) {
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
      const group = entries.filter((g) => entryKey(g) === key);
      if (group.every(isEntrySolved) && group.length) {
        solved++;
        if (!(hintLevels[key] > 0) && !(revealsUsed[key] > 0)) noHints++;
      }
      levelsUsed += hintLevels[key] || 0;
      lettersRevealed += revealsUsed[key] || 0;
    });
    $("scorebar").innerHTML =
      `Solved <strong>${solved}/${total}</strong> clues · <strong>${noHints}</strong> with no hints · <strong>${levelsUsed}</strong> hint levels used`
      + (lettersRevealed ? ` · <strong>${lettersRevealed}</strong> letter${lettersRevealed > 1 ? "s" : ""} revealed` : "");
  }

  // ---------- picker ----------
  function renderPicker() {
    const ul = $("picker-list");
    ul.innerHTML = "";
    INDEX.puzzles.forEach((p) => {
      const li = document.createElement("li");
      if (P && p.id === P.id) li.className = "current";
      const prog = store.get("ct:" + p.id, null);
      const filled = prog && prog.letters ? Object.keys(prog.letters).length : 0;
      const d = p.date ? new Date(p.date).toISOString().slice(0, 10) : "";
      const btn = document.createElement("button");
      btn.innerHTML = `<span class="p-num">№ ${p.number}</span>
        <span>${esc(p.setter)}</span>
        <span class="badge ${p.annotated ? "full" : "auto"}">${p.annotated ? "full hints" : "auto hints"}</span>
        <span class="p-meta">${d}${filled ? " · " + filled + " letters in" : ""}</span>`;
      btn.onclick = () => { openPuzzle(p.id); togglePicker(false); };
      li.appendChild(btn);
      ul.appendChild(li);
    });
  }
  function togglePicker(show) {
    const el = $("picker-panel");
    const want = (show === undefined) ? el.classList.contains("hidden") : show;
    el.classList.toggle("hidden", !want);
    if (want) renderPicker();
  }

  // ---------- puzzle lifecycle ----------
  function openPuzzle(id) {
    const puzzle = window.CRYPTIC_PUZZLES[id];
    if (!puzzle) return;
    P = puzzle;
    meta = INDEX.puzzles.find((p) => p.id === id) || { annotated: false };
    store.set("ct:last", id);
    buildModel();
    hintLevels = {}; revealsUsed = {}; solvedWith = {};
    restoreState();
    const first = entries[0];
    cur = { x: first.position.x, y: first.position.y, dir: first.direction };
    $("app").classList.remove("hidden");
    $("puzzle-title").innerHTML =
      `${esc(P.name)} — set by <em>${esc(P.setter)}</em> ` +
      `<span class="badge ${meta.annotated ? "full" : "auto"}">${meta.annotated ? "full hints" : "auto hints"}</span>`;
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

    $("chk-letter").onclick = () => { const c = cells[cur.y][cur.x]; if (c) checkCells([c]); };
    $("chk-entry").onclick = () => { const e = currentEntry(); if (e) checkCells(entryCells(e)); };
    $("chk-grid").onclick = () => { const all = []; forEachCell((c) => all.push(c)); checkCells(all); };
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
      hintLevels = {}; revealsUsed = {}; solvedWith = {};
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

    if (!INDEX.puzzles.length) {
      $("puzzle-title").textContent = "No puzzles found — run tools/fetch_puzzle.py first.";
      $("app").classList.remove("hidden");
      return;
    }
    loadPuzzleScripts(() => {
      const last = store.get("ct:last", null);
      const firstAnnotated = (INDEX.puzzles.find((p) => p.annotated) || INDEX.puzzles[0]).id;
      const want = (last && window.CRYPTIC_PUZZLES[last]) ? last : firstAnnotated;
      openPuzzle(want);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
