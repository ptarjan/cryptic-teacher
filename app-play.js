"use strict"; // app part 3 of 7 (selection, typing, checking, the hint ladder). Classic script sharing the page scope with its siblings; see tools/app_src.js.
  // ---------- selection & movement ----------
  // The clue being worked on: in a jigsaw the one picked off the list, anywhere
  // else the light under the cursor unless an off-grid clue was picked.
  function currentEntry() { return jigsaw || (pick && pick.offGrid) ? pick : gridEntry(); }
  // The light under the cursor, which typing, checking and clearing act on.
  function gridEntry() {
    const c = cells[cur.y] && cells[cur.y][cur.x];
    if (!c) return null;
    const id = c[cur.dir] || c[cur.dir === "across" ? "down" : "across"];
    const e = id ? byId[id] : null;
    // On a light that leads two answers, the one picked off the clue list.
    const v = leadPick && byId[leadPick];
    return v && e && v.base === id ? v : e;
  }

  // Choosing a clue should put the clue in front of you. On a phone the layout
  // is a single column — grid, toolbar, hint panel, then the clue lists — so
  // picking an entry updated a panel that was off the bottom of the screen if
  // you'd come from the grid and off the top if you'd come from the list, and
  // either way you had to go looking for it. block:"nearest" is what keeps
  // this from being annoying: it scrolls the least it can, and does nothing at
  // all when the panel is already visible, which is the desktop two-column
  // case. Typing and the arrow keys do not come through here — scrolling on
  // every keystroke would be intolerable.
  // A little air above the panel when it is scrolled to the top of the screen,
  // so it reads as the top of something rather than as a cut-off.
  const HINT_SCROLL_GAP = 8;
  // scrollIntoView({block:"nearest"}) would take two goes on an iPad in
  // portrait: one tap moves a little, the next moves the rest. Three rules
  // avoid that.
  //
  // Measure late. refreshAll() has just rewritten the panel and a
  // different clue is a different height — fewer rungs up, a longer clue, a
  // wider letter strip — so the page reflows and, on iOS, the smooth scroll in
  // flight gets clamped against a document that changed under it. Measure after
  // layout, never in the same tick as the tap.
  //
  // Place absolutely. "nearest" scrolls the least it can FROM WHERE YOU ARE,
  // so the same tap lands somewhere different depending on where you started,
  // which is what "a bit, then all the way" is. Computing one absolute target
  // makes the move idempotent: after it, the panel is fully on screen, so the
  // next tap takes the already-visible branch and the page holds still. That
  // branch is also what keeps the desktop's two columns from ever scrolling.
  //
  // Measure the screen the reader can see. iOS does NOT shrink window.innerHeight
  // when the soft keyboard comes up: the layout viewport stays its full height
  // and the keys sit on top of the bottom third of it, so a panel judged "fully
  // in view" against it can be parked behind them, on an iPad. visualViewport is
  // the part still showing — and since tapping a clue also raises the keyboard,
  // this is the ordinary case, not an edge one.
  //
  // The band of the page you can actually see, in the same client coordinates
  // getBoundingClientRect() speaks. offsetTop is where the visible part starts
  // inside the layout viewport (the keyboard can push it down as well as cut it
  // short). innerHeight is the fallback for browsers without visualViewport.
  function visibleBand() {
    const vv = window.visualViewport;
    const band = (vv && vv.height) ? { top: vv.offsetTop || 0, bottom: (vv.offsetTop || 0) + vv.height }
      : { top: 0, bottom: window.innerHeight || 0 };
    // The home-screen app's tab bar (appnav.js) covers the foot of the screen;
    // a panel parked under it is as hidden as one under the keyboard.
    const bar = document.querySelector && document.querySelector(".tabbar");
    const rect = bar && bar.getClientRects && bar.getClientRects().length && bar.getBoundingClientRect();
    if (rect && rect.height) band.bottom = Math.min(band.bottom, rect.top);
    return band;
  }
  // One tap, one move. Scrolling the moment the tap is handled and then
  // re-placing on every visualViewport resize is a fight a phone cannot win.
  // Three things go wrong at once, and all three are the same mistake:
  // SCROLLING BEFORE THE VIEWPORT HAS STOPPED MOVING.
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
  // never look again. That reads as "worked for some but not others" on an
  // iPhone: identical code, and whether it lands depends on whether the
  // keyboard beat the deadline.
  //
  // The trigger is deliberately NOT "does the panel look wrong now" — the smooth
  // scroll is very likely still in flight at this point, so the panel legitimately
  // looks wrong and re-scrolling on that is the wiggle again. It is whether the
  // keyboard is in a different state from when we placed (see
  // confirmHintPlacement). The target
  // is safe to recompute mid-flight: y + r.top is the panel's position in the
  // document, which scrolling does not change.
  const HINT_CONFIRM_MS = 450;
  // The first tap of a session is the slow one: the keyboard has never been
  // raised, so iOS builds it cold — keys, then the predictive bar — and the
  // resize can land well past deadline + one confirm.
  // Every later tap finds the keyboard already up, resizes nothing, and lands on
  // the first placement, which is why only the first one misses.
  //
  // So the confirming look WAITS for the viewport to go quiet instead of firing
  // at a fixed delay: a viewport event inside the watch window pushes it further
  // out, and the window bounds how long it can be pushed.
  //
  // The correction is gated on the keyboard, not on a count of moves (see
  // confirmHintPlacement). Our own smooth scroll moves the visual viewport,
  // which fires the same events the keyboard does, so a correction that fired on
  // any viewport event would be a loop feeding on its own output: a pan and a
  // keyboard both just move the band. Whether a keyboard is up does not change
  // under our own scroll, so a correction gated on it cannot loop.
  //
  // How long the correction stays available after the tap. A keyboard that
  // has not started coming up yet looks exactly like a viewport that is never
  // going to move — both are silence — so the placement goes ahead against the
  // band as it is, and this window is the room the keys have to arrive in and be
  // scrolled clear of. Long enough for a cold first keyboard, which is the slow
  // one; past it the page belongs to the reader again.
  const HINT_WATCH_MS = 5000;
  // Taller than any URL bar, shorter than any soft keyboard: the two are an order
  // of magnitude apart, so nothing hinges on where in the gap this sits.
  const KEYBOARD_MIN_PX = 100;
  function keyboardUp() {
    const vv = window.visualViewport;
    const ih = window.innerHeight || 0;
    return !!(vv && vv.height && ih && ih - vv.height >= KEYBOARD_MIN_PX);
  }
  // Nothing is ever waited for. A tap CANNOT know whether a keyboard is coming:
  // an iPad with a hardware keyboard, or one whose keyboard was dismissed with
  // the chevron, looks exactly like a phone about to raise one, so any rule
  // for guessing it holds the page still for a second on the devices where the
  // keys were never coming.
  // So: place on the settle, always, and if a keyboard does turn up it is a
  // viewport change like any other and confirmHintPlacement re-places for it.
  // A tap that guessed right costs one move; the phone that raises keys pays for
  // the correction, which is the way round it should be.
  let settleTimer = null, settleBy = 0, confirmTimer = null, placedKeys = null,
      watchUntil = 0;
  // What this tap is bringing into view. The panel itself for a new clue; the
  // rung that just opened for a tap on the ladder, because a panel taller than
  // the screen is placed by its TOP and the new rung is at the bottom, so
  // "scroll the panel into view" shows a solver everything except the thing
  // they just asked for.
  // And the panel it belongs to: the thing that has to be on the page for any of
  // this to mean anything, and what the target falls back to. Defaulting both to
  // the hint panel keeps every existing caller saying what it said; the finish
  // box passes its own, because the viewport rules here are the VIEWPORT'S —
  // a keyboard covers a scoreline exactly the way it covers a hint.
  // And where the target ends, when it is a run of the panel rather than one
  // box: the letter strip's tap targets the clue down to the strip, because
  // that is what someone typing reads. Both are on screen when the strip is
  // tapped, so nothing moves until the keys cover them, and then once.
  let placeTargetId = "hint-panel", placeOwnerId = "hint-panel", placeEndId = null;
  function scrollToHintPanel(targetId, ownerId, endId) {
    placeTargetId = targetId || "hint-panel";
    placeOwnerId = ownerId || "hint-panel";
    placeEndId = endId || null;
    const now = Date.now();
    settleBy = now + HINT_DEADLINE_MS;
    watchUntil = now + HINT_WATCH_MS;
    if (confirmTimer) { clearTimeout(confirmTimer); confirmTimer = null; }
    armHintPlacement();
  }
  function armHintPlacement() {
    if (settleTimer) clearTimeout(settleTimer);
    // The settle, or what is left of the deadline if a resize has already eaten
    // most of it: long enough for the layout this tap caused to flush, and short
    // enough that the travel reads as the answer to the tap.
    const left = Math.max(0, settleBy - Date.now());
    settleTimer = setTimeout(() => {
      placeHintPanel();
      armConfirm(HINT_CONFIRM_MS);
    }, Math.min(HINT_SETTLE_MS, left));
  }
  // Re-arming only ever postpones the one confirm this tap is allowed; it never
  // buys another.
  function armConfirm(delay) {
    if (confirmTimer) clearTimeout(confirmTimer);
    confirmTimer = setTimeout(confirmHintPlacement, delay);
  }
  // The correction fires on the keyboard, not on the band. The band cannot say
  // who moved it: OUR OWN SMOOTH SCROLL moves it, because iOS pans the visual
  // viewport under a scroll and slides the URL bar away as well, so a
  // correction keyed on the band would give every well-placed panel a second
  // move — down, then up a little, on iOS.
  //
  // The keyboard can say. It is the one thing we were unsure about when we
  // measured, it is the only thing that can invalidate the placement, and at a
  // hundred pixels it is out of reach of a pan or a toolbar. So: re-place only
  // if the keyboard is not in the state it was in when we placed. A tap that
  // measured the truth costs exactly one move; the correction is left for the
  // tap that guessed.
  // What bounds the correction is the KEYBOARD, not a budget: our own smooth
  // scroll, a URL bar sliding away and a pan all cost nothing and cannot feed
  // the wiggle, because none of them changes whether a keyboard is up. A counted
  // allowance could not tell those apart — whichever event fired first would
  // spend it, and the keys would then come up over the clue with nothing left
  // to move it. Every transition inside the watch window is corrected for —
  // keys up and keys away, however many times either happens — and once the
  // window is past the page belongs to the reader again.
  function confirmHintPlacement() {
    confirmTimer = null;
    if (placedKeys === null || Date.now() > watchUntil) return;
    if (keyboardUp() === placedKeys) return;
    placeHintPanel();
  }
  // Only ever called off that timer, so layout has long since flushed and there
  // is nothing to measure a frame later for.
  function placeHintPanel() {
    settleTimer = null; settleBy = 0;
    const panel = $(placeOwnerId);
    if (!panel || panel.classList.contains("hidden")) return;
    // Falls back to the whole panel whenever the target is not on screen — a
    // rung that this clue does not have, or a render that dropped it.
    let p = (placeTargetId !== placeOwnerId && $(placeTargetId)) || panel;
    if (!p.getBoundingClientRect) return;
    let r = p.getBoundingClientRect();
    if (!r.height && p !== panel) { p = panel; r = panel.getBoundingClientRect(); }
    const end = p !== panel && placeEndId && $(placeEndId);
    const er = end && end.getBoundingClientRect();
    if (er && er.height && er.bottom > r.bottom) {
      r = { top: r.top, bottom: er.bottom, height: er.bottom - r.top };
    }
    const band = visibleBand();
    const vh = band.bottom - band.top;
    if (vh <= 0 || !r.height) return;
    // What we were unsure about when we measured, for confirmHintPlacement to
    // compare against. Recorded even when we decide not to scroll: "already in
    // view" measured against a band the keyboard is still eating is the same
    // wrong answer as any other.
    placedKeys = keyboardUp();
    if (r.top >= band.top && r.bottom <= band.bottom) return;   // all there already
    // A run only decides WHETHER to move. Once it must, the whole panel goes if
    // it fits, so the rungs being typed from stay on screen with it.
    if (end) {
      const pr = panel.getBoundingClientRect();
      if (pr.height <= vh - HINT_SCROLL_GAP) r = pr;
    }
    const y = window.pageYOffset || 0;
    // Too tall to fit, or hanging off the top: line its top up with the top of
    // the band. Otherwise it is below, so pull its bottom up to the band's floor.
    const top = (r.height > vh - HINT_SCROLL_GAP || r.top < band.top)
      ? y + r.top - band.top - HINT_SCROLL_GAP
      : y + r.bottom - band.bottom + HINT_SCROLL_GAP;
    // Smooth: the travel is how the reader keeps their place. Reduced motion
    // gets the jump instead, as everywhere else.
    const still = window.matchMedia &&
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Ours, not the reader's — see markOwnScroll() below the keyboard rules, so
    // the scroll listener that puts the keyboard away on a real scroll ignores
    // the one this line is about to fire.
    markOwnScroll();
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
    window.visualViewport.addEventListener("resize", syncCursor);
  }
  if (document.addEventListener) {
    document.addEventListener("focusin", () => setTimeout(syncCursor, 300));
    document.addEventListener("focusout", () => setTimeout(syncCursor, 300));
  }
  // A keyboard raised for another field is that field's, so focus landing
  // anywhere but the hidden inputs ends the tap's watch: the picker's search
  // box must not drag the page back down to the clue.
  if (document.addEventListener) document.addEventListener("focusin", (ev) => {
    const id = ev.target && ev.target.id;
    if (id === "kbd" || id === "ana-kbd") return;
    watchUntil = 0; settleBy = 0;
    if (settleTimer) { clearTimeout(settleTimer); settleTimer = null; }
    if (confirmTimer) { clearTimeout(confirmTimer); confirmTimer = null; }
  });

  // Every tap on the grid brings the clue to you, including a tap on the entry
  // already selected: 1-across is selected before you touch anything, so
  // starting the puzzle by tapping its first square must still bring the clue
  // into view.
  //
  // Nothing needs gating on the selection changing: typing and the arrow keys
  // do not come through here, and placeHintPanel already does nothing when the
  // panel is fully in the visible band. A tap is a deliberate act; treat every
  // one the same.
  function onCellClick(c) {
    leadPick = null;
    if (!jigsaw) pick = null;
    if (cur.x === c.x && cur.y === c.y) {
      const other = cur.dir === "across" ? "down" : "across";
      if (c[other]) cur.dir = other;
    } else {
      cur.x = c.x; cur.y = c.y;
      if (!c[cur.dir]) cur.dir = c.across ? "across" : "down";
    }
    // Picking a square picks a CLUE and does not raise the keyboard: the first
    // thing the ladder does with a clue you have just picked is ask you a
    // question you answer by tapping, and a keyboard over the bottom half of
    // the screen buries it. The letter strip under the clue
    // is where typing starts, and it is the only thing that summons one.
    // A jigsaw's square picks no clue, so tapping one is a decision to type.
    if (jigsaw) focusKbd(); else keepKbd();
    hintFocus = jigsaw ? hintFocus : null;
    refreshAll();
    if (!jigsaw && currentEntry()) followPick();
  }
  // A touch screen has to be taken to the clue and its letter strip, because
  // that strip is where a soft keyboard is summoned. With a mouse and a
  // keyboard the letters go straight into the grid (the document keydown
  // handler), so a pick leaves the page where it is. CT_PANEL_SCROLL: test
  // harnesses that predate this keep the old behaviour (tools/fake_dom.js).
  function followPick() {
    if (isTouchPrimary() || window.CT_PANEL_SCROLL) scrollToHintPanel();
  }

  // Picking a clue off the list. A jigsaw's clue, and an off-grid one, stays off the grid.
  function selectEntry(e, jumpToStart) {
    if (!jigsaw && !e.offGrid) { moveToEntry(e, jumpToStart); return; }
    hintFocus = null;
    pick = e;
    refreshAll();
    scrollToHintPanel();
  }

  function moveToEntry(e, jumpToStart) {
    hintFocus = null;
    leadPick = e.vid || null;
    if (!jigsaw) pick = null;
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
    followPick();
  }

  const cellAt = (e, i) => cells[e.position.y + (e.direction === "down" ? i : 0)][e.position.x + (e.direction === "across" ? i : 0)];
  const cellInEntry = (x, y, e) =>
    (e.direction === "across" && y === e.position.y && x >= e.position.x && x < e.position.x + e.length) ||
    (e.direction === "down" && x === e.position.x && y >= e.position.y && y < e.position.y + e.length);

  function moveInEntry(delta) {
    const e = gridEntry();
    if (!e) { stepLight(delta); return; }
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
  // Overtyping: when the square just typed in already held a letter, the cursor
  // goes to the very next square in the entry even if that one is filled, so a
  // filled word can be retyped straight through. Only locked squares are skipped.
  function advanceToGap(overtype) {
    const e = gridEntry();
    const light = e ? entryCells(e) : currentLight();
    const i = light ? light.findIndex((c) => c && c.x === cur.x && c.y === cur.y) : -1;
    if (overtype && light && i >= 0) {
      const nxt = light.slice(i + 1).find((c) => c && !cellConfirmed(c));
      if (nxt) { cur.x = nxt.x; cur.y = nxt.y; return; }
    }
    if (!e) {
      const gap = light && light.slice(i + 1).find((c) => !c.letter);
      if (gap) { cur.x = gap.x; cur.y = gap.y; } else stepLight(1);
      return;
    }
    for (let j = i + 1; j < e.length; j++) {
      const c = cellAt(e, j);
      if (!c.letter) { cur.x = c.x; cur.y = c.y; return; }
    }
    moveInEntry(1);
  }

  function stepEntry(delta) {
    const e = gridEntry();
    const lights = entries.filter((g) => !g.offGrid);
    let i = lights.indexOf(e);
    i = (i + delta + lights.length) % lights.length;
    moveToEntry(lights[i], true);
  }

  // ---------- typing ----------
  // A word this puzzle has confirmed is not yours to unmake. Every letter in it
  // is right and the grid has said so, so there is nothing a keystroke on one
  // can be except an accident — including the accident of backspacing through it
  // from the crossing entry you are actually typing in, which is the same letter
  // seen from the side.
  // Typing over a letter is a delete with a letter on the end of it, so it is
  // refused in the same place. Clearing the whole puzzle still clears it: that
  // is asked for, by name, and this is only ever about the accidents.
  // A lock nobody can see is a keyboard that reads as broken, so every refusal
  // answers on the square it was refused on: the letter pulses, and the cursor
  // moves the way the keystroke was asking it to. The grid itself stays unpainted
  // — a standing tint on finished words is noise across a filling grid.
  function confirmedCells() {
    const s = new Set();
    entries.forEach((e) => {
      if (isEntrySolved(e)) entryCells(e).forEach((c) => { if (c && c.letter) s.add(c); });
    });
    return s;
  }
  function cellConfirmed(c) { return !!c && !!c.letter && (c.printed || confirmedCells().has(c)); }

  function typeLetter(ch) {
    const c = cells[cur.y][cur.x];
    if (!c) return;
    if (cellConfirmed(c)) { pulseCells([c]); advanceToGap(true); refreshAll(); return; }
    const overtype = !!c.letter;
    beacon("letter");
    c.letter = ch; c.wrong = false; c.revealed = false;
    checkSolvedEntries(true);
    advanceToGap(overtype);
    refreshAll(); saveState();
  }

  function clearCell(c) {
    if (!c) return;
    if (cellConfirmed(c)) { pulseCells([c]); return; }
    c.letter = ""; c.wrong = false;
  }

  // A locked letter is not yours to delete, but Backspace on one still has to
  // move: the square before it is the one that was being reached for, and a
  // cursor that stays put reads as a dead key. It moves one square per press,
  // the mirror of typing's advance, and deletes nothing on the way — the letter
  // behind the lock was not the one under the cursor.
  function backspace() {
    const c = cells[cur.y][cur.x];
    if (cellConfirmed(c)) { pulseCells([c]); moveInEntry(-1); refreshAll(); return; }
    if (c && c.letter) clearCell(c);
    else { moveInEntry(-1); clearCell(cells[cur.y][cur.x]); }
    refreshAll(); saveState();
  }

  function onKey(ev) {
    if ($("app").classList.contains("hidden")) return;
    // A key on the grid hands the clue back from an off-grid one to the cursor's.
    if (!jigsaw && pick) { pick = null; refreshAll(); }
    const k = ev.key;
    if (squareKey(k)) { typeLetter(k.toUpperCase()); ev.preventDefault(); }
    else if (k === "Backspace") { backspace(); ev.preventDefault(); }
    else if (k === "Delete") { clearCell(cells[cur.y][cur.x]); refreshAll(); saveState(); ev.preventDefault(); }
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
    focusHidden(kbd);
  }
  // The hidden inputs are focused at the top of the band you can see, because
  // iOS scrolls the focused element clear of the keyboard as the keys come up,
  // and preventScroll does not stop that one. Anywhere the keys can cover is a
  // second scroll racing placeHintPanel's: halfway down the layout viewport is
  // under an iPad's landscape keyboard. Placed on every focus rather than once,
  // because the band's top moves whenever iOS pans the visual viewport.
  function focusHidden(el) {
    const vv = window.visualViewport;
    el.style.top = ((vv && vv.offsetTop) || 0) + "px";
    el.focus({ preventScroll: true });
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
  // BACK — so on that one state this function would summon the very thing it exists
  // to avoid summoning. There is nothing
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

  // A real scroll should put the soft keyboard away. On a phone it eats half the
  // screen while any input is focused, and scrolling is exactly what you do to
  // read the clue, the ladder or the grid out from under it.
  //
  // Every focusable text field is covered, not just the grid's #kbd — the picker
  // search box and the sync join-code field raise the same keyboard and deserve
  // the same courtesy.
  //
  // Two things must NOT trigger this. First, placeHintPanel()'s own
  // window.scrollTo() moves the reader without their asking, and it must never
  // blur what they were typing — that would drop the very keyboard a hint tap is
  // about to need again. Sniffing touch or scroll distance cannot tell our
  // scroll apart from a genuine flick; only knowing we started one can, so every
  // call the app makes to move the page marks a guard window and this listener
  // stays quiet until it passes. Long enough to cover a smooth-scroll animation
  // in flight, short enough that a reader who then keeps scrolling for a real
  // reason is not kept waiting.
  //
  // Second, a desktop scroll wheel: there is no soft keyboard to reclaim the
  // screen there, and losing focus mid-type under a mouse would just be
  // maddening. Gated on the same touch signal as the rest of this file.
  //
  // Paul 10-30: "Dropping the keyboard all the time might be wrong. Sometimes I'm
  // slightly adjusting around the clue solve section." So the threshold is a
  // real scroll (about a third of a phone screen), not a nudge: a small
  // adjustment keeps the keyboard, reading down the page still drops it.
  //
  // The threshold is what keeps a 1-2px jitter — or Safari's URL bar collapsing
  // as an ordinary scroll gets going — from counting. It measures from where the
  // page was when this input's focus last drew a scroll event, not from the last
  // event alone, so a real scroll that arrives in many small ticks still crosses
  // it as soon as it has genuinely moved, while a bounce that returns to where it
  // started never does.
  const SCROLL_BLUR_GUARD_MS = 1000;
  const SCROLL_BLUR_PX = 120;
  const SCROLL_BLUR_IDS = ["kbd", "picker-search", "sync-join-code"];
  // A flag on a timer, not a Date.now() deadline: a smooth scroll can still be
  // travelling when the browser fires its last 'scroll' event for it, and the app
  // has no other signal for "has our own animation finished" than waiting the
  // guard back out.
  let ownScroll = false, ownScrollTimer = null;
  let scrollBlurBaseline = null;
  function markOwnScroll() {
    ownScroll = true;
    if (ownScrollTimer) clearTimeout(ownScrollTimer);
    ownScrollTimer = setTimeout(() => { ownScroll = false; ownScrollTimer = null; }, SCROLL_BLUR_GUARD_MS);
  }
  function onPageScroll() {
    if (typeof navigator === "undefined" || !navigator.maxTouchPoints) return;
    const el = document.activeElement;
    if (!el || SCROLL_BLUR_IDS.indexOf(el.id) === -1) { scrollBlurBaseline = null; return; }
    if (ownScroll) return;
    const y = window.pageYOffset || 0;
    if (scrollBlurBaseline === null) { scrollBlurBaseline = y; return; }
    // Blur only, never anything that touches value or app state: the keyboard
    // leaves, whatever was already typed stays exactly where it was.
    if (Math.abs(y - scrollBlurBaseline) >= SCROLL_BLUR_PX) { scrollBlurBaseline = null; el.blur(); }
  }
  if (document.addEventListener) document.addEventListener("scroll", onPageScroll);

  // ---------- checking / revealing ----------
  function canCheck() { return hasSolutions(); }

  // A check must ALWAYS visibly answer (a check that changed nothing on screen
  // would read as a broken button). Two signals:
  // a sentence in #check-result saying what was found, and a brief pulse on the
  // squares that were examined, so you can see WHICH squares the check covered.
  function checkCells(list, scope) {
    if (!canCheck()) return;
    beacon("check");
    let wrong = 0, right = 0, blank = 0;
    list = list.filter((c) => !c.printed);
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

  // Paper mode's first "I'm done" on a grid that is not right: whether it is
  // solved, and nothing about where. No count either, since "1 wrong" is
  // already a clue to which one. Held until the solver acts, not timed out,
  // because it is the answer to the question they asked.
  function announceVerdict(blank) {
    const el = $("check-result");
    if (!el) return;
    clearTimeout(checkMsgTimer);
    el.className = "check-result bad";
    el.textContent = (blank
      ? `Not solved yet — ${blank} square${blank === 1 ? "" : "s"} still empty.`
      : "Not right yet — at least one letter is wrong.")
      + " Keep going, or press “Show what’s wrong”.";
  }

  function pulseCells(list) {
    list.forEach((c) => { if (c.el) c.el.classList.add("pulse"); });
    setTimeout(() => list.forEach((c) => { if (c.el) c.el.classList.remove("pulse"); }), 600);
  }

  // A tint that settles away on the cells you just finished: a gentle
  // celebration when a clue is solved. Only
  // typeLetter's call into checkSolvedEntries passes viaType,
  // so this never fires from revealLetter or fillAnswer: a revealed answer is
  // not a solve. class add/remove, same shape as pulseCells above, so a
  // reduced-motion visitor still gets the held tint the CSS falls back to.
  //
  // Solved with no hints and no letter reveals gets the gold ("clean") tier
  // instead of the green one — same duration, same easing, colour only.
  // noHintsSolve() reads solvedWith/revealsUsed, both persisted for scoring, so
  // the distinction needs no extra storage and survives a reload the same way
  // the score does.
  function celebrateSolve(e) {
    nuxAdvance();
    const clean = noHintsSolve(e);
    const cs = entryCells(e);
    cs.forEach((c) => {
      if (!c.el) return;
      c.el.classList.add("solved-flash");
      if (clean) c.el.classList.add("clean");
    });
    setTimeout(() => cs.forEach((c) => {
      if (c.el) c.el.classList.remove("solved-flash", "clean");
    }), 450);
    // A clue solved cold earns a pop of its own, over the box being worked in:
    // the clue panel's own letter boxes, then the panel, and the entry's middle
    // square only when neither is on screen.
    if (clean) {
      const mid = cs[Math.floor(cs.length / 2)];
      const target = onScreenBox($("hint-pattern")) || onScreenBox($("hint-panel")) || (mid && mid.el);
      if (target) fireworksAt(target, 1, 28);
    }
  }
  // el, if it has a laid-out box at least partly inside the window; else null.
  function onScreenBox(el) {
    if (!el || !el.getBoundingClientRect) return null;
    const r = el.getBoundingClientRect();
    const vh = window.innerHeight || Infinity;
    return r.height > 0 && r.bottom > 0 && r.top < vh ? el : null;
  }

  // True once an entry is solved for the price of nothing: no rung was charged
  // against it (hintsCharged, frozen in solvedWith the moment it solved) and no
  // letter was revealed on it (revealsUsed, the escape hatch). Both are the
  // exact figures the scorebar's own "n with no hints" tally already reads
  // (renderScore below), put through the one rule, cleanSolve.
  function noHintsSolve(e) {
    if (!isEntrySolved(e)) return false;
    return cleanSolve(hintsCharged(e), revealsUsed[entryKey(e)]);
  }
  function entryCells(e) {
    const out = [];
    if (!e.offGrid) for (let i = 0; i < e.length; i++) out.push(cellAt(e, i));
    return out;
  }

  function revealCell(c) { c.letter = c.sol; c.wrong = false; c.revealed = true; }

  // Escape hatch, available at ANY hint level: reveal one letter. It doesn't
  // advance the teaching ladder, but it does count against the score.
  function revealLetter() {
    const e = currentEntry();
    const light = !e && currentLight();
    if (light && canCheck()) {
      const cSel = cells[cur.y][cur.x];
      const target = cSel.letter !== cSel.sol ? cSel : light.find((c) => c.letter !== c.sol);
      if (target) revealCell(target);
      refreshAll(); saveState();
      return;
    }
    if (!e || !canCheck()) return;
    if (e.offGrid) {
      // The first letter of the box that is missing or wrong.
      const i = [...e.solution].findIndex((ch, j) => e.typed[j] !== ch);
      if (i < 0) return;
      e.typed = e.solution.slice(0, i + 1) + e.typed.slice(i + 1);
      e.revealed = true;
      const key = entryKey(e);
      revealsUsed[key] = (revealsUsed[key] || 0) + 1;
      checkSolvedEntries(); refreshAll(); saveState();
      return;
    }
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
    focusHint(ANSWER_RUNG);
    showHint(e, ANSWER_RUNG);
    entryCells(e).forEach(revealCell);
    if (e.offGrid) { e.typed = e.solution; e.revealed = true; }
    checkSolvedEntries(); refreshAll(); saveState();
  }

  // What the grid holds, and what the solver is told: the same thing except on
  // paper, where nothing is solved until "I'm done" (see paper mode above).
  function lettersRight(e) {
    if (!e.solution) return false;
    if (e.offGrid) return e.typed === e.solution;
    for (let i = 0; i < e.length; i++) if (cellAt(e, i).letter !== e.solution[i]) return false;
    return true;
  }
  function isEntrySolved(e) { return !paperHides() && lettersRight(e); }

  // The whole of a linked group, not one leg of it: a linked clue's hints cover
  // both entries, so getting the first must not hand over the second.
  function groupSolved(e) {
    const h = holderOf(e);
    return (h.group || [entryId(h)]).map((id) => byId[id]).filter(Boolean).every(isEntrySolved);
  }

  // Solving the clue with the building blocks open does NOT turn that rung into
  // a worked-out one. Every free way onto the rung marks it earned when it opens
  // (a question answered, or a piece whose letters are already in the clue), and
  // every other way asked for two taps under "costs a hint". A blocks rung that
  // is shown but not earned was therefore bought, and refunding it at the solve
  // left the warning a lie: Paul, on 28A THANE, "This said it would cost a clue
  // but didn't" — the clue kept its star and read "no hints at all".

  // viaType marks the one call (typeLetter) that represents an actual solve;
  // revealLetter and fillAnswer call this too, so solvedWith is frozen for them
  // as well, but must not trigger celebrateSolve() — revealing the
  // rest of an answer is not the moment being celebrated.
  function checkSolvedEntries(viaType) {
    let typedOne = false;
    entries.forEach((e) => {
      if (isEntrySolved(e) && solvedWith[entryId(e)] === undefined) {
        solvedWith[entryId(e)] = Math.max(0, shownRungs(e).length - earnedRungs(e).length);
        // You were being quizzed on a rung of this clue and then you solved it
        // from the grid. Leaving the question up asks you to go on hunting for
        // the definition in a clue you have already beaten — the same reason
        // the rung buttons stop quizzing once a clue is solved. So hand the
        // rung over instead of dropping the guess on the floor: you were owed
        // an explanation and the score is settled anyway, so it is free.
        // Marked WORKED OUT, not merely handed over. The score is already
        // settled above and the rung is free either way, but the panel says
        // which rungs were earned and which were bought, and a handed-over rung
        // would look bought. Solving the clue is a better answer to
        // "which words define it" than pointing at the words, so it is scored
        // as one.
        if (guessing && guessing.key === entryKey(e)) {
          if (earnedRungs(e).indexOf(guessing.rung) < 0) earnedRungs(e).push(guessing.rung);
          showHint(e, guessing.rung);
          guessing = null;
        }
        beacon("entry");
        if (viaType) { celebrateSolve(e); typedOne = true; }
      }
    });
    // After the loop, not inside it: one letter can finish two clues, and a
    // save taken between them would price the second as clean.
    if (typedOne) noteMilestone();
  }

  // ---------- hint ladder ----------
  // The ladder is BUILT PER CLUE, not fixed: a rung only exists if it has
  // something to say. A double definition has no indicators, so it gets no
  // "spot the indicator" rung, and
  // its rungs are worded for two definitions rather than one. See docs/APP.md.
  const FILL_LABEL = "Fill in answer";

  // The clue types and their families, from tools/data/clue_types.json by way
  // of the list. An annotation's `type` is an array of type names.
  //
  // The type rung must not hand the mechanism over. It names the FAMILY — the
  // shape of the job — and the precise (honest, compound) type is held back
  // until the building-blocks rung. The families are in precedence order: the
  // first one a compound type uses is the one the rung names. See docs/APP.md.
  //
  // A family's `n` is how many annotated clues in puzzles/ it is a correct
  // answer for — grading accepts every family a compound type uses, so that is
  // the count a solver's odds actually run on. It orders the chips, not the
  // families; tools/smoke_test.js recounts the corpus and fails if a share has
  // drifted.
  const TYPES = Object.fromEntries(INDEX.clueTypes.types.map((t) => [t.name, t]));
  const FAMILIES = INDEX.clueTypes.families;

  // The chips the type rung offers, commonest first. The families are in
  // precedence order, so that order cannot also be the order a solver reads: read
  // as one it would open with "Definitions only" and "&lit", which are among the
  // rarest families, in front of every solver on every clue.
  //
  // Only the families that are a real share of the corpus get a chip (at least
  // PICKER_SHARE of all the family counts). A rarer one -- rebus, reverse clue --
  // would be a button that is almost never right, so it is folded into the
  // family its `picker` names: a clue of that family is answered by that chip,
  // while the hint, the walkthrough and the explanation still name the real
  // type. See docs/APP.md.
  const PICKER_SHARE = 0.005;
  const FAMILY_TOTAL = FAMILIES.reduce((s, f) => s + f.n, 0);
  const PICKED = FAMILIES.filter((f) => f.n >= PICKER_SHARE * FAMILY_TOTAL);
  const FAMILY_CHIPS = PICKED.slice().sort((a, b) => b.n - a.n).map((f) => f.label);
  function pickerOf(f) {
    return PICKED.includes(f) ? f : FAMILIES.find((g) => g.name === f.picker);
  }

  // Every family a compound type actually uses, dominant one first. A clue can be
  // more than one thing at once, and on a type like "charade with
  // alternate letters" both answers are the truth. The ladder still NAMES one,
  // because a headline has to pick, but marking the others wrong teaches the
  // solver that a clue has exactly one mechanism, which is the opposite of what
  // this rung is for.

  function familiesOf(types) {
    const used = new Set((types || []).map((t) => TYPES[t].family));
    return FAMILIES.filter((f) => used.has(f.name));
  }
  // Every type belongs to a family, so any non-empty type has one.
  function familyOf(types) {
    return familiesOf(types)[0];
  }

  function typeBlurb(types) {
    return (types || []).map((t) => TYPES[t].blurb).join(" ");
  }
  // A type array as a reader says it: "charade + letter selection".
  function typeLabels(types) {
    return (types || []).map((t) => TYPES[t].label).join(" + ");
  }
  // The anagram family's blurb for a clue whose anagram is only part of the
  // answer (see the type rung in ladderSteps). It says the letters fall short
  // and nothing about how the rest is made: that is the blocks rung's to tell.
  const ANAGRAM_PART = "Letters handed to you in the clue get shuffled, but here they make only part of the answer: " +
    "they come up short of the number in brackets, and the rest arrives another way.";
  // The charade family's blurb says "read the wordplay left to right", which is
  // false when the outermost step is a container or a reversal (INHUMAN: HUM + A
  // inside INN), and a solver who believes it joins HUM, A and INN and gets
  // nonsense. So there the rung says the pieces are not simply end to end.
  const CHARADE_MOVED = "The answer is built from pieces each clued separately, but here they do not simply sit " +
    "end to end in the order the clue reads: the clue also turns something round or puts one piece inside another.";
  const movedCharade = (ann) => ["container", "reversal"].includes((ann.wordplay || {}).op);
  // Accented letters count: MAÑANA is six, not five (NFD splits Ñ into N and its tilde).
  const letterCount = (s) => String(s || "").normalize("NFD").replace(/[^A-Za-z]/g, "").length;
  function partAnagram(ann) {
    const made = ((ann.assembly || {}).anagrams || []).map((a) => letterCount(a.gives));
    return made.length > 0 && Math.max(...made) < letterCount(ann.answer);
  }

  // Fixed prose with the clue's answer blanked out. The family and type
  // sentences are written once for every clue of their kind, so each word in
  // them is some clue's answer, and a rung before the walkthrough may not say
  // the answer. Every fixed sentence on those rungs goes through here rather
  // than being worded around the corpus. Whole words, any case; a multi-word
  // answer matches spaced, hyphenated or run together, and each of its words
  // of four letters or more is blanked alone too (shorter ones are "in",
  // "the", and blanking those would gut the sentence).
  function maskAnswer(text, answer) {
    const words = String(answer || "").match(/[A-Za-z]+/g);
    if (!words) return String(text || "");
    const alts = [words.join("[\\s\\-'\u2019]*")];
    if (words.length > 1) alts.push(...words.filter((w) => w.length >= 4));
    return String(text || "").replace(new RegExp(`\\b(?:${alts.join("|")})\\b`, "gi"), "\u2026");
  }

  // The letters a block may show, "" when it may show none.
  //
  // A cryptic definition has no building blocks — having none is what makes it
  // one — so `gives` is never rendered for it. The only "block" a cryptic
  // definition can have is the whole clue → the whole answer, which would hand
  // over the solve (“Might this keep you to time?” → WATCHSTRAP) on a clue whose
  // definition rung has already said there is no separable wordplay here. The
  // validator also refuses a `gives` on a cryptic definition and
  // demands the clue be split, so this suppression is belt to that braces.
  //
  // A block whose letters ARE the whole answer hands over the solve on the rung
  // before the walkthrough, which is the WATCHSTRAP failure again with a
  // different type on it: it happens on almost every hidden word and homophone
  // and most double definitions, because for those devices one block
  // legitimately resolves to the entire word. Suppressed here
  // rather than in the annotation, deliberately — the annotation keeps recording
  // what the block gives, and no wording a future run picks can leak it. What
  // survives is the fragment, the sounded form and the note.
  //
  // One function, because the rung renders these and the pacing counts them. A
  // second copy of the rule would let the two disagree about what a piece is,
  // and then piece 2 of the body sits under question 3.
  function wholeWord(s) { return String(s || "").toUpperCase().replace(/[^A-Z]/g, ""); }
  function blockLetters(ann, b) {
    if (!b.gives) return "";
    if ((ann.type || []).includes("cryptic_definition")) return "";
    const answer = wholeWord(ann.answer);
    if (answer && wholeWord(b.gives) === answer) return "";
    // An arrow from a word to its own letters teaches nothing: “goat” → GOAT is
    // the fragment already printed to the left of it, with the spaces taken out.
    // Anagram fodder is where this happens — the letters ARE the clue's words,
    // so there is no step to show — and the note beside it still says what the
    // fragment is doing there. A block left with neither is dropped by
    // `blockShows`, and a rung left with no blocks is never charged for.
    if (wholeWord(b.gives) === wholeWord(b.clueFragment)) return "";
    // An anagram's result is the solve of that anagram: “Londoners worried” →
    // ORDNELSON left nothing to do but read it off. The piece shows its fodder
    // instead, and nothing when the fodder is words the fragment prints.
    const shuffled = ((ann.assembly || {}).anagrams || [])
      .find((a) => wholeWord(a.gives) === wholeWord(b.gives));
    if (shuffled) {
      const words = String(b.clueFragment || "").split(/\s+/).map(wholeWord);
      const fodder = wholeWord(shuffled.fodder);
      const printed = words.some((w, i) => words.slice(i).some((_, j) => words.slice(i, i + j + 1).join("") === fodder));
      return printed ? "" : shuffled.fodder;
    }
    return b.gives;
  }
  // The rung exists when something will RENDER in it, not when the data holds a
  // field: a clue whose every block is suppressed and carries no note would
  // otherwise charge a hint for a list of clue fragments the solver can already
  // see. No clue in the corpus does that, and this is what keeps it that way.
  const blockShows = (ann, b) => !!(b.note || b.soundsLike || blockLetters(ann, b));

  // A double definition's halves are its definitions, and a block that is one
  // of them and shows nothing but a note is not a building block. The
  // definition rung has already named those words and asked the solver to tap
  // them, and its letters are the whole answer, so a blocks rung made of them
  // asks the same question again and shows nothing new but the note. The note
  // is about that sense of that definition, so it renders on the definition
  // rung beside the split, and the block is no piece of the blocks rung.
  //
  // What the definition rung never named still is one: a third definition, a
  // half that is wordplay, a sounded form. So a compound type keeps its rung,
  // and a clue with three senses keeps the one the split did not mention.
  // The split names the first two definitions. A file holds a third sense as a
  // third definition (WATERLOO's "Single"), and its block stays a building
  // block, so only the split's two count here.
  //
  // Unless the ladder has no blocks rung to carry it: a puzzle that is not a
  // cryptic (straightLadder) is the definition and the walkthrough, so there the
  // split names every sense (cryptic-12581's "Bird — country — flop") and none
  // is left a building block that no rung shows.
  function senseBlock(ann, b) {
    const defs = (ann.definitions || []).slice(0, splitNames(ann));
    if (defs.length < 2 || !(ann.type || []).includes("double_definition")) return false;
    if (b.soundsLike || blockLetters(ann, b)) return false;
    // Digits count: a definition can be a cross-reference ("31"), which has no
    // letters at all.
    const key = (t) => String(t || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    const frag = key(b.clueFragment);
    return !!frag && defs.map((d) => key(d.text))
      .some((d) => d && (d.includes(frag) || frag.includes(d)));
  }
  // A puzzle that is not a cryptic (meta.style, tools/puzzle_style.py) has no
  // wordplay to spot, name or build: its ladder is the definition and the
  // walkthrough. The tag is a puzzle-wide majority (85%), so a clue in it that
  // does carry indicators (times-26's "It sounds sluggish", "(anag.)") is real
  // wordplay and keeps its full ladder. `meta` is the open puzzle's index row;
  // a harness that lifts these functions out of app.js has none.
  function straightLadder(ann) {
    return typeof meta !== "undefined" && !!meta && meta.style === "straight"
      && !(ann.indicators || []).length;
  }
  // How many definitions the definition rung's split names.
  const splitNames = (ann) => (straightLadder(ann) ? Infinity : 2);
  const buildingBlocks = (ann) => (ann.blocks || []).filter((b) => !senseBlock(ann, b));
  const senseBlocks = (ann) => (ann.blocks || []).filter((b) => b.note && senseBlock(ann, b));

  // What an indicator actually INSTRUCTS in this clue. How to recognise the
  // device next time is DEVICE_RULES', below. A line like "these tell you what to do with the rest" is true of
  // every indicator in every clue ever written — content-free, and a rung the
  // solver spends a hint on. The operation is derivable from the type we
  // already store, so this costs nothing and cannot drift from the annotation.
  //
  // Plain language, not the jargon: "rearrange the letters it points at" rather
  // than "anagram indicator". The precise mechanism is still held back for the
  // building-blocks rung (see `mechanics`), and naming the job is the teaching
  // content — naming the term would only be the label.
  const INDICATOR_OPS = [
    ["anagram", "rearrange the letters it points at"],
    ["composite_anagram", "rearrange the letters it points at, once the extra letters the clue names are taken out of them"],
    ["container", "put one piece inside another"],
    ["reversal", "write a piece backwards"],
    ["deletion", "drop letters from a word"],
    ["hidden_word", "find a run of letters already sitting in the clue"],
    ["homophone", "take how a word sounds, not how it is spelled"],
    ["spoonerism", "swap the opening sounds of two words"],
    ["alternate", "take every other letter"],
    ["regular", "count through the letters at a fixed step and keep the ones you land on"],
    ["first", "take the opening letter of the words it points at"],
    ["last", "take the final letter of the words it points at"],
    ["middle", "take just the middle of a word"],
    ["outer", "keep only the outside letters of a word"],
    ["cycling", "move letters from one end to the other, keeping their order"],
    ["move", "take a letter out of a word and put it back somewhere else in that word"],
    ["substitution", "swap one letter or chunk for another"],
    ["palindrome", "check that the answer reads the same in both directions"],
    ["letter_selection", "keep only some of the letters of the words it points at"]
  ];
  // A clue's operations in the order its type applies them. The rows are keyed
  // by type name, except that a letter selection is keyed by what its blocks
  // `select`, falling back to the general letter_selection row.
  function indicatorOps(types, blocks) {
    const row = (k) => INDICATOR_OPS.find(([o]) => o === k);
    const selects = [...new Set(blocks.map((b) => b.select).filter((v) => row(v)))];
    return types.flatMap((k) => k !== "letter_selection" ? [k] : selects.length ? selects : [k])
      .map(row).filter(Boolean);
  }

  // The reusable rule for each device: what its indicator words usually mean
  // and other words that do the same job, so a hint about one clue leaves the
  // solver something to bring to the next. Keyed by clue type, the value an
  // indicator's `for` holds; `learn` is the id of that device's section in
  // tools/tutorial.html, which /learn/ renders (tools/smoke_test.js checks
  // every one exists). The indicator rung shows the rule beside the
  // indicators, and the finish recap links each device it counts to its section.
  //
  // Fixed text written once for every clue, so it is masked and filtered like
  // the family blurbs: `also` drops any word printed in this clue (on the type
  // rung that would point at the indicator, which is another rung's work) and
  // the line goes through maskAnswer.
  const DEVICE_RULES = {
    anagram: { learn: "anagram", means: "shuffle the letters of the words beside it",
      also: ["broken", "wild", "mixed", "novel", "drunk", "poorly", "off", "about"] },
    charade: { learn: "charade", means: "put two pieces side by side in the order it says",
      also: ["after", "before", "with", "by", "next to", "following", "on (in a down clue)"] },
    container: { learn: "container", means: "put one piece inside another",
      also: ["in", "about", "around", "holding", "eating", "embracing", "outside", "swallowing"] },
    reversal: { learn: "reversal", means: "read a piece backwards",
      also: ["back", "returned", "recalled", "over", "around", "up (in a down clue)", "rising (in a down clue)"] },
    deletion: { learn: "deletion", means: "drop letters from a word",
      also: ["headless (the first)", "endless (the last)", "heartless (the middle)", "nearly (the last)", "short", "without"] },
    substitution: { learn: "substitution", means: "swap one letter or piece for another",
      also: ["for", "replacing", "instead of", "in place of", "changing"] },
    palindrome: { learn: "palindrome", means: "the answer reads the same both ways",
      also: ["either way", "both ways", "back and forth", "from either end"] },
    cycling: { learn: "cycling", means: "move a letter from one end of a word to the other",
      also: ["cycling", "rotated", "circulating", "going round", "first to last"] },
    move: { learn: "move", means: "take a letter out of a word and put it back somewhere else in that word",
      also: ["dropping", "moving", "shifted", "going down (in a down clue)", "going up (in a down clue)", "to the right"] },
    hidden_word: { learn: "hidden-word", means: "the letters are already written inside the clue, across the word breaks",
      also: ["in", "some", "part of", "held by", "within", "a bit of", "partly"] },
    letter_selection: { learn: "letter-selection", means: "keep only some letters: the first, last, middle or every other one",
      also: ["initially", "leaders", "finally", "ends", "heart of", "oddly", "regularly", "edges"] },
    homophone: { learn: "homophone", means: "take how a word sounds, not how it is spelled",
      also: ["we hear", "reportedly", "on the radio", "said", "aloud", "announced", "they say"] },
    spoonerism: { learn: "spoonerism", means: "swap the opening sounds of two words",
      also: ["Spooner", "Spooner's", "the Reverend says"] },
    double_definition: { learn: "double-definition", means: "two meanings of one word sit side by side",
      also: ["and", "or", "for", "is", "with"] },
    cryptic_definition: { learn: "cryptic-definition", means: "a word is used in an odd sense",
      also: ["a question mark at the end"] },
    and_lit: { learn: "and-lit", means: "the whole clue is both the wordplay and the definition",
      also: ["an exclamation mark at the end"] },
    rebus: { learn: "rebus", means: "describe the picture the letters make, and the description is the answer",
      also: ["a clue with no lower-case letters", "a question mark at the end"] },
    composite_anagram: { learn: "composite-anagram", means: "the letters beside it are the answer plus some extra letters, shuffled together: take the extras out, then rearrange what is left",
      also: ["broken", "wild", "mixed", "novel", "drunk", "poorly", "off", "about"] },
    reverse_clue: { learn: "reverse-clue", means: "the clue is what the answer's wordplay would produce, so run the wordplay forwards from the answer's pieces",
      also: ["a question mark at the end", "a clue that reads like an instruction but names the result"] }
  };
  // The type rung names only the family, so its rule is the family's: how to
  // spot one next time, without saying which member this clue is. `learn` is
  // where the family's sections start in the lesson.
  const FAMILY_RULES = {
    definition: { learn: "double-definition",
      spot: "suspect one when the clue is short and no word reads as an instruction; a question mark often flags the playful kind",
      also: [] },
    and_lit: { learn: "and-lit",
      spot: "suspect one when the whole clue is wordplay and yet still describes a single thing; an exclamation mark often flags it",
      also: [] },
    rebus: { learn: "rebus",
      spot: "suspect one when the clue has no ordinary words: only capitals, figures and symbols",
      also: [] },
    reverse: { learn: "reverse-clue",
      spot: "suspect one when the clue reads like a piece of wordplay yet the definition leaves nothing else to build: try splitting the answer so its halves, put through the operation the clue describes, give the clue's words",
      also: [] },
    anagram: { learn: "anagram",
      spot: "look for a word suggesting mess or change beside a run of letters to shuffle",
      also: ["broken", "wild", "mixed", "novel", "drunk"] },
    homophone: { learn: "homophone",
      spot: "listen for a word about hearing or speaking, and say the piece beside it aloud",
      also: ["we hear", "reportedly", "on the radio", "said"] },
    charade: { learn: "charade",
      spot: "split the wordplay into short words you can swap for synonyms or abbreviations, and join them left to right",
      also: ["with", "after", "before", "by"] },
    change: { learn: "container",
      spot: "look for a word that says put inside, turn back or cut short, and apply it to the piece next to it",
      also: ["in", "eating", "returned", "up (in a down clue)", "endless", "headless"] },
    selection: { learn: "hidden-word",
      spot: "look for a word saying the letters are already there: hidden in the words beside it, or their first, last or alternate letters",
      also: ["some", "part of", "held by", "initially", "finally", "oddly"] }
  };
  // The INDICATOR_OPS rows that are kinds of letter selection, not types.
  const SELECT_OPS = ["alternate", "regular", "first", "last", "middle", "outer"];
  // The words of `also` this clue does not print and that are not the answer.
  function ruleAlso(also, clue, ann) {
    const said = new Set((String(clue || "") + " " + String(ann.answer || ""))
      .toLowerCase().match(/[a-z']+/g) || []);
    return also.filter((w) => !(w.replace(/\s*\(.*\)$/, "").toLowerCase()
      .match(/[a-z']+/g) || []).every((x) => said.has(x)));
  }
  // A device's section of the lesson. Resolved against the front door like
  // every URL the app builds (addressUrl): a bare "learn/#x" in the hint panel
  // resolves against the address bar, which says /puzzles/<id>/ once a puzzle
  // is chosen, and 404s at /puzzles/<id>/learn/.
  function learnHref(section) { return esc(addressUrl("learn/") + "#" + section); }
  function ruleHTML(text, also, learn, clue, ann) {
    const more = ruleAlso(also, clue, ann);
    return `<span class="device-rule">${esc(maskAnswer(
      text + (more.length ? `; also: ${more.join(", ")}` : "") + ".", ann.answer))}
      <a class="learn-link" href="${learnHref(learn)}">More in the lesson</a></span>`;
  }
  // A rung's general rule sits behind a small chip at the end of its last line,
  // so the rung is no taller until the solver asks for it. `rulesOpen` holds
  // "<entry key>|<rung key>" for each rule opened by a tap on #hint-body.
  const rulesOpen = new Set();
  function withRuleChip(html, rule, rung, open) {
    if (!rule) return html;
    const chip = `<button type="button" class="rule-chip" data-rule="${rung}" aria-expanded="${open}"
      aria-label="${open ? "Hide" : "Show"} the general rule">rule</button>${open ? rule : ""}`;
    const end = html.match(/<\/(p|li)>(\s*<\/ul>)?\s*$/);
    return end ? `${html.slice(0, end.index)} ${chip}${html.slice(end.index)}` : `${html}<p>${chip}</p>`;
  }
  // The indicator rung's rules: one line per device, naming this clue's words
  // for it. The device is the indicator's own `for`; without one, the clue's
  // single operation, when it has exactly one.
  function indicatorRulesHTML(ann, clue, ops) {
    const one = ops.length === 1 ? ops[0][0] : "";
    const fallback = SELECT_OPS.includes(one) ? "letter_selection" : one;
    const byKind = new Map();
    for (const i of ann.indicators || []) {
      const kind = DEVICE_RULES[i.for] ? i.for : DEVICE_RULES[fallback] ? fallback : "";
      if (!kind) continue;
      if (!byKind.has(kind)) byKind.set(kind, []);
      byKind.get(kind).push(i.text);
    }
    return [...byKind].map(([kind, words]) => {
      const r = DEVICE_RULES[kind];
      const who = words.map((w) => `“${w}”`).join(" and ");
      return ruleHTML(`${who} usually ${words.length > 1 ? "mean" : "means"}: ${r.means}`,
        r.also, r.learn, clue, ann);
    }).join("");
  }
  function familyRuleHTML(family, clue, ann) {
    const r = FAMILY_RULES[family.name];
    return r ? ruleHTML(`Next time, ${r.spot}`, r.also, r.learn, clue, ann) : "";
  }

  // The whole answer isn't a teaching rung — it's the end of the road — but it
  // shares the ladder's bookkeeping so it counts against the score like one.
  const ANSWER_RUNG = "answer";
  // Which rungs are up for this clue. A save that holds the legacy high-water
  // integer is migrated lazily here rather than in restoreState(): converting "level 3" into
  // rung keys needs ladderSteps(), which needs the annotation, and at restore
  // time the model isn't built yet. Reading is the first moment both exist.
  function shownRungs(e) {
    const key = entryKey(e);
    if (!hintsShown[key]) {
      const old = hintLevels[key] || 0;
      hintsShown[key] = old > 0
        ? ladderSteps(annOf(e), clueText(e)).slice(0, old).map((s) => s.key).concat(
            old > ladderSteps(annOf(e), clueText(e)).length ? [ANSWER_RUNG] : [])
        : [];
    }
    return hintsShown[key];
  }
  const isShown = (e, rung) => shownRungs(e).indexOf(rung) >= 0;

  // The pieces of the blocks rung, in clue order — the order they are read in
  // and the order the assembly runs in. Every block is one, including the ones
  // whose letters are suppressed: those still show their fragment, which is the
  // whole lesson on a hidden word. A double definition's own halves are not
  // (see senseBlock): the definition rung carries them.
  const blockPieces = (e) => { const a = annOf(e); return a ? buildingBlocks(a) : []; };
  // How many of them are on screen.
  function piecesShown(e) {
    const key = entryKey(e);
    if (blocksAt[key] === undefined) {
      // No count on record, paced or not, means nothing extra beyond what the
      // rung being open already implies — never "hand over every remaining
      // piece". A count that should be here but isn't is a reason to hold
      // back, not a reason to dump the lot.
      blocksAt[key] = 0;
    }
    return blocksAt[key];
  }
  // A piece is out when the count has reached it or the formula took it out of
  // turn. At most 30 pieces can be taken that way (the mask is a 32-bit int);
  // the formula is not offered for a clue with more.
  const PICKABLE = 30;
  const pickedBit = (e, i) => i < PICKABLE && (((piecesPicked[entryKey(e)] || 0) >> i) & 1) === 1;
  const pieceOut = (e, i) => i < piecesShown(e) || pickedBit(e, i);
  const piecesLeft = (e) => blockPieces(e).filter((_, i) => !pieceOut(e, i)).length;
  // The piece the "next" button is for: the first one not out yet.
  const nextPiece = (e) => blockPieces(e).findIndex((_, i) => !pieceOut(e, i));
  // Forwards only, and it is the reveal that moves it — both routes in, being
  // told and pointing at the right words, land here.
  //
  // A piece with no question in it is not a step. Pacing exists so the rung asks
  // before it tells, and a piece that cannot ask has nothing to hold back: the
  // click that fetches it hands it over the instant it lands, which is a tap
  // charged for nothing. So those
  // ride out with the piece before them, and "Next piece" is only ever offered
  // for one that is going to ask something.
  function revealPiece(e, at) {
    const pieces = blockPieces(e);
    let n = Math.max(piecesShown(e), (at || 0) + 1);
    // A piece already taken from the formula has nothing left to ask either.
    while (n < pieces.length && (pickedBit(e, n) || !guessAsk(e, "blocks", n))) n++;
    blocksAt[entryKey(e)] = n;
    saveState();
  }

  // ---------- the formula in the blocks rung ----------
  //
  // Any piece, in any order: a chip in the blocks rung's formula hands over that
  // one piece, the way "Next building block" hands over the next (it asks first
  // when the piece has a question). Which pieces are out is pieceOut's,
  // whichever way they came, so a piece cannot be charged for twice or shown
  // twice. The chips only exist once the rung is open, so a chip never opens it
  // (pickPiece's opening branch is kept for safety, not used by the panel).
  const pickCosts = (e, i) => !!e && !groupSolved(e) && !isShown(e, "blocks") && !blocksFree(e, i);
  function pickPiece(e, i) {
    if (pieceOut(e, i) || i >= Math.min(PICKABLE, blockPieces(e).length)) return;
    // A question about this very piece is moot: it has been told.
    if (guessing && guessing.rung === "blocks" && guessing.step === i) guessing = null;
    if (!isShown(e, "blocks")) {
      if (!groupSolved(e) && blocksFree(e, i) && earnedRungs(e).indexOf("blocks") < 0) earnedRungs(e).push("blocks");
      showHint(e, "blocks");
    }
    const key = entryKey(e);
    piecesPicked[key] = (piecesPicked[key] || 0) | (1 << i);
    saveState();
  }

  // Tiers, not a chain, and not a free-for-all either. Inside a tier the order
  // is the solver's business; across tiers it can't be, because a later rung
  // contains the earlier ones' answers — the building blocks name the
  // definition and the indicators on the way to spelling out the wordplay, and
  // the walkthrough hands over everything. Unrestricted choice
  // would put "skip to the walkthrough" one click from cold,
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
    // Solved: nothing left to protect, so the whole ladder opens. The tiers exist so the walkthrough can't be taken before the
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
    // The pieces count starts at 0 as the rung opens, so the save records it.
    if (rung === "blocks" && blocksAt[entryKey(e)] === undefined) blocksAt[entryKey(e)] = 0;
    shownRungs(e).push(rung);
    // WHICH kind of help was reached for, named for the rung. Each rung teaches
    // a different thing — where the definition sits, what the indicators do, how
    // the blocks assemble — so "which one do solvers ask for" says which lesson
    // to write, which is the only question a teaching site can act on. A depth
    // would answer nothing: the ladder is built per clue, and no number on that
    // scale appears anywhere a solver can see.
    beacon("hint-" + rung);
    // Asked for and got: whatever line is up, the solver has just worked the
    // ladder, which is what all of them are asking for.
    nuxRungTaken(e);
    saveState();
  }

  // The formula, drawn twice. Under the type rung (interactive false) it is a
  // picture: every chip blank, role + letter count, no buttons. Under the
  // building blocks rung (interactive true) it is that rung's picture of
  // progress: a chip still blank is a button for its piece, and a chip whose
  // piece is out (by the count or by a tap here) is filled in with the piece's
  // letters (f.fills). The rung's piece list stays under it because it says WHY
  // (the clue words and the note each piece comes from); the chip repeats only
  // the letters, as the picture of the sum. A tap that would cost arms the chip
  // first (confirmBlock), and the armed chip says so itself, as every other
  // armed button does (Paul: "The required two tap should be uniformly on the
  // button").
  function formulaHTML(e, f, interactive) {
    const armed = interactive && f.chips.some((_, i) => armedFor(e, "piece-" + i));
    const chip = (i) => {
      const label = esc(f.chips[i]);
      // The type rung: a picture, every chip blank (role + letter count).
      if (!interactive) return `<span class="formula-chip">${label}</span>`;
      // A solved clue lists every piece (paced), so its chips are all filled too.
      if (groupSolved(e) || pieceOut(e, i)) return `<span class="formula-chip got">${esc(f.fills[i])}</span>`;
      const a = armedFor(e, "piece-" + i);
      return `<button type="button" class="formula-chip${a ? " arm-cost" : ""}" data-piece="${i}" data-arm="piece-${i}">${
        a ? ARMED_TEXT : label}</button>`;
    };
    // A word told once its chips are out (formulaOf's `when`): the letters a
    // step supplies, drops or makes. Blank on the type rung's picture.
    const told = (p) => interactive && (groupSolved(e) || p.needs.every((i) => pieceOut(e, i)));
    const word = (w) => `<span class="formula-word">${esc(w)}</span>`;
    return `<div class="formula"><span class="formula-lead">${esc(f.lead)}</span> ${
      f.parts.map((p) => (typeof p === "string" ? word(p) : typeof p === "number" ? chip(p) : (told(p) ? p.show : p.hide) ? word(told(p) ? p.show : p.hide) : ""))
        .filter(Boolean).join(" ")}${
      f.after ? ` <span class="formula-word">${esc(f.after)}</span>` : ""}${
      !interactive || armed || !piecesLeft(e) ? "" : `<p class="muted">Tap a piece to see it.</p>`}</div>`;
  }

  // ---------- a building block that costs takes two taps ----------
  //
  // Paul: "If a building blocks can't be free it should make me click twice to
  // confirm I want it." Most ways onto the blocks rung cost nothing — it asks a
  // question first, and pointing at the right words is free; it has already been
  // paid for, so the next piece rides on that; or the clue is solved, so nothing
  // charges any more. What is left is a tap that adds a hint to the clue on the
  // spot. That tap only arms the button, and its label says so; the same button
  // again within a few seconds takes the hint, and a tap anywhere else, focus
  // moving away, or the time running out puts it back.
  //
  // The price is hintsCharged's: rungs shown less rungs earned, frozen once the
  // group is solved. So a tap charges exactly when the group is unsolved and it
  // either opens the blocks rung, or — "Just tell me" on a blocks question —
  // takes back a blocks rung earned by an earlier piece.
  // A piece handed over unasked (guessAsk is null: the last unlit words, or its
  // own letters) whose letters are all printed in the words it names tells the
  // solver nothing they cannot see, so opening the rung on it is not a purchase.
  // Anagram fodder qualifies; a synonym's letters are not in the clue and cost.
  function blocksFree(e, at) {
    if (!e || guessAsk(e, "blocks", at || 0)) return false;
    const b = blockAskAt(e, at || 0);
    if (!b) return false;
    const have = {};
    wholeWord(b.clueFragment).split("").forEach((c) => { have[c] = (have[c] || 0) + 1; });
    return wholeWord(b.gives).split("").every((c) => have[c]-- > 0);
  }

  // Paul: "Anything that immediately costs needs two." Every rung (not only the
  // blocks), "Just tell me", Reveal one letter and the first reveal of the
  // answer go through this one rule and the one confirmBlock helper below.
  function rungCosts(e, rung, tell) {
    if (!e || groupSolved(e)) return false;
    if (!isShown(e, rung)) return rung === "blocks" ? !blocksFree(e, 0) : true;
    return !!tell && earnedRungs(e).indexOf(rung) >= 0;
  }
  const blocksCost = (e, tell) => rungCosts(e, "blocks", tell);
  // Filling the answer in is the paid way to the answer; once the walkthrough
  // or the answer itself is up there is nothing left to protect.
  const fillCosts = (e) => !!e && !groupSolved(e) && !isShown(e, "walkthrough") && !isShown(e, ANSWER_RUNG);

  const ARM_MS = 4000;
  // The button specs/markup for the paid buttons outside the rung row.
  function fillSpec(e, text) {
    if (!fillCosts(e)) return { fill: true, text };
    const armed = armedFor(e, "fill");
    return { fill: true, arm: "fill", cls: armed ? "arm-cost" : "", text: armed ? ARMED_TEXT : text };
  }
  function letterBtnHTML(e) {
    const armed = armedFor(e, "letter");
    return `<button id="hx-letter" data-arm="letter" class="ghost small${armed ? " arm-cost" : ""}">${
      armed ? ARMED_TEXT : "Stuck? Reveal one letter"}</button>`;
  }
  function letterTap(ev) {
    if (!confirmBlock(currentEntry(), "letter", ev)) return;
    revealLetter();
  }
  const ARMED_TEXT = "Tap again to reveal · costs a hint";
  let blockArm = null;   // { key, id, timer }
  // A light with no clue has no entry; it still arms, under a key of its own.
  const armKey = (e) => (e ? entryKey(e) : "light");
  const armedFor = (e, id) => !!(blockArm && blockArm.key === armKey(e) && blockArm.id === id);
  const armOf = (el) => {
    for (let n = el; n && n.getAttribute; n = n.parentNode) {
      const v = n.getAttribute("data-arm");
      if (v) return v;
    }
    return null;
  };
  // Rebuilding the row or the question replaces the button, so a keyboard
  // user's focus has to be put back on its successor or the second Enter lands
  // nowhere.
  function focusArm(id) {
    const el = document.querySelector && document.querySelector(`[data-arm="${id}"]`);
    if (el && el.focus) el.focus({ preventScroll: true });
  }
  function disarmBlock(redraw) {
    if (!blockArm) return;
    clearTimeout(blockArm.timer);
    const id = blockArm.id;
    const had = armOf(document.activeElement) === id;
    blockArm = null;
    if (redraw) { renderHintPanel(); if (had) focusArm(id); }
  }
  // True when the tap should go ahead. A second click inside one double-click
  // (detail 2 and up) is the same gesture as the first and confirms nothing.
  function confirmBlock(e, id, ev) {
    if (window.CT_ONE_TAP) return true;   // test harnesses only (tools/fake_dom.js)
    if (armedFor(e, id)) {
      if (ev && ev.detail > 1) return false;
      disarmBlock(false);
      return true;
    }
    disarmBlock(false);
    blockArm = { key: armKey(e), id, timer: setTimeout(() => disarmBlock(true), ARM_MS) };
    renderHintPanel();
    focusArm(id);
    return false;
  }
  if (document.addEventListener) {
    // Capture, so it sees the tap before whatever it lands on acts on it; the
    // redraw waits a tick so that target's own handler still finds its button.
    const away = (ev) => {
      if (!blockArm || armOf(ev.target) === blockArm.id) return;
      disarmBlock(false);
      setTimeout(renderHintPanel, 0);
    };
    document.addEventListener("click", away, true);    document.addEventListener("focusin", away, true);
  }

  // Where the definition sits, and therefore where the wordplay starts. A fair
  // cryptic splits into exactly two parts and finding that seam is most of the
  // battle, so the seam is what this rung should hand over. It is computable
  // from the clue text, which means every clue gets its own sentence instead of
  // one generic sentence about definitions living at one end. Falls back to a bare full stop when the definition has no span in
  // the clue (a blog underline that is not a literal substring) rather than guessing.
  //
  // A link word touching the definition is the seam itself, not wordplay, so it
  // is dropped from the quoted side: "Inventive musician's remote control sound"
  // quotes "remote control sound", never "'s remote control sound".
  function defPlace(clue, def, links) {
    const c = String(clue || "");
    const i = def && def.text && def.at >= 0 ? cpToIdx(c, def.at) : -1;
    if (i < 0 || c.slice(i, i + def.text.length) !== def.text) return ".";
    // A side with no letters in it ("?" or "!" after a definition that ends the
    // clue) is punctuation, not wordplay, so it must not make the seam mid-clue.
    const trim = (s) => {
      const t = s.trim().replace(/^[,;:.—–-]+|[,;:—–-]+$/g, "").trim();
      return /[a-z0-9]/i.test(t) ? t : "";
    };
    const apos = (s) => s.replace(/[‘’]/g, "'").toLowerCase();
    const lws = (links || []).map((w) => apos(String(w || "").trim())).filter(Boolean);
    const unlink = (s, atStart) => {
      for (const w of lws) {
        const k = apos(s);
        // Whole words only: the next character past the link word must not be
        // a letter, so "for" never eats the front of "forest".
        if (atStart && k.startsWith(w) && !/[a-z0-9]/i.test(k.charAt(w.length)) && trim(s.slice(w.length)))
          return trim(s.slice(w.length));
        if (!atStart && k.endsWith(w) && !/[a-z0-9]/i.test(k.charAt(k.length - w.length - 1)) && trim(s.slice(0, -w.length)))
          return trim(s.slice(0, -w.length));
      }
      return s;
    };
    const before = unlink(trim(c.slice(0, i)), false);
    const after = unlink(trim(c.slice(i + def.text.length).replace(/\s*\([^)]*\)\s*$/, "")), true);
    if (!before && !after) return " — which is the whole clue, and that is what makes this one unusual.";
    // The clue is on screen just above, so the wordplay is named by where it
    // sits, never quoted back.
    if (!before) return ", so the clue opens with it and the rest is wordplay.";
    if (!after) return ", right at the end, so everything before it is wordplay.";
    return ", sitting mid-clue, with wordplay either side of it.";
  }

