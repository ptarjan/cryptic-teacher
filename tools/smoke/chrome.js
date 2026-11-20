// The letter strip, current-clue box, clue types and chips, series badges and the
// book shelf.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { FULL, ROOT, SLICE, appSrc, assert, fs, path, pp, registry, stripTags } = T;
// --- letter pattern strip: one box per cell, checked vs unchecked marked ---
const patHTML = () => registry["hint-pattern"].innerHTML;
// note the space: it must not also match the "pat-boxes" wrapper
const patBoxes = () => (patHTML().match(/class="pat-box [^"]*"/g) || []);
{
  const boxes = patBoxes();
  const m = patHTML().match(/(\d+) of (\d+) letters in place/);
  assert(boxes.length >= 3, "pattern strip renders boxes: " + boxes.length);
  assert(m && Number(m[2]) === boxes.length, "pattern box count matches the entry length: " + patHTML());
  assert(m && Number(m[1]) === 0, "pattern starts with no letters in place: " + patHTML());
  assert(boxes.some((b) => b.includes("checked") && !b.includes("unchecked")), "checked squares marked");
  assert(patHTML().includes("checked"), "pattern summary mentions checking: " + patHTML());
}

// --- the current-clue box is the clue, not a status report ---
// The pattern strip's aria-label is not printed beside the boxes: it is twenty
// words restating what the boxes already show. The summary stays for screen readers, which cannot see the boxes; it must never
// come back as visible prose, and the meter beside it must stay a count. Asserted
// at both ends so neither half can rot — the label has to still be there, and the
// strip has to still be nothing but boxes.
{
  assert(/aria-label="[^"]*letters? in place/.test(patHTML()),
    "the pattern strip still describes itself to a screen reader: " + patHTML());
  // The strip wraps each word of the enumeration in a span, so the rule is
  // stated as text: the only text a sighted solver reads
  // here is letters and the odd hyphen or apostrophe between words.
  assert(/^[A-Z’\-]*$/.test(stripTags(patHTML(), "")),
    "the pattern strip renders the boxes and nothing else — the summary is the " +
    "aria-label, not a line of prose under the clue: " + patHTML());
  const meter = stripTags(registry["hint-meter"].innerHTML, "");
  assert(meter.length < 40,
    `the hint meter is a count, not a sentence (${meter.length} chars): ${meter}`);
}

// --- every clue type belongs to exactly one family (tools/data/clue_types.json) ---
const CLUE_TYPES = JSON.parse(fs.readFileSync(path.join(ROOT, "tools/data/clue_types.json"), "utf8"));
const TYPE_FAMILY = Object.fromEntries(CLUE_TYPES.types.map((t) => [t.name, t.family]));
{
  const famNames = CLUE_TYPES.families.map((f) => f.name);
  assert(CLUE_TYPES.types.length > 10, "clue types read from clue_types.json: " + CLUE_TYPES.types.length);
  CLUE_TYPES.types.forEach((t) => assert(famNames.includes(t.family),
    `clue type '${t.name}' names family '${t.family}', which clue_types.json declares`));
  famNames.forEach((f) => assert(CLUE_TYPES.types.some((t) => t.family === f),
    `family '${f}' claims at least one clue type`));
  assert(new Set(CLUE_TYPES.types.map((t) => t.name)).size === CLUE_TYPES.types.length,
    "every clue type is named once");
  assert(JSON.stringify(global.CRYPTIC_INDEX.clueTypes) === JSON.stringify(CLUE_TYPES),
    "the index (head-static, composed by fake_dom) carries clue_types.json as it stands — run python3 tools/fetch_puzzle.py --reindex");
}

// --- the chips are offered commonest first, and `n` still says how common ---
{
  // The order is computed from `n`, so the only thing that can rot is `n`
  // itself: annotate a few hundred more clues and a hand-typed count from an
  // older corpus quietly stops being the reason the chips sit where they do.
  // Shares rather than raw counts, because the corpus only grows and a count
  // that grew with it is not wrong.
  const fams = CLUE_TYPES.families;
  assert(fams.length === 9 && fams.every((f) => f.n > 0)
    && fams.filter((f) => f.picker).every((f) => fams.some((g) => g.name === f.picker && !g.picker)),
    "every clue family in clue_types.json declares its corpus count: " + JSON.stringify(fams.map((f) => [f.name, f.n])));

  const seen = {};
  pp.puzzleFiles()
    .forEach((f) => {
      const puz = pp.readView(f);  // the shim form: a file stores no `type`
      (puz.entries || []).forEach((e) => {
        const types = (e.annotation || {}).type;
        if (!Array.isArray(types)) return;
        // Every family the type uses, not just the dominant one: gradeChoice
        // accepts any of them, so that is what a chip's odds run on.
        new Set(types.map((t) => TYPE_FAMILY[t])).forEach((fam) => { seen[fam] = (seen[fam] || 0) + 1; });
      });
    });
  const total = (o) => fams.reduce((a, f) => a + (typeof o === "function" ? o(f) : o[f.name] || 0), 0);
  const declaredTotal = total((f) => f.n), countedTotal = total(seen);
  assert(countedTotal > 5000, "the corpus was actually read: " + countedTotal + " family hits");
  fams.forEach((f) => {
    const want = (seen[f.name] || 0) / countedTotal, got = f.n / declaredTotal;
    assert(Math.abs(want - got) <= 0.03,
      `clue_types.json says ${f.label} is ${(got * 100).toFixed(1)}% of family hits; the corpus `
      + `now says ${(want * 100).toFixed(1)}% (${seen[f.name] || 0}) — run python3 tools/clue_types.py --recount, then python3 tools/fetch_puzzle.py --reindex`);
  });
}

// --- every series in the index must have a badge in app.js ---
{
  // The badge names which paper a row is from, for every series: the Guardian
  // is not a default, and an unbadged row reads as one nobody got round to
  // labelling.
  const badgeBlock = appSrc.slice(appSrc.indexOf("const SERIES_BADGE"),
                                 appSrc.indexOf("function seriesBadge"));
  const badged = [...badgeBlock.matchAll(/^\s{4}(\w+):/gm)].map((m) => m[1]);
  assert(badged.length > 3, "SERIES_BADGE parsed from app.js: " + badged.length);
  const indexSeries = [...new Set((global.CRYPTIC_INDEX.puzzles || [])
    .map((p) => p.series || "cryptic"))];
  indexSeries.forEach((s) => assert(badged.includes(s),
    `series '${s}' has a badge in app.js's SERIES_BADGE`));

  /* --- a push notification says WHICH PAPER, and there is still one table ---

     On the site a row wears a badge, so "Cryptic crossword No 30,106" is
     obviously the Guardian's. On a lock screen there is no badge, so the
     notification has to name the paper itself.

     sync/worker.js can import neither app.js nor tools/series.py, so the
     temptation is a second list of papers in the Worker — the list that would
     still say five the night a sixth arrives. Instead the paper is carried in
     puzzles/index.json, which the fan-out already fetches, written there by
     tools/fetch_puzzle.py out of tools/series.py. That makes the index and
     SERIES_BADGE two views of the same fact, written from opposite ends, so
     what is checked here is that every series the index names can be badged.

     One direction only. `papers` is derived from the puzzles actually on disk,
     while a series is registered in tools/series.py and SERIES_BADGE before its
     first puzzle is filed -- a new feed is wired up before it is first fetched.
     So a badge with no puzzles yet is the normal state, and only the reverse is
     a defect: a paper in the index with no badge to render ships a blank pill
     to a reader. */
  const papers = global.CRYPTIC_INDEX.papers || {};
  assert(Object.keys(papers).length > 3,
    "puzzles/index.json carries a `papers` table: " + JSON.stringify(papers));
  const unbadged = Object.keys(papers).filter((s) => !badged.includes(s));
  assert(unbadged.length === 0,
    "every series in index.json's `papers` has an entry in app.js's SERIES_BADGE; "
    + "unbadged: " + unbadged.join(",") + " (badged: " + badged.slice().sort().join(",") + ")");

  const CTNotify = require("../../sync/notify.js");
  const sample = {};
  (global.CRYPTIC_INDEX.puzzles || []).forEach((p) => { sample[p.series] = sample[p.series] || p; });
  Object.keys(sample).forEach((s) => {
    const t = CTNotify.title(sample[s], papers);
    assert(t.includes(papers[s]), `a ${s} notification names its paper: ${t}`);
    // "Independent Independent cryptic crossword" — the Independent's two
    // series already carry the paper in their names, so prefixing is wrong for
    // them and right for the Guardian's three.
    assert(!/\b(\w+) \1\b/.test(t), `and names it once: ${t}`);
  });
  assert(CTNotify.title({ series: "cryptic", name: "Cryptic crossword No 30,106" }, papers)
    === "Guardian Cryptic crossword No 30,106", "the Guardian's daily says Guardian");
  assert(CTNotify.title({ series: "indysunday", name: "Independent on Sunday cryptic crossword No 1,906" },
                        papers) === "Independent on Sunday cryptic crossword No 1,906",
    "a name that already opens with its paper is left alone");
  // An index deployed before `papers` existed. The notification is worse, not
  // missing: a title nobody gets is not an improvement on an unattributed one.
  assert(CTNotify.title({ series: "cryptic", name: "Cryptic crossword No 30,106" }, {})
    === "Cryptic crossword No 30,106", "and an index with no papers table still notifies");
}

// --- the book shelf: one series, and every puzzle on it names a real book ---
{
  /* The scanned books are ONE series with one chip, and which book a puzzle
     came out of is in its number: book_index * 1000 + position, resolved
     through tools/data/books.json. tools/fetch_puzzle.py --reindex copies the
     browser's half of that registry into puzzles/index.json, so app.js prints
     "Penguin book 5 No 18" without a second table of shelf labels — which is
     exactly what an 18-key BOOK_SHELF object in app.js used to be.

     A book whose row the index does not carry prints its number raw ("No
     3,018"), which is the right failure for an index deployed before the table
     existed and the wrong state for this checkout. */
  const books = global.CRYPTIC_INDEX.books || {};
  assert(Object.keys(books).length > 0,
    "puzzles/index.json carries the `books` registry app.js reads shelf labels from");
  const shelf = (global.CRYPTIC_INDEX.puzzles || []).filter((p) => p.series === "book");
  assert(shelf.length > 0, "and there are book puzzles to name: " + shelf.length);

  /* EVERY SHELF LABEL IS UNIQUE, which is the whole reason a label exists.
     One chip says "book" for thirty books, so the only thing on the row that
     says WHICH is "<shelf> <volume> No <position>" — and a bare "book 2 No 7"
     would be the Herald's, the Scotsman's, the Sunday Telegraph's and the
     Daily Mail's at once. Checked over the corpus rather than over the
     registry, so a row whose shelf and volume collide with another's is caught
     by the puzzles it would mislabel. */
  const seen = {};
  shelf.forEach((p) => {
    const row = books[String(Math.floor(p.number / 1000))];
    assert(row, `${p.id} names a book that puzzles/index.json describes`);
    assert(p.number % 1000 !== 0, `${p.id} carries a position; positions start at 1`);
    if (!row) return;
    const label = `${row.shelf} ${row.volume} No ${p.number % 1000}`;
    assert(!seen[label], `"${label}" names one puzzle: ${p.id} and ${seen[label]}`);
    seen[label] = p.id;
  });

  /* A SERIES WITH NO PAPER IS A SHELF, never a lookup that failed. `papers`
     answers "" for the books because one shelf reprints a dozen papers, and
     CTNotify.title() then leaves the name alone — which is only right because
     a book puzzle's own name opens with the paper that printed it. A feed that
     turned up here would be shipping anonymous notifications. */
  const papers = global.CRYPTIC_INDEX.papers || {};
  Object.keys(papers).filter((s) => !papers[s]).forEach((s) => {
    const rows = (global.CRYPTIC_INDEX.puzzles || []).filter((p) => (p.series || "cryptic") === s);
    assert(rows.length > 0 && rows.every((p) => books[String(Math.floor(p.number / 1000))]),
      `series '${s}' has no paper in index.json, so every one of its puzzles has `
      + `to be out of a registered book — a feed with an empty publisher notifies anonymously`);
  });
}

/* --- quiet hours: held until the hour this device asked for, then sent once ---

   Tested as arithmetic and never as a push. The subscription in KV is a real
   phone on somebody's bedside table, so "does the hold work" cannot be answered
   by running the fan-out; it can be answered completely by the two numbers the
   fan-out compares. */
{
  const CTNotify = require("../../sync/notify.js");
  const tz = "America/Edmonton";
  const threeAM = Date.parse("2026-09-08T09:00:00Z");  // 03:00 there, in September
  const nineAM = Date.parse("2026-09-08T15:00:00Z");   // 09:00 there

  assert(CTNotify.parseAfter("07:00") === 420, "07:00 is 420 minutes into the day");
  assert(CTNotify.parseAfter("7:00") === null && CTNotify.parseAfter("24:00") === null
    && CTNotify.parseAfter(420) === null && CTNotify.parseAfter(null) === null,
    "and anything that is not a 24-hour clock time is not a time");
  assert(CTNotify.minutesOfDay(tz, threeAM) === 180,
    "the zone decides the local clock, not the server's: " + CTNotify.minutesOfDay(tz, threeAM));

  assert(!CTNotify.due(420, tz, threeAM),
    "a puzzle annotated at 3am local is HELD — the annotation run finishes in the small hours");
  assert(CTNotify.due(420, tz, nineAM), "and goes out on the first run after seven");
  // A floor, not a window: the panel asks for the earliest time of day, so a
  // puzzle that lands at half eleven at night is not held until tomorrow.
  assert(CTNotify.due(420, tz, Date.parse("2026-09-09T05:30:00Z")),
    "an evening puzzle is not held overnight");

  // Every unknown resolves to "send". A hold has to be asked for explicitly:
  // the failure mode of guessing the other way is a notification that never
  // arrives and never says why.
  assert(CTNotify.due(null, tz, threeAM),
    "a subscription saved before quiet hours existed is not held at all");
  assert(CTNotify.due(420, "", threeAM) && CTNotify.due(420, "Mars/Olympus", threeAM),
    "nor is one whose zone this runtime cannot read");
  assert(CTNotify.due(0, tz, threeAM), "and midnight means no quiet hours at all");
  assert(CTNotify.zone(tz) === tz, "a real zone is stored as it came");
  assert(!CTNotify.zone("Mars/Olympus") && !CTNotify.zone("") && !CTNotify.zone("../../etc"),
    "and a zone Intl does not know is not stored at all");

  // The page has to send BOTH. "07:00" without a zone is seven o'clock nowhere.
  assert(/after: notifyAfter\(\), tz: notifyZone\(\)/.test(appSrc),
    "putNotify carries the chosen time and the device's zone alongside the papers");
  assert(/Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone/.test(appSrc),
    "and the zone is the browser's own IANA name, not an offset");

  /* The arithmetic above is the easy half. The half that loses a notification
     is the bookkeeping around it — n:seen is written BEFORE the fan-out, so a
     held puzzle has already been announced to the world and exists nowhere but
     its subscriber's own queue. That is behaviour, not a shape source can be
     read for, so it is a real run of scheduled() against a fake KV.

     Shelled out because sync/worker.js is a Worker module and cannot be
     require()d from here. Its output is printed on failure and swallowed on
     success: it has its own ok/FAIL lines, and duplicating a passing suite
     inside a passing suite is noise. */
  // Five processes, each booting a second node or bash to test the Worker, the
  // cron and the scheduled jobs' shell, none of which app.js can break. CI pays for them; the
  // edit-and-run loop does not, because a loop nobody waits out is the only
  // kind that gets run before a push. Change any of these and run CI=1.
  if ((FULL || process.env.CI) && SLICE.i === 0) {
    const hold = require("child_process").spawnSync(
      process.execPath, [path.join(ROOT, "tests/test_push_hold.js")], { encoding: "utf8" });
    assert(hold.status === 0,
      "tests/test_push_hold.js: the cron holds an out-of-hours puzzle and delivers it "
      + "exactly once\n" + (hold.stdout || "") + (hold.stderr || ""));

    /* Ticking a second paper while the first tick is still being saved. Shelled
       out for the same reason and a different one: the suite here is synchronous,
       and a race only exists between two promises. */
    const race = require("child_process").spawnSync(
      process.execPath, [path.join(ROOT, "tests/test_notify_race.js")], { encoding: "utf8" });
    assert(race.status === 0,
      "tests/test_notify_race.js: a paper ticked while another is saving is queued, "
      + "not dropped and then unticked\n" + (race.stdout || "") + (race.stderr || ""));

    /* The bridge path the pre-reset burn's alerts resolve at runtime. Shelled
       out because it is bash, and checked here because nothing else runs on a
       schedule that would notice: when it is wrong, the alert saying so is the
       thing that goes silent. */
    const paths = require("child_process").spawnSync(
      "bash", [path.join(ROOT, "tests/test_prereset_paths.sh")], { encoding: "utf8" });
    assert(paths.status === 0,
      "tests/test_prereset_paths.sh: the burn finds wake.sh from its worktree\n" + (paths.stdout || "") + (paths.stderr || ""));

    /* The catch-all alert, which exists to report failures nobody thought of --
       and so must not re-report the one the run already explained. */
    const claimed = require("child_process").spawnSync(
      "bash", [path.join(ROOT, "tests/test_alert_claimed.sh")], { encoding: "utf8" });
    assert(claimed.status === 0,
      "tests/test_alert_claimed.sh: a traceback an alert already quoted is not "
      + "sent again as unexplained\n" + (claimed.stdout || "") + (claimed.stderr || ""));

    /* Which tree a scheduled job runs in. The wrong one is not an error there:
       the job runs, plans from a stale corpus, and hands out work that is
       already pushed. */
    const tree = require("child_process").spawnSync(
      "bash", [path.join(ROOT, "tests/test_nightly_worktree.sh")], { encoding: "utf8" });
    assert(tree.status === 0,
      "tests/test_nightly_worktree.sh: a job gets its own worktree, or refuses "
      + "to run in a checkout that is dirty or behind\n"
      + (tree.stdout || "") + (tree.stderr || ""));
  }
}

Object.assign(T, { CLUE_TYPES, TYPE_FAMILY, patBoxes, patHTML });
