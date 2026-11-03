"use strict"; // app part 2 of 7 (saving, the model, grid and clue-list drawing). Classic script sharing the page scope with its siblings; see tools/app_src.js.
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
    forEachCell((c) => { if (c.letter && !c.printed) letters[c.x + "," + c.y] = c.letter + (c.revealed ? "!" : ""); });
    // An off-grid clue's letters are held under its entry id, the whole answer in one value.
    const offIds = entries.filter((e) => e.offGrid).map(entryId);
    entries.forEach((e) => { if (e.offGrid && e.typed) letters[entryId(e)] = e.typed + (e.revealed ? "!" : ""); });
    // When each square last changed, carried forward from the previous save
    // and re-stamped only where something actually moved. Rubbing a letter
    // out leaves no letter behind, so without this the merge cannot tell a
    // square you cleared from one you never filled in, and would put the
    // letter straight back. A stamp with no letter is
    // how a deletion gets to the other device.
    const letterAt = Object.assign({}, prev.letterAt);
    forEachCell((c) => {
      const k = c.x + "," + c.y;
      if (letters[k] !== was[k]) letterAt[k] = now;
    });
    offIds.forEach((k) => { if (letters[k] !== was[k]) letterAt[k] = now; });
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
    store.set(stateKey(), { grid: gridPrint(P), letters, letterAt, hintsShown, hintsEarned, revealsUsed,
                            blocksAt, piecesPicked, solvedWith, timing,
                            clearedAt: prev.clearedAt || 0, updated: now });
    syncPushSoon();
  }
  // Time only counts while the puzzle is in front of you. The gap between two
  // saves is the sitting, so a tab left open behind another window would bank
  // the whole interval as solving. Going away banks the sitting up to that
  // moment and ends it; coming back starts a new one, so the time away is not
  // counted at all.
  const timingStarted = () => {
    const s = store.get(stateKey(), null);
    return !!(s && s.timing && s.timing.lastAt);
  };
  function pauseTiming() {
    // Nothing typed yet and nothing pending: opening a puzzle and switching
    // away must not start its clock, or every puzzle glanced at is in progress.
    if (saveTimer === null && !timingStarted()) return;
    clearTimeout(saveTimer);
    writeState();
  }
  function resumeTiming() {
    const s = store.get(stateKey(), null);
    if (!s || !s.timing || !s.timing.lastAt) return;
    s.timing.lastAt = Date.now();
    store.set(stateKey(), s);
    timing = s.timing;
  }
  function restoreState() {
    let s = store.get(stateKey(), null);
    // A save typed into another grid is reset, not just skipped: the reset's
    // clearedAt is what stops a sync merge handing its letters back.
    if (!fitsGrid(s, P)) {
      const now = Date.now();
      s = { grid: gridPrint(P), letters: {}, letterAt: {}, hintsShown: {}, hintsEarned: {}, blocksAt: {},
            piecesPicked: {}, revealsUsed: {}, solvedWith: {}, timing: {}, clearedAt: now, updated: now };
      store.set(stateKey(), s);
    }
    hintsShown = (s && s.hintsShown) || {};
    hintsEarned = (s && s.hintsEarned) || {};
    hintLevels = (s && s.hintLevels) || {};
    revealsUsed = (s && s.revealsUsed) || {};
    blocksAt = (s && s.blocksAt) || {};
    piecesPicked = (s && s.piecesPicked) || {};
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
    entries.forEach((e) => {
      if (!e.offGrid) return;
      const v = (s && s.letters && s.letters[entryId(e)]) || "";
      e.typed = v.replace("!", ""); e.revealed = v.endsWith("!");
    });
    applyPrinted();
  }

  /* ---------- sync engine ----------
     No account, no password: the eight-character code IS the identity. There is
     nothing here worth protecting with a login — it is which squares of a
     newspaper crossword you have filled in — and a password would only add a
     thing to forget, a reset flow to maintain, and an email address
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
  // them: full walkthrough could appear and then disappear. Merging is not
  // a precaution here, it is the only correct
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
      // The Worker marks the site owner's own code, and this browser then
      // stays out of the counts until a sync says otherwise (sync/worker.js).
      if (r.status < 500) {
        try {
          if (r.headers.get("x-ct-internal") === "1") localStorage.setItem(INTERNAL_KEY, "1");
          else localStorage.removeItem(INTERNAL_KEY);
        } catch (e) { /* private mode: counted, which is the safe way to be wrong */ }
      }
      if (r.status === 404 && method === "GET") return null; // code not used yet
      if (!r.ok) throw new Error("sync " + r.status);
      return r.json();
    });
  }

  // ---- sync scheduler (tests/test_sync_retry.js runs this block as is) ----
  /* Every save is in localStorage before any of this runs, and a push only
     ever reads from there, so a push that fails loses nothing: the letters
     are still on this device and go up with the next push. What a failure
     must not do is leave them there until the solver happens to type again —
     a finished puzzle never types again. So a failure schedules a retry of
     its own, backing off from 30 seconds to 15 minutes, and coming back
     online retries at once. The retry is a pull, which pushes only when the
     server turns out to lack something, so a retry after a push that did
     land in the end costs a read rather than a write.

     Pushes are at most one a minute. Each one that changes anything is a KV
     write, the free tier allows 1,000 a day across every solver, and with
     only "two seconds of quiet" a cryptic solved at thinking pace was a
     write per answer. A minute is still well inside "I picked up the iPad",
     and a tab being hidden pushes whatever is waiting straight away. */
  const SYNC_QUIET_MS = 2000, SYNC_MIN_GAP_MS = 60 * 1000;
  const SYNC_RETRY_MS = 30 * 1000, SYNC_RETRY_MAX_MS = 15 * 60 * 1000;
  let syncTimer = null, syncBusy = false, syncAgain = false;
  let syncLastPush = 0, syncFails = 0, syncRetryTimer = null;
  function syncPushSoon() {
    if (!syncOn()) return;
    clearTimeout(syncTimer);
    const wait = Math.max(SYNC_QUIET_MS, syncLastPush + SYNC_MIN_GAP_MS - Date.now());
    syncTimer = setTimeout(() => { syncTimer = null; syncPush(); }, wait);
  }
  // A push waiting on its timer goes now: the tab is being put down.
  function syncFlush() {
    if (syncTimer === null) return;
    clearTimeout(syncTimer);
    syncTimer = null;
    syncPush();
  }
  function syncFailed(retry) {
    syncFails++;
    // Known offline (a flight): nothing to retry against, and no alarm. The
    // letters are in localStorage, and the "online" listener below pulls and
    // pushes the moment the connection is back (syncFails is what arms it).
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      clearTimeout(syncRetryTimer);
      syncRetryTimer = null;
      syncNote("Offline — your progress is saved here and will sync when you’re back online");
      return;
    }
    syncNote("Can’t reach the sync server — will try again");
    clearTimeout(syncRetryTimer);
    const wait = Math.min(SYNC_RETRY_MAX_MS, SYNC_RETRY_MS * Math.pow(2, syncFails - 1));
    syncRetryTimer = setTimeout(() => { syncRetryTimer = null; (retry || syncPull)(); }, wait);
  }
  function syncOk() {
    syncFails = 0;
    clearTimeout(syncRetryTimer);
    syncRetryTimer = null;
    syncNote("Synced");
  }
  function syncPush() {
    if (!syncOn()) return Promise.resolve();
    if (syncBusy) { syncAgain = true; return Promise.resolve(); }
    syncBusy = true;
    syncLastPush = Date.now();
    return syncFetch("PUT", localEnvelope())
      .then((merged) => {
        // The response is the merged truth, including anything another machine
        // pushed while this one was typing — so a push is also a pull.
        if (applyEnvelope(merged)) { restoreState(); refreshAll(); }
        syncOk();
      })
      .catch(() => syncFailed())
      .then(() => {
        syncBusy = false;
        if (syncAgain) { syncAgain = false; syncPushSoon(); }
      });
  }
  /* `missing` is what to do when the code has nothing stored under it, and only
     the join below passes one: there, a 404 means the code was typed wrong, and
     seeding it would upload these grids to a code nobody holds and say "Synced".
     Every other caller already owns its code, where a 404 is simply the first
     machine on it and pushing is right. */
  function syncPull(missing) {
    if (!syncOn()) return Promise.resolve();
    return syncFetch("GET", null)
      .then((remote) => {
        if (!remote) return missing ? missing() : syncPush(); // first machine on this code
        const merged = CTMerge.mergeSaves(localEnvelope(), remote);
        if (applyEnvelope(merged)) { restoreState(); refreshAll(); }
        // Push back whatever the server did not have. Cheap, and it means the
        // machine you just opened is not the only one holding your morning.
        if (JSON.stringify(merged) !== JSON.stringify(remote)) return syncPush();
        syncOk();
      })
      // The join's own `missing` goes with the retry: without it a 404 on the
      // retry would seed a mistyped code with this device's grids.
      .catch(() => syncFailed(() => syncPull(missing)));
  }
  if (typeof window !== "undefined" && window.addEventListener)
    window.addEventListener("online", () => { if (syncFails && syncOn()) syncPull(); });
  // ---- end sync scheduler ----

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

  /* The QR is the same handover as the code, with the typing taken out: it
     encodes a link back to this page carrying the code, so the other device's
     camera - which is on its lock screen already - lands on the join panel with
     the code filled in. Drawn here rather than fetched from an image service
     for the same reason there is no login: the code IS the account, and that
     service would be handed every grid on it.

     Black on white whatever the theme. A scanner locks onto the quiet zone, and
     a code inverted into a dark panel is one a camera will sit and stare at. */
  const SYNC_QUIET = 4;    // modules of margin, as the standard requires
  const SYNC_QR_CSS_PX = 176;

  const syncJoinURL = (code) => new URL("?sync=" + encodeURIComponent(code), location.href).href;

  function drawSyncQr(code) {
    const canvas = $("sync-qr");
    if (!canvas || !canvas.getContext) return;
    let rows = null;
    try { rows = code && window.CTQR ? window.CTQR.encode(syncJoinURL(code)) : null; }
    catch (e) { rows = null; }
    // Nothing to encode, or qr.js never loaded: the code itself is still on
    // screen, so the panel loses a shortcut rather than the feature.
    canvas.hidden = !rows;
    if (!rows) return;
    const span = rows.length + 2 * SYNC_QUIET;
    const dpr = window.devicePixelRatio || 1;
    // Whole device pixels per module, or the modules land on half pixels and
    // the edges blur into each other.
    const px = Math.max(2, Math.round((SYNC_QR_CSS_PX / span) * dpr));
    canvas.width = canvas.height = span * px;
    canvas.style.width = canvas.style.height = (span * px) / dpr + "px";
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#000";
    for (let r = 0; r < rows.length; r++) {
      for (let c = 0; c < rows.length; c++) {
        if (rows[r][c]) ctx.fillRect((c + SYNC_QUIET) * px, (r + SYNC_QUIET) * px, px, px);
      }
    }
  }

  /* ---------- taking a code by camera ----------
     The square is a link, so the phone's own camera app can read it — and on iOS
     it opens that link in Safari, which is a different storage jar from the copy
     of this site sitting on the home screen. The code lands in an app the solver
     was not using and the one they were still shows nothing. So the scan has to
     happen in here.

     BarcodeDetector does it in Chrome and costs nothing. Safari has none, so
     vendor/jsQR-1.4.0.js is fetched on the first press of the button and never
     otherwise — see vendor/README.md for why that is a quarter of a megabyte. */
  const JSQR_SRC = "vendor/jsQR-1.4.0.js";
  let scanStop = null;

  // Resolves to decode(canvas) -> Promise of the text in the square, or null.
  function loadDecoder() {
    if (window.BarcodeDetector) {
      const det = new window.BarcodeDetector({ formats: ["qr_code"] });
      return Promise.resolve((canvas) => det.detect(canvas).then(
        (hits) => (hits && hits[0] && hits[0].rawValue) || null, () => null));
    }
    const reader = () => (canvas) => {
      const px = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
      // dontInvert: the thing being read is a screen, always dark on light, and
      // trying the negative as well doubles the work of every frame.
      const hit = window.jsQR(px.data, px.width, px.height, { inversionAttempts: "dontInvert" });
      return Promise.resolve((hit && hit.data) || null);
    };
    if (window.jsQR) return Promise.resolve(reader());
    return new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = JSQR_SRC;
      s.onload = () => (window.jsQR ? ok(reader()) : fail(new Error("no decoder")));
      s.onerror = () => fail(new Error("no decoder"));
      document.head.appendChild(s);
    });
  }

  /* A camera is a light on someone's phone: it goes off the moment this stops
     being the thing they are doing — a hit, the button, the panel closing. */
  function stopScan(note) {
    if (scanStop) scanStop();
    scanStop = null;
    $("sync-scan-box").classList.add("hidden");
    if (note) syncNote(note);
  }

  function startScan() {
    const media = navigator.mediaDevices;
    if (!media || !media.getUserMedia) {
      syncNote("This browser can’t use the camera here — type the code instead.");
      return;
    }
    const video = $("sync-scan-video");
    const canvas = document.createElement("canvas");
    let live = true;
    $("sync-scan-box").classList.remove("hidden");
    syncNote("Starting the camera…");
    Promise.all([loadDecoder(), media.getUserMedia({ video: { facingMode: "environment" } })])
      .then((both) => {
        const decode = both[0], stream = both[1];
        // Permission can be granted after the panel was closed again, and a
        // stream that arrives then has to be put straight back.
        if (!live) { stream.getTracks().forEach((tr) => tr.stop()); return; }
        scanStop = () => {
          live = false;
          stream.getTracks().forEach((tr) => tr.stop());
          video.srcObject = null;
        };
        video.srcObject = stream;
        if (video.play) video.play();
        syncNote("Point the camera at the QR code on your other device.");
        // A frame every eighth of a second, not every frame: decoding is the
        // expensive part and a code held up to a camera is held there.
        const tick = () => {
          if (!live) return;
          const again = () => setTimeout(tick, 125);
          if (!video.videoWidth) { again(); return; }
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
          decode(canvas).then((text) => {
            const code = codeFromScan(text);
            if (!code) { again(); return; }
            stopScan();
            $("sync-join-code").value = code;
            joinCode(code);
          }, again);
        };
        tick();
      })
      .catch((err) => stopScan(err && err.name === "NotAllowedError"
        ? "Camera access was blocked — type the code instead."
        : "The camera wouldn’t start — type the code instead."));
  }

  /* What the square holds is a join URL, but a code photographed off a screen or
     printed on its own is worth taking too. Anything that does not come out as
     eight code characters is somebody's wifi QR and is ignored rather than
     joined: a scanner that pastes rubbish into the box is worse than one that
     goes on looking. */
  function codeFromScan(text) {
    if (!text) return null;
    const up = String(text).toUpperCase();
    const m = up.match(/[?&]SYNC=([A-Z0-9]+)/);
    const raw = (m ? m[1] : up).replace(/[^A-Z0-9]/g, "");
    if (raw.length !== 8) return null;
    return raw.split("").every((ch) => CODE_ALPHABET.indexOf(ch) >= 0) ? raw : null;
  }

  function joinCode(text) {
    const raw = String(text || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (raw.length !== 8) { syncNote("A sync code is 8 characters long."); return; }
    // CODE_ALPHABET has no 0, O, 1, I, L or U, so a code containing one was
    // misread rather than mistyped, and the character names itself.
    const stray = raw.split("").filter((ch) => CODE_ALPHABET.indexOf(ch) < 0);
    if (stray.length) {
      syncNote("Sync codes never contain " + stray.join(", ") + " — check the code on the other device again.");
      return;
    }
    const had = store.get("ct:sync", null);
    store.set("ct:sync", raw);
    renderSyncPanel();
    syncNote("Fetching…");
    // Pull, not push: the machine you are joining *from* is the one that knows
    // things, and the merge means joining can only ever add to what is here.
    syncPull(() => {
      // Nothing under that code. Put back whatever this device was doing before,
      // so a typo costs a sentence rather than the code it was on.
      if (had) store.set("ct:sync", had); else store.del("ct:sync");
      renderSyncPanel();
      syncNote("No progress is saved under " + raw + ". Nothing on this device has changed — "
               + "check the code on the other device, or make a new code here.");
    });
  }

  function renderSyncPanel() {
    const code = store.get("ct:sync", null);
    $("sync-code").textContent = code || "—";
    drawSyncQr(code);
    $("sync-on").classList.toggle("hidden", !code);
    $("sync-off").classList.toggle("hidden", !!code);
    /* A device with no code shows exactly one button, and someone arriving with
       a code in their hand presses it — "Turn on sync" reads as the way to turn
       on sync, and mints a second code instead. So the code box leads while sync
       is off, and goes back under the QR once this device has a code of its own,
       where it is the afterthought again. */
    $("sync-panel").insertBefore($("sync-join-row"), code ? $("sync-status") : $("sync-off"));
    // Taking a code is offered in both states, so the wording has to say what
    // pressing it does to a device that already has one.
    $("sync-join-label").textContent = code
      ? "Want this device on another device’s code instead? Enter it here. It replaces this code, and the progress on both is combined."
      : "Already syncing on another device? Enter its code here.";
    syncNote(code ? "" : "Not syncing — progress is saved on this device only.");
  }

  /* ---------- being told when the next one is up ----------
     Which papers this browser wants to hear about, held here and asserted to
     sync/worker.js, which pushes when a puzzle first appears ANNOTATED — the
     hint ladder is the thing worth being woken for, and a puzzle is fetched
     hours before it has one.

     Per DEVICE, and it cannot be anything else: the subscription a browser
     hands out IS the address, there is no account to hang it off, and the sync
     code deliberately names a pile of crosswords rather than a person. So this
     is a setting and never a save — hence `notify` in SYNC_RESERVED, without
     which the scan above would upload it as though it were a grid. */
  const NOTIFY_KEY = "ct:notify";
  /* The earliest time of day this device is willing to be woken, held next to
     the papers and sent with them.

     Seven in the morning by default, because the annotation run finishes in the
     small hours and a notification then would arrive in the middle of the
     night. A device that never opens the panel still gets the
     default: refreshNotify() re-asserts on every load, so the hold arrives with
     the next page view rather than waiting for someone to go looking for it. */
  const NOTIFY_AFTER_KEY = "ct:notify-after";
  const NOTIFY_AFTER_DEFAULT = "07:00";
  const notifyAfter = () => {
    const saved = store.get(NOTIFY_AFTER_KEY, null);
    return /^([01]\d|2[0-3]):[0-5]\d$/.test(saved) ? saved : NOTIFY_AFTER_DEFAULT;
  };
  /* The zone travels with the time, because the Worker is the one that decides.
     "07:00" on its own means seven o'clock wherever Cloudflare happened to run
     the cron, which is nowhere anybody lives. */
  const notifyZone = () => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) {
      return "";
    }
  };
  // The public half of the VAPID pair whose private half signs every push in
  // sync/wrangler.toml. A push service checks a subscription against the key
  // that signed for it, so the two are one pair: replacing either means
  // replacing both, and every subscription taken out under the old one is dead.
  const VAPID_PUBLIC_KEY = "BBaYG5WN1oquOhkTinUjxhbyxNcNM-0VrN_XJ83tnxwH1LoboNch3QIvUFHL7ogMvHjiT1RSCac1hw-4uiASvlY";

  // subscribe() wants that key as bytes. It is published as base64url — base64
  // with -_ for +/ and the padding dropped — so both are put back before atob.
  function vapidKeyBytes() {
    const b64 = (VAPID_PUBLIC_KEY + "===".slice((VAPID_PUBLIC_KEY.length + 3) % 4))
      .replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(b64);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  // The same rule the Sync button follows: a control that explains it cannot
  // work is worse than no control. No endpoint to register with, or a browser
  // without any one of these three, and the button is not offered at all.
  const notifyAvailable = () => !!(SYNC_ENDPOINT && navigator.serviceWorker &&
    window.PushManager && typeof Notification !== "undefined");

  /* Web push on an iPhone or iPad works only for a site added to the Home
     Screen. Everything notifyAvailable() looks for is present in the browser
     there and subscribing simply fails, so this is the one case where the panel
     opens on a sentence instead of tickboxes — the sentence being the only
     thing that fixes it. iPadOS calls itself a Macintosh, and a Mac has neither
     touch points nor navigator.standalone, so touch is what separates them. */
  function iosNeedsHomeScreen() {
    const ua = navigator.userAgent || "";
    const ios = /iPad|iPhone|iPod/.test(ua) ||
      (/Macintosh/.test(ua) && (navigator.maxTouchPoints || 0) > 1);
    return ios && navigator.standalone !== true;
  }

  // Read back through SERIES_BADGE, so a paper that leaves that table stops
  // being ticked here rather than being asserted to the Worker forever.
  const notifySeries = () => {
    const saved = store.get(NOTIFY_KEY, null);
    return Array.isArray(saved) ? saved.filter((s) => SERIES_BADGE[s]) : [];
  };

  function notifyNote(msg) {
    const el = $("notify-status");
    if (el) el.textContent = msg;
  }

  // The list of papers is SERIES_BADGE and nothing else, for the reason the
  // table's own comment gives: it is what keeps the papers complete as they are
  // added, and a second list is the one that would not be.
  function renderNotifyPanel() {
    const list = $("notify-list");
    if (!list) return;
    const when = $("notify-when");
    if (iosNeedsHomeScreen()) {
      list.innerHTML = `<li class="muted small-note">On an iPhone or iPad, a site can only send
        notifications once it is on your Home Screen. Tap Share, then “Add to Home Screen”, open
        the site from that icon, and tick your papers there.</li>`;
      // Nothing here can be notified yet, so a time to be notified AT is a
      // control that promises something the browser will not do.
      if (when) when.classList.add("hidden");
      return;
    }
    if (when) {
      when.classList.remove("hidden");
      $("notify-after").value = notifyAfter();
    }
    const on = new Set(notifySeries());
    const { multi, single } = paperGroups();
    const order = multi.flat().concat(single);
    const rank = (s) => (order.includes(s) ? order.indexOf(s) : order.length);
    list.innerHTML = Object.keys(SERIES_BADGE).sort((a, b) => rank(a) - rank(b)).map((s) =>
      `<li><label><input type="checkbox" data-series="${s}"${on.has(s) ? " checked" : ""}>`
      + `${seriesChip(s)}</label></li>`).join("");
  }

  // This browser's subscription, made if it has not got one. register() is
  // idempotent and getSubscription() answers out of what the browser already
  // holds, so the first tick and the silent refresh below are the same call.
  function pushSubscription() {
    // sw.js is registered UNSTAMPED and must stay out of stamp_assets.py's
    // ASSETS: the URL is the worker's identity, so a hash on it registers a
    // second worker beside the one already holding this device's subscription.
    return navigator.serviceWorker.register(at("sw.js"))
      .then((reg) => reg.pushManager.getSubscription()
        .then((sub) => sub || reg.pushManager.subscribe({
          userVisibleOnly: true, applicationServerKey: vapidKeyBytes(),
        })));
  }

  /* The whole conversation with the Worker: these papers, at this address.

     An empty list is how it is turned off, so there is one code path and no
     separate unsubscribe — "tell me about nothing" and "forget this device" are
     the same request, and two of them would be two states to hold in step.

     The Worker says which part of the subscription it would not take, and that
     sentence goes on the screen: it can only ever be a bug on this side, and
     "couldn't save" would send whoever hits it looking at their wifi. */
  function putNotify(sub, series) {
    return fetch(SYNC_ENDPOINT.replace(/\/$/, "") + "/n", {
      method: "PUT", headers: { "content-type": "application/json" },
      // The quiet hours are read here rather than passed in, so every caller —
      // a tick, a change of time, the silent refresh on load — sends the same
      // three things and there is no path that saves papers without them.
      body: JSON.stringify(Object.assign({}, sub.toJSON(), {
        series, after: notifyAfter(), tz: notifyZone(),
      })),
    }).then((r) => r.json().catch(() => null).then((body) => {
      if (!r.ok || !body || body.error) throw new Error((body && body.error) || "HTTP " + r.status);
      return body.series || [];
    }));
  }

  // Ticking saves, so there is no save button to leave unpressed — and one save
  // at a time, because two boxes tapped in a second would otherwise race and the
  // slower answer would be the one stored.
  //
  // The second tick is QUEUED, never dropped: a dropped tick would be
  // repainted from the store by the first save's redraw, and its box would
  // come back unticked.
  //
  // notifyWant is what the panel has been ASKED for; the store is what the
  // Worker has agreed to. Between a tick and its answer the two differ, and a
  // tick made in that window must be counted from the former: counted from the
  // store it silently undoes the tick before it.
  let notifyBusy = false;
  let notifyWant = null;
  const notifyWanted = () => notifyWant || notifySeries();
  function saveNotify(next) {
    notifyWant = next;
    if (notifyBusy) return;
    notifyBusy = true;
    // Redrawn from the store however it ends, so the boxes show what the Worker
    // will actually act on. A tick left standing over a save that failed is the
    // panel promising a notification nobody is going to send. Unless something
    // was ticked while this was in flight: then the newest set goes out instead,
    // and the redraw waits for an answer about what is actually on screen.
    const done = (msg) => {
      notifyBusy = false;
      if (String(notifyWant) !== String(next)) { saveNotify(notifyWant); return; }
      notifyWant = null;
      renderNotifyPanel();
      notifyNote(msg);
    };
    notifyNote(next.length ? "Saving…" : "Turning notifications off…");
    /* Permission is asked for on the first tick and never on load: a prompt
       nobody asked for is how a site gets permanently blocked. And "denied" is
       final — the browser will not ask again however often we do — so the panel
       says where to undo it rather than leaving a box that looks live. */
    Promise.resolve(next.length && Notification.permission === "default"
        ? Notification.requestPermission() : Notification.permission)
      .then((perm) => {
        if (next.length && perm !== "granted") {
          done(perm === "denied"
            ? "Your browser is blocking notifications from this site and won’t ask again — "
              + "allow them in the browser’s settings for this site."
            : "You didn’t allow notifications, so none are turned on.");
          return null;
        }
        return pushSubscription();
      })
      .then((sub) => sub && putNotify(sub, next).then((series) => {
        if (series.length) { store.set(NOTIFY_KEY, series); done("Saved."); return; }
        store.del(NOTIFY_KEY);
        // Nothing on the server points at this browser now, so the address it is
        // still holding is dead weight: dropping it means the next tick asks for
        // a fresh one instead of reviving one that may already have been retired.
        return sub.unsubscribe().catch(() => {})
          .then(() => done("Notifications are off — nothing will be sent to this device."));
      }))
      .catch((err) => done("Couldn’t save — please try again (error: " + ((err && err.message) || err) + ")."));
  }

  /* Re-assert the subscription on load, in the background.

     The Worker keeps one for 180 days and this is the only thing that winds that
     clock, so a device still being opened never expires while one that has
     stopped drops off by itself. It is the repair, too: a browser may retire a
     subscription and mint a new one whenever it likes, and the address left
     behind is otherwise found out only by pushing at it and failing.

     Silent either way. Nobody asked for it, nothing on screen is about it, and
     a load that cannot reach the Worker has the next load to try again. */
  function refreshNotify() {
    if (!notifyAvailable() || iosNeedsHomeScreen()) return;
    const series = notifySeries();
    if (!series.length || Notification.permission !== "granted") return;
    pushSubscription().then((sub) => putNotify(sub, series)).catch(() => {});
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
    const DIR_ORDER = { across: 0, down: 1, offgrid: 2 };
    entries = expandEntries(P.entries).concat(offGridEntries(P)).sort((a, b) =>
      DIR_ORDER[a.direction] - DIR_ORDER[b.direction] || a.number - b.number);
    byId = {};
    entries.forEach((e) => { byId[entryId(e)] = e; });
    leaderOf = buildLeaderOf(entries);
    entries.forEach((e) => {
      if (e.vid || e.offGrid) return;
      for (let i = 0; i < e.length; i++) {
        const x = e.position.x + (e.direction === "across" ? i : 0);
        const y = e.position.y + (e.direction === "down" ? i : 0);
        if (!cells[y][x]) cells[y][x] = { x, y, sol: null, num: null, across: null, down: null, letter: "", wrong: false, revealed: false };
        const c = cells[y][x];
        c[e.direction] = entryId(e);
        if (i === 0) c.num = c.num || e.number;
        if (e.solution) c.sol = e.solution[i];
      }
    });
    // Unclued lights own their squares as entries do, but are walked by their
    // listed cells; printed letters are given, so they are filled and locked.
    unclued = (P.unclued || []).map((u, n) => u.cells.map(({ x, y }, i) => {
      if (!cells[y][x]) cells[y][x] = { x, y, sol: null, num: null, across: null, down: null, letter: "", wrong: false, revealed: false };
      const c = cells[y][x];
      if (c.light === undefined) c.light = n;
      c.unclued = true;
      c.sol = c.sol || (u.solution ? u.solution[i] : null);
      return c;
    }));
    applyPrinted();
  }

  function applyPrinted() {
    (P.printed || []).forEach(({ x, y, letter }) => {
      const c = cells[y] && cells[y][x];
      if (!c) return;
      c.printed = true; c.sol = c.sol || letter;
      c.letter = letter; c.wrong = false; c.revealed = false;
    });
  }

  // The unclued light the cursor is walking: only on a square no entry covers,
  // since a shared square is reached through its entry.
  function currentLight() {
    const c = cells[cur.y] && cells[cur.y][cur.x];
    if (!c || c.across || c.down || c.light === undefined) return null;
    return unclued[c.light];
  }
  function stepLight(delta) {
    const light = currentLight();
    if (!light) return;
    const i = light.findIndex((c) => c.x === cur.x && c.y === cur.y);
    const c = light[Math.min(light.length - 1, Math.max(0, i + delta))];
    cur.x = c.x; cur.y = c.y;
  }
  function selectLight(light) {
    hintFocus = null;
    const c = light.find((q) => !q.letter && !q.across && !q.down)
      || light.find((q) => !q.across && !q.down) || light[0];
    cur.x = c.x; cur.y = c.y;
    if (!c.across && !c.down) cur.dir = "across";
    else if (!c[cur.dir]) cur.dir = c.across ? "across" : "down";
    refreshAll();
  }
  // A square no source answered counts once it is filled.
  const uncluedSolved = () => unclued.every((l) => l.every((c) => (c.sol ? c.letter === c.sol : !!c.letter)));

  // ---------- grid rendering ----------
  function renderGrid() {
    const grid = $("grid");
    grid.innerHTML = "";
    grid.style.gridTemplateColumns = `repeat(${P.dimensions.cols}, var(--cellsize))`;
    grid.style.setProperty("--cols", P.dimensions.cols);
    // The wide layout sizes the grid column off the puzzle's shape, and that
    // column is a sibling of the grid, so the numbers live on their shared parent.
    const lay = grid.closest && grid.closest(".layout");
    if (lay) {
      lay.style.setProperty("--cols", P.dimensions.cols);
      lay.style.setProperty("--rows", P.dimensions.rows);
    }
    if (!layoutTracked) { layoutTracked = true; trackLayoutTop(); }
    for (let y = 0; y < P.dimensions.rows; y++) {
      for (let x = 0; x < P.dimensions.cols; x++) {
        const div = document.createElement("div");
        const c = cells[y][x];
        if (!c) {
          div.className = "cell block";
        } else {
          div.className = "cell" + (c.unclued ? " unclued" : "") + (c.printed ? " printed" : "");
          if (c.num && gridNumbers) div.innerHTML = `<span class="num">${c.num}</span>`;
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
            // above is one of them — so bailing out before it would let a finger
            // that HAD moved fall through to mousedown and select the cell
            // anyway, which is the exact thing this guard exists to stop.
            ev.preventDefault();
            if (touchAnchor && Math.hypot(t.clientX - touchAnchor.x, t.clientY - touchAnchor.y) > 10) return;
            onCellClick(c);
          }, { passive: false });
        }
        grid.appendChild(div);
      }
    }
    // A barred grid's bars: "r" on a cell is a bar on its right, "b" one
    // below it, "+" both.
    (P.bars || []).forEach((row, y) => {
      [...row].forEach((ch, x) => {
        const c = cells[y] && cells[y][x];
        if (!c || !c.el) return;
        if (ch === "r" || ch === "+") c.el.classList.add("bar-r");
        if (ch === "b" || ch === "+") c.el.classList.add("bar-b");
      });
    });
    // word-separator marks; a barred grid has none, as a thick line there
    // would read as a bar
    if (!P.bars) entries.forEach((e) => {
      if (e.vid || e.offGrid) return;   // a virtual lead's squares are its base's; an off-grid clue has none
      (e.clue.separators || []).forEach(({ at: pos, mark }) => {
        if (pos <= 0 || pos >= e.length) return;
        const x = e.position.x + (e.direction === "across" ? pos - 1 : 0);
        const y = e.position.y + (e.direction === "down" ? pos - 1 : 0);
        const c = cells[y][x];
        if (!c || !c.el) return;
        const suffix = e.direction === "across" ? "r" : "b";
        c.el.classList.add((mark === "-" ? "dash-" : "sep-") + suffix);
      });
    });
    refreshGrid();
  }

  // Paul 10-30: "Why do we show a cursor selection when there isnt a keyboard
  // up". On a touch screen the cursor square marks where the next typed letter
  // goes, which means nothing while the keys are away, so it is drawn as one
  // more square of the entry until they return. A screen with no touch (a
  // desktop and its physical keyboard) has no soft keyboard to wait for and
  // always shows it.
  let cursorWasShown = true;
  function cursorVisible() {
    if (typeof navigator === "undefined" || !navigator.maxTouchPoints) return true;
    return keyboardUp();
  }
  // Redraw only on a change, from the events that raise or drop the keys.
  function syncCursor() {
    if (cursorVisible() !== cursorWasShown) refreshGrid();
  }

  function refreshGrid() {
    const e = gridEntry();
    const showCur = cursorWasShown = cursorVisible();
    const typeIt = !jigsaw && nuxTypeIt(e);
    const light = currentLight();
    forEachCell((c) => {
      const el = c.el;
      if (!el) return;
      el.querySelector(".letter").textContent = c.letter;
      el.classList.toggle("wrong", !!c.wrong);
      el.classList.toggle("revealed", !!c.revealed);
      const inEntry = e && ((e.direction === "across" && c.y === e.position.y && c.x >= e.position.x && c.x < e.position.x + e.length)
        || (e.direction === "down" && c.x === e.position.x && c.y >= e.position.y && c.y < e.position.y + e.length));
      el.classList.toggle("hl", !!(inEntry || (light && light.indexOf(c) >= 0)) && !(showCur && c.x === cur.x && c.y === cur.y));
      el.classList.toggle("sel", showCur && c.x === cur.x && c.y === cur.y);
      // The walk's last instruction is "type it in", and this is where that
      // happens: the empty squares wear the walk's pointer.
      el.classList.toggle("walk-point", !!inEntry && !c.letter && typeIt);
    });
  }

  // ---------- clue lists ----------
  // The guard is on the LIST, not on a row: the two clicks land on different
  // rows, which is the whole symptom. See the click handler below.
  const CLUE_TAP_GUARD_MS = 350;
  let lastClueTap = 0;
  // Touches only. The stray second click is something a touchscreen does — iOS
  // synthesises a click for a finger that came down before the list moved and
  // went up after it — and a mouse cannot produce it at all, so a pointer user
  // keeps every click they make. It also keeps this off the test harness, which
  // calls the click handlers directly and would otherwise lose every selection
  // it makes inside one millisecond.
  let clueTouchAt = 0;
  const clueTapIsAnAccident = () => {
    const now = Date.now();
    return now - clueTouchAt < CLUE_TAP_GUARD_MS && now - lastClueTap < CLUE_TAP_GUARD_MS;
  };
  // A jigsaw's clues are one list in their answers' alphabetical order, as the
  // paper printed them: no number, no direction, nothing that says where.
  const jigsawOrder = (list) => list.slice().sort((a, b) =>
    String(a.solution || "").localeCompare(String(b.solution || ""))
    || clueText(a).localeCompare(clueText(b)));
  function renderClues() {
    $("clues-across-h").textContent = jigsaw ? "Clues" : "Across";
    $("clues-down-section").classList.toggle("hidden", jigsaw);
    $("offgrid-section").classList.toggle("hidden", jigsaw || !entries.some((e) => e.offGrid));
    ["across", "down", "offgrid"].forEach((dir) => {
      const ol = $("clues-" + dir);
      ol.innerHTML = "";
      const list = jigsaw ? (dir === "across" ? jigsawOrder(entries) : [])
        : entries.filter((e) => e.direction === dir);
      list.forEach((e) => {
        const li = document.createElement("li");
        li.id = "clue-" + entryId(e);
        li.innerHTML = (jigsaw || e.offGrid ? "" : `<span class="clue-num">${e.number}</span>`) +
          `<span class="clue-text"></span><span class="checkers"></span>`;
        if (e.offGrid) li.appendChild(offGridBox(e));
        // No focusKbd: picking a clue off the list is not a decision to type,
        // so it must not raise a keyboard over half the screen. See the
        // mousedown handler on these lists for the other half of that rule.
        //
        // One tap can only choose one clue. Choosing one rewrites the hint panel
        // and scrolls it into view, so the list moves under the finger between
        // the touch going down and the click coming out — and on an iPad a
        // second click then lands on whatever row has slid into that spot, which
        // is the clue that was selected a moment ago. Nobody picks two clues a third of a
        // second apart on purpose, so the second one is the accident.
        li.addEventListener("click", () => {
          if (clueTapIsAnAccident()) return;
          lastClueTap = Date.now();
          selectEntry(e, true);
        });
        ol.appendChild(li);
      });
    });
    renderUncluedList();
    refreshClues();
  }

  // An off-grid clue's answer is typed into a box on its own row. The grid's
  // key handler ignores inputs, so typing here moves no cursor; focusing the
  // box picks the clue for the hint panel without scrolling to it.
  function offGridBox(e) {
    const box = document.createElement("input");
    box.className = "offgrid-answer";
    box.maxLength = e.length;
    box.size = e.length;
    box.autocomplete = "off";
    box.spellcheck = false;
    box.setAttribute("autocapitalize", "characters");
    box.setAttribute("aria-label", "Answer (" + (e.clue.enumeration || e.length) + ")");
    box.addEventListener("click", (ev) => ev.stopPropagation());
    box.addEventListener("focus", () => { if (pick !== e) { hintFocus = null; pick = e; refreshAll(); } });
    box.addEventListener("input", () => {
      const v = box.value.toUpperCase().replace(/[^A-Z]/g, "").slice(0, e.length);
      box.value = v;
      e.typed = v; e.revealed = false;
      checkSolvedEntries(true);
      refreshAll(); saveState();
    });
    return box;
  }

  // Unclued lights have no clue to show, only what the puzzle says they are.
  function renderUncluedList() {
    const ol = $("clues-unclued");
    if (!ol) return;
    ol.innerHTML = "";
    $("unclued-section").classList.toggle("hidden", !unclued.length);
    (P.unclued || []).forEach((u, n) => {
      const li = document.createElement("li");
      li.className = "unclued-light";
      li.innerHTML = `<span class="clue-text">${esc(u.note || "Unclued light")}</span>`
        + (u.enumeration ? `<span class="clue-enum"> (${esc(u.enumeration)})</span>` : "");
      li.addEventListener("click", () => {
        if (clueTapIsAnAccident()) return;
        lastClueTap = Date.now();
        selectLight(unclued[n]);
      });
      ol.appendChild(li);
    });
  }

  // Every rung marks up its OWN words, independently of the others.
  //
  // Markup is not gated on the definition rung. Tier 0 lets you take the rungs
  // in any order — asking for the indicators first is a legitimate route
  // because working out where the definition sits is most of the skill — so a
  // clue with only the indicator rung up must still show them.
  // Rule: highlight exactly what has been revealed, and
  // never anything that hasn't.
  // The setter's italics and the solver's highlights are two independent lists
  // of ranges over the same plain string (tools/fetch_puzzle.flatten_clue keeps
  // the clue plain so that annotation fragments can still be found in it by
  // indexOf). They overlap freely — an italicised title can BE the definition —
  // so instead of nesting one inside the other the clue is cut at every
  // boundary either list has and each piece wrapped in whatever covers it.
  // Adjacent pieces of one italic render as one italic; nothing shows the seam.
  // `edges` asks for data-edge="start"/"end" on the pieces that sit at the two
  // ends of a mark. A caller that marks up a whole string gets one <mark> per
  // range and has no use for it; a caller that marks the same range up in
  // pieces — pickableClueHTML, a piece per word and a piece per space — needs
  // to know which pieces are the ends, because the pieces paint as one band and
  // only a band's ends are rounded.
  function markUp(text, marks, italics, edges) {
    // Curled whole, before it is cut, so each quote is read in context.
    text = CTQuotes.curl(text);
    const cuts = [0, text.length];
    marks.forEach((m) => cuts.push(m.i, m.i + m.len));
    italics.forEach((r) => cuts.push(r.at, r.at + r.length));
    const pts = cuts.filter((p, i) => p >= 0 && p <= text.length && cuts.indexOf(p) === i)
                    .sort((a, b) => a - b);
    let out = "";
    for (let s = 0; s < pts.length - 1; s++) {
      const a = pts[s];
      const covers = (i, len) => i <= a && a < i + len;
      const m = marks.filter((k) => covers(k.i, k.len))[0];
      let piece = esc(text.slice(a, pts[s + 1]));
      if (italics.filter((r) => covers(r.at, r.length)).length) piece = "<i>" + piece + "</i>";
      // A mark cut short by the slice it was asked about is not ending here: the
      // rest of it is in the next slice, so it opens or closes nothing.
      const edge = m && edges
        ? `${a === m.i ? " start" : ""}${pts[s + 1] === m.i + m.len ? " end" : ""}`.trim()
        : "";
      out += m
        ? `<mark class="${m.cls}"${edge ? ` data-edge="${edge}"` : ""}>${piece}</mark>`
        : piece;
    }
    return out;
  }
  // Italics are the setter's, so they show whether or not any hint is up.
  // clue.italics are code-point ranges; markUp cuts by string index.
  const italicsOf = (e) => (e.clue.italics || []).map((r) => {
    const at = cpToIdx(clueText(e), r.at);
    return { at, length: cpToIdx(clueText(e), r.at + r.length) - at };
  });
  // The clue's words, without its enumeration; "" where the paper printed none.
  function clueText(e) { return e.clue.text || ""; }
  // The enumeration printed after the words, as the paper prints it: " (5,4)".
  // A clue whose words the source lost and we rebuilt from the wordplay
  // (schema clue.reconstructed) says so after its enumeration, every time it
  // is drawn: the words are ours, not the paper's.
  const reconstructedHTML = (e) => (e.clue.reconstructed
    ? ` <span class="clue-reconstructed" title="The source lost words of this clue and no other print was found: these words are rebuilt from the answer's wordplay, not printed">reconstructed</span>` : "");
  const enumHTML = (e) => (e.clue.enumeration
    ? `<span class="clue-enum">${clueText(e) ? " " : ""}(${esc(e.clue.enumeration)})</span>` : "") + reconstructedHTML(e);
  const plainClueHTML = (e) => markUp(clueText(e), [], italicsOf(e)) + enumHTML(e);

  // Where a fragment goes is a placement, not a search. indexOf() takes the
  // first substring that matches, and that goes wrong two ways:
  //
  //   mid-word  the indicator 'in' matches inside "Conclud(in)g", "island",
  //             "confusion", marking a syllable of an innocent word instead of
  //             the instruction;
  //   dropped   because the wrong position usually lands under the definition,
  //             the overlap rule below would throw the indicator away
  //             entirely — and always the indicator, because indicators are
  //             pushed last and the loser is whoever comes second. Buying the
  //             definition would make an earlier hint vanish.
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
    // A whole word somewhere else beats a syllable of the right word: the
    // fragment is a word of the clue, so a match that is not one is a
    // coincidence of spelling. Ties go to the earliest.
    const rank = (i) => {
      const b = onBoundary(i), f = free(i);
      return b && f ? 0 : b ? 2 : f ? 3 : 4;
    };
    let best = -1;
    for (let i = clue.indexOf(text); i >= 0; i = clue.indexOf(text, i + 1))
      if (best < 0 || rank(i) < rank(best)) best = i;
    return best;
  }

  // Every fragment the annotation names, with the position it claims, in
  // annotation order. Every fragment claims its position whether or not it has
  // been bought, and the highlighter and the grader both read from here. A
  // position that depended on what had been paid for would move the link word
  // to a different "in" as soon as the indicators were bought.
  //
  // A definition carries its offset (`at`), so it claims exactly that span
  // first. The rest search, longest first: a long fragment usually has one
  // possible position and a short one has several.
  //
  // Link words claim after everything else, because a connective is a word or
  // two the clue is free to use twice: "Wears underwear twisted in the middle
  // in drinking spots" has one "in" inside the indicator and one doing the
  // linking. If they claimed first, a word could be taken away from a hint
  // the solver has bought, and the highlighter must never do that.
  function placedFragments(e) {
    const ann = annOf(e);
    if (!ann) return [];
    const frags = [];
    const add = (text, kind, at) => { if (text) frags.push({ text, kind, n: frags.length, at }); };
    (ann.definitions || []).forEach((d, k) => add(d.text, k ? "def2" : "def", d.at));
    (ann.indicators || []).forEach((t) => add(t.text, "ind"));
    (ann.linkWords || []).forEach((t) => add(t, "link"));
    // A definition's position is stored, so it claims that span before anything
    // searches; the rest are placed around it.
    const taken = [];
    for (const f of frags) {
      if (f.at === undefined) continue;
      const i = f.at >= 0 ? cpToIdx(clueText(e), f.at) : -1;
      f.i = i >= 0 && clueText(e).slice(i, i + f.text.length) === f.text ? i : -1;
      if (f.i >= 0) taken.push({ i: f.i, len: f.text.length });
    }
    const order = frags.filter((f) => f.at === undefined).sort((a, b) =>
      (a.kind === "link") - (b.kind === "link") || b.text.length - a.text.length || a.n - b.n);
    for (const f of order) {
      f.i = bestOccurrence(clueText(e), f.text, taken);
      if (f.i >= 0) taken.push({ i: f.i, len: f.text.length });
    }
    return frags.filter((f) => f.i >= 0);
  }

  // Which stretches of the clue are lit, and why. Kept apart from clueHTML
  // because the same ranges have to be painted twice over: once across the whole
  // string, and once word by word when the words themselves are the targets of a
  // question — see pickableClueHTML.
  function clueMarks(e) {
    // Link words ride with the definition rung: all they do is show where the
    // definition stops and the wordplay starts, which gives away where the
    // definition ends. They do not have a rung of their own.
    const rungOf = { def: "definition", def2: "definition", link: "definition", ind: "indicators" };
    const marks = placedFragments(e)
      .filter((f) => isShown(e, rungOf[f.kind]))
      .map((f) => ({ i: f.i, len: f.text.length, cls: f.kind }));
    // Where two marks still overlap — an indicator genuinely sitting inside the
    // definition — markUp gives each cut piece to the FIRST mark that covers it,
    // so shortest-first hands the overlap to the more specific of the two and
    // the longer one keeps everything either side. Both stay visible; neither is
    // thrown away.
    //
    // Two marks on the EXACTLY same range have no more-specific one to choose
    // between: a word can be its own anagram indicator and the definition at
    // once ("Held Ruby's piano composition"). They become one mark wearing both
    // classes, because handing the range to whichever was pushed first takes a
    // hint the solver has paid for off the screen.
    const merged = [];
    for (const m of marks.sort((a, b) => a.len - b.len)) {
      const same = merged.find((k) => k.i === m.i && k.len === m.len);
      if (same) same.cls += " " + m.cls;
      else merged.push({ ...m });
    }
    return merged;
  }

  const clueHTML = (e) => markUp(clueText(e), clueMarks(e), italicsOf(e)) + enumHTML(e);

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
      const li = $("clue-" + entryId(e));
      if (!li) return;
      const holder = holderOf(e);
      const solved = isEntrySolved(e);
      li.querySelector(".clue-text").innerHTML = ((holder === e) ? clueHTML(e) : plainClueHTML(e))
        + (solved && holder === e ? hiddenLetterHTML(e) : "");
      // Nothing to tell you about a clue you have finished — the row greys out
      // and a full row of dots would just be noise on every solved line.
      li.querySelector(".checkers").innerHTML = (solved || jigsaw) ? "" : checkerDots(e);
      const box = e.offGrid && li.querySelector(".offgrid-answer");
      if (box) {
        if (box.value !== e.typed) box.value = e.typed;
        box.readOnly = solved;
      }
      li.classList.toggle("active", !!curE && entryKey(curE) === entryKey(e));
      li.classList.toggle("solved", solved);
      // The gold star is a standing fact about how this clue was solved, not a
      // moment — it must be right on every render, including a fresh boot that
      // never ran celebrateSolve() at all.
      li.classList.toggle("no-hints", solved && noHintsSolve(e));
    });
    renderHiddenMessage();
    keepActiveClueInView();
  }

  // The wide layout (style.css, "wide screens") gives each clue list its own
  // scrollbar, so the page no longer carries the active clue into view. Move only
  // that list's scroller, never the page; a no-op where the list does not scroll.
  function keepActiveClueInView() {
    const li = document.querySelector && document.querySelector(".clue-list li.active");
    const box = li && li.closest && li.closest(".clue-list");
    if (!box || box.scrollHeight <= box.clientHeight + 1) return;
    const lt = li.offsetTop - box.offsetTop;
    if (lt < box.scrollTop + 30) box.scrollTop = Math.max(0, lt - 30);
    else if (lt + li.offsetHeight > box.scrollTop + box.clientHeight - 8) {
      box.scrollTop = lt + li.offsetHeight - box.clientHeight + 8;
    }
  }

  // Where the puzzle starts on the page, for the wide layout's height sum (CSS
  // cannot know how tall the header and preamble above it are).
  let layoutTracked = false;
  function trackLayoutTop() {
    const lay = document.querySelector && document.querySelector("#app .layout");
    if (!lay || !lay.getBoundingClientRect) return;
    const set = () => {
      const r = lay.getBoundingClientRect();
      const y = r.top + (window.pageYOffset || 0);
      if (y > 0) document.documentElement.style.setProperty("--lay-top", Math.round(y) + "px");
    };
    set();
    if (window.ResizeObserver) {
      const head = document.querySelector(".puzzle-head");
      if (head) new ResizeObserver(set).observe(head);
    }
    window.addEventListener("resize", set);
  }

  // A hidden-letter device (tools/hidden_messages.py): the letter a clue's
  // wordplay adds, omits or misprints, shown on the clue once it is solved and
  // never before, since it narrows the answer.
  const HIDDEN_KIND = { extra: "extra letter", omitted: "omitted letter",
    misprint: "misprint, corrected", clue: "letter from the clue" };
  function hiddenLetterOf(e) {
    const h = (e.annotation || {}).hiddenLetter;
    return h && h.letter ? h : null;
  }
  function hiddenLetterHTML(e) {
    const h = hiddenLetterOf(e);
    if (!h) return "";
    const what = h.kind === "misprint" ? `${esc(h.printed)}→${esc(h.letter)}` : esc(h.letter);
    return ` <span class="hidden-letter" title="${esc(HIDDEN_KIND[h.kind] || "")}">${what}</span>`;
  }

  // The phrase the hidden letters spell (P.messages), built under the grid one
  // letter per solved clue, in the message's order; spaces and hyphens show
  // from the start so the solver sees the phrase's shape.
  function renderHiddenMessage() {
    const el = $("hidden-message");
    if (!el) return;
    const msgs = (P && P.messages) || [];
    el.classList.toggle("hidden", !msgs.length || paperHides());
    el.innerHTML = msgs.map((m) => {
      const givers = entries.filter((e) => holderOf(e) === e
        && (!m.direction || e.direction === m.direction)
        && (hiddenLetterOf(e) || {}).kind === m.kind);
      const letterOf = (e) => (m.printed ? hiddenLetterOf(e).printed : hiddenLetterOf(e).letter);
      const solved = givers.filter(isEntrySolved);
      // Unordered letters fill left to right as they come; ordered ones take
      // their own clue's place.
      const queue = m.order === "unordered" ? solved.map(letterOf) : null;
      let i = 0;
      const slots = [...m.text].map((ch) => {
        if (!/[A-Z]/.test(ch)) return `<span class="hm-gap">${esc(ch)}</span>`;
        const e = givers[i++];
        const got = queue ? queue.shift() : (e && isEntrySolved(e) ? letterOf(e) : "");
        return got ? `<span class="hm-letter">${esc(got)}</span>` : `<span class="hm-slot"></span>`;
      }).join("");
      return `<span class="hm-row">${slots}</span>`;
    }).join("");
  }

