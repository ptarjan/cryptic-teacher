"use strict"; // app part 4 of 7 (anagram ring, walkthrough, naming words, dragging). Classic script sharing the page scope with its siblings; see tools/app_src.js.
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
  // `ring` is whichever ring was drawn last, which is what the tile, keyboard
  // and chip handlers act on. The paid ring and the free wheel each keep their
  // own state here as well, because one render can build both: the blocks
  // rung's markup is assembled whether or not it ends up on screen, and if the
  // two shared one slot that build would replace the free wheel's letters with
  // the dealt fodder, and the free wheel would then start over empty.
  const ringShelf = { paid: null, free: null };
  // The entryKey of the clue whose free wheel is open, or null. Free means the
  // wheel is offered on EVERY clue and costs nothing: a button on anagrams only
  // would give the clue type away, and the blocks rung above is what charges.
  let freeWheel = null;

  // Deal an order that is neither the fodder as written nor the answer as
  // spelled. Landing on either would make a shuffle look broken, and landing on
  // the answer would hand over the solve by luck a rung early.
  //
  // `from` and `spots` are how a re-shuffle keeps the settled letters where they
  // are: only the ring POSITIONS in `spots` trade places, everything else is
  // carried through untouched. Omit both and it deals the whole ring, which is
  // the opening deal.
  function dealRing(letters, forbidden, from, spots) {
    const bad = forbidden.map((w) => (w || "").toUpperCase().replace(/[^A-Z]/g, ""));
    const base = from || letters.map((_, i) => i);
    const free = spots || base.map((_, pos) => pos);
    let order = base;
    for (let attempt = 0; attempt < 20; attempt++) {
      order = base.slice();
      for (let i = free.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        const a = free[i], b = free[j];
        [order[a], order[b]] = [order[b], order[a]];
      }
      if (bad.indexOf(order.map((i) => letters[i]).join("")) < 0) return order;
    }
    return order;  // repeated letters can make every deal a forbidden one
  }

  // True once the hidden #ana-kbd input has real DOM focus — read straight off
  // document.activeElement rather than tracked in a variable, because #ana-kbd
  // lives outside the hint panel (see its wiring below) and so survives every
  // redraw the ring itself goes through; activeElement is therefore always the
  // live answer, even the instant after a keystroke has just rebuilt the disc.
  function ringKbdFocused() {
    return !!(document.activeElement && document.activeElement.id === "ana-kbd");
  }

  // Keyed off the annotation rather than the clue id: ladderSteps() is a pure
  // function of the annotation and is called for counting as well as drawing,
  // and threading a grid coordinate through it to remember a shuffle would put
  // board state into the thing that describes a clue.
  function ringKey(ann) {
    return (ann.answer || "") + "|" + ringFodder(ann);
  }

  // The anagram the ring deals: the one whose gives is the whole answer, else
  // the longest one. A part-anagram is still the step a solver gets stuck
  // rearranging (CHOMPED is CHO(MP)ED, and the work is turning COD HE into
  // CHOED), so a clue typed anagram gets a ring whichever piece the shuffle
  // makes. ringPins compares letter sets, so only a whole-answer fodder pins.
  const bareLetters = (s) => String(s || "").toUpperCase().replace(/[^A-Z]/g, "");
  function ringAnagram(ann) {
    const want = bareLetters((ann || {}).answer);
    const all = (((ann || {}).assembly) || {}).anagrams || [];
    return all.find((a) => want && bareLetters(a.gives) === want) ||
      all.reduce((best, a) => (!best || bareLetters(a.fodder).length >
        bareLetters(best.fodder).length ? a : best), null);
  }

  function ringFodder(ann) {
    const a = ringAnagram(ann);
    return bareLetters(a && a.fodder);
  }

  // The answer's words, one ring each. A ring reads clockwise from the top as
  // position 1 of the answer onwards, and that only says anything if you can see
  // where a word of it ends: "KNIGHTS ERRANT" drawn as one circle of thirteen
  // pins the K somewhere and tells you nothing further. Cut
  // into a seven and a six, the same pin says which word the letter is in and
  // where. A one-word answer has exactly one ring.
  const ringWords = (ann) =>
    String((ann || {}).answer || "").toUpperCase().split(/[^A-Z]+/).filter(Boolean);

  // A letter already in the grid is not part of the anagram any more: it has a
  // POSITION, and the ring is the one place that position can be shown. So it
  // pins its tile to the matching spot — the tile at the top is letter 1 of the
  // answer, and each step clockwise is the next letter — and every deal works
  // round the pins.
  //
  // Only when the fodder is the whole answer: an anagram of one piece of a
  // charade has no letter i of the answer to be pinned to, and comparing the
  // two letter sets is the cheapest way to tell those apart. It also switches
  // the pins off the moment the solver types into the ring, which is right —
  // an edited set of letters is no longer the one the grid is spelling.
  function ringPins(letters, key) {
    const pins = {};
    const e = currentEntry();
    // An altered entry's letter i is not its answer's letter i.
    if (!e || !e.solution || jigsaw || e.alteration) return pins;
    const ann = annOf(e);
    if (key.startsWith("free|") ? key !== "free|" + entryKey(e) : (!ann || ringKey(ann) !== key)) return pins;
    const sol =String(e.solution).toUpperCase().replace(/[^A-Z]/g, "");
    if (sol.split("").sort().join("") !== letters.slice().sort().join("")) return pins;
    const taken = {};
    entryCells(e).forEach((c, i) => {
      if (!c || !c.letter || c.wrong) return;
      for (let j = 0; j < letters.length; j++) {
        if (taken[j] || letters[j] !== c.letter) continue;
        taken[j] = true;
        pins[i] = j;
        return;
      }
    });
    return pins;
  }

  // Rebuild the draw order with each pinned letter at its own position and
  // everything else falling into what is left, in the order it was already in.
  // Placing a letter therefore slides one tile aside instead of re-dealing the
  // ring under the solver.
  function applyRingPins(order, pins) {
    const pinned = {};
    Object.keys(pins).forEach((p) => { pinned[pins[p]] = true; });
    const rest = order.filter((idx) => !pinned[idx]);
    return order.map((_, pos) => (pins[pos] === undefined ? rest.shift() : pins[pos]));
  }

  function ringHTML(ann) {
    // Paul 10-30: "An anagram for part of a clue shouldn't show the wheel the
    // building blocks. Only when it is all." The ring sits on the blocks rung,
    // so a part-anagram (CHO(MP)ED) leaves the rung to its pieces and gives no
    // wheel; the free wheel (freeRingHTML) is still there to open by hand.
    if (partAnagram(ann)) return "";
    const fodder = ringFodder(ann);
    const key = ringKey(ann);
    // Three letters have six arrangements and you can see all of them at once,
    // so a ring is furniture rather than help.
    if (fodder.length < 4) return "";
    if (!ringShelf.paid || ringShelf.paid.key !== key) {
      const letters = fodder.split("");
      const forbidden = [fodder, ann.answer, (ringAnagram(ann) || {}).gives];
      ringShelf.paid = { key, letters, forbidden, order: dealRing(letters, forbidden), struck: {} };
    }
    ring = ringShelf.paid;
    return ringDraw(ann, key);
  }

  // The free wheel: the same ring, opened empty on any clue. Nothing is dealt
  // because nothing is known — the solver types what they think the fodder is,
  // and `forbidden` is empty since there is no fodder or answer to steer a
  // shuffle away from. The key says "free" so ringPins knows there is no
  // annotation to compare against, only the clue it was opened on.
  function freeRingHTML(e, ann) {
    const key = "free|" + entryKey(e);
    if (!ringShelf.free || ringShelf.free.key !== key) ringShelf.free = { key, letters: [], forbidden: [], order: [], struck: {} };
    ring = ringShelf.free;
    return ringDraw(ann, key) + (ring.letters.length ? ""
      : `<p class="muted">Type the letters you think are the anagram.</p>`);
  }

  // The clue's own words, already on screen in #hint-clue, are the wheel's
  // picker (pickableClueHTML draws them as buttons while it is open): tap one
  // to add its letters to the ring, tap it again to take them out. A word in
  // the ring is drawn selected, keyed by its token index in the clue.

  // Add or remove a whole clue word. Removing drops that word's tiles and
  // renumbers the rest, since struck marks and the draw order are by position.
  function toggleRingWord(wi, word) {
    if (!ring) return;
    const prevRects = ringTileRects();
    ring.words = ring.words || {};
    if (ring.words[wi]) {
      const gone = new Set(ring.words[wi]);
      const remap = {};
      const letters = [];
      ring.letters.forEach((ch, idx) => { if (!gone.has(idx)) { remap[idx] = letters.length; letters.push(ch); } });
      ring.letters = letters;
      ring.order = ring.order.filter((idx) => !gone.has(idx)).map((idx) => remap[idx]);
      const struck = {};
      Object.keys(ring.struck).forEach((k) => { if (remap[k] !== undefined && ring.struck[k]) struck[remap[k]] = true; });
      ring.struck = struck;
      Object.keys(ring.words).forEach((k) => {
        ring.words[k] = k === String(wi) ? null : ring.words[k].map((idx) => remap[idx]);
      });
      delete ring.words[wi];
    } else {
      ring.words[wi] = word.split("").map((ch) => {
        const idx = ring.letters.length;
        ring.letters.push(ch);
        ring.order.push(idx);
        return idx;
      });
    }
    renderHintPanel();
    playRingFlip(prevRects);
  }

  function ringDraw(ann, key) {
    // Letters and order are read off `ring` from here on, not off the fresh
    // fodder split above: typing into the ring (addRingLetter/removeLastRingLetter)
    // edits `ring.letters` directly, and a re-render must draw what is there now,
    // not re-deal the clue's original fodder out from under an edit in progress.
    //
    // The pins are recomputed on EVERY render rather than kept on `ring`,
    // because the thing they are read off — the letters in the grid — changes
    // under the ring while it is open. Typing a crossing letter has to move its
    // tile to where it belongs without being told.
    ring.pins = ringPins(ring.letters, key);
    ring.order = applyRingPins(ring.order, ring.pins);
    // The deal is checked against the forbidden words BEFORE the pins move its
    // tiles, so a clean deal can still pin into one: with the M of MERIT already
    // in the grid, the other four letters fall in deal order behind it, and one
    // deal in 24 lands on MERIT itself. The check is therefore made again on what
    // is actually drawn, and a forbidden word re-deals only the positions still
    // in play, the way the shuffle button does.
    const spelled = ring.order.map((i) => ring.letters[i]).join("");
    const bad = ring.forbidden.map((w) => (w || "").toUpperCase().replace(/[^A-Z]/g, ""));
    if (bad.indexOf(spelled) >= 0) {
      const free = [];
      ring.order.forEach((idx, pos) => {
        if (!ring.struck[idx] && ring.pins[pos] === undefined) free.push(pos);
      });
      ring.order = dealRing(ring.letters, ring.forbidden, ring.order, free);
    }
    const pinnedTile = {};
    Object.keys(ring.pins).forEach((p) => { pinnedTile[ring.pins[p]] = true; });
    const n = ring.letters.length;
    // The ring grows with the fodder so the tiles never overlap; the disc is
    // sized off the same radius so the box is never taller than its contents.
    // What has to clear is the straight line between two neighbouring tiles,
    // not the arc through them: spacing the centres by arc length (n * pitch /
    // 2PI) leaves a chord of 2R*sin(PI/n), which is shorter than the tile at
    // every length and gets worse the more letters there are. Solving the chord
    // for the pitch instead is the right sum. Capped so a
    // very long fodder cannot push the disc wider than a phone.
    const PITCH = 42;
    // One ring per word of the answer, in order, as long as the words account
    // for exactly the letters in hand: typing into the ring makes a set that is
    // no longer the answer's, and a cut that does not add up would put a word
    // boundary at a letter that is not one.
    const lens = ringWords(ann).map((w) => w.length);
    const cuts = (lens.length > 1 && lens.reduce((a, b) => a + b, 0) === n) ? lens : [n];
    let from = 0;
    // ONE ring, with a gap in it where each word of the answer ends. Two rings
    // side by side would be two objects to compare — which is the four and which
    // the five would have to be counted rather than seen. A break in a single
    // circle is the same fact told once: the
    // letters are still one jumble, which is what an anagram is, and the shape
    // of the answer is drawn through them rather than beside them.
    //
    // A break costs one tile's worth of arc, so the circle is sized for the
    // letters plus the gaps and the pitch between neighbours holds either side
    // of one. There is a break after EVERY word, the last one included: a
    // circle has no end, so a gap only between words leaves the last word
    // running straight into the first and the reader counting to find where
    // one stops. One word gets no breaks at all — an unbroken ring is the
    // whole point of it.
    // A tile is the same button whichever shape it sits in; only where it goes
    // differs, so the ring and the line share it.
    const tile = (idx, w, x, y, extra) => `<button type="button" class="ana-tile${
        ring.struck[idx] ? " struck" : ""}${pinnedTile[idx] ? " fixed" : ""}"
          data-ana="${idx}" data-word="${w}" aria-pressed="${ring.struck[idx] ? "true" : "false"}"
          title="${pinnedTile[idx] ? "Already in the crossword grid — fixed in its place" : ring.struck[idx] ? "Crossed off — tap to put it back" : "Tap to cross off once used"}"
          style="left:calc(50% + ${x}px);
                 top:calc(50% + ${y}px)${extra || ""}">${ring.letters[idx]}</button>`;
    const focus = ringKbdFocused() ? " ana-focus" : "";
    // Once a letter is pinned the circle is the wrong shape. A ring says the
    // letters have no order, and a pinned letter is exactly a piece of order:
    // it is letter 4 of the answer, not "somewhere round there". Counting
    // clockwise from the top to find slot 4 is work the solver should not be
    // doing, so with any pin the tiles stand in a LINE in answer order, the
    // way the light itself runs, each pinned letter in its own slot and the
    // free ones filling the slots between. Words are split by a gap, and a word
    // that would push the line wider than the ring ever gets starts a new row.
    // No pins, no order: the ring stays.
    if (Object.keys(ring.pins).length) {
      const MAXW = 314;  // the widest the ring itself is ever drawn
      const rows = [];   // each row: [[word index, start, len], ...]
      let start = 0, row = [], used = 0;
      cuts.forEach((len, w) => {
        const need = used ? used + 1 + len : len;   // +1: the gap before this word
        if (row.length && need * PITCH > MAXW) { rows.push(row); row = []; used = 0; }
        row.push([w, start, len]);
        used = used ? used + 1 + len : len;
        start += len;
      });
      rows.push(row);
      const width = (r) => r.reduce((a, [, , len]) => a + len, 0) + r.length - 1;
      const widest = Math.max(...rows.map(width));
      // A single word longer than the panel is wide closes the tiles up rather
      // than wrapping mid-word, which would put a break where the answer has none.
      const pitch = Math.min(PITCH, Math.floor(MAXW / widest));
      const narrow = pitch < PITCH ? `;min-width:0;width:${pitch - 3}px;padding-left:0;padding-right:0` : "";
      const ROW = 46;
      const tiles = rows.map((r, ri) => {
        const y = Math.round((ri - (rows.length - 1) / 2) * ROW);
        let slot = 0;
        const left = -((width(r) - 1) / 2) * pitch;
        return r.map(([w, s0, len]) => {
          const out = ring.order.slice(s0, s0 + len).map((idx, k) =>
            tile(idx, w, Math.round(left + (slot + k) * pitch), y, narrow)).join("");
          slot += len + 1;
          return out;
        }).join("");
      }).join("");
      const lineDisc = `<div class="ana-disc ana-line${focus}" style="width:${
        widest * pitch + 34}px;height:${rows.length * ROW + 10}px">${tiles}</div>`;
      return `<div class="anagram-ring">
      <div class="ana-discs">${lineDisc}</div>
      <button type="button" id="ana-shuffle" class="ghost small">Shuffle</button>
    </div>`;
    }
    const slots = n + (cuts.length > 1 ? cuts.length : 0);
    const radius = Math.max(56, Math.min(140,
      Math.ceil(PITCH / (2 * Math.sin(Math.PI / Math.max(3, slots))))));
    const d = radius * 2 + 34;
    const tiles = cuts.map((len, w) => {
      const slice = ring.order.slice(from, from + len);
      const before = from + w;   // letters already placed, plus one arc per break
      from += len;
      return slice.map((idx, pos) => {
        const a = ((before + pos) / slots) * 2 * Math.PI - Math.PI / 2;
        return tile(idx, w, Math.round(Math.cos(a) * radius), Math.round(Math.sin(a) * radius));
      }).join("");
    }).join("");
    const discs = `<div class="ana-disc${focus}" style="width:${
      d}px;height:${d}px">${tiles}</div>`;
    // ana-focus is a plain function of activeElement at render time, not of a
    // focus/blur listener toggling a class: the disc is thrown away and rebuilt
    // on every keystroke (a new tile has to be drawn), so anything the DOM
    // itself would have set on the old disc is gone with it. Deriving the class
    // fresh on every render is what makes the ring survive its own redraws.
    return `<div class="anagram-ring">
      <div class="ana-discs">${discs}</div>
      <button type="button" id="ana-shuffle" class="ghost small">Shuffle</button>
    </div>`;
  }

  // ---------- animating the ring ----------
  //
  // A plain redraw blinks the letters into a new order and the eye has nothing
  // to follow, which is the one thing a physical set of tiles gives you for
  // free. FLIP fixes that without a library — measure every
  // tile's rect before the redraw, let the redraw happen, then for each tile
  // that still exists work out how far it moved and play that distance
  // backwards as a transform, so the tile appears to still be at its old spot
  // and animates from there back to zero. A tile with no old rect is new (typed
  // in) and gets a pop-in instead; a tile that has no new rect was deleted
  // (Backspace) and gets a fading ghost planted at its last known position,
  // since the real element is already gone by the time this runs.
  function reduceMotion() {
    return !!(typeof window !== "undefined" && window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function ringTileRects() {
    const rects = {};
    const panel = $("hint-panel");
    panel.querySelectorAll("button.ana-tile").forEach((b) => {
      rects[b.getAttribute("data-ana")] = b.getBoundingClientRect();
    });
    return rects;
  }

  function playRingFlip(prevRects) {
    if (reduceMotion()) return;
    const panel = $("hint-panel");
    panel.querySelectorAll("button.ana-tile").forEach((b) => {
      const prev = prevRects[b.getAttribute("data-ana")];
      if (prev) {
        const now = b.getBoundingClientRect();
        const dx = prev.left - now.left, dy = prev.top - now.top;
        if (Math.abs(dx) < .5 && Math.abs(dy) < .5) return;
        b.style.transition = "none";
        b.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
        b.getBoundingClientRect();  // force layout so the jump above is not itself animated
        requestAnimationFrame(() => {
          b.style.transition = "transform var(--mo-in) var(--mo-ease)";
          b.style.transform = "translate(-50%, -50%)";
        });
      } else {
        // Freshly typed: pop in rather than sliding from nowhere.
        b.style.transition = "none";
        b.style.opacity = "0";
        b.style.transform = "translate(-50%, -50%) scale(.3)";
        b.getBoundingClientRect();
        requestAnimationFrame(() => {
          b.style.transition = "transform var(--mo-in) var(--mo-ease), opacity var(--mo-in) var(--mo-ease)";
          b.style.opacity = "1";
          b.style.transform = "translate(-50%, -50%) scale(1)";
        });
      }
    });
  }

  // Backspace removes a tile that is already gone from the DOM by the time
  // playRingFlip runs, so there is nothing left to animate out — a ghost stands
  // in for it, planted at its last real position and faded there.
  function ghostRingTile(rect, text) {
    if (reduceMotion() || !rect || !document.body) return;
    const ghost = document.createElement("div");
    ghost.className = "ana-tile ana-ghost";
    ghost.textContent = text;
    ghost.style.position = "fixed";
    ghost.style.left = rect.left + "px";
    ghost.style.top = rect.top + "px";
    ghost.style.width = rect.width + "px";
    ghost.style.height = rect.height + "px";
    ghost.style.margin = "0";
    ghost.style.transform = "none";
    ghost.style.opacity = "1";
    ghost.style.pointerEvents = "none";
    document.body.appendChild(ghost);
    requestAnimationFrame(() => {
      ghost.style.transition = "transform var(--mo-in) var(--mo-ease), opacity var(--mo-in) var(--mo-ease)";
      ghost.style.transform = "translateY(-8px) scale(.5)";
      ghost.style.opacity = "0";
    });
    setTimeout(() => ghost.remove(), 260);
  }

  // ---------- typing into the ring ----------
  //
  // Tapping struck a letter off; typing edits the set itself. A letter key
  // appends a tile, Backspace deletes the most recently added one — plain
  // array push/pop on `ring.letters`, with `ring.order` (the shuffled draw
  // order the tiles are actually drawn in) kept in step so a mid-shuffle edit
  // does not scramble indices out from under struck-off tiles that survive it.
  function addRingLetter(ch) {
    if (!ring) return;
    const prevRects = ringTileRects();
    const idx = ring.letters.length;
    ring.letters.push(ch);
    ring.order.push(idx);
    renderHintPanel();
    playRingFlip(prevRects);
  }

  function removeLastRingLetter() {
    if (!ring || !ring.letters.length) return;
    const prevRects = ringTileRects();
    const idx = ring.letters.length - 1;
    const removedRect = prevRects[String(idx)];
    const removedText = ring.letters[idx];
    ring.letters.pop();
    const pos = ring.order.indexOf(idx);
    if (pos >= 0) ring.order.splice(pos, 1);
    delete ring.struck[idx];
    renderHintPanel();
    playRingFlip(prevRects);
    ghostRingTile(removedRect, removedText);
  }

  // ---------- the walkthrough's steps, read off the wordplay tree ----------
  // The prose walkthrough says why; the tree says what happens, so every step
  // is listed from it: each part's words and what they give, each operation's
  // indicator and what it does to which pieces, ending in the answer. Letters
  // a node does not store (the shuffle of an anagram, the outer of a container)
  // are worked out here from its siblings and the answer, never stored; where
  // that has two readings the step shows no result.
  const WP_FUNCTION_WORDS = new Set(["a", "an", "the", "of", "to", "for", "and", "with", "by", "in", "on", "as",
    "at", "is", "are", "was", "be", "has", "from", "that", "it", "its", "this"]);
  const WP_ADJACENT = ["anagram", "reversal", "hidden"];
  const WP_PICK = { first: "the first letter of", last: "the last letter of", middle: "the middle of",
    outer: "the outer letters of", alternate: "alternate letters of", regular: "regularly spaced letters of",
    nth: "regularly spaced letters of" };
  const wpLetters = (s) => String(s || "").normalize("NFD").replace(/[^A-Za-z]/g, "").toUpperCase();
  const wpSorted = (s) => s.split("").sort().join("");

  // The letters a node gives from its own parts alone, or null.
  function wpKnown(n) {
    if (typeof n.gives === "string") return wpLetters(n.gives);
    if (!n.op) return "words" in n ? wpLetters(n.words) : null;
    const ks = (n.parts || []).map(wpKnown);
    if (n.op === "charade" && ks.length && ks.every((k) => k != null)) return ks.join("");
    if (n.op === "reversal" && ks[0] != null) return ks[0].split("").reverse().join("");
    return null;
  }

  // The letters of the inner step that make `target` with `outer` around it,
  // or null unless exactly one reading fits. `fodder` (letters the inner step
  // is built from, when known) must be a rearrangement of the result.
  function wpInside(target, outer, fodder) {
    const found = new Set();
    for (let k = 1; k < outer.length; k++) {
      if (target.length > outer.length && target.startsWith(outer.slice(0, k)) && target.endsWith(outer.slice(k))) {
        const x = target.slice(k, target.length - (outer.length - k));
        if (fodder == null || wpSorted(x) === wpSorted(fodder)) found.add(x);
      }
    }
    return found.size === 1 ? [...found][0] : null;
  }
  function wpAround(target, inner) {
    const found = new Set();
    for (let j = 1; j + inner.length < target.length; j++) {
      if (target.startsWith(inner, j)) found.add(target.slice(0, j) + target.slice(j + inner.length));
    }
    return found.size === 1 ? [...found][0] : null;
  }

  // Map node -> the letters it gives into the answer, for every op node that can be told.
  function wpResults(root, answer) {
    const out = new Map();
    const fodderOf = (n) => {
      const ks = (n.parts || []).map(wpKnown);
      return n.op === "anagram" && ks.length && ks.every((k) => k != null) ? ks.join("") : null;
    };
    const walk = (n, target) => {
      if (!n.op || n.unchecked) return;
      const ks = (n.parts || []).map(wpKnown);
      let own = typeof n.gives === "string" ? wpLetters(n.gives) : target != null ? target : wpKnown(n);
      if (own != null && n.op === "anagram" && fodderOf(n) != null && wpSorted(fodderOf(n)) !== wpSorted(own)) own = null;
      if (own != null) out.set(n, own);
      const want = (n.parts || []).map((p, i) => ks[i]);
      if (own != null) {
        if (n.op === "charade") {
          const un = ks.map((k, i) => (k == null ? i : -1)).filter((i) => i >= 0);
          if (un.length === 1) {
            const pre = ks.slice(0, un[0]).join(""), post = ks.slice(un[0] + 1).join("");
            if (own.length > pre.length + post.length && own.startsWith(pre) && own.endsWith(post)) {
              want[un[0]] = own.slice(pre.length, own.length - post.length);
            }
          }
        } else if (n.op === "reversal") {
          want[0] = own.split("").reverse().join("");
        } else if (n.op === "container") {
          if (ks[0] != null && ks[1] == null) want[1] = wpInside(own, ks[0], fodderOf(n.parts[1]));
          else if (ks[1] != null && ks[0] == null) want[0] = wpAround(own, ks[1]);
        }
      }
      (n.parts || []).forEach((p, i) => walk(p, want[i]));
    };
    const whole = wpLetters(answer), known = wpKnown(root);
    walk(root, known != null && known !== whole ? null : whole);
    return out;
  }

  // Code-point slice of the clue, as the stored `at` offsets count.
  function wpSpan(n) {
    const spans = [];
    const visit = (m) => {
      if ("words" in m && "at" in m) spans.push([m.at, m.at + [...m.words].length]);
      (m.indicators || []).forEach((i) => { if ("at" in i) spans.push([i.at, i.at + [...i.text].length]); });
      (m.parts || []).forEach(visit);
    };
    visit(n);
    return spans.length ? [Math.min(...spans.map((s) => s[0])), Math.max(...spans.map((s) => s[1]))] : null;
  }

  // Each anagram, reversal or hidden indicator with a content word between it
  // and its fodder: [{ind, gap}]. Link words the annotation declares, and the
  // small words that join, do not count.
  function wpApart(root, clue, linkWords) {
    const cps = [...clue];
    const ok = new Set(WP_FUNCTION_WORDS);
    (linkWords || []).forEach((l) => (String(l).toLowerCase().match(/[a-z]+/g) || []).forEach((w) => ok.add(w)));
    const out = [];
    const visit = (n) => {
      if (n.op && WP_ADJACENT.includes(n.op) && !n.unchecked) {
        const fod = (n.parts || []).map(wpSpan).filter(Boolean);
        if (fod.length) {
          const fs = Math.min(...fod.map((s) => s[0])), fe = Math.max(...fod.map((s) => s[1]));
          (n.indicators || []).forEach((ind) => {
            if (!("at" in ind)) return;
            const i0 = ind.at, i1 = ind.at + [...ind.text].length;
            const gap = i0 >= fe ? cps.slice(fe, i0).join("") : i1 <= fs ? cps.slice(i1, fs).join("") : "";
            const bad = (gap.toLowerCase().replace(/\([^)]*\)/g, " ").match(/[a-z]+/g) || []).filter((w) => !ok.has(w));
            if (bad.length) out.push({ ind: ind.text, gap: gap.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "") });
          });
        }
      }
      (n.parts || []).forEach(visit);
    };
    visit(root);
    return out;
  }

  // {lines: [<li> html], liberties: [text]}; both empty when the tree has no steps to show.
  function wordplaySteps(tree, answer, clue, linkWords) {
    const none = { lines: [], assembly: [], liberties: [] };
    if (!tree || !tree.op || ["cryptic", "rebus", "reverse"].includes(tree.op)) return none;
    const results = wpResults(tree, answer);
    const g = (s) => `<span class="gives">${esc(s)}</span>`;
    const piece = (p) => {
      const k = results.get(p) || wpKnown(p);
      return k != null ? g(k) : p.words ? `“${escClue(p.words)}”` : "the step above";
    };
    const joined = (parts, sep) => (parts || []).map(piece).filter(Boolean).join(sep);
    // `assembly` is `lines` without the one-word-to-letters leaves, which the
    // building-blocks rung already lists; shown instead once that rung is open.
    const lines = [], assembly = [];
    const visit = (n, top) => {
      (n.parts || []).forEach((p) => visit(p, false));
      if (!n.op) {
        if (typeof n.gives === "string" && n.words && wpLetters(n.gives) !== wpLetters(n.words)) {
          lines.push(`<li>“${escClue(n.words)}” → ${g(n.gives)}${n.note ? ` <span class="muted">— ${esc(n.note)}</span>` : ""}</li>`);
        }
        return;
      }
      const P = (n.parts || []).map(piece);
      const res = top ? g(answer) : results.get(n) != null ? g(results.get(n)) : "";
      let what;
      switch (n.op) {
        case "charade": what = `join ${joined(n.parts, " + ")} in order`; break;
        case "anagram": what = `rearrange the letters of ${joined(n.parts, " + ")}`; break;
        case "reversal": what = `reverse ${P[0]}`; break;
        case "container": what = `put ${P[1]} inside ${P[0]}`; break;
        case "deletion": what = `take ${P[1]} out of ${P[0]}`; break;
        // The fodder's own words, not what it gives: its gives is the hidden
        // stretch itself, so piece() would read "hidden in GEORDIE → GEORDIE".
        case "hidden": what = `find the answer hidden in ${(n.parts || [])[0] && n.parts[0].words ? `“${escClue(n.parts[0].words)}”` : P[0]}`; break;
        case "homophone": what = `${P[0]} sounds like ${g(n.spelt || "")}`; break;
        case "substitution": what = `in ${P[0]}, swap ${P[1]} for ${P[2]}`; break;
        case "cycling": what = `move letters round from one end of ${P[0]} to the other`; break;
        case "move": what = `move ${P[1]} to another place in ${P[0]}`; break;
        case "palindrome": what = P.length ? `check that ${P[0]} reads the same both ways` : "check that the answer reads the same both ways"; break;
        default: what = WP_PICK[n.op] ? `take ${WP_PICK[n.op]} ${P.length > 1 ? P.slice(0, -1).join(", ") + " and " + P[P.length - 1] : P[0]}` : `apply ${esc(n.op)} to ${joined(n.parts, " + ")}`;
      }
      const inds = n.indicators || [];
      const marks = inds.map((i) => `<mark class="ind">${escClue(i.text)}</mark>`).join(LIST_SEP);
      const why = inds.filter((i) => i.note).map((i) => i.note).join("; ");
      const li = `<li>${marks ? marks + " — " : ""}${what}${res ? ` → ${res}` : ""}` +
        `${why ? ` <span class="muted">— ${esc(why)}</span>` : ""}</li>`;
      lines.push(li);
      assembly.push(li);
    };
    visit(tree, true);
    const liberties = wpApart(tree, clue, linkWords).map((a) =>
      `This clue takes a liberty: '${a.ind}' isn't next to its fodder (it is separated by '${a.gap}').`);
    return { lines, assembly, liberties };
  }

  // "Entered as SAPIR: RIPAS → reversal → SAPIR": each step's op by its own
  // name (alterationOp in tools/data/puzzle.schema.json), so no table here can drift from it.
  function enteredHTML(ann) {
    const alt = ann.alteration;
    if (!alt || !ann.entered) return "";
    const chain = [`<span class="gives">${esc(alt.from)}</span>`];
    for (const step of alt.steps || []) chain.push(esc(step.op), `<span class="gives">${esc(step.gives || ann.entered)}</span>`);
    return `<p>Entered as <span class="gives">${esc(ann.entered)}</span>: ${chain.join(" → ")}</p>`;
  }

  // The clue's formula as a skeleton, for the type rung: what the answer is made
  // of with every piece blank. A chip names a piece's ROLE and its letter count
  // and nothing else; what it stands for is the blocks rung's to say, and the
  // solver takes it by tapping. `parts` is read left to right: a string is a
  // word of the formula, a number is the index of a chip, which is also the
  // index of that piece in the blocks rung. The counts come off `gives`, which
  // blockLetters may withhold from the rung but which the solver is entitled to
  // the LENGTH of — a hidden word's single piece is the answer's own length.
  function formulaOf(ann, blocks) {
    // The pieces total what the clue itself solves to: where the grid holds an
    // altered entry (alteration), that is alteration.from, not the entered letters.
    const built = (ann.alteration && ann.alteration.from) || ann.answer;
    const shuffled = ((ann.assembly || {}).anagrams || []).map((a) => wholeWord(a.gives));
    // A block carries no role field: what it IS is read off its fields and its
    // note. The anagram's own fodder, a sound, the clue words as written (the
    // letters are the clue's own), a cut or selection from them, an abbreviation
    // the note names, else a synonym (a different word that means it).
    const role = (b) => {
      if (b.anagramOf || shuffled.includes(wholeWord(b.gives))) return "anagram";
      if (b.soundsLike) return "sound";
      const note = b.note || "";
      if (/abbreviat|short for|symbol/i.test(note)) return "abbreviation";
      if (wholeWord(b.clueFragment) === wholeWord(b.gives)) return "as written";
      if (b.select || /\b(first|last|middle|letters?|ends?)\b/i.test(note)) return "selection";
      return "synonym";
    };
    const chips = blocks.map((b) => {
      const n = letterCount(b.gives);
      // The role is fixed prose too: a clue whose answer is SYNONYM must not
      // wear a "synonym" chip before the walkthrough.
      return maskAnswer(role(b), built) + (n ? ` ${n}` : "");
    });
    const all = chips.map((_, i) => i);
    const join = (idx, sep) => idx.reduce((out, i, k) => out.concat(k ? [sep, i] : [i]), []);
    const tree = ann.wordplay || {};
    // A container reads "inner inside outer", which needs to know which chip is
    // which: found by the words each part of the tree names, and given up (the
    // chips simply joined) when a part is not one plain clue phrase.
    const at = (p) => (p && p.words ? blocks.findIndex((b) => wholeWord(b.clueFragment) === wholeWord(p.words)) : -1);
    const outer = tree.op === "container" && blocks.length === 2 ? at((tree.parts || [])[0]) : -1;
    const inner = tree.op === "container" && blocks.length === 2 ? at((tree.parts || [])[1]) : -1;
    // A deletion reads "whole − cut" the same way: joined with "+" it says
    // the letters taken out are added (WANDER + N for WADER).
    const whole = tree.op === "deletion" && blocks.length === 2 ? at((tree.parts || [])[0]) : -1;
    const cut = tree.op === "deletion" && blocks.length === 2 ? at((tree.parts || [])[1]) : -1;
    // Only the operations the family line has already named. "Anagram" and "the
    // answer is built from pieces, one inside another" are said by the rung
    // above this; "reversal of" or "hidden in" would pick one member out of a
    // family it deliberately leaves whole (the precise type is the blocks
    // rung's), so those formulas are just their pieces.
    const head = { anagram: "anagram of" }[tree.op];
    // Every operation in the tree is shown (a flat "A + B + C" dropped the
    // reversal / container / anagram wrapped round some of the pieces): the
    // tree is walked, each leaf is its chip, and a nested operation is
    // bracketed. Given up (the flat reading below) when a leaf is not a chip.
    //
    // Walked whatever the number of chips, one included: "most of THANET" has
    // a single chip, and reading it as that chip alone says a six makes a five.
    // A piece with no clue words of its own — the letter a deletion drops — is
    // no chip, so it is told by where it comes off the whole and how many
    // letters it is ("− last letter"), which is what makes the counts add up.
    const vals = wpResults(tree, built);
    const val = (n) => (n ? (vals.get(n) != null ? vals.get(n) : wpKnown(n)) : null);
    const plural = (k, w) => `${k === 1 ? "" : k + " "}${w}${k === 1 ? "" : "s"}`;
    // W the whole, cuts the letters each dropped piece gives, R what is left
    // (any of them may be unknown). Where they come off is read off the letters:
    // R itself when it is known, else which end of W the cut matches.
    const cutWords = (W, cuts, R) => {
      const C = cuts.every((c) => c != null) ? cuts.join("") : null;
      const k = C ? C.length : W && R ? W.length - R.length : 0;
      if (!(k > 0)) return "− some letters";
      const fits = (rest) => (R ? rest === R : true);
      if (W && cuts.length === 2 && C && W.startsWith(cuts[0]) && W.endsWith(cuts[1])
        && W.length > k && fits(W.slice(cuts[0].length, W.length - cuts[1].length))) {
        return k === 2 ? "− first and last letters" : `− ${cuts[0].length} from the front and ${cuts[1].length} from the back`;
      }
      if (W && (!R || W.length - k === R.length)) {
        const last = (!C || W.endsWith(C)) && (R ? W.slice(0, -k) === R : C && !W.startsWith(C));
        const first = (!C || W.startsWith(C)) && (R ? W.slice(k) === R : C && !W.endsWith(C));
        if (last) return `− ${plural(k, "last letter")}`;
        if (first) return `− ${plural(k, "first letter")}`;
        const m = (W.length - k) / 2;
        if (R && Number.isInteger(m) && W.slice(0, m) + W.slice(m + k) === R) return `− ${plural(k, "middle letter")}`;
      }
      return `− ${k} letter${k === 1 ? "" : "s"}`;
    };
    const OP_WORDS = { anagram: "anagram of", reversal: "reversal of", hidden: "hidden in", homophone: "sounds like",
      first: "first letter of", last: "last letter of", middle: "middle of", outer: "outer letters of",
      alternate: "alternate letters of", regular: "regular letters of", nth: "regular letters of",
      spoonerism: "spoonerism of", substitution: "swap in", cycling: "cycled", move: "moved letters of", palindrome: "palindrome of" };
    // A whole-clue op has no fodder to name: the chip already labels it, and "cryptic of" is no prose.
    const WHOLE_CLUE = ["cryptic", "rebus", "reverse"];
    const chipless = (p) => p && !p.op && !p.words && val(p) != null;
    const used = new Set();
    const walk = (node, top) => {
      if (!node) return null;
      if (!node.op || !node.parts) {
        const i = at(node);
        if (i >= 0 && !used.has(i)) { used.add(i); return [i]; }
        // A letter the clue gives without words of its own, inside a charade.
        if (chipless(node)) return [plural(val(node).length, "letter")];
        return null;
      }
      const op = node.op;
      const here = top ? wholeWord(built) : val(node);
      let out;
      if (op === "deletion" && node.parts.slice(1).every(chipless)) {
        const whole = walk(node.parts[0], false);
        if (!whole) return null;
        out = whole.concat(cutWords(val(node.parts[0]), node.parts.slice(1).map(val), here));
      } else {
        const kids = node.parts.map((p) => walk(p, false));
        if (!kids.length || kids.some((k) => !k)) return null;
        if (op === "container" && kids.length === 2) out = [].concat(kids[1], "inside", kids[0]);
        else if (op === "deletion" && kids.length === 2) out = [].concat(kids[0], "−", kids[1]);
        // A composite anagram's fodder is the answer's letters plus the second
        // piece's (comp(x, y), tools/wordplay.py): the answer is the first less the second.
        else if (op === "composite" && kids.length === 2) out = ["anagram of", "("].concat(kids[0], "−", kids[1], ")");
        // A move's second piece is letters of the first, moved, not letters added to it.
        else if (op === "move" && kids.length === 2) out = [].concat(kids[0], "with", kids[1], "moved");
        else {
          const lead = op === "charade" || op === "composite" || WHOLE_CLUE.includes(op) ? [] : [OP_WORDS[op] || `${op.replace(/_/g, " ")} of`];
          out = lead.concat(...kids.map((k, n) => (n ? ["+"].concat(k) : k)));
        }
      }
      return top || out.every((x) => typeof x === "number") && out.length === 1 ? out : ["("].concat(out, ")");
    };
    const walked = tree.op && tree.parts && blocks.length ? walk(tree, true) : null;
    const treeParts = walked && used.size === blocks.length ? walked : null;
    // Pieces whose counts do not sum to the answer's, with no walkable tree to
    // say what else happens to them, are only "made from" each other: "+" would claim
    // SPACE + S is PACE.
    const sums = blocks.reduce((t, b) => t + letterCount(b.gives), 0) === letterCount(built);
    const parts = treeParts ? treeParts
      : outer >= 0 && inner >= 0 && outer !== inner ? [inner, "inside", outer]
      : whole >= 0 && cut >= 0 && whole !== cut ? [whole, "−", cut]
      : !sums ? ["made from"].concat(join(all, "and"))
      : (head ? [head] : []).concat(join(all, "+"));
    const lead = ((ann.definitions || []).length && !ann.definedByPreamble ? "definition" : "answer")
      + ` (${letterCount(built)}) =`;
    // What a chip reads once its piece is out: the letters the piece gives
    // (blockLetters, so withheld ones stay withheld), else the clue words.
    const fills = blocks.map((b) => blockLetters(ann, b) || b.clueFragment || "?");
    // The step from the built answer to the grid entry, said by its length only.
    const after = ann.alteration && ann.entered && wholeWord(ann.entered) !== wholeWord(built)
      ? `then ${(ann.alteration.steps || []).map((x) => x.op).join(", ") || "altered"} \u2192 grid entry (${letterCount(ann.entered)})` : "";
    return { after, lead: maskAnswer(lead, built), parts: parts.map((p) => typeof p === "string" ? maskAnswer(p, built) : p), chips, fills };
  }

  // Build the rungs this particular clue deserves. Each rung: {key, label, html}.
  function ladderSteps(ann, clue) {
    if (!ann) return [];
    const t = ann.type || [];
    const isDD = t.includes("double_definition");
    const isCD = t.includes("cryptic_definition");
    const isLit = t.includes("and_lit");
    const isPic = t.includes("rebus");
    const inds = ann.indicators || [];
    const defs = ann.definitions || [];
    const blocks = buildingBlocks(ann);
    const steps = [];

    // Every rung is NAMED for the question it asks, never for the answer it is
    // about to give, because the unbought rungs' names are on screen the whole
    // time — that is how you choose which to buy. A name that carries its type
    // ("How can the whole clue be the definition?" on an &lit, "Where does the
    // clue split?", "What each half means") announces, on the button for a hint
    // nobody has paid for, what kind of clue it is, which on a semi-&lit hidden
    // word is the entire solve; an indicator label that varies between
    // singular and plural hands over the count.
    //
    // So a label is a function of the rung's key and nothing else, and the
    // smoke test holds the corpus to exactly that: one label per key, across
    // every annotated clue there is. Type-specific wording belongs in the body,
    // which is what you are paying for.
    //
    // Written in ladder order, and that order is the only copy of it: the sort
    // below is Object.keys(LABELS), and tools/build_readme.py reads this same
    // map to number the rungs in README.md. Reorder these five lines and the
    // app, the README and tools/smoke_test.js all move together — there is
    // nowhere left to write a ladder that disagrees with itself.
    const LABELS = {
      indicators: "Spot the indicator words",
      definition: "Where is the definition?",
      type: "What kind of clue is this?",
      blocks: "The building blocks",
      walkthrough: "Full walkthrough"
    };
    // Only the dominant family: a headline names one mechanism. The others a
    // compound type is made of still grade right on this rung's quiz
    // (familyAsk), so a solver who names any of them is not marked wrong.
    //
    // The anagram blurb says to check the shuffled letters "add up to the number
    // in brackets", which is false whenever the anagram is only a piece of the
    // answer (CHOMPED: MP inside an anagram of COD HE), and a solver who believes
    // it goes hunting for the missing letters to throw in. So when no anagram the annotation builds
    // is as long as the answer, the rung says the count comes up short instead.
    if (t.length) steps.push({
      key: "type",
      label: LABELS.type,
      html: [familyOf(t)].map((f) => `<p><strong>${esc(maskAnswer(f.label, ann.answer))}</strong>. ` +
        `${esc(maskAnswer(f.name === "anagram" && partAnagram(ann) ? ANAGRAM_PART
          : f.name === "charade" && movedCharade(ann) ? CHARADE_MOVED : f.blurb, ann.answer))}</p>`).join(""),
      rule: familyRuleHTML(familyOf(t), clue, ann)
    });

    // The exact mechanism, held back until every spotting rung is behind the
    // solver — the indicators, the definition and the family, in whatever order
    // the ladder is currently in.
    //
    // Double and cryptic definitions are not exempt from this line. Their
    // family is "Definitions only", whose blurb offers BOTH arms — "either two
    // plain definitions sit side by side, or one sly one describes the answer
    // the long way round" — and never says which arm this clue is, so the family
    // label has not named the type. They get the NAME, which is the missing
    // word; they do not get the generic blurb, which on these two types would
    // only re-say the definition rung ("no separable wordplay" twice over) and no
    // rung may restate an earlier one.
    // A blog's blocks can come without a type it named or spelled out, and a
    // mechanism line with no mechanism in it says nothing.
    const mechanics = !t.length ? "" : `<p class="mechanism">Mechanism: <strong>${esc(maskAnswer(typeLabels(t), ann.answer))}</strong>.
      ${isDD || isCD ? "" : esc(maskAnswer(typeBlurb(t), ann.answer))}</p>`;

    // Where the definition lives. For a double definition the news is not "there
    // are two" — the family rung says that, and says it later — it is WHERE the
    // clue splits, and which sense each half is read in.
    if (ann.definedByPreamble) {
      // Nothing in the clue to point at, so the rung tells rather than asks.
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>No words in this clue define the answer: the puzzle's preamble
          does: <q>${esc((P && P.preamble) || "")}</q></p>`
      });
    } else if (!defs.length && isPic) {
      // A rebus defines nothing. The rung says so without naming the
      // family, which is the type rung's to sell.
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>No words in this clue define the answer: every character in it is wordplay,
          and none of it is an instruction to follow.</p>`
      });
    } else if (!defs.length) {
      // A blog fact with a type and no clean underline: no definition rung.
    } else if (isDD && defs.length >= 2) {
      // Three senses or more: the split names the first two, and the rest are
      // building blocks the split did not mention (senseBlock), except on a
      // ladder with no blocks rung, where it names them all (splitNames).
      const senses = senseBlocks(ann).map((b) =>
        `<li>“${escClue(b.clueFragment)}” <span class="muted">— ${esc(b.note)}</span></li>`).join("");
      const named = defs.slice(0, splitNames(ann)).map((d, i) =>
        `<mark class="${i ? "def2" : "def"}">${escClue(d.text)}</mark>`);
      const count = ["two", "three", "four", "five"][named.length - 2] || String(named.length);
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>It splits between ${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}
          — ${count} unrelated meanings of the same answer.</p>` +
          (senses ? `<ul>${senses}</ul>` : "")
      });
    } else if (isLit && !ann.fromBlog) {
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>Read <mark class="def">${escClue(defs[0].text)}</mark> straight through as a
          description of the answer, then read the very same words again as wordplay.</p>`
      });
    } else if (isCD && !ann.fromBlog) {
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>There's no separate wordplay here: <mark class="def">${escClue(defs[0].text)}</mark>
          is a whole-clue description of the answer.</p>`
      });
    } else {
      // Say WHERE the definition sits and WHERE the wordplay therefore starts:
      // the split point is the actual solving move, and it is computable from the
      // clue text we already have.
      steps.push({
        key: "definition",
        label: LABELS.definition,
        html: `<p>The definition is <mark class="def">${escClue(defs[0].text)}</mark>${defPlace(clue, defs[0], ann.linkWords)}</p>`
      });
    }

    // `linkWords` names the connective words that carry no wordplay at all,
    // which is the commonest reason a beginner keeps hunting for a mechanism
    // that was never there. It hangs off the definition rung because it is about
    // the CLUE, and a solver can act on it without knowing the answer.
    //
    // A definition's `note` does not hang here: it explains why the definition
    // does not agree with the ANSWER ("payment" for PEANUTS, singular for a
    // plural), so it is written about the answer, and a note comparing the answer
    // to the definition is not an early hint, whatever words it uses. It renders
    // beside definitionFit on the walkthrough rung, where the answer is already
    // on the table.
    const defStep = steps[steps.length - 1];
    if ((ann.linkWords || []).length && defStep) {
      const lw = ann.linkWords.map((w) => `<mark class="link">${escClue(w)}</mark>`).join(LIST_SEP);
      defStep.html += `<p class="muted">${lw} ${ann.linkWords.length > 1 ? "are link words" : "is a link word"}:
        no letters.</p>`;
    }

    // Indicators only exist for some clue types — no rung that says "none".
    if (inds.length) {
      // A blog marks its indicators and credits them to a mechanism only when
      // it names a single type, so pairing its words with operations would guess.
      const ops = ann.fromBlog ? [] : indicatorOps(t, ann.blocks || []);
      const marks = inds.map((i) => `<mark class="ind">${escClue(i.text)}</mark>`).join(LIST_SEP);
      // What is only true of THIS clue comes first: an indicator's `note` says
      // why these words signal their mechanism here, and failing that its `for`
      // names the operation it asks for. Where every indicator has one of the
      // two, the rung is that list and nothing else. The type-derived sentences
      // below are the same on every clue of a type and describe the type, not
      // the indicators, so they are said only when the indicators themselves
      // cannot be.
      const said = (i) => {
        const op = INDICATOR_OPS.find(([o]) => o === i.for);
        return i.note || (op ? `tells you to ${op[1]}` : "");
      };
      const written = inds.filter(said);
      const noteList = `<ul class="ind-notes">${written.map((i) =>
        `<li><mark class="ind">${escClue(i.text)}</mark> — ${esc(said(i))}</li>`).join("")}</ul>`;
      let html;
      if (written.length === inds.length) {
        html = noteList;
      } else if (ops.length === 1) {
        html = `<p>${marks} — ${inds.length > 1 ? "they tell" : "it tells"} you to
          ${ops[0][1]}.</p>`;
      } else if (ops.length > 1) {
        // A compound type has more than one operation and usually more than one
        // indicator. The list is counted off the ops rather than written into
        // the sentence, so the number always matches what is printed.
        const HOWMANY = ["no", "one", "two", "three", "four", "five", "six"];
        html = `<p>${marks} — this clue does ${HOWMANY[ops.length] || ops.length} things, and
          the indicators are what tell them apart:</p><ul>${ops.map(([, op]) => `<li>${op}</li>`).join("")}</ul>
          <p class="muted">Your job here is to work out which word asks for which.</p>`;
      } else {
        html = `<p>${marks} — ${inds.length > 1 ? "these tell" : "this tells"} you
          what to do with the rest of the wordplay.</p>`;
      }
      // Where only some indicators can be explained, the generic wording carries
      // the rest and the explained ones are listed under it.
      if (written.length && written.length !== inds.length) html += noteList;
      steps.push({
        key: "indicators",
        label: LABELS.indicators,
        html,
        // The rule that outlives this clue, behind a chip (withRuleChip).
        rule: indicatorRulesHTML(ann, clue, ops)
      });
    }

    // On a cryptic definition the rung is named for the only honest job it has:
    // splitting a clue that does not split into letters into the two ideas the
    // setter fused together. What each block may show is blockLetters'.
    const shows = (b) => blockShows(ann, b);
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
      // A sentence underneath repeating the same pairs would be a second reading
      // of something already on the screen, so the abbreviation itself is linked.
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
      const pieces = blocks.map((b) => {
        let s = "<li>";
        if (b.clueFragment) s += `“${escClue(b.clueFragment)}”`;
        // A homophone's whole mechanism is the word you say aloud: “Cockney mob”
        // → OARED needs HORDE and the dropped aitch shown. So the sounded form
        // gets its own arrow, ahead of the letters it turns into, and the
        // validator refuses a sound clue that has none.
        if (b.soundsLike) s += ` → <span class="gives">${esc(b.soundsLike)}</span> <span class="muted">said aloud</span>`;
        const letters = blockLetters(ann, b);
        if (letters) {
          const href = glossaryHref(b);
          const gives = `<span class="gives">${esc(letters)}</span>`;
          s += " → " + (href
            ? `<a class="gloss" href="${href}" title="A standard crossword abbreviation — tap to see the list">${gives}</a>`
            : gives);
        }
        if (b.note) s += ` <span class="muted">— ${esc(b.note)}</span>`;
        return s + "</li>";
      });
      // The rung is paced: `pieces` is handed over one at a time, and only the
      // panel knows how many are out yet (renderHintPanel's paceStep). `html`
      // stays the whole rung so that anything reading a step's content — the
      // static pages, the Python port — sees the rung entire.
      //
      // The ring waits for the last piece. It is a workbench for the assembly,
      // and offering it while pieces are still in the box invites the solver to
      // shuffle letters they have not been given yet.
      steps.push({
        key: "blocks",
        label: LABELS.blocks,
        lead: mechanics,
        // The type rung of a double/cryptic definition names only the family
        // ("Double or cryptic definition"), so this line is the one naming which.
        leadAlways: isDD || isCD,
        pieces,
        tail: (t.includes("anagram") ? ringHTML(ann) : ""),
        html: mechanics + `<ul>${pieces.join("")}</ul>` +
          (t.includes("anagram") ? ringHTML(ann) : "")
      });
      // The type rung carries the formula whenever the blocks rung it hands
      // pieces to exists. It is data, not html: which chips are taken is the
      // panel's to know (formulaHTML). The label and the family line are as
      // they were, so nothing about the rung's name depends on the clue.
      // The blocks rung carries the same data and is where the chips are taps.
      const typeStep = steps.find((s) => s.key === "type");
      if (blocks.length <= PICKABLE) {
        const formula = formulaOf(ann, blocks);
        if (typeStep) typeStep.formula = formula;
        steps.find((s) => s.key === "blocks").formula = formula;
      }
    }

    // The half of the clue that isn't mechanical.
    //
    // The blocks spell the answer OUT of the wordplay and the definition rung
    // points at the words, but neither joins the two ends:
    // why do those words mean this answer? That link is
    // where the actual vocabulary of cryptics lives — a definition by synonym,
    // by example, by a sense of the word nobody uses outside crosswords — and
    // it is exactly what a solver is missing when they have the right letters
    // and no confidence in them. It goes LAST, immediately before the answer,
    // because it is the step that turns a spelling into a solve.
    const prose = { ...(ann.explanation || {}) };
    // The line prints "definition → ANSWER:" itself, so a fit that opens with its
    // own "definition -> ANSWER:" echo (a model slip; tools/annotate_prompt.md
    // forbids it) loses that prefix instead of showing it twice.
    if (prose.definitionFit) {
      const ans = String(ann.answer || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      prose.definitionFit = prose.definitionFit.replace(
        new RegExp(`^[^:]{0,160}?\\s*(?:->|→|=>)\\s*${ans}\\s*:\\s*`, "i"), "");
    }
    const fit = prose.definitionFit && ann.definedByPreamble
      ? `<p class="def-fit"><b class="wt-part">Why that's the answer</b>the preamble → <span class="gives">${esc(ann.answer)}</span>: ${esc(prose.definitionFit)}</p>`
      : prose.definitionFit
      ? `<p class="def-fit"><b class="wt-part">Why that's the answer</b>${(ann.definitions || []).map((d, k) =>
          `<mark class="${k ? "def2" : "def"}">${escClue(d.text)}</mark>`).join(" and ")
        } → <span class="gives">${esc(ann.answer)}</span>: ${esc(prose.definitionFit)}</p>`
      : "";
    // Why the definition may fairly disagree with the answer in number or part of
    // speech — a footnote to the fit, so it sits with it rather than two rungs above.
    const note = (ann.definitions || []).filter((d) => d.note)
      .map((d) => `<p class="def-note">${esc(d.note)}</p>`).join("");
    // Two labelled parts, each shown only when it is actually there. What the
    // clue PRETENDS to say and what it is DOING are different things, and one
    // label over both would be wrong whichever word it used: "The trick" over a
    // sentence about the surface reads as a mislabel, and "The surface" over a
    // convention ("Rivers are the crossword's favourite three-letter filler")
    // would be a lie. Which is present is a fact about the annotation, not a
    // guess about its prose — no phrase list can tell a surface sentence from a
    // mechanical one — so `explanation.surface` is its own field and the labels follow it.
    // Clues with no surface apart from their mechanism (double definitions,
    // cryptic definitions, idioms) have none and show "The trick" alone.
    const joke = prose.surface
      ? `<p><b class="wt-part">What it seems to say</b>${esc(prose.surface)}</p>` : "";
    // A puzzle that is not a cryptic: the definition and the walkthrough
    // (straightLadder). Dropping the rung that sells a clue's indicator would
    // leave a paid-for hint off the screen, so a clue with one keeps its ladder.
    if (straightLadder(ann)) steps.splice(0, steps.length, ...steps.filter((s) => s.key === "definition"));
    // A blog-derived ladder stops at what the blogger marked; the rest of the
    // explanation is theirs, and the panel links to it (blogCreditHTML).
    const wp = ann.fromBlog || straightLadder(ann) ? { lines: [], assembly: [], liberties: [] }
      : wordplaySteps(ann.wordplay, ann.answer, clue, ann.linkWords);
    const libHTML = wp.liberties.map((l) => `<p class="liberty">${esc(l)}</p>`).join("");
    const olHTML = (ls) => ls.length ? `<div class="wp-steps"><b class="wt-part">Step by step</b><ol>${ls.join("")}</ol></div>` : "";
    const wpHTML = olHTML(wp.lines) + libHTML;
    const hasBlocks = steps.some((s) => s.key === "blocks");
    const wtBody = (wpPart, mech) => mech + joke + wpPart +
      (prose.walkthrough ? `<p><b class="wt-part">${wpPart ? "Why" : "The trick"}</b>${esc(prose.walkthrough)}</p>` : "") + fit + note +
      // The fit line above already names the answer; print it once.
      (fit ? "" : `<p>Answer: <span class="gives">${esc(ann.answer)}</span></p>`) + enteredHTML(ann);
    if (!ann.fromBlog) steps.push({
      key: "walkthrough",
      label: LABELS.walkthrough,
      html: wtBody(wpHTML, hasBlocks ? "" : mechanics),
      // The same rung when the building blocks are open above it: the pieces
      // are not listed a second time, only how they join (renderHintPanel).
      afterBlocks: hasBlocks ? wtBody(olHTML(wp.assembly) + libHTML, "") : null
    });
    // Ordered by how much each rung gives away, cheapest first — not by the
    // order the rungs are built in, and not by the order people solve in.
    // The indicator is the cheap one: it names the mechanism and leaves the
    // definition to find, which is most of the skill. Naming the definition
    // hands that half over, and with checkers in the grid it often hands over
    // the answer with it, so it goes second. The kind of clue is not asked
    // before either of them: from a cold read that is a guess between seven
    // families, and it usually arrives already spent (see spentBy), which is
    // the honest outcome — a solver who has named the indicator and the
    // definition has worked the family out and should not be sold it.
    //
    // A sort, not a reordered set of pushes: the walkthrough's html asks whether
    // a blocks rung exists, so every rung has to be built before any is placed.
    // The order itself is LABELS' own, not a second list beside it — a literal
    // array here would be a copy that can drift from the live ladder.
    const RUNG_ORDER = Object.keys(LABELS);
    // A clue the checker has flagged (ann.redo, from tools/data/shape_reannotate.json
    // at build) has a known-bad step-by-step: the building blocks go and the
    // walkthrough says so instead. The definition, indicators, type, letter
    // reveal and wheel are untouched.
    if (ann.redo) {
      const wt = steps.find((s) => s.key === "walkthrough");
      steps.splice(0, steps.length, ...steps.filter((s) => s.key !== "blocks" && s.key !== "walkthrough"));
      // The formula hands its pieces to the blocks rung, which is gone.
      steps.forEach((s) => { delete s.formula; });
      if (wt) steps.push({ key: "walkthrough", label: wt.label,
        html: `<p class="redo-note"><b class="wt-part">Being rewritten</b>This hint is being rewritten. The step-by-step for this clue was flagged by our checker, so we are not showing it until it is fixed.</p>` });
    }
    steps.sort((a, b) => RUNG_ORDER.indexOf(a.key) - RUNG_ORDER.indexOf(b.key));
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
  // literal spans of the clue (every definition and indicator, nearly every
  // fragment).
  //
  // The type rung is the exception to "literal spans": its answer is a family,
  // not words in the clue, so it asks by offering the seven. It belongs here all
  // the same — a ladder that asks about every other part and hands this one over
  // is a ladder that answers one of its own questions.
  const GUESSABLE = { type: 1, definition: 1, indicators: 1, blocks: 1 };

  // The clue's words split into things you can put a finger on.
  // Whitespace-delimited, so the punctuation welded to a word rides along with
  // it. The enumeration is never a pickable word: it is not in the text, except
  // for a count in words ("(11, two words)", tools/enumeration.py WORDED), which
  // stays in the text as printed and is cut off here.
  //
  // A hyphenated or en-dashed compound is ONE word ("Drug-free", 255 of the
  // corpus's 265 annotated compounds are named whole), unless an annotation
  // fragment starts or ends at its hyphen: then the highlight in the clue
  // heading covers only half of it ("free" the indicator in "Drug-free"), and a
  // chip for the whole compound would disagree with the heading about which
  // words are lit. `cuts` is the list of such fragment edges (clueCuts); the
  // compound is split after the hyphen there, so the chips and the highlights
  // are always cut at the same places.
  function clueTokens(clue, cuts) {
    const body = String(clue || "")
      .replace(/\(\s*\d{1,2}\s*,\s*(two|three|four|five|six|seven|eight)\s+words\s*\)\s*$/i, "");
    const out = [];
    const re = /\S+/g;
    let m;
    while ((m = re.exec(body))) {
      let from = 0;
      const dash = /[-\u2010-\u2015](?=[^\s-\u2010-\u2015])/g;
      let d;
      while (cuts && cuts.length && (d = dash.exec(m[0]))) {
        const h = m.index + d.index;
        if (d.index > from - 1 && cuts.some((b) => b === h || b === h + 1)) {
          out.push({ i: m.index + from, text: m[0].slice(from, d.index + 1) });
          from = d.index + 1;
        }
      }
      out.push({ i: m.index + from, text: m[0].slice(from) });
    }
    return out;
  }

  // The edges of every fragment the heading can light (placedFragments): where
  // clueTokens may have to split a compound.
  function clueCuts(e) {
    const cuts = [];
    placedFragments(e).forEach((f) => { cuts.push(f.i, f.i + f.text.length); });
    return cuts;
  }
  const tokensOfClue = (e) => clueTokens(clueText(e), clueCuts(e));

  // Piece `at` of the blocks rung, when it is one that can be pointed at: it has
  // to name a span of the clue and yield letters. Indexed off blockPieces rather
  // than off a filtered list of its own, so question n and piece n are the same
  // piece — two lists would drift the moment a block carried a note and no
  // letters, and then the body's piece 2 sat under question 3.
  function blockAskAt(e, at) {
    const b = blockPieces(e)[at || 0];
    return b && b.clueFragment && b.gives ? b : null;
  }

  // The whole charade at once, instead of a piece at a time.
  //
  // Handing pieces over one click each asks nothing. By the time the
  // last one comes round the others are already placed, so "which words give
  // H?" is answered by whatever words are left. Allocating every fragment to
  // every chunk in one go is the move the solver actually has to make, and it
  // cannot be done by elimination until the very last pair.
  function matchAsk(e) {
    const ann = annOf(e);
    const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
    // The same exclusion the single-piece question makes: a fragment that IS
    // its own letters is not a pairing, it is a chip with its answer written on
    // it, and it would pair itself on sight.
    const pairs = blockPieces(e)
      .map((b) => ({ frag: b.clueFragment, gives: blockLetters(ann, b) }))
      .filter((p) => p.frag && p.gives && bare(p.frag) !== bare(p.gives));
    // Three is the smallest set with a decision in it. The last pairing of any
    // matching question is forced — one chunk, one row, nothing to choose — and
    // with two pairs the FIRST one is also the last, so placing one chunk
    // would place the other: one tap dressed as a puzzle. Those clues ask the
    // paced one-piece-at-a-time question below instead, which is a real
    // question about every piece it names.
    if (pairs.length < 3) return null;
    // A fixed shuffle, not a random one: the panel is redrawn on every tap, and
    // chips that jumped between taps would be a memory test of the wrong thing.
    // Ordered by a hash of the chunk, so it holds still without holding state.
    const h = (str) => { let n = 0; for (let i = 0; i < str.length; i++) n = (n * 31 + str.charCodeAt(i)) % 99991; return n; };
    const chips = pairs.map((p) => p.gives).sort((a, b) => h(a) - h(b) || (a < b ? -1 : 1));
    // One order in a hundred-odd comes back out in clue order, which reads as a
    // puzzle that forgot to shuffle and can be answered straight down the list.
    if (chips.join("|") === pairs.map((p) => p.gives).join("|")) {
      const swap = chips[0]; chips[0] = chips[1]; chips[1] = swap;
    }
    return { prompt: "Match each part of the clue to the letters it gives.",
             pairs, chips, step: 0 };
  }

  // Right or wrong per pairing, and a count — never which one was misplaced.
  // The rung opens underneath with the whole split named, so saying it here as
  // well is the page telling you twice.
  function gradeMatch(ask, slots) {
    const got = ask.pairs.filter((p, i) => slots[i] >= 0 && ask.chips[slots[i]] === p.gives).length;
    const n = ask.pairs.length;
    if (got === n) return { right: true, said: "Yes — every part matched correctly." };
    if (!got) return { right: false, said: "None of those match. Here is how the clue breaks down." };
    return { right: false, said: `${got} of the ${n} matched correctly — here is how the whole clue breaks down.` };
  }

  // Which words of the clue a rung names. Kept apart from guessAsk because a
  // rung can be unaskable and still have named its words — a piece that is all
  // the clue has left has no question in it, and every word of it is
  // nonetheless settled for the rung asked next.
  //
  // The blocks rung names one PIECE at a time: step is which. Every other rung
  // has one step and ignores it.
  //
  // One entry per span the rung names, each a list of token indices, in the
  // order the rung names them. Kept apart because where one span ends and the
  // next begins is what decides which of its words are optional, and a flat
  // list of the union cannot say.
  function rungSpans(e, rung, step) {
    const ann = annOf(e);
    if (!ann) return [];
    const tokens = tokensOfClue(e);
    const spans = [];
    const add = (t, i) => {
      const span = [];
      tokens.forEach((tok, n) => {
        if (tok.i < i + t.length && i < tok.i + tok.text.length) span.push(n);
      });
      if (span.length) spans.push({ text: t, tokens: span });
    };
    const kinds = { definition: ["def", "def2"], indicators: ["ind"], link: ["link"] }[rung];
    if (kinds) {
      placedFragments(e).filter((f) => kinds.includes(f.kind)).forEach((f) => add(f.text, f.i));
    } else if (rung === "blocks") {
      const b = blockAskAt(e, step);
      const i = b && b.clueFragment ? bestOccurrence(clueText(e), b.clueFragment, []) : -1;
      if (i >= 0) add(b.clueFragment, i);
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
  // the app is fussy.
  //
  // Only at the ENDS of a span, and only for a DEFINITION. In wordplay every
  // word is either letters or an instruction — "a" is a letter of the fodder —
  // so there dropping one is a real mistake and stays one.
  const EDGE_WORDS = ("a an the this these those it its one such by of for from " +
                      "with in on at to and that as so s").split(" ");

  // A token is the clue's text split on spaces, so it carries the punctuation
  // around it: the "in'" that closes "'It's right to tuck in'" (azed-2344 25d).
  // An apostrophe inside a word is part of it ("it's" is not "its"), but one at
  // either end is a quote mark, curly or straight, and is not.
  function edgeTokens(span, tokens) {
    const bare = (n) => tokens[n].text.toLowerCase().replace(/[‘’]/g, "'")
      .replace(/[^a-z']/g, "").replace(/^'+|'+$/g, "");
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
  // that is a definition. A piece that is also a definition — the sounded half
  // of a double definition + homophone — inherits the same latitude.
  function rungEdges(e, rung, step) {
    const ann = annOf(e);
    if (!ann || rung === "indicators") return [];
    const defs = (ann.definitions || []).map((d) => d.text);
    const tokens = tokensOfClue(e);
    return rungSpans(e, rung, step)
      .filter((s) => rung === "definition" || defs.indexOf(s.text) >= 0)
      .reduce((a, s) => a.concat(edgeTokens(s.tokens, tokens)), []);
  }

  // The type rung's question. Its answer is a family rather than a run of words,
  // so what comes back has `choices` where the others have `tokens`, and every
  // reader downstream branches on that one field.
  //
  // All seven are always offered, commonest first and never shuffled: the list
  // IS the vocabulary this site is trying to teach, and seeing the same seven in
  // the same order under every clue is most of how it gets learned. Narrowing it
  // to plausible ones would make the question easier and the lesson smaller.
  function familyAsk(ann) {
    // Empty for a type no rule claims: there would be no right answer to pick, so
    // there is no question and the rung is simply handed over.
    // A core type (ann.typeCore) is a lower bound: the clue may also cut a word
    // or select letters from one, so those families are right answers too.
    const right = familiesOf((ann.type || []).concat(ann.typeCore ? ["deletion", "letter_selection"] : [])).map((f) => pickerOf(f).label);
    if (!right.length) return null;
    // The families are named for the devices themselves, which means a chip can
    // be a word that is somewhere an answer — 30103 28A is a cryptic definition
    // whose answer is ANAGRAM. The rung must never print one, so a clue whose
    // answer is the name of a family is told rather than asked, the same as any
    // other clue with no question in it.
    const bare = (t) => String(t || "").replace(/[^A-Za-z]/g, "").toUpperCase();
    if (FAMILY_CHIPS.some((c) => bare(c) === bare(ann.answer))) return null;
    return { prompt: "Which kind of clue is it? Each kind is explained once you answer.", choices: FAMILY_CHIPS,
             answer: right[0], answers: right, step: 0 };
  }

  // What a rung asks, which tokens answer it, and which are no longer anybody's
  // to pick. Null when this clue cannot pose the question at all — a type with
  // no indicators, a block rung with nothing that yields letters — and the rung
  // is then simply handed over.
  //
  // A word an earlier rung already named is not a choice. Leaving it tappable
  // invites a solver who has the definition to offer it back as the indicator,
  // and marks them wrong for a thing the screen had already told them.
  // They are shown, greyed and inert: the scaffolding is the point, since
  // knowing where the definition ends is most of knowing where the wordplay
  // starts.
  //
  // Nothing is charged for without being offered first: if a rung has anything
  // to point at, it asks, even when what is left to point at IS the whole answer.
  // An easy question is a free rung; a rung handed over
  // unasked is a rung the solver paid for and was never given the chance to
  // win. The only rung that cannot ask is one with nothing to point at at all,
  // and the only piece that cannot is one that is all the clue has left. A
  // definition that is the whole clue is still asked: nothing is settled yet,
  // so seeing that every word defines is the judgement being tested. A piece
  // is asked once everything else is named, and there it is only arithmetic.
  // A charade has more than one piece, and "it isn't knowing it is a charade
  // that is hard, it is DOING the charade" — so the blocks rung asks for
  // each piece in turn rather than one and done. step says which piece; a piece
  // already placed is settled scaffolding for the next question, by the same
  // rule that settles the definition when the indicators are asked for.
  function guessAsk(e, rung, step) {
    const ann = annOf(e);
    if (!ann) return null;
    const at = step || 0;
    if (at && rung !== "blocks") return null;
    if (rung === "type") return familyAsk(ann);
    const tokens = tokensOfClue(e);
    const target = rungTokens(e, rung, at);
    if (!target.length) return null;
    let prompt = "", gives = "";
    if (rung === "definition") {
      prompt = "Which words define the answer?";
    } else if (rung === "indicators") {
      prompt = "Which words tell you what to do with the rest?";
    } else if (rung === "blocks") {
      // The matching question covers the rung entire, so it is only ever the
      // first thing asked; once a piece has been placed the rest are asked a
      // piece at a time.
      if (!at) { const m = matchAsk(e); if (m) return m; }
      const b = blockAskAt(e, at);
      if (!b) return null;
      const n = blockPieces(e).length;
      const of = n > 1 ? ` <span class="muted">(${at + 1} of ${n})</span>` : "";
      // What a piece may show is decided in ONE place, and the question in
      // front of the rung is bound by it exactly as the rung's body is. A
      // prompt that reads its letters straight off the annotation prints on the
      // way in what the body was careful not to print once it was open, and on
      // the clues where a piece IS the answer that prompt is the whole solve.
      gives = blockLetters(annOf(e), b);
      if (gives) {
        prompt = `Which words give <span class="gives">${esc(gives)}</span>?${of}`;
      } else if (wholeWord(b.gives) === wholeWord(ann.answer)) {
        // Held back letters are not a missing question. Which words carry the
        // whole answer is still a real thing to point at, and on a hidden word
        // it is the only question there is. Asked unnamed, it keeps the free way
        // off a rung that would otherwise have to be bought.
        prompt = `Which words give the answer?${of}`;
      } else {
        // A fragment that is its own letters has nothing to point at: "which
        // words give CIA?" with CIA sitting in the clue is not a question but a
        // tap. The rung is handed over like any other.
        return null;
      }
    }
    // Everything already named and not part of this answer: the tier-0 rungs
    // that are up, plus the pieces of this charade already placed.
    const named = SPOTTING.filter((k) => k !== rung && isShown(e, k))
      .reduce((a, k) => a.concat(rungTokens(e, k)), []);
    for (let n = 0; n < at; n++) named.push.apply(named, rungTokens(e, rung, n));
    const known = named.filter((n) => target.indexOf(n) < 0);
    // A piece whose words are all the clue has left is a tap with one answer:
    // the definition, the indicators, the link words and the pieces before it
    // are on screen, so what remains is this piece by elimination. That is not
    // a question, so the piece is handed over like one with nothing to point at.
    // Unlit means what the solver sees, so it is read off clueMarks, which is
    // also the only place the link words are placed. Bare punctuation is no
    // word anyone would pick.
    if (rung === "blocks") {
      const lit = clueMarks(e);
      // A word is lit by a mark on its letters. A punctuation link word ("muses,")
      // lights the comma welded to the word, not the word.
      const wordStart = (tok) => tok.i + tok.text.search(/[A-Za-z0-9]/);
      const wordEnd = (tok) => tok.i + tok.text.length - tok.text.split("").reverse().join("").search(/[A-Za-z0-9]/);
      const open = tokens.filter((tok, n) => target.indexOf(n) < 0 && known.indexOf(n) < 0 &&
        /[A-Za-z0-9]/.test(tok.text) && !lit.some((m) => m.i < wordEnd(tok) && wordStart(tok) < m.i + m.len));
      if (!open.length) return null;
    }
    // The spans, not just their union: which words belong to which indicator is
    // what lets a pick be graded phrase by phrase.
    return { prompt, target, tokens, known, gives, step: at,
             edge: rungEdges(e, rung, at),
             free: rung === "definition" ? rungTokens(e, "link").filter((n) => target.indexOf(n) < 0) : [],
             spans: rungSpans(e, rung, at).map((s) => s.tokens) };
  }


  // A guess in progress, and the verdict on the one just made. Neither is
  // persisted: what survives a reload is hintsEarned, because that is the part
  // that changed the score. A half-made guess is not progress.
  let guessing = null;   // { key, rung, step, picked: [] }
  let lastGuess = null;  // { key, rung, tokens, known, mk: <verdict> }
  // Which block of the panel the last tap on the ladder produced: a rung key
  // for a rung that opened, "guess" for a question that was asked. The panel
  // only ever grows, so what a tap made is always at the bottom and is the one
  // thing that has to be in front of you afterwards. Marked in the body as
  // #hint-focus and handed to scrollToHintPanel as the thing to place.
  let hintFocus = null;
  function focusHint(key) { hintFocus = key; scrollToHintPanel("hint-focus"); }
  // A single clue coming out gets no announcement of its own beyond the tint
  // (and a small burst when it was solved cold, celebrateSolve): 28 messages
  // would be 28 interruptions. The whole grid is the finish — see celebrate().

  // The clue's words, wearing whatever is known about them. Buttons while the
  // question is open, the identical markup as plain spans once it has been
  // answered — because the marked-up clue IS the answer, and it stays on screen
  // underneath the verdict for as long as the solver is on this clue.
  //
  // Nothing here is on a timer: a reading deadline on the one part of this that
  // teaches anything would defeat it. The animations are entrances — they say a
  // thing has arrived, they do not say how long you have with it.
  function guessWordsHTML(tokens, mk, picked, known, rung, target) {
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
      ? `<span class="gw${settled.indexOf(i) >= 0 ? " known" : cls(i)}">${escClue(t.text)}</span>`
      : `<button type="button" id="gw-${i}" class="gw${cls(i)}${
          nuxPointsWord({ target: target }, i, picked) ? " walk-point" : ""}">${escClue(t.text)}</button>`);
    // "ask" while it is the question, "mk" once it has been graded. The two are
    // the same words in two places, and flipCapture/flipPlay use the pair to
    // measure the journey between them.
    //
    // The rung rides along because the colour of a picked word is the colour that
    // KIND of word wears everywhere else on the site: green for a definition,
    // pink for an indicator, so the solver does not learn one colour for
    // "I chose this" and another for the thing they correctly chose.
    return `<p class="guess-clue ${mk ? "mk" : "ask"} pick-${rung || "indicators"}">${
      words.join(" ")}</p>`;
  }

  // The question, asked of the clue itself rather than of a second copy of it:
  // two copies of the same sentence, one lit and unpickable and one pickable and
  // unlit, would have the reader deciding which is the clue before they can start.
  //
  // Marks are ranges over the clue string and words are ranges over that same
  // string, so each word is marked up from its own slice and the gaps between
  // them — the spaces and trailing punctuation — are marked up as themselves,
  // and the enumeration follows the words. Every mark already bought therefore stays lit,
  // inside the word you are pointing at.
  //
  // One mark therefore arrives as a piece per word and a piece per space, and
  // the pieces have to paint as ONE band across the run: a pill's padding and
  // rounding on each piece would draw a bead per word. The pieces say which of
  // them are the run's two ends (markUp's `edges`) and style.css does the rest —
  // see `.guess-clue mark`.
  //
  // Called with no ask (rung not being asked right now) it still wraps every
  // word in the same .gw box, just an inert one: a plain sentence and a row of
  // picking buttons do not share a box model, so reading the clue and then
  // starting to tap it would reflow the whole line under the solver's eye.
  // The box is always there; only its border's colour and its element's
  // interactivity change with the state.
  function pickableClueHTML(e, ask, picked, rung, wheel) {
    const marks = clueMarks(e);
    const italics = italicsOf(e);
    // markUp clips its own cut points to the slice and asks only whether a range
    // covers a position, so a mark that starts before this slice or ends after it
    // needs shifting and nothing else.
    // Curled before it is sliced, so a quote at a slice's edge keeps its context.
    const shown = CTQuotes.curl(clueText(e));
    const slice = (a, b) => markUp(shown.slice(a, b),
      marks.map((m) => ({ i: m.i - a, len: m.len, cls: m.cls })),
      italics.map((r) => ({ at: r.at - a, length: r.length })), true);
    const tokens = ask ? ask.tokens : tokensOfClue(e);
    let out = "", at = 0;
    tokens.forEach((t, i) => {
      const settled = ask && ask.known.indexOf(i) >= 0;
      const inner = slice(t.i, t.i + t.text.length);
      // While the free wheel is open the resting clue's words are its picker:
      // a word in the ring is drawn selected (.on), a tap toggles it.
      const lit = wheel && wheel[i] ? " on" : "";
      out += slice(at, t.i) + (!ask
        ? (wheel && t.text.replace(/[^A-Za-z]/g, "")
          ? `<button type="button" class="gw still${lit}" data-aw="${i}" aria-pressed="${lit ? "true" : "false"}">${inner}</button>`
          : `<span class="gw still">${inner}</span>`)
        : settled
        ? `<span class="gw known">${inner}</span>`
        : `<button type="button" id="gw-${i}" class="gw${
            picked.indexOf(i) >= 0 ? " on" : ""}${
            nuxPointsWord(ask, i, picked) ? " walk-point" : ""}">${inner}</button>`);
      at = t.i + t.text.length;
    });
    return `<span class="guess-clue ${ask ? "ask" : "still"} pick-${rung || "indicators"}">${
      out + slice(at, clueText(e).length) + enumHTML(e)}</span>`;
  }

  // ---------- dragging a run of words ----------
  //
  // A definition is a RUN of words, and pointing at a run is one gesture rather
  // than four taps. A drag ADDS its run to whatever was picked already, so
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
      if (el) el.className = "gw" + (guessing.picked.indexOf(i) >= 0 ? " on"
        : (nuxPointsWord(ask, i, guessing.picked) ? " walk-point" : ""));
    });
    const check = $("guess-check");
    if (check) {
      check.disabled = !guessing.picked.length;
      check.classList.toggle("walk-point", nuxPointsCheck(nuxAsk()));
    }
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
      if (!drag || !guessing) return;
      // Until the finger has committed to going ACROSS the words, a move that is
      // mostly DOWN the page is the page scrolling: .gw is touch-action: pan-y,
      // so the browser will take that gesture, and it fires pointermoves for a
      // while first. Painting on those would light up every word the finger
      // passed over and then hand the gesture away. Once a drag is really under
      // way the axis stops mattering; a run of words wraps, and following it
      // round the wrap is legitimate.
      if (!drag.moved) {
        const dx = Math.abs(ev.clientX - drag.x), dy = Math.abs(ev.clientY - drag.y);
        if (dy > 8 && dy > dx) { drag = null; swallowClick = false; return; }
      }
      dragOver(wordAt(ev.clientX, ev.clientY));
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
    // Once a drag is under way the finger owns the gesture: a slide up or down
    // off the words must not become a page scroll, because the browser would
    // cancel the pointer mid-drag. Before that, pan-y still scrolls the page.
    document.addEventListener("touchmove", (ev) => {
      if (drag && drag.moved && ev.cancelable) ev.preventDefault();
    }, { passive: false });
    // A cancelled pointer is the browser taking the gesture away. A drag that
    // had already crossed words keeps its picks, since sliding off the words is
    // not taking them back; the pointermove guard above has already dropped a
    // gesture that set out as a scroll. The click flag is cleared either way: a
    // cancelled gesture never delivers the click that would have cleared it,
    // and a latched flag would eat the next real tap.
    document.addEventListener("pointercancel", () => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      swallowClick = false;
      if (guessing && moved) renderHintPanel();
    });
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
  // drawn and never again: an entrance that replays is not an entrance, it is a
  // fidget.
  //
  // `quiet` drops the marked words and keeps the sentence, for when the clue line
  // above has become the tapping surface for the NEXT question. Otherwise the
  // panel holds two copies of the same clue — the live one at the top and this
  // graded one further down — and the solver is being told to tap words while
  // looking at a set of identical words that do not answer to a tap. The count and the verdict survive; only the duplicate goes.
  function verdictHTML(g, quiet) {
    const fresh = g.fresh ? " fresh" : "";
    g.fresh = false;
    return `<div class="guess-result${fresh}"><p class="guess-verdict ${
      g.mk.right ? "right" : "miss"}">${esc(g.mk.said)}</p>${
      g.tokens && !quiet ? guessWordsHTML(g.tokens, g.mk, [], g.known, g.rung) : ""}</div>`;
  }

  // Doing a charade IS watching it assemble, so the pieces already placed stay
  // on screen while the next one is asked for: each piece is handed over as it
  // is settled and the list is the rung itself, sitting directly above.

  // One of seven, and the tap IS the answer: there is a single bit to give, so a
  // confirm step would only ask for it twice. Pointing at words keeps its check
  // button because a run of words is assembled before it is offered.
  function guessChoicesHTML(ask) {
    return `<p class="guess-choices">${
      ask.choices.map((c, i) =>
        `<button type="button" id="gc-${i}" class="gc${
          nuxPointing() && c === ask.answer ? " walk-point" : ""}">${esc(c)}</button>`).join("")}</p>`;
  }

  // Words are pointed at up in the clue itself, so a words question has no answer
  // of its own down here: the prompt, and the two buttons that end it. The seven
  // families have nowhere else to live and keep their chips, and so does a linked
  // clue, whose own words are not the ones on display — see renderHintPanel.
  //
  // For a matching question a chunk goes in the slot you last picked it up for. Two taps, both of them
  // reversible: tapping a filled slot puts its chunk back on the strip, so
  // nothing you try costs you anything until Check.
  function guessMatchHTML(ask) {
    const slots = guessing.slots || [];
    const rows = ask.pairs.map((p, i) => {
      const at = slots[i];
      const has = at >= 0;
      const armed = !has && guessing.heldSlot === i;
      return `<li><button type="button" id="gm-slot-${i}" class="gm-slot${
        has ? " on" : ""}${armed ? " armed" : ""}">“${
        esc(p.frag)}” → <span class="gives">${has ? esc(ask.chips[at]) : "?"}</span></button></li>`;
    }).join("");
    // A placed chunk leaves its space on the strip behind it, invisible. If the
    // strip closed up instead, the next chunk would slide under the finger or
    // pointer that just placed one and wear its hover border — which reads as
    // the page picking the next answer out.
    const chips = ask.chips.map((c, i) => slots.indexOf(i) >= 0
      ? `<button type="button" class="gc spent" tabindex="-1" aria-hidden="true" disabled>${esc(c)}</button>`
      : `<button type="button" id="gm-chip-${i}" class="gc${
          guessing.held === i ? " on" : ""}">${esc(c)}</button>`).join("");
    return `<ul class="gm-rows">${rows}</ul><p class="gm-chips">${chips}</p>`;
  }

  // "Just tell me" on a blocks question that would cost a hint is a building
  // block bought, so it takes the same two taps as the rung button.
  function tellHTML() {
    const armed = armedFor(currentEntry(), guessing.rung + "-tell");
    return `<button id="guess-tell" data-arm="${guessing.rung}-tell" class="ghost small${armed ? " arm-cost" : ""}">${
      armed ? ARMED_TEXT : "Just tell me"}</button>`;
  }

  function guessHTML(ask, position, label, inClue) {
    const answer = ask.choices
      ? guessChoicesHTML(ask)
      : ask.pairs ? guessMatchHTML(ask)
      : inClue ? ""
      : guessWordsHTML(ask.tokens, null, guessing.picked, ask.known, guessing.rung, ask.target);
    const ready = ask.pairs
      ? (guessing.slots || []).every((n) => n >= 0)
      : guessing.picked.length;
    const check = ask.choices ? "" : `<button id="guess-check" class="primary${
      nuxPointsCheck(nuxAsk()) ? " walk-point" : ""}"${
      ready ? "" : " disabled"}>Check my answer</button> `;
    return `<div class="hint-step guess"><span class="step-label">${position} · ${esc(label)}</span>
      <p>${ask.prompt}${inClue && !ask.choices && !ask.pairs
        ? ` <span class="tap-hint">Tap them in the clue above.</span>` : ""}</p>
      ${answer}
      <p class="guess-actions">${check}${tellHTML()}
      <button id="guess-later" class="ghost small">Skip for now</button></p></div>`;
  }

  // Right or not, and which one you said — never what the right one was. The
  // rung opens directly underneath and names it, with the paragraph explaining
  // what that family means, and saying it twice in two voices two lines apart
  // reads as the page arguing with itself.
  // A compound clue has every family it is made of, and each of them is a right
  // answer. The one the rung goes on to name is the dominant one, so a solver who
  // named a different true one is told that theirs is in there too — otherwise
  // the paragraph underneath, which names only the main family, reads as a
  // correction of an answer that was correct. One line either way:
  // a family label can be three words long ("container, reversal or deletion"),
  // and a verdict that quotes it back and then explains itself would run to
  // three lines on a phone.
  function gradeChoice(ask, picked) {
    const right = ask.answers || [ask.answer];
    if (picked === right[0]) return { choice: picked, right: true, said: "Yes — that’s the one." };
    if (right.indexOf(picked) >= 0) {
      return { choice: picked, right: true, said: "Yes — that\u2019s one of them." };
    }
    return { choice: picked, right: false,
             said: `Not ${picked.toLowerCase()} — here’s what it actually is.` };
  }

  // Right is the whole set and nothing else. Anything short of that opens the
  // rung too — the point was never to withhold it — but says what was missed,
  // because "wrong" with no account of it is the least useful thing a teacher
  // can say.
  function gradeGuess(ask) {
    // A link word picked along with the definition is no mistake: it only joins
    // the definition to the wordplay, and the rung shows it either way.
    const free = ask.free || [];
    const picked = guessing.picked.filter((x) => free.indexOf(x) < 0).sort((a, b) => a - b);
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
               said: `Yes — solvers disagree on whether “${words}” is part of the definition, so either way counts.` };
    }
    // Either half of a double definition defines the answer on its own, so
    // pointing at one of them, whole and nothing else, answers the question.
    // The other half is painted in with the verdict.
    if (guessing.rung === "definition" && !spare.length && hit.length && ask.spans && ask.spans.length > 1) {
      const one = ask.spans.find((sp) => picked.every((x) => sp.indexOf(x) >= 0)
        && sp.every((x) => picked.indexOf(x) >= 0 || edge.indexOf(x) >= 0));
      if (one) {
        const rest = ask.spans.filter((sp) => sp !== one)
          .map((sp) => sp.map((x) => ask.tokens[x].text).join(" "));
        return { hit: target, spare, missed: [], right: true,
                 said: `Yes — that’s one definition, and “${rest.join("” and “")}” is the other.` };
      }
    }
    // An indicator is a phrase, and which of its words carry the instruction is
    // not the lesson: "according to Spooner", "for Spooner" and "Spooner" all
    // point at the same thing, and marking a solver down for the linking words
    // teaches them nothing except that the app is fussy.
    // Finding every indicator and pointing at nothing else is the whole of what
    // the rung asks, so that is what it marks, and then says the phrase in full.
    // Every span still needs a word of its own: "in" is often an entire
    // indicator, and a rule that let a phrase be dropped altogether would hand
    // the rung over for pointing at one of two.
    if (guessing.rung === "indicators" && !spare.length && ask.spans
        && ask.spans.every((sp) => sp.some((x) => picked.indexOf(x) >= 0))) {
      const said = ask.spans.map((sp) => sp.map((x) => ask.tokens[x].text).join(" "));
      return { hit: target, spare, missed: [], right: true,
               said: missed.length
                 ? `Yes — in full it’s “${said.join("” and “")}”.`
                 : "Yes — that’s exactly it." };
    }
    if (hit.length === n) {
      return { ...v, right: false, said: `You had all ${n}, plus ${spare.length} word${
        spare.length > 1 ? "s that aren’t" : " that isn’t"} doing that job.` };
    }
    if (hit.length) {
      // "Close" only when it is close: picking two words of a four-word
      // definition — half of it, and therefore the wrong split — is not close. A
      // teacher who calls everything close is not marking anything, and the
      // solver reads praise for an answer that was wrong.
      const near = !spare.length && missed.length === 1;
      return { ...v, right: false, said: `${near ? "So close" : "Not quite"} — ${
        hit.length} of ${n} right${spare.length ? `, and ${spare.length} that ${
        spare.length > 1 ? "aren’t" : "isn’t"}` : ""}.` };
    }
    return { ...v, right: false, said: "Not those. Here’s where they actually are." };
  }

  // The marked clue is the same words in a different place. The question sits at
  // the bottom of the panel, under everything already bought; the verdict belongs
  // beside the rung it judged, which is wherever that rung falls in the ladder.
  // Re-rendering puts it there instantly, and the whole panel reads as a lurch.
  //
  // FLIP: measure where it was, let the render happen, put it back with a
  // transform and then let it travel. The eye follows the one thing that did not
  // change, which is the thing worth reading. Everything is guarded because this
  // is decoration — a DOM without getBoundingClientRect gets the same panel,
  // arriving in one step.
  //
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
      el.style.transition = "transform var(--mo-in) var(--mo-ease)";
      el.style.transform = "";
    });
  }

  // Paul 10-30: "When you finish a hint ring it should go to the next." What
  // finishing one means here is a rung done and the ladder's next question
  // being the obvious thing to do, so the app asks it rather than waiting for
  // the tap on a button that is already leading the row. Only ever a QUESTION:
  // asking costs nothing and an answer earns the rung, whereas opening a rung
  // with no question is a purchase and stays behind its two-tap button. What
  // comes next is what the row leads with: the rest of the building blocks
  // while pieces are left, else the first rung not yet up that is available
  // and can be asked.
  function nextQuestion(e) {
    if (!e || isEntrySolved(e) || guessing) return null;
    const ann = annOf(e);
    if (!ann) return null;
    if (isShown(e, "blocks") && piecesLeft(e)) {
      const at = nextPiece(e);
      return guessAsk(e, "blocks", at) ? { rung: "blocks", step: at } : null;
    }
    const steps = ladderSteps(ann, clueText(e));
    const s = steps.find((x) => !isShown(e, x.key));
    return s && GUESSABLE[s.key] && rungAvailable(e, steps, s.key) && guessAsk(e, s.key, 0)
      ? { rung: s.key, step: 0 } : null;
  }
  function advanceLadder(e) {
    const n = nextQuestion(e);
    if (!n) return false;
    const asked = guessAsk(e, n.rung, n.step);
    guessing = { key: entryKey(e), rung: n.rung, step: n.step, picked: [],
                 slots: (asked.pairs || []).map(() => -1), held: -1, heldSlot: -1 };
    return true;
  }

  // Opens the rung and ends the guess, in the same tick as the tap that asked
  // for it. Nothing waits: the answer and the explanation of it arrive together
  // and both stay, so there is no moment the solver has to catch.
  function finishGuess(verdict, ask) {
    if (!guessing) return;
    const e = currentEntry();
    if (!e || entryKey(e) !== guessing.key) { guessing = null; return; }
    const from = flipCapture();
    lastGuess = verdict && { key: guessing.key, rung: guessing.rung, fresh: true,
                             tokens: ask.tokens, known: ask.known, mk: verdict };
    // Earned means every piece taken was pointed at correctly. A rung asked in
    // pieces must not turn into three chances to have already won it, so a
    // wrong one — or a "just tell me" — takes it back off the free list. One
    // rung, one price, one verdict.
    const won = earnedRungs(e).indexOf(guessing.rung);
    if (verdict && verdict.right) { if (won < 0) earnedRungs(e).push(guessing.rung); }
    else if (won >= 0) earnedRungs(e).splice(won, 1);
    // The piece just settled goes up, and only that one (blocksAt holds how many
    // are out). Whether to go on to the next piece is the solver's call, and the
    // rung is theirs either way: a question is never a dead end.
    // A matching question was asked about every piece at once, so every piece
    // is settled by answering it — pacing what the question already covered
    // would be make-work.
    if (guessing.rung === "blocks") {
      // A chip tapped out of turn settles that piece alone: the count must not
      // jump over the pieces before it, so it is marked taken instead.
      if (!ask.pairs && guessing.step > nextPiece(e)) {
        piecesPicked[guessing.key] = (piecesPicked[guessing.key] || 0) | (1 << guessing.step);
      } else {
        revealPiece(e, ask.pairs ? blockPieces(e).length - 1 : guessing.step);
      }
    }
    focusHint(guessing.rung);
    showHint(e, guessing.rung);
    guessing = null;
    // A right answer finishes the rung well; go straight on to the next question.
    if (verdict && verdict.right) advanceLadder(e);
    refreshAll();
    flipPlay(from);
  }

  function earnedRungs(e) {
    const key = entryKey(e);
    return hintsEarned[key] || (hintsEarned[key] = []);
  }

  // `won` marks a rung that was opened by pointing at the right words rather
  // than bought. The verdict banner says so at the moment it happens and is then
  // gone — it is deliberately not persisted — so without this the ladder reads
  // identically whether you earned five rungs or paid for five, and the one
  // number the site is for disappears as soon as you scroll.
  function hintStepHTML(step, position, won, ruleOpen) {
    return `<div class="hint-step${won ? " won" : ""}"><span class="step-label">${
      position} · ${esc(step.label)}${
      won ? '<span class="step-won">worked out · free</span>' : ""}</span>${
      withRuleChip(step.html, step.rule, step.key, !!ruleOpen)}${step.after || ""}</div>`;
  }

  // Where the answer's words break, read straight off the clue's own
  // `enumeration`: 3,6 is three boxes, a gap, then six. The grid cannot show
  // this — its squares run on regardless — so the strip is the only place a
  // solver can see that they are looking for two words rather than a nine-letter
  // one, which rules out most of what they were considering.
  //
  // Trusted only when the digits add up to the squares THIS entry has. A linked
  // clue prints the whole group's enumeration on its first leg, so applying it
  // to one leg would draw the breaks in the wrong places; a mismatch means no
  // breaks rather than wrong ones, and so does anything that isn't digits and
  // separators ("(two words)" and friends). "." is a separator because feeds do
  // print (6.6) where they mean (6,6).
  const ENUM_SEPS = { ",": " ", " ": " ", "-": "-", "–": "-", "—": "-", "'": "’", "’": "’", ".": " " };
  function enumBreaks(enumeration, cells) {
    if (!enumeration) return null;
    const breaks = {};
    let n = 0;
    for (const tok of enumeration.match(/\d+|\S/g) || []) {
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
    // The walk's last instruction points at this strip, so the strip is what
    // wears the pulse — same mark the grid's own empty squares take.
    const typeIt = nuxTypeIt(e);
    const breaks = enumBreaks(e.clue.enumeration, cs.length);
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
      if (typeIt && !c.letter) cls.push("walk-point");
      const title = (c.letter ? esc(c.letter) : "blank") + (isChecked ? ", shared with a crossing answer" : ", no crossing answer");
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
      + (unchecked ? `${checked} shared with crossing answers, ${unchecked} not (dashed boxes)`
                   : `all ${checked} shared with crossing answers`);
    // The note is for screen readers only. Printed next to the boxes it would
    // restate what the boxes already show — which squares have letters, and
    // which are dashed — in prose sitting directly under the clue you are
    // trying to read. The clue is what the box is for; every
    // line that is not the clue pushes it further from being read.
    //
    // How many boxes and how many word breaks, so the strip can size itself down
    // to fit the panel instead of stacking one word per line. CSS cannot count
    // letters and JS should not be measuring screens, so the count comes from
    // here and the arithmetic stays in the stylesheet next to the box geometry.
    const brk = segs.length ? segs.length - 1 : 0;
    return `<span class="pat-boxes" role="img" style="--n:${cs.length};--w:${brk}"`
         + ` aria-label="${esc(note)}">${html}</span>`;
  }

