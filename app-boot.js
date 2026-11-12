"use strict"; // app part 7 of 7 (boot and offline mode). Classic script sharing the page scope with its siblings; see tools/app_src.js.
  // ---------- boot ----------

  // Feedback about the site itself, filed down the same pipe as a bad-hint
  // report with no clue attached and rung "site" — tools/reports.py is the queue
  // for both, and one queue is exactly why this does not get a route of its own.
  // Wired once at boot, not per render: it is a header panel like sync and
  // notify, nothing redraws it, and it has to be reachable when the complaint IS
  // the page.
  function bindFeedback() {
    const note = $("fb-note"), msg = $("fb-msg");
    if (!note) return;
    $("btn-feedback").onclick = () => { if (showPanel("fb-panel")) { note.focus(); beacon("feedback"); } };
    $("btn-feedback-close").onclick = () => showPanel("fb-panel", false);
    const send = () => {
      const text = (note.value || "").trim();
      if (!text) return;
      msg.textContent = "Sending…";
      fetch(SYNC_ENDPOINT.replace(/\/$/, "") + "/r", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ puzzle: P && P.id, clue: "", rung: "site", note: text }),
      }).then((r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        note.value = "";
        msg.textContent = "Thank you — sent. A person reads every note.";
      }).catch((err) => {
        // The error itself, never "see the log": this box is the only place the
        // sender will ever hear anything back about it.
        msg.textContent = "Couldn’t send — please try again (error: " + ((err && err.message) || String(err)) + ").";
      });
    };
    $("fb-send").onclick = send;
    note.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) send();
    });
  }

  function boot() {
    bindFeedback();
    $("btn-stats").onclick = () => { if (toggleStats()) beacon("stats"); };
    $("btn-stats-close").onclick = () => toggleStats(false);
    // #stats is the stats page as a link, which is what a toast points at.
    if (location.hash === "#stats") toggleStats(true);
    bindWelcome();
    // The lesson is /learn/ — a page, reached by a plain link in the header,
    // because it is a document you read end to end.
    $("btn-picker").onclick = () => { if (togglePicker()) beacon("picker"); };
    $("btn-picker-close").onclick = () => togglePicker(false);
    // #picker opens it, as #stats does the stats: the home-screen app's
    // Puzzles tab (appnav.js) links here from pages that are not the app.
    if (location.hash === "#picker") togglePicker(true);
    window.addEventListener("popstate", applyRoute);
    window.addEventListener("hashchange", applyRoute);

    // ---- sync ----
    // The button is only offered if there is somewhere to sync to. A control
    // that explains it cannot work is worse than no control.
    if (!SYNC_ENDPOINT) $("btn-sync").classList.add("hidden");
    $("btn-sync").onclick = () => {
      if (showPanel("sync-panel")) { renderSyncPanel(); if (syncOn()) syncPull(); beacon("sync"); }
    };
    $("btn-sync-close").onclick = () => showPanel("sync-panel", false);

    /* Arriving from a scan. The code is filled in and the panel opened, but
       joining is still a press: a link is a thing anyone can send you, and a
       silent join would pour a stranger's crosswords into these ones. The
       parameter is dropped from the address bar either way, so a bookmark or a
       shared link is of the site and not of somebody's grids. */
    const params = new URLSearchParams(location.search);
    const scanned = (params.get("sync") || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (scanned.length === 8) {
      params.delete("sync");
      const rest = params.toString();
      setAddress(location.pathname + (rest ? "?" + rest : ""));
      showPanel("sync-panel", true);
      const already = store.get("ct:sync", null) === scanned;
      if (!already) $("sync-join-code").value = scanned;
      renderSyncPanel();
      syncNote(already ? "Already syncing with this code."
                       : "Code scanned — press “Use this code” to sync with it.");
    }

    // ---- notifications ----
    if (!notifyAvailable()) $("btn-notify").classList.add("hidden");
    $("btn-notify").onclick = () => {
      if (showPanel("notify-panel")) { renderNotifyPanel(); notifyNote(""); beacon("notify"); }
    };
    $("btn-notify-close").onclick = () => showPanel("notify-panel", false);
    // Bound to the list and not to the boxes, because renderNotifyPanel() throws
    // the boxes away and builds new ones after every save.
    $("notify-list").addEventListener("change", (ev) => {
      const box = ev.target;
      const series = box && box.dataset ? box.dataset.series : null;
      if (!series) return;
      const on = new Set(notifyWanted());
      if (box.checked) on.add(series); else on.delete(series);
      // Ordered off SERIES_BADGE, so what goes on the wire does not depend on
      // which box was tapped first.
      saveNotify(Object.keys(SERIES_BADGE).filter((s) => on.has(s)));
    });
    /* The time is stored first and asserted second, so a browser with no papers
       ticked still remembers it — saveNotify([]) is the unsubscribe, and running
       it here would turn "not before eight" into "never". */
    $("notify-after").addEventListener("change", (ev) => {
      const value = (ev.target && ev.target.value) || "";
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) { renderNotifyPanel(); return; }
      store.set(NOTIFY_AFTER_KEY, value);
      const series = notifyWanted();
      if (!series.length) { notifyNote("Time saved — now tick a series to get notifications."); return; }
      saveNotify(series);
    });
    $("sync-start").onclick = () => {
      store.set("ct:sync", newSyncCode());
      renderSyncPanel();
      syncNote("Uploading…");
      syncPush();
    };
    $("sync-copy").onclick = copySyncCode;
    $("sync-join").onclick = () => joinCode($("sync-join-code").value);
    // A browser with no camera to offer is not shown a button that asks for one.
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
      $("sync-scan").classList.add("hidden");
    $("sync-scan").onclick = startScan;
    $("sync-scan-stop").onclick = () => stopScan("");
    $("sync-stop").onclick = () => {
      // Local progress is deliberately left alone. Stopping sync means "don't
      // send my crosswords anywhere any more", not "throw away my crosswords".
      store.del("ct:sync");
      renderSyncPanel();
    };
    // Coming back to a tab is exactly when the other machine's work is waiting,
    // and it is the cheapest possible moment to ask.
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { pauseTiming(); syncFlush(); return; }
      resumeTiming();
      if (syncOn()) syncPull();
    });
    // A desktop tab stays visible behind another window, so hidden is only half
    // of "in front of you"; focus is the other half.
    window.addEventListener("blur", pauseTiming);
    window.addEventListener("focus", resumeTiming);
    // Typing is the whole navigation model once the list outgrows a screen, so
    // the box is focused on open and Enter takes the top row — number in, puzzle
    // open, no mouse. Escape gets you back out; the global key handler ignores
    // inputs, so it has to be handled here.
    // Rows the list does not hold yet are asked for as the query needs them (loadForQuery).
    $("picker-search").addEventListener("input", () => {
      renderPicker();
      loadForQuery(($("picker-search").value || "").trim().toLowerCase());
    });
    $("picker-search").addEventListener("focus", loadAllSoon);
    ["picker-paper", "picker-band", "picker-tag"].forEach((id) => {
      $(id).addEventListener("focus", loadAllNow);
      $(id).addEventListener("mousedown", loadAllNow);
    });
    const keepMenus = () => {
      store.set("ct:picker", { paper: $("picker-paper").value || "", band: $("picker-band").value || "",
                               tag: $("picker-tag").value || "" });
      renderPicker();
      loadForQuery(($("picker-search").value || "").trim().toLowerCase());
    };
    $("picker-paper").addEventListener("change", keepMenus);
    $("picker-band").addEventListener("change", keepMenus);
    $("picker-tag").addEventListener("change", keepMenus);
    $("picker-search").addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { togglePicker(false); focusKbd(); return; }
      if (ev.key !== "Enter") return;
      const first = $("picker-list").children[0];
      const btn = first && first.children[0];
      if (btn && btn.onclick) btn.onclick();
    });

    $("chk-letter").onclick = () => { const c = cells[cur.y][cur.x]; if (c) checkCells([c], "square"); };
    $("chk-entry").onclick = () => {
      const e = gridEntry(), light = !e && currentLight();
      if (e || light) checkCells(e ? entryCells(e) : light, "word");
    };
    $("chk-grid").onclick = () => { const all = []; forEachCell((c) => all.push(c)); checkCells(all, "grid"); };
    $("paper-done").onclick = () => { if (paperHides()) verifyPaper(); };
    $("paper-reveal").onclick = () => { if (paperHides()) endPaper(); };
    $("paper-toggle").onchange = () => togglePaper($("paper-toggle").checked);
    $("clear-entry").onclick = () => {
      const e = gridEntry();
      const light = !e && currentLight();
      if (light) light.forEach(clearCell);
      if (light) { refreshAll(); saveState(); }
      if (!e) return;
      entryCells(e).forEach((c) => { if (!c.printed) { c.letter = ""; c.wrong = false; c.revealed = false; } });
      refreshAll(); saveState();
    };
    $("reset-puzzle").onclick = () => {
      if (!confirm("Clear every letter and every hint you have used on this puzzle? This can’t be undone.")) return;
      // Deleting the save is not enough once there is a second device: an empty
      // slot reads as "never played this", so the other machine would hand the
      // whole grid back on the next pull. The reset is recorded as a moment
      // instead, and merge.js drops everything either side knew before it.
      const now = Date.now();
      // The clock goes with it. "Clear the grid and all hint history" means a
      // fresh attempt, and an attempt that starts on a grid you have already
      // solved once is not a time anything should be averaging.
      store.set(stateKey(), { grid: gridPrint(P), letters: {}, letterAt: {}, hintsShown: {}, hintsEarned: {},
                              blocksAt: {}, piecesPicked: {}, revealsUsed: {}, solvedWith: {}, timing: {},
                              clearedAt: now, updated: now });
      forEachCell((c) => { c.letter = ""; c.wrong = false; c.revealed = false; });
      entries.forEach((e) => { if (e.offGrid) { e.typed = ""; e.revealed = false; } });
      applyPrinted();
      hintsShown = {}; hintsEarned = {}; hintLevels = {}; revealsUsed = {}; blocksAt = {}; piecesPicked = {};
      solvedWith = {}; timing = {};
      if (paper.on && paperable()) setOnPaper(P.id, true);
      refreshAll();
      syncPushSoon();
    };

    document.addEventListener("keydown", (ev) => {
      if (ev.target && (ev.target.tagName === "INPUT" && ev.target.id !== "kbd" || ev.target.tagName === "TEXTAREA")) return;
      // A select owns every key while it has focus, open or closed. Where the
      // page draws the open list (appearance: base-select), focus sits on an
      // <option>, so arrows and Enter would otherwise steer the grid instead.
      if (ev.target && ev.target.closest && ev.target.closest("select")) return;
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
      const v = squareChars(ev.target.value);
      if (v) typeLetter(v[v.length - 1]);
      ev.target.value = "";
    });

    // The anagram ring's own hidden input, wired once here rather than inside
    // renderHintPanel(): #ana-kbd is a static element (see index.html) that
    // survives every ring redraw, so it only ever needs one set of listeners,
    // the same way #kbd's are wired once for the life of the page.
    $("ana-kbd").addEventListener("keydown", (ev) => {
      const k = ev.key;
      if (/^[a-zA-Z]$/.test(k)) { addRingLetter(k.toUpperCase()); ev.preventDefault(); }
      else if (k === "Backspace") { ringBackspace(); ev.preventDefault(); }
      // Anything else (Tab, Escape, arrows...) is left alone — this is a real
      // input and those keys already do the right thing on one.
    });
    // Same mobile fallback as #kbd: some on-screen keyboards report every key
    // as "Unidentified" and only the resulting `input` event is trustworthy.
    $("ana-kbd").addEventListener("input", (ev) => {
      const v = letterOf(ev.target.value);
      if (v) addRingLetter(v[v.length - 1]);
      ev.target.value = "";
    });
    // Losing focus has to redraw too, or the outline ringHTML() drew off
    // activeElement would sit there until some unrelated render happened to
    // clear it.
    $("ana-kbd").addEventListener("blur", () => { if (ring) renderHintPanel(); });

    // THE ONE PLACE THAT SUMMONS A KEYBOARD: the letter strip, the row of boxes
    // for the answer. Tapping the squares you are about to fill in is the only
    // tap on the page that says "I am going to type" — everything else on the
    // way to an answer is reading and choosing.
    //
    // On mousedown, because iOS only opens the keyboard for a focus() inside the
    // gesture and this strip re-renders itself on the way through: by the time a
    // click handler's focus() ran, the box that was tapped would have been thrown
    // away with the rest of the strip's innerHTML, leaving a moved cursor and no
    // keyboard.
    //
    // Summoning a keyboard is a viewport change like any other, and what it
    // covers is the clue sitting directly above the strip that was tapped.
    // placeHintPanel already corrects for a keyboard that arrives
    // a beat late — its watch window exists for exactly that — so this tap only
    // needs to arm it, the way picking a square does.
    //
    // Only on the tap that RAISES the keyboard. The strip is also how you steer,
    // and re-placing the panel under every steer would move the clue on each box
    // you touched. Nothing is newly covered by a keyboard
    // that was already up, so there is nothing to correct for.
    $("hint-pattern").addEventListener("mousedown", () => {
      const up = document.activeElement === $("kbd");
      focusKbd();
      if (!up) scrollToHintPanel("hint-clue", "hint-panel", "hint-pattern");
    });

    // Everything else keeps a keyboard and never raises one. Picking a square is
    // how you pick a CLUE, and the ladder answers a new clue with a
    // question you answer by tapping, so tapping the grid is not a decision to
    // type. The hint buttons, the clue lists and the grid share this rule, so
    // the strip is the only exception and the strip is where typing starts.
    //
    // Bound to the containers, not the buttons, because refreshAll() throws the
    // buttons away and rebuilds them on every render. The mousedown listener
    // runs before the default focus transfer, so activeElement still says
    // whether the keyboard was up when the finger landed.
    ["grid", "clues-across", "clues-down", "clues-unclued", "clues-offgrid", "hint-next", "hint-escape"].forEach((id) =>
      $(id).addEventListener("mousedown", keepKbd));

    // Bound here for the same reason, and to the list rather than to a row: the
    // rows are rebuilt with every puzzle, and the second click of the double-tap
    // accident lands on a different row from the first — see clueTapIsAnAccident.
    ["clues-across", "clues-down", "clues-unclued", "clues-offgrid"].forEach((id) =>
      $(id).addEventListener("touchstart", () => { clueTouchAt = Date.now(); },
                             { passive: true }));

    // The letter strip is also how you steer: tap a box to put the cursor on
    // that square of the current entry.
    // A rule chip on a rung opens or closes that rung's general rule.
    $("hint-body").addEventListener("click", (ev) => {
      const data = (ev.target && ev.target.dataset) || {};
      const rung = data.rule;
      const e = currentEntry();
      // A chip in the blocks rung's formula: take that piece (pickPiece). A
      // piece that would cost arms first, like every paid button.
      if (data.piece !== undefined && e) {
        const i = Number(data.piece);
        const ann = annOf(e);
        if (!ann || !Number.isInteger(i) || pieceOut(e, i)) return;
        if (!rungAvailable(e, ladderSteps(ann, clueText(e)), "blocks")) return;
        // Chips live in the blocks rung and go the way its "next piece" button
        // does: if the piece has a question (point at the words that give it),
        // ask it, and an answer earns the piece for nothing. Only "Just tell
        // me" on that question (guess-tell's own confirm) costs.
        const asked = !isEntrySolved(e) && guessAsk(e, "blocks", i);
        if (asked) {
          guessing = { key: entryKey(e), rung: "blocks", step: i, picked: [],
                       slots: (asked.pairs || []).map(() => -1), held: -1, heldSlot: -1 };
          focusHint("guess");
          refreshAll();
          return;
        }
        if (pickCosts(e, i) && !confirmBlock(e, "piece-" + i, ev)) return;
        pickPiece(e, i);
        refreshAll();
        return;
      }
      if (!rung || !e) return;
      const k = entryKey(e) + "|" + rung;
      if (!rulesOpen.delete(k)) rulesOpen.add(k);
      renderHintPanel();
    });

    $("hint-pattern").addEventListener("click", (ev) => {
      const box = ev.target && ev.target.dataset ? ev.target : null;
      const idx = box ? Number(box.dataset.i) : NaN;
      const e = currentEntry();
      if (!e || e.offGrid || !Number.isInteger(idx)) return;
      const c = cellAt(e, Math.max(0, Math.min(e.length - 1, idx)));
      cur.x = c.x; cur.y = c.y;
      // Focus first: refreshAll() rebuilds this strip and removes the node the
      // click is still travelling through.
      focusKbd(); refreshAll();
    });

    let idxLinkDone = false;
    // Partial index: draw the puzzle the URL (or the last one) names from its
    // own file now, and run the rest of the boot once the full index is in.
    if (INDEX.partial) {
      // The newest rows are here already: draw from them, and loadShards
      // fetches the rest as it is needed.
      fastOpen(bootWithIndex);
    } else {
      bootWithIndex();
    }

    function bootWithIndex() {
    // A link that names a puzzle by anything but its id needs rows this list
    // may not hold yet: fetch them (one series for a series-date alias, all
    // for a bare number), then boot as ever.
    const linked = new URLSearchParams(location.search).get("p");
    // A canonical id fastOpen has already drawn (BY_ID holds its row, made
    // from the puzzle's own file) opens as it is; the shards fill in later.
    if (linked && !listFull() && !IS_ID[linked] && !BY_ID[linked] && !idxLinkDone) {
      idxLinkDone = true;
      loadForLink(linked, bootWithIndex);
      return;
    }
    if (!INDEX.puzzles.length) {
      $("puzzle-title").textContent = "No puzzles found — run tools/fetch_puzzle.py first.";
      showApp();
      return;
    }
    // ?p=30072 wins over the remembered puzzle: the static answer pages under
    // /puzzles/<n>/ link in that way, and dropping someone on last night's
    // puzzle instead of the one they clicked would be baffling.
    // Links that name a puzzle by an older spelling of its id must keep
    // opening the puzzle they named.
    migrateSavedIds();
    const askedRaw = new URLSearchParams(location.search).get("p");
    const asked = askedRaw ? canonicalId(askedRaw) : null;
    // ?p=4098, a bare number or an old book id, names a puzzle by a spelling
    // that is not its id, and rewriting only the bar leaves the old URL a page
    // of its own for crawlers to index apart from the puzzle.
    // So it is a real navigation, to the address picking that puzzle gives
    // (shareUrl), with the tab flag the write-up's <head> sends back into the
    // app (app_return in tools/build_seo_pages.py). A crawler carries no flag
    // and stays on the write-up.
    if (asked && asked !== askedRaw && BY_ID[asked] && location.replace) {
      const c = new URLSearchParams(location.search).get("c");
      try { sessionStorage.setItem(`ct:app:${asked}`, "1"); } catch (e) { /* no storage: the write-up shows */ }
      location.replace(shareUrl(asked, c ? encodeURIComponent(c) : null));
      return;
    }
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
        showApp();
        return;
      }
      if (fast.id === want) {
        // Already on screen from its own file, with a row made from that file.
        // The real row may know more (tags, style): draw again only then.
        const real = BY_ID[want], key = (m) => JSON.stringify([m.annotated, m.tags, m.style, m.solutionsUnofficial, m.unlisted]);
        const differs = !!real && key(real) !== key(meta);
        if (asked) pointUrlAtPuzzle(want);
        if (differs) openPuzzle(want, false); else if (real) meta = real;
      } else {
        openPuzzle(want, !!asked);
      }
      // Everything below is after the first paint on purpose. The pull is a
      // network round trip and the solver should be looking at yesterday's
      // letters while it happens, not a blank page; if it brings anything new,
      // applyEnvelope redraws. The started puzzles are only needed by the
      // picker, which is shut.
      if (syncOn()) syncPull();
      // Same reasoning: a round trip that keeps the Worker's copy of this
      // device alive, run behind a grid that is already on screen.
      refreshNotify();
      offlineInit();
      autoUpdateInit();
      loadStartedPuzzles(() => {
        if (!$("picker-panel").classList.contains("hidden")) renderPicker();
      });
    });
    }
  }

  // The puzzle the address names (?p=), or else the one played last, drawn
  // from its own file before the rest of the list has arrived. `fast.id` is
  // set only when it was drawn; any miss (an old spelling of an id, a reprint,
  // offline with nothing cached) leaves the normal boot to open it. The
  // unversioned .gz is what sw.js serves network-first, cache when offline.
  const fast = { id: null };
  function fastOpen(done) {
    const raw = new URLSearchParams(location.search).get("p") || store.get("ct:last", null);
    if (!raw || !/^[A-Za-z0-9_.-]+$/.test(raw) || !window.fetch || location.hash) return done();
    window.fetch(at("puzzles/" + raw + ".js.gz"), { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
      .then(unzipText)
      .then((text) => {
        new Function("window", text)(window);
        const puz = window.CRYPTIC_PUZZLES[raw];
        if (!puz) return;
        const all = puz.entries || [];
        BY_ID[raw] = { id: raw, number: puz.number, series: puz.series, name: puz.name, file: raw + ".js",
          ...(puz.setter ? { setter: puz.setter } : {}),
          ...(puz.date ? { date: puz.date } : {}), ...(puz.year ? { year: puz.year } : {}),
          annotated: all.length > 0 && all.every((e) => e.annotation), unlisted: false };
        fast.id = raw;
        openPuzzle(raw, false);
      })
      .catch(() => { fast.id = null; delete window.CRYPTIC_PUZZLES[raw]; })
      .then(done);
  }

  // ---------- offline ----------
  // sw.js keeps the app and every puzzle opened (see its header). This is the
  // page's half: tell the worker what the page loaded, let the solver save a
  // batch before a flight, and show which puzzles a dead connection can open.
  const PUZZLE_CACHE = "ct-puzzles-1";   // the name sw.js files puzzles under
  const OFFLINE_BATCH = 100;   // about 1 MB gzipped (median puzzle ~10 KB)
  const OFFLINE_CAP = 250;     // sw.js MAX_PUZZLES: the most the device keeps
  const offlineOK = () => !!(navigator.serviceWorker && window.caches && typeof fetch === "function");
  // Offline is the browser saying so, or the server not answering: wifi that
  // is up but dead (a plane) leaves navigator.onLine true.
  let netDown = false;
  const isOffline = () => netDown || (typeof navigator !== "undefined" && navigator.onLine === false);
  let offlineFiles = null;   // puzzle files held on this device, once read

  // sw.js is the one file the worker never answers, so fetching it asks the
  // server itself. Any change of state redraws what depends on it.
  const PROBE_MS = 5000;
  function probeNet() {
    if (!offlineOK()) return;
    const ctl = window.AbortController ? new AbortController() : null;
    const timer = ctl && setTimeout(() => ctl.abort(), PROBE_MS);
    fetch(at("sw.js"), { cache: "no-store", method: "HEAD", ...(ctl ? { signal: ctl.signal } : {}) })
      .then((r) => r.ok, () => false)
      .then((ok) => {
        clearTimeout(timer);
        if (netDown === !ok) return;
        netDown = !ok;
        offlineRefresh(() => {
          if (!$("picker-panel").classList.contains("hidden")) renderPicker();
        }, true);
      });
  }

  // While offline with the cache read: a test of whether a puzzle row can be
  // opened here. Null otherwise (the list is the normal one).
  function offlineList() {
    if (!isOffline() || !offlineFiles) return null;
    return (p) => offlineHas(p) === true;
  }

  const puzzleUrl = (p) => at("puzzles/" + p.file + ".gz" + (p.v ? "?v=" + p.v : ""));

  // true / false while offline and the cache has been read; null otherwise,
  // when nothing is to be said about it.
  function offlineHas(p) {
    if (!isOffline() || !offlineFiles) return null;
    const own = BY_ID[p.reprintOf || p.id];
    return !!(own && offlineFiles.has(own.file));
  }

  function offlineRefresh(then, always) {
    if (!offlineOK()) return;
    caches.open(PUZZLE_CACHE).then((c) => c.keys()).then((keys) => {
      const held = new Set(keys.map((k) => decodeURIComponent(new URL(k.url).pathname)
        .replace(/^.*\/puzzles\//, "").replace(/\.gz$/, "")));
      const changed = !offlineFiles || held.size !== offlineFiles.size;
      offlineFiles = held;
      renderOfflineBox();
      if ((changed || always) && then) then();
    }).catch(() => {});
  }

  // The next puzzles this solver would be handed: unfinished ones they have
  // started, then the newest annotated ones from the papers they play (every
  // paper while they have played none), skipping finished grids.
  // With `more` (the Save now button), only puzzles not held yet, so every
  // tap adds puzzles until the device holds OFFLINE_CAP.
  function offlineBatch(more) {
    const prog = savedProgress();
    const out = [], seen = {};
    const has = more && offlineFiles ? offlineFiles : new Set();
    const size = more ? Math.min(OFFLINE_BATCH, Math.max(0, OFFLINE_CAP - has.size)) : OFFLINE_BATCH;
    const add = (p) => {
      if (p && p.file && !p.reprintOf && !seen[p.id] && !has.has(p.file) && out.length < size) { seen[p.id] = 1; out.push(p); }
    };
    Object.keys(prog).forEach((id) => { if (BY_ID[id] && !pickerStatus(BY_ID[id]).done) add(BY_ID[id]); });
    const played = new Set(Object.keys(prog).map((id) => BY_ID[id] && BY_ID[id].series).filter(Boolean));
    for (const p of INDEX.puzzles) {
      if (out.length >= size) break;
      if (!p.annotated || (played.size && !played.has(p.series))) continue;
      if (prog[p.id] && pickerStatus(p).done) continue;
      add(p);
    }
    return out;
  }

  // Files of the puzzles this solver has completed. A finished puzzle is not
  // worth a place on the device, so it is neither saved nor counted.
  function solvedFiles() {
    const out = new Set(), prog = savedProgress();
    Object.keys(prog).forEach((id) => {
      const p = BY_ID[id], own = p && BY_ID[p.reprintOf || p.id];
      if (own && own.file && pickerStatus(p).done) out.add(own.file);
    });
    return out;
  }
  // How many saved puzzles are still worth having: held, and not completed.
  function offlineCount() {
    if (!offlineFiles) return 0;
    const solved = solvedFiles();
    let n = 0;
    offlineFiles.forEach((f) => { if (!solved.has(f)) n++; });
    return n;
  }

  function offlineNote(msg) {
    const el = $("offline-status");
    if (el) el.textContent = msg;
  }

  const readyText = (n) => (n ? `${n} puzzle${n > 1 ? "s" : ""} ready offline` : "No puzzles saved offline yet");
  let offlineBusy = false;
  // The Save now button is its own progress display: disabled while a save runs.
  function offlineBtn(busy) {
    const b = $("btn-offline");
    if (b) b.disabled = !!busy;
  }
  function renderOfflineBox() {
    const box = $("offline-box");
    if (!box || !offlineOK()) return;
    box.classList.remove("hidden");
    if (!offlineBusy) offlineNote(readyText(offlineCount()));
  }

  // Saving needs no tap: the page does it once idle after loading online, at
  // most every OFFLINE_EVERY_MS, and again when a puzzle is solved (`force`).
  const OFFLINE_EVERY_MS = 6 * 3600 * 1000;
  const OFFLINE_KEY = "ct:offline-at";
  const OFFLINE_BATCH_KEY = "ct:offline-batch";   // files the last batch held
  function offlineAuto(force) {
    if (isOffline() || offlineBusy) return;
    const c = navigator.connection;
    if (c && c.saveData) return;
    let last = 0;
    try { last = Number(localStorage.getItem(OFFLINE_KEY)) || 0; } catch (e) { /* no storage */ }
    if (!force && Date.now() - last < OFFLINE_EVERY_MS) return;
    saveOffline(true);
  }

  function saveOffline(quiet, listed) {
    if (isOffline()) { offlineNote("You’re offline. Connect to wifi and try again."); return; }
    // Offline search and the Library need every row, so the list is completed
    // first (once: a list that cannot be completed saves what it has).
    // Only the installed app does that on its own (it needs everything offline);
    // the automatic save in a browser tab saves what the page already has and
    // fetches no shard it was not asked for. Save now always completes the list.
    if (!listed && !listFull() && (!quiet || isAppMode())) { loadShards(null, () => saveOffline(quiet, true)); return; }
    const more = !quiet;
    const rows = offlineBatch(more);
    if (offlineBusy) return;
    // Recycling. Dropped: a saved puzzle that is now solved, and one the last
    // batch held that this pick no longer includes. Kept: every unfinished
    // puzzle with letters on it, and anything merely opened (the worker's cap
    // retires those, oldest first). Letters live in localStorage and the sync
    // Worker, never in this cache, so a drop cannot lose progress; and while a
    // sync push is failing, nothing is dropped at all.
    const prog = savedProgress();
    const want = new Set(rows.map((p) => p.file));
    const started = new Set(), solved = new Set();
    Object.keys(prog).forEach((id) => {
      const p = BY_ID[id], own = p && BY_ID[p.reprintOf || p.id];
      if (!own || !own.file) return;
      (pickerStatus(p).done ? solved : started).add(own.file);
    });
    let prev = [];
    try { prev = JSON.parse(localStorage.getItem(OFFLINE_BATCH_KEY) || "[]"); } catch (e) { prev = []; }
    // Save now adds to what the last batch held rather than replacing it.
    if (more) prev.forEach((f) => want.add(f));
    // Candidates: the last batch, every completed puzzle, and (on the quiet,
    // automatic save) anything else held that is not in this pick, such as
    // puzzles merely opened once. The open puzzle stays.
    const cur = P && BY_ID[P.reprintOf || P.id];
    const stale = more || !offlineFiles ? [] : [...offlineFiles].filter((f) => !(cur && cur.file === f));
    // A partial list does not know every started puzzle, so it drops nothing.
    let dropFiles = syncFails || !listFull() ? [] : [...new Set([...prev, ...solved, ...stale])].filter((f) => !solved.has(f) ? !want.has(f) && !started.has(f) : true);
    if (offlineFiles) for (let i = dropFiles.length - 1; i >= 0; i--) if (!offlineFiles.has(dropFiles[i])) dropFiles.splice(i, 1);
    // Both stored forms of a file: the .gz and the plain script.
    const drop = [];
    dropFiles.forEach((f) => { drop.push(at("puzzles/" + f + ".gz"), at("puzzles/" + f)); });
    // The worker's cap must not retire a puzzle with letters on it.
    const keep = [...started].map((f) => at("puzzles/" + f + ".gz"));
    if (!rows.length && !drop.length) {
      const n = offlineCount();
      offlineNote(more && n >= OFFLINE_CAP ? `${n} puzzles ready offline, the most this device keeps`
        : more ? `Nothing new to save${n ? " — " + readyText(n) : ""}` : readyText(n));
      return;
    }
    if (!navigator.serviceWorker) { offlineNote("Offline saving isn’t available in this browser."); return; }
    offlineBusy = true;
    offlineBtn(true);
    offlineNote(rows.length ? `Saving 0 of ${rows.length}…` : "Tidying saved puzzles…");
    // The count is read back from the cache before the line is written, so it
    // says what the device now holds.
    const end = (msg) => {
      offlineBusy = false;
      offlineBtn(false);
      offlineRefresh(() => {
        offlineNote(msg(offlineCount()));
        if (!$("picker-panel").classList.contains("hidden")) renderPicker();
      }, true);
    };
    navigator.serviceWorker.ready.then((reg) => {
      const ch = new MessageChannel();
      ch.port1.onmessage = (ev) => {
        const m = ev.data || {};
        if (!m.finished) { offlineNote(`Saving ${m.done + m.failed} of ${m.total}…`); return; }
        if (!m.failed) {
          try {
            localStorage.setItem(OFFLINE_KEY, String(Date.now()));
            localStorage.setItem(OFFLINE_BATCH_KEY, JSON.stringify([...want]));
          } catch (e) { /* no storage */ }
        }
        end((n) => (m.failed ? `Saved ${m.done} of ${m.total}; ${m.failed} couldn’t be reached. Will try again.`
          : more ? (m.done ? `Saved ${m.done} puzzle${m.done > 1 ? "s" : ""} — ${n} ready offline`
            : `Nothing new to save${n ? " — " + readyText(n) : ""}`) : readyText(n)));
      };
      reg.active.postMessage({ type: "save", urls: rows.map(puzzleUrl), drop, keep }, [ch.port2]);
    }).catch(() => end(() => "Couldn’t save just now. Try again."));
  }

  /* Self-update. A Home Screen app is resumed from memory, so it may never
     navigate, and the home HTML is served with max-age=600: left alone, a deploy
     can take a long time to reach it. So on launch, and whenever the app comes
     back to the front (at most every 5 minutes), it asks the worker to look for
     a new sw.js and fetches the home HTML with cache "no-store" (sw.js lets that
     request through to the network). The page's stamped assets (?v=<hash>) are
     compared with the ones fetched; a new one means a deploy.
     Progress is in localStorage and sync, so a reload loses nothing, but a
     solver mid-word should not see the grid vanish: if there was any input in
     the last 20s the reload waits for the app to be hidden and shown again, and
     a small "Updated — tap to reload" pill is shown meanwhile. The reload first
     pushes any pending sync and waits a moment for it. */
  const UPDATE_GAP_MS = 5 * 60 * 1000, UPDATE_BUSY_MS = 20 * 1000, UPDATE_LOOP_MS = 2 * 60 * 1000;
  const UPDATE_RELOAD_KEY = "ct:updReload";
  function autoUpdateInit() {
    if (typeof fetch !== "function" || location.protocol === "file:") return;
    let lastCheck = 0, lastInput = 0, found = false, checking = false;
    ["keydown", "input", "pointerdown"].forEach((t) =>
      document.addEventListener(t, () => { lastInput = Date.now(); }, true));
    const stamps = (pairs) => {
      const out = new Set();
      pairs.forEach((u) => {
        try {
          const x = new URL(u, homeUrl());
          if (x.search.startsWith("?v=") && x.origin === location.origin) out.add(x.pathname + x.search);
        } catch (e) { /* skip */ }
      });
      return out;
    };
    const mine = () => stamps([...document.querySelectorAll("script[src],link[href]")]
      .map((el) => el.getAttribute("src") || el.getAttribute("href")));
    const theirs = (html) => stamps((html.match(/(?:src|href)="[^"]*\?v=[0-9a-f]+"/g) || [])
      .map((m) => m.slice(m.indexOf('"') + 1, -1)));
    function reloadNow() {
      try { sessionStorage.setItem(UPDATE_RELOAD_KEY, String(Date.now())); } catch (e) { /* no storage */ }
      try { syncFlush(); } catch (e) { /* nothing to flush */ }
      const t0 = Date.now();
      (function go() {
        if ((syncBusy || syncTimer !== null) && Date.now() - t0 < 3000) { setTimeout(go, 150); return; }
        location.reload();
      })();
    }
    function pill() {
      if ($("update-pill")) return;
      const b = document.createElement("button");
      b.id = "update-pill";
      b.type = "button";
      b.textContent = "Updated — tap to reload";
      b.style.cssText = "position:fixed;left:50%;transform:translateX(-50%);bottom:calc(76px + env(safe-area-inset-bottom,0px));" +
        "z-index:9999;padding:8px 16px;border:0;border-radius:999px;background:#1b5e20;color:#fff;font:600 14px system-ui,sans-serif;" +
        "box-shadow:0 2px 10px rgba(0,0,0,.3)";
      b.onclick = reloadNow;
      document.body.appendChild(b);
    }
    function apply(fromVisible) {
      if (!found) return;
      let recent = false;
      try { recent = Date.now() - Number(sessionStorage.getItem(UPDATE_RELOAD_KEY) || 0) < UPDATE_LOOP_MS; } catch (e) { /* none */ }
      const busy = Date.now() - lastInput < UPDATE_BUSY_MS;
      if (recent || (busy && !fromVisible)) { pill(); return; }
      reloadNow();
    }
    function check() {
      if (checking || (navigator.onLine === false)) return;
      if (Date.now() - lastCheck < UPDATE_GAP_MS) return;
      lastCheck = Date.now();
      checking = true;
      if (navigator.serviceWorker) navigator.serviceWorker.getRegistration().then((r) => r && r.update()).catch(() => {});
      fetch(at("./"), { cache: "no-store", credentials: "same-origin" })
        .then((r) => (r.ok ? r.text() : ""))
        .then((html) => {
          const now = mine();
          if (!html || !now.size) return;
          for (const s of theirs(html)) if (!now.has(s)) { found = true; break; }
          apply(false);
        })
        .catch(() => {})
        .then(() => { checking = false; });
    }
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      // Shown again with an update already found: now is the safe moment.
      if (found) apply(true); else check();
    });
    if (document.readyState === "complete") check();
    else window.addEventListener("load", check);
  }

  function offlineInit() {
    if (!offlineOK()) return;
    const btn = $("btn-offline");
    if (btn) btn.onclick = (ev) => { ev.preventDefault(); saveOffline(false); };
    // Registered here as well as when notifications are ticked: the app must
    // be offline-capable for someone who never touches notifications.
    // at(), not a bare "sw.js": opening a puzzle rewrites the bar to
    // /puzzles/<id>/, and a reload there would ask for /puzzles/<id>/sw.js (404).
    navigator.serviceWorker.register(at("sw.js")).then(() => navigator.serviceWorker.ready).then((reg) => {
      // The worker cannot see requests made before it controlled the page, so
      // say what this page loaded.
      const urls = [];
      document.querySelectorAll("script[src],link[rel~=stylesheet],link[rel~=icon],link[rel~=apple-touch-icon],link[rel=manifest]")
        .forEach((el) => urls.push(el.src || el.href));
      urls.push(at("inflate.js"), at("icon-192.png"));
      if (reg.active) reg.active.postMessage({ type: "precache", urls });
    }).catch(() => {});
    offlineRefresh();
    probeNet();
    const again = () => {
      probeNet();
      renderOfflineBox();
      if (!$("picker-panel").classList.contains("hidden")) renderPicker();
    };
    // Once the page is idle, so it never competes with the first paint.
    const idle = () => offlineAuto(false);
    const later = () => (window.requestIdleCallback ? requestIdleCallback(idle, { timeout: 10000 }) : setTimeout(idle, 3000));
    if (document.readyState === "complete") later();
    else window.addEventListener("load", later);
    window.addEventListener("online", () => { again(); offlineAuto(false); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) probeNet(); });
    window.addEventListener("offline", again);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
