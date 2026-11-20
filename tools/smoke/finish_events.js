// Finishing the grid, nods, the event names and link words.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { EVENTS, ROOT, assert, beacons, clueText, defTexts, entryId, ev, fs, isAsking, kd,
  openFromPicker, panelHTML, path, pickerRowFor, registry, reported } = T;
// --- finishing the grid is an event, not a number going up ---
// "There should be some celebration when you complete." Two properties, and the
// second is what keeps it from being noise: it fires on the TRANSITION, in the
// session that earned it, so re-opening a puzzle you finished last week throws
// no paper at you. And what it says is the scoreline — clues, unaided solves,
// hints spent, minutes — because that is the part a solver cannot see anywhere
// else once the grid is full.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  const id = Object.keys(puzzles).sort().find((k) =>
    (puzzles[k].entries || []).every((e) => e.solution));
  assert(id, "some puzzle in the corpus ships every solution");
  const open = () => openFromPicker(id);
  // The vote tally comes back from /v whenever it comes back, and "whenever"
  // includes the second and a half the fireworks are in the air. Held here
  // rather than left to the network, so the test can land it exactly then.
  // Settled synchronously, because the suite has no event loop turn to wait in
  // and app.js consumes the reply with .then(), never await. Everything that is
  // not the tally simply stays in flight, which is what a slow network looks
  // like and is the honest thing for a harness with no server behind it.
  const inFlight = { then: () => inFlight, catch: () => inFlight };
  const realFetch = global.fetch;
  let landTally = null;
  global.fetch = (url) => {
    if (!/\/v\?/.test(String(url))) return inFlight;
    const queued = [];
    const chain = { then(f) { queued.push(f); return chain; }, catch() { return chain; } };
    landTally = (tally) => {
      let v = { ok: true, json: () => tally };
      queued.forEach((f) => { v = f(v); });
    };
    return chain;
  };

  const firstOpen = beacons.length;
  open();
  const box = registry["celebrate"];
  assert(box.classList.contains("hidden"), "nothing is celebrated on opening a fresh grid");
  // #celebrate is two children: the burst and the scoreline, kept apart so a
  // tally landing mid-burst cannot delete the fireworks. The separation is
  // itself the thing under test.
  const childOf = (cls) => box.children.find((c) => c.classList.contains(cls));
  const said = () => (childOf("scoreline") || { innerHTML: "" }).innerHTML;

  const puz = puzzles[id];
  const cols = puz.dimensions.cols;
  const cellAt = (x, y) => registry["grid"].children[y * cols + x];
  const squares = new Set();
  const walk = (e, f) => {
    for (let i = 0; i < e.length; i++) {
      f(e.direction === "across" ? e.position.x + i : e.position.x,
        e.direction === "across" ? e.position.y : e.position.y + i, i);
    }
  };
  puz.entries.forEach((e) => walk(e, (x, y) => squares.add(x + "," + y)));

  // Filled square by square, the way a solver does it, so the moment of
  // completion is the moment the LAST light square gets its letter — which is
  // somewhere in the middle of an entry, not at the end of a loop.
  // Laid out out of the band, which is where it is when the last letter lands:
  // the box sits between the title and the grid, so on a phone the page has
  // scrolled down to the grid with the keyboard up and the box is off the top,
  // and on a tablet the whole page fits and it is already in view. Off the
  // bottom here — the same travel, and the easier of the two to nail down.
  registry["celebrate"].layout(1800, 120);
  global.window.pageYOffset = 0; global.window.scrolls.length = 0;
  const filled = new Set();
  let fired = 0;
  for (const e of puz.entries) {
    walk(e, (x, y, i) => {
      const k = x + "," + y;
      if (filled.has(k)) return;
      cellAt(x, y).listeners.mousedown[0]({ preventDefault() {} });
      kd(ev(e.solution[i]));
      filled.add(k);
      const done = filled.size === squares.size;
      if (!box.classList.contains("hidden")) fired++;
      assert(box.classList.contains("hidden") !== done,
        done ? "the last light square in the grid is celebrated: " + said()
             : `the grid is ${squares.size - filled.size} squares short and it celebrated anyway`);
    });
  }
  assert(fired === 1, "and celebrated once, not on every keystroke after: " + fired);
  assert(/\d+<\/strong> clues/.test(said()) && /hint/.test(said()),
    "and it says what was achieved, not just that something was: " + said());
  // Fireworks, and every spark carrying the vector it flies along: a burst whose
  // sparks all share one angle is a dribble, and that is only visible by eye.
  const burst = childOf("fireworks");
  assert(burst && (burst.innerHTML.match(/--dx:/g) || []).length > 20,
    "finishing sets off fireworks, each spark with its own vector: "
    + (burst && burst.innerHTML));
  // Held, and held by nobody having looked yet — not by a scroll having been
  // ordered. It needs fake_dom's IntersectionObserver: without one the app takes
  // its "no observer, burn now" branch, and a burst that went off into an empty
  // screen looks exactly like one that went off in front of someone.
  assert(burst.classList.contains("hold"),
    "the burst waits rather than burning into a page that is still moving: " + burst.className);
  // LIVE observers, and exactly one of them. The .fireworks node is built once
  // and reused by every finish in the session, so an observer left watching it
  // is still there for the next burst — one for every grid any earlier test in
  // this file has finished, all of them watching the same div. Keep it
  // counting every watcher of the node, not just the one this burst made, or it
  // stops being able to see that again.
  assert(global.watchersOf(burst) === 1,
    "and exactly one observer is watching for the box to arrive: " + global.watchersOf(burst));
  // And the page goes to it. The keyboard is up — the last letter of the puzzle
  // was just typed — so a finish nobody scrolls to is a vote never asked for.
  global.flushTimers(10000);
  assert(global.window.scrolls.length === 1,
    "finishing moves the page once, to the finish box: "
    + JSON.stringify(global.window.scrolls));
  {
    const r = registry["celebrate"].getBoundingClientRect();
    assert(r.top >= 0 && r.bottom <= global.window.innerHeight,
      `and the whole box is on screen after it (top ${r.top}, bottom ${r.bottom}, `
      + `viewport ${global.window.innerHeight})`);
  }

  // --- the tally arriving cannot take the fireworks with it ---
  // The /v reply redraws the scoreline, and it lands whenever it lands: the
  // request goes out when the puzzle opens, so it is routinely still in the air
  // as the last letter goes in. Redrawing the whole box would delete the
  // .fireworks div mid-burst and re-arm nothing, taking the burst away from
  // someone who WAS looking at it. So this asserts the structure: same node, same
  // sparks, same state, and a scoreline that really did change underneath.
  assert(typeof landTally === "function", "the finish box asked /v for the tally when it opened");
  {
    const sparks = burst.innerHTML;
    landTally({ [`p:${id}`]: { up: 7, down: 1 } });
    assert(/7 of 8 liked it/.test(said()),
      "the tally landing really does redraw the scoreline: " + said());
    assert(childOf("fireworks") === burst && burst.innerHTML === sparks
      && burst.classList.contains("hold"),
      "and the burst it redraws around is untouched: " + burst.className);
  }

  // --- and it goes off when, and only when, the box is looked at ---
  assert(global.intersect(burst) === 1,
    "the observer really is watching the burst, so this record reaches it");
  assert(!burst.classList.contains("hold") && burst.classList.contains("lit"),
    "the first intersecting record lets the burst go: " + burst.className);
  assert(global.watchersOf(burst) === 0,
    "and the observer disconnects behind it rather than firing all afternoon");
  // Spent, not left in the page. A burst that has finished is invisible either
  // way, so without a state on the element the DOM cannot tell "over" from
  // "never happened".
  global.flushTimers(10000);
  assert(burst.classList.contains("spent") && burst.innerHTML === "",
    "and the shells come out of the page once they have burned: " + burst.className);
  // Nothing to dismiss, and nothing that can dismiss it: the scoreline is a
  // fact about the puzzle, not a notification. It has to
  // survive the renders that follow, which is what a stray keystroke causes.
  assert(!registry["celebrate-done"], "and there is no Thanks button to clear it away");
  const settled = said();
  cellAt(puz.entries[0].position.x, puz.entries[0].position.y)
    .listeners.mousedown[0]({ preventDefault() {} });
  assert(!box.classList.contains("hidden") && said() === settled,
    "and it stays, unchanged, when the grid is redrawn under it: " + said());

  // --- and the solve was counted, once per thing, not once per keystroke ---
  // A whole grid is hundreds of keystrokes and dozens of finished entries. If
  // the at-most-once set ever stops holding, this is where it shows: the run
  // above would report a beacon per letter instead of a beacon per milestone.
  {
    const sent = reported(firstOpen);
    assert(sent.every((n) => EVENTS.indexOf(n) >= 0),
      "every name reported is on the shared list in sync/events.js: " + sent.join(","));
    assert(new Set(sent).size === sent.length,
      `a solved grid reports each name once, not once per keystroke: ${sent.length} beacons, `
        + sent.join(","));
    ["open", "letter", "half", "entry", "done"].forEach((n) => assert(sent.indexOf(n) >= 0,
      `filling the whole grid reports "${n}": ` + sent.join(",")));
    assert(beacons.every((b) => /\/e$/.test(b.url) && b.body.type === "text/plain"),
      "and it goes to /e as text/plain, which is what keeps it free of a preflight");
  }
  const reopen = beacons.length;
  // Re-opening the finished puzzle: still solved, nothing earned. The save is
  // debounced, so it has to be flushed first — without that the reopened grid
  // comes back empty and this assertion passes for the wrong reason.
  global.flushTimers(200);
  open();
  assert(/Solved <strong>(\d+)\/\1<\/strong>/.test(registry["scorebar"].innerHTML),
    "the reopened puzzle really is the finished one: " + registry["scorebar"].innerHTML);
  // Re-opening it shows the scoreline again — it is what you did to this
  // puzzle, and it reads the same next week — but throws no paper. The paper
  // is the moment; the sentence is the record.
  assert(!box.classList.contains("hidden") && /<strong>\d+<\/strong> clues/.test(said()),
    "re-opening a puzzle you already finished still shows what you did: " + said());
  // Asserted on the burst node, not by grepping the box for a class name, which
  // passes just as well once the name no longer exists.
  assert(childOf("fireworks").innerHTML === "",
    "but does not throw fireworks at you a second time: " + childOf("fireworks").innerHTML);
  // The same rule the celebration follows, in the counter: progress that was
  // already in the grid when it opened belongs to the session that made it.
  // Without this a returning solver's every visit would report a finished
  // puzzle again, and "how many people finish" would count sessions.
  // Opening it through the picker reports "picker" too; that is a panel
  // being used, not the solve, so the panel names (the ones events.js lists
  // after "done") are left out of what is compared.
  const panels = EVENTS.slice(EVENTS.indexOf("done") + 1);
  assert(reported(reopen).filter((n) => panels.indexOf(n) < 0).join(",") === "open",
    "re-opening a finished puzzle reports only that it was opened: "
      + reported(reopen).join(","));

  // --- a burst nobody ever looked at is given up, and says so ---
  // The other half of the observer. If the box never comes on screen the sparks
  // must not be left in the page frozen at opacity 0, and the four ways a burst
  // can end must not all be the same nothing.
  // Solved again from a reset, because that is the only way to a second, unseen
  // burst; the same node holds it, which is why the abandon timer names the run
  // it belongs to rather than trusting the node it finds.
  {
    registry["reset-puzzle"].onclick();
    assert(box.classList.contains("hidden"), "clearing the grid takes the finish box with it");
    const again = new Set();
    for (const e of puz.entries) {
      walk(e, (x, y, i) => {
        const k = x + "," + y;
        if (again.has(k)) return;
        cellAt(x, y).listeners.mousedown[0]({ preventDefault() {} });
        kd(ev(e.solution[i]));
        again.add(k);
      });
    }
    assert(childOf("fireworks") === burst && burst.classList.contains("hold"),
      "solving it again after a reset earns a fresh burst in the same node: " + burst.className);
    global.flushTimers(61000);
    assert(burst.classList.contains("missed") && !burst.classList.contains("hold"),
      "a burst nobody ever looked at is given up rather than burned into an empty "
      + "screen, and the element says so: " + burst.className);
    assert(burst.innerHTML === "",
      "and its shells come out of the page rather than sitting there invisible: "
      + burst.innerHTML);
  }
  global.fetch = realFetch;
}

// --- a single clue's own solve gets a gentle nod, once, only when typed ---
// "Celebrate gently when a clue is solved," in two tiers: any solve settles a
// tint on its cells, and a solve with
// no hints taken and no letters revealed also earns a small gold marker that
// STAYS on the clue row after the flash fades — the thing worth highlighting
// is the fact, not the moment. See celebrateSolve()/noHintsSolve() in app.js;
// noHintsSolve reuses hintsCharged()/revealsUsed, the exact figures the
// scorebar's own "n with no hints" tally already reads, so there is no second,
// driftable definition of "clean" and nothing new to persist — solvedWith and
// revealsUsed are already saved for scoring.
//
// Reuses the one running instance rather than a second boot(): a mid-file
// boot() leaves the ORIGINAL instance's picker unable to find "Definition" in
// the run-of-words test further down — some piece of shared state does not
// survive a second app existing at once. Every other test on this fixture puzzle gets a clean
// slate the same way: open it and click reset-puzzle.
{
  const id = "cryptic-30066";
  const openFresh = () => openFromPicker(id);
  openFresh();
  registry["reset-puzzle"].onclick();
  const key = (k) => kd(ev(k));
  const puz = global.window.CRYPTIC_PUZZLES[id];
  const cols = puz.dimensions.cols;
  const cellsOf = (e) => {
    const out = [];
    for (let i = 0; i < e.length; i++) {
      const x = e.direction === "across" ? e.position.x + i : e.position.x;
      const y = e.direction === "across" ? e.position.y : e.position.y + i;
      out.push(registry["grid"].children[y * cols + x]);
    }
    return out;
  };
  const select = (e) => registry["clue-" + entryId(e)].listeners.click[0]();

  const candidates = (puz.entries || []).filter((e) => e.solution && e.length >= 2);
  assert(candidates.length >= 3, "cryptic-30066 has at least three typeable entries");
  const [cleanE, otherE, revealedE] = candidates;

  // --- tier 1: solved by typing, no hints taken — the clean tier ---
  select(cleanE);
  const cells = cellsOf(cleanE);
  // The clean-solve burst goes over the clue panel's letter boxes, the box
  // being worked in, not the grid: spy on which rect fireworksAt measures.
  const panelEl = registry["hint-pattern"], midEl = cells[Math.floor(cells.length / 2)];
  const measured = [];
  const spyRect = (el, name) => {
    const orig = el.getBoundingClientRect;
    el.getBoundingClientRect = function () { measured.push(name); return orig.call(this); };
    return () => { el.getBoundingClientRect = orig; };
  };
  const unspyPanel = spyRect(panelEl, "panel"), unspyMid = spyRect(midEl, "mid");
  // The panel is laid out in page space: earlier sections leave the window
  // scrolled, which would put this box above the viewport (not on screen).
  const savedYOffset = global.window.pageYOffset;
  global.window.pageYOffset = 0;
  panelEl.layout(100, 200);
  cleanE.solution.slice(0, -1).split("").forEach((c) => key(c));
  assert(!cells.some((c) => c.classList.contains("solved-flash")),
    "an entry one letter short of solved gets no flash yet");
  key(cleanE.solution[cleanE.solution.length - 1]);
  assert(cells.every((c) => c.classList.contains("solved-flash")),
    "every cell of the just-solved entry carries the settling flash");
  // measured: onScreenBox's own look (panel), then fireworksAt's (panel again).
  assert(measured.includes("panel") && !measured.includes("mid"),
    "a clean solve's burst is centred on the clue panel, not the grid square: " + measured);
  unspyPanel(); unspyMid();
  // Panel not laid out (no box on screen): fall back to the middle square.
  // Solve otherE on an empty grid with the panel at 0x0.
  // Both the letter boxes and the hint panel must be off screen, or the burst
  // legitimately lands on the panel (onScreenBox tries #hint-pattern, then #hint-panel).
  // The reset matters: otherE (1-down) shares its first square with cleanE
  // (1-across), and selecting a clue puts the cursor on its first EMPTY square,
  // so typing the whole answer over cleanE's letter lands one square late and
  // otherE never solves, so it never bursts at all.
  registry["reset-puzzle"].onclick();
  panelEl.layout(0, 0);
  registry["hint-panel"].layout(0, 0);
  select(otherE);
  const otherMid = cellsOf(otherE)[Math.floor(otherE.length / 2)];
  measured.length = 0;
  const unspyOther = spyRect(otherMid, "mid");
  otherE.solution.split("").forEach((c) => key(c));
  assert(measured.includes("mid"), "no panel on screen: the burst falls back to the middle square: " + measured);
  unspyOther();
  global.window.pageYOffset = savedYOffset;
  registry["reset-puzzle"].onclick();
  select(cleanE);
  cleanE.solution.split("").forEach((c) => key(c));
  // No flush here: the 450ms timer is what removes the gold class again.
  assert(cells.every((c) => c.classList.contains("clean")),
    "solved with no hints and no reveals gets the gold tier, distinct from the green one");
  assert(registry["clue-" + entryId(cleanE)].classList.contains("no-hints"),
    "the clue row picks up the persistent no-hints marker");

  // The flash is transient...
  global.flushTimers(500);
  assert(!cells.some((c) => c.classList.contains("solved-flash") || c.classList.contains("clean")),
    "the flash classes clear themselves once the settle is over");
  // ...but the marker on the row is a standing fact about how it was solved,
  // not a leftover of the animation — it must still be there with no flash.
  assert(registry["clue-" + entryId(cleanE)].classList.contains("no-hints"),
    "the no-hints marker outlives the flash");
  // The squares are the other way round: the flash is the whole of it, and a
  // finished word leaves no standing tint behind ("you don't have to add the
  // green to locked in letters on the grid, it is a bit gross"). The lock
  // announces itself when it is bumped into — a pulse and
  // a cursor that moves — not by colouring a filling grid.
  assert(!cells.some((c) => c.classList.contains("confirmed")),
    "a solved entry's squares carry no standing tint once the flash is over");

  // --- fires once: a later re-render of the board must not replay it ---
  select(otherE);
  key(otherE.solution[0]);
  assert(!cells.some((c) => c.classList.contains("solved-flash")),
    "typing into a different entry re-renders the board but does not replay " +
    "the flash on an entry that was already solved");

  // --- a revealed answer is not a solve: neither tier, on a fresh entry ---
  // Every clue in this puzzle is annotated, so "Fill in answer" only appears
  // once the blocks rung is up (or the ladder is exhausted) — climb it the
  // same way the sync-reply test below does, answering any question asked
  // along the way rather than guessing at it.
  select(revealedE);
  let climbGuard = 12;
  while (!registry["hx-entry"] && climbGuard--) {
    const btn = registry["hint-next"].children.find((b) => !b.disabled);
    if (!btn) break;
    btn.onclick();
    if (isAsking(registry["hint-body"])) registry["guess-tell"].onclick();
  }
  const hx = registry["hx-entry"];
  if (assert(hx && hx.onclick, "fill-in-answer becomes reachable once the ladder is climbed")) {
    hx.onclick();
    const rcells = cellsOf(revealedE);
    assert(!rcells.some((c) => c.classList.contains("solved-flash") || c.classList.contains("clean")),
      "revealing the whole answer gets no flash, of either tier");
    assert(!registry["clue-" + entryId(revealedE)].classList.contains("no-hints"),
      "and no gold marker either — a reveal is not a clean solve");
  }

  // --- the no-hints marker survives a restore, not just a re-render ---
  // Closing the puzzle in the picker and reopening it goes through the same
  // save/restore path a reload does; the row is rebuilt from scratch, so this
  // is the marker coming back from solvedWith/revealsUsed rather than from
  // anything the flash itself touched.
  global.flushTimers(200);
  openFresh();  // no reset this time — this is the restore path under test
  assert(registry["clue-" + entryId(cleanE)].classList.contains("no-hints"),
    "the no-hints marker survives closing and reopening the puzzle");
  assert(!registry["clue-" + entryId(revealedE)].classList.contains("no-hints"),
    "and a revealed entry still carries no marker after that same restore");
}

// --- a misspelled event name is invisible forever, so it fails here ---
// The list in sync/events.js is the whole contract: app.js may only report a
// name on it and the Worker only stores names on it. Both ends are checked
// against the one file, because a name that drifts is not an error anywhere —
// it is a counter that reads zero, which looks exactly like a thing nobody does.
{
  const app = require("../app_src").read(ROOT);
  const worker = fs.readFileSync(path.join(ROOT, "sync/worker.js"), "utf8");
  const page = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

  assert(Array.isArray(EVENTS) && new Set(EVENTS).size === EVENTS.length && EVENTS.length > 0,
    "sync/events.js is a list of distinct names: " + JSON.stringify(EVENTS));

  // The whole argument, so the rung beacons — whose name is built rather than
  // written — are not mistaken for a literal called "hint".
  const literals = [...app.matchAll(/beacon\("([^"]+)"\)/g)].map((m) => m[1]);
  assert(literals.length >= 5, "app.js reports events at all: " + literals.join(","));
  literals.forEach((n) => assert(EVENTS.indexOf(n) >= 0,
    `app.js reports "${n}", which is not on the list in sync/events.js`));
  const nuxIds = [...app.matchAll(/\{ id: "(\w+)",/g)].map((m) => m[1]).filter((i) => i !== "welcome");
  assert(/beacon\("nux-" \+ line\.id\)/.test(app) && nuxIds.join() === "ladder,free,score,done",
    "app.js reports each tour line by id: " + nuxIds.join());
  nuxIds.forEach((i) => assert(EVENTS.indexOf("nux-" + i) >= 0, `tour line "${i}" has no "nux-${i}" on the list in sync/events.js`));
  // The rung beacons are named for the rung rather than written out, so the
  // grep above cannot see them: take the rungs from the ladder itself — every
  // key of RUNG_TIER, plus the answer rung, which sits outside the tiers — and
  // hold the two lists together in BOTH directions. A rung the app can reveal
  // with no name on the list is a hint the Worker drops on the floor; a name on
  // the list with no rung behind it is a column that reads zero forever, and
  // neither is an error anywhere else.
  assert(/beacon\("hint-" \+ rung\)/.test(app),
    "app.js reports a hint rung by its name");
  const tiers = app.match(/const RUNG_TIER = \{([^}]*)\}/);
  assert(tiers, "app.js still declares RUNG_TIER");
  const rungKeys = [...tiers[1].matchAll(/(\w+)\s*:/g)].map((m) => m[1])
    .concat((app.match(/const ANSWER_RUNG = "([^"]+)"/) || [, null])[1] || []);
  assert(rungKeys.length === 6, "the ladder still has its six rungs: " + rungKeys.join(","));
  rungKeys.forEach((r) => assert(EVENTS.indexOf("hint-" + r) >= 0,
    `app.js can reveal the "${r}" rung, and "hint-${r}" is not on the list in sync/events.js`));
  EVENTS.filter((n) => n.indexOf("hint-") === 0).forEach((n) =>
    assert(rungKeys.indexOf(n.slice(5)) >= 0,
      `sync/events.js lists "${n}", which is not a rung app.js can reveal`));

  assert(/import CTEvents from "\.\/events\.js"/.test(worker) &&
         /CTEvents\.indexOf\(name\) < 0/.test(worker),
    "the Worker validates against the same file rather than a copy of the list");
  // Structural, not a spelling check: a second list in the Worker is the drift
  // this file exists to prevent, so no event name may appear in it as a literal.
  assert(EVENTS.every((n) => !worker.includes(`"${n}"`)),
    "and the Worker holds no second copy of the names");
  // Stamped or bare: the stamp is added by the build, not stored (see the
  // cache-busting block above). What matters here is that the page loads the
  // one list rather than carrying its own copy of the names.
  assert(/<script src="sync\/events\.js(\?v=[0-9a-f]+)?"/.test(page),
    "the page loads the list, the same file the Worker validates against");
}

// --- a link word picked with the definition costs nothing ---
// "which words define it" is answered by the definition; the link word next to
// it only joins it to the wordplay, and the rung paints it anyway.
{
  const puzzles = global.window.CRYPTIC_PUZZLES;
  let found = null;
  for (const id of Object.keys(puzzles).sort()) {
    for (const e of puzzles[id].entries || []) {
      const defs = defTexts(e.annotation);
      const link = ((e.annotation && e.annotation.linkWords) || [])[0];
      if (defs.length !== 1 || !link || /\s/.test(link)) continue;
      const words = clueText(e).split(/\s+/);
      const n = defs[0].trim().split(/\s+/).length;
      if (!clueText(e).startsWith(defs[0] + " " + link + " ") || n + 1 >= words.length) continue;
      found = { id, e, n };
      break;
    }
    if (found) break;
  }
  assert(found, "some clue opens with its definition then a link word");
  registry["btn-picker"].onclick();
  pickerRowFor(found.id).children[0].onclick();
  registry["reset-puzzle"].onclick();
  registry["clue-" + entryId(found.e)].listeners.click[0]();
  registry["hint-next"].children.find((b) => /definition/i.test(b.textContent || "") && !b.disabled).onclick();
  for (let i = 0; i <= found.n; i++) registry["gw-" + i].onclick();
  registry["guess-check"].onclick();
  assert(panelHTML().includes("guess-verdict right"),
    `the definition plus its link word is right (${found.id}): ` + panelHTML());
}
