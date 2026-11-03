// The picker: its default list, search, rows and the day of the week.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, appSrc, assert, fs, numberOf, path, readBuilt, registry, rowHasNumber, storage } = T;
// --- picker: taught puzzles by default, everything by search ---
// The rule is two-sided: only show puzzles that have full annotations, and
// stay navigable as more puzzles get added. Default list = what can actually
// teach you. Search = the whole collection, so nothing is unreachable and a
// number you know still works.
const allPuzzles = global.CRYPTIC_INDEX.puzzles || [];
// A reprint stays listed under its reprinting paper as a row pointing at its
// original: one row per index `reprints` entry whose original the index holds.
const allReprints = (() => {
  const held = new Map([...allPuzzles, ...(global.CRYPTIC_INDEX.unlisted || [])]
    .map((p) => [p.id, p]));
  return (global.CRYPTIC_INDEX.reprints || []).filter((r) => held.has(r.reprintOf))
    .map((r) => Object.assign({}, r, { original: held.get(r.reprintOf) }));
})();
const pickerRows = () => registry["picker-list"].children;
const pickerHTMLNow = () => pickerRows().map((li) => li.children[0].innerHTML).join("");
// How many rows go in before the list has to be scrolled. Read out of app.js
// rather than written down again: a test that holds its own copy of the chunk
// size is a test that can agree with a number the app does not use.
const PICKER_CHUNK = Number((/const PICKER_CHUNK = (\d+);/.exec(appSrc) || [])[1]);
assert(PICKER_CHUNK > 0, "app.js still draws the picker `PICKER_CHUNK` rows at a time");
// The list is built a chunk at a time and grows as it is scrolled, so
// pickerRows() is what is ON SCREEN and not what the search matched. Any sweep
// that means "every row this search found" has to scroll to the end first —
// without this it would pass by only ever looking at the first two dozen, which
// is a test that stops testing without ever failing.
//
// Scrolling is firing the observer app.js put on the last row drawn, which is
// exactly what a browser does when that row comes near the bottom of the
// screen. The bound is a safety net and is asserted, so a list that appends
// forever fails here rather than hanging the suite.
const drainPicker = () => {
  const last = () => pickerRows()[pickerRows().length - 1];
  let guard = 0;
  while (last() && global.watchersOf(last()) && guard++ < 2000) global.intersect(last());
  assert(guard < 2000, "the picker stops appending rows rather than growing forever");
  return pickerRows();
};
// A menu is a <select>: set its value and fire change, as the browser does.
const chooseIn = (id, value) => {
  registry[id].value = value;
  registry[id].listeners.change[0]();
};
const choosePaper = (value) => chooseIn("picker-paper", value);
const typeInPicker = (q) => {
  registry["picker-search"].value = q;
  registry["picker-search"].listeners.input[0]();
};
// A number is not an identity. Seventy numbers in the corpus name a puzzle in
// two series at once — cyclops-838 and quiptic-838 both exist — so a search for
// the number alone returns both rows, and taking the first opens whichever the
// index happens to list first. Everything afterwards then misses by a whole
// puzzle: the clue ids belong to the puzzle that was meant, not the one that
// opened. The series is printed on the row's badge and is in the picker's
// haystack, so searching for both is also what a person does.
// Both halves fall back to the id itself, which spells them: a puzzle file the
// index has not caught up with is still findable, rather than searched for as
// "undefined undefined" and reported as a picker that cannot find it.
const seriesOf = (id) => ((allPuzzles.find((p) => p.id === id) || {}).series
  || String(id).replace(/-\d+$/, ""));
const numberIn = (id) => numberOf(id) || Number(String(id).replace(/^.*-/, ""));
const pickerSearchFor = (id) => typeInPicker(numberIn(id) + " " + seriesOf(id));
// The menus are remembered across opens, so a filter left set would hide the
// puzzle being looked up by id: clear them first.
const pickerRowFor = (id) => {
  ["picker-paper", "picker-band", "picker-tag"].forEach((m) => { if (registry[m].value) chooseIn(m, ""); });
  pickerSearchFor(id);
  const rows = drainPicker();
  // The series chip too: a number and a series word can name two puzzles,
  // since "218 toughie" finds both toughie-218 and sundaytough-218.
  const chip = (appSrc.match(new RegExp("^\\s{4}" + seriesOf(id) + ': \\["([^"]+)"', "m")) || [])[1];
  const byNumber = rows.find((li) => li.children[0]
    && rowHasNumber(li.children[0].innerHTML, numberIn(id))
    && li.children[0].innerHTML.includes(`>${chip}</span>`));
  // A row prints the number a READER reads, and a book's is "Penguin book 2
  // No 52" — the stored 1052 is nowhere in its markup, because one chip covers
  // thirty books and the shelf label is the only thing on the row that says
  // which. The search above is the number AND the series, which is what an id
  // is, so one surviving row is that puzzle and matching its markup would only
  // be re-deriving what the search already decided.
  // A number search can still return several books, since "3003" is inside
  // 30033; the shelf label the row prints is the last part of the puzzle's name.
  const name = (allPuzzles.find((p) => p.id === id) || {}).name || "";
  const shelf = name.includes(", ") && name.split(", ").pop();
  const byShelf = shelf && rows.find((li) => li.children[0] && new RegExp(
    ">" + shelf.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?!\\d)").test(li.children[0].innerHTML));
  return byNumber || byShelf || (rows.length === 1 && rows[0].children[0] ? rows[0] : undefined);
};
// Opens the picker first, because most callers are arriving from another puzzle.
const openFromPicker = (id) => {
  registry["btn-picker"].onclick();
  const li = pickerRowFor(id);
  // Guarded, because every caller's next line is about the puzzle this was
  // supposed to open: unguarded, a miss throws on `.children` and the stack
  // trace kills the suite, so one missing row hides every assertion after it.
  // The labels of what DID come back, because the failure is always "the
  // search found something else" and the message is the only place to see it.
  if (!assert(li, `picker finds ${id} when searched for; rows were `
      + (pickerRows().map((r) => (r.children[0] || {}).innerHTML || "?").join(" | ")
        || "(none)"))) return null;
  li.children[0].onclick();
  return li;
};
// The corpus sweeps' door, and theirs alone. They walk clue by clue through
// puzzles that hold dozens of them, and the picker charges a full filter of
// every row in the index for a row it has already proved findable — transport,
// not testing. "ct:last" is the app's own record of what is open, so this cannot drift
// out of step with the page the way a count kept here would.
//
// The repeat visit gets its clean slate from reset-puzzle, which clears MORE
// than re-opening does: the grid and the save as well as the hint state. That
// is why anything asserting progress SURVIVES a re-open must keep using
// openFromPicker — this one throws the progress away.
//
// The reset is charged only where a cold ladder is not already guaranteed: on
// the puzzle's first open, which wipes whatever an earlier section climbed
// here, and on a SECOND visit to the same clue. A clue this sweep has not
// opened yet is cold already, because app.js keeps hint state per clue.
const sweptClues = new Map();  // puzzle id -> clues opened since its last reset
const reopenForSweep = (id, clueId) => {
  const fresh = () => { registry["reset-puzzle"].onclick(); sweptClues.set(id, new Set()); };
  if (storage["ct:last"] !== id) {
    if (!openFromPicker(id)) return;
    fresh();
  }
  const seen = sweptClues.get(id);
  if (clueId === undefined || !seen || seen.has(clueId)) fresh();
  sweptClues.get(id).add(clueId);
};
registry["btn-picker"].onclick();
assert(pickerRows().length >= 5, "picker lists the annotated puzzles: " + pickerRows().length);
assert(registry["picker-search"].value === "", "the filter box starts empty on open");
// --- every row says which day of the week it is ---
// A Guardian week has a shape — Monday gentle, the Saturday prize hard — so the
// weekday is a difficulty cue, not trim. Two things have to hold and neither is
// checkable by eye across 85 rows: the day must AGREE with the date next to it
// (it is derived, so a timezone slip is the way it goes wrong, and a row reading
// "Sat" for a date that was actually a Sunday is worse than no day at all), and
// typing the day's name must find those rows, or the label is a filter that
// lies about being one.
{
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const seen = {};
  // The date column: every row carries its date there.
  const rowDate = (li) => (/<span class="p-meta">([^<]*)</.exec(li.children[0].innerHTML) || [])[1] || "";
  pickerRows().forEach((li) => {
    const m = rowDate(li).match(/^(\w{3}) ((\d{1,2}) (\w{3}) (\d{4}))$/);
    if (!assert(m && MONS.includes(m[4]), "every picker row carries a weekday and a date: " + rowDate(li))) return;
    const want = DAYS[new Date(Date.UTC(+m[5], MONS.indexOf(m[4]), +m[3])).getUTCDay()];
    assert(m[1] === want, `${m[2]} was a ${want}, not a ${m[1]}`);
    seen[want] = (seen[want] || 0) + 1;
  });
  const day = Object.keys(seen).sort((a, b) => seen[b] - seen[a])[0];
  const full = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    .find((d) => d.startsWith(day));
  typeInPicker(full.toLowerCase());
  // Drained: "and finds nothing else" is a claim about every row the day
  // matched, and a day matches a seventh of the archive.
  const hits = drainPicker();
  assert(hits.length >= seen[day],
    `searching "${full.toLowerCase()}" finds its ${seen[day]} row(s), got ${hits.length}`);
  // The search is over the row's whole text, so a title that NAMES the day is a
  // legitimate hit with no weekday of its own: the book shelves ("Sunday
  // Telegraph book 4 No 52", "Penguin Sunday Times book 1") carry a year, not a
  // date. Those are exempt; anything else matching has to be dated that day.
  // Only the offenders are named, capped, rather than all 3,700 hits.
  const rowTitle = (li) => ((/<span class="p-num"[^>]*>([^<]*)</.exec(li.children[0].innerHTML) || [])[1] || "");
  const strays = hits.filter((li) => !rowDate(li).startsWith(day + " ")
    && !rowTitle(li).toLowerCase().includes(full.toLowerCase()));
  assert(strays.length === 0,
    `and finds nothing else: ${strays.length} stray hit(s): `
    + strays.slice(0, 10).map((li) => `${rowTitle(li)} (${rowDate(li) || "no date"})`).join(" | "));
  typeInPicker("");
}

/* --- the archive row IS the picker row, and it is one line when there is room ---

   /puzzles/ and the in-app picker list the same thing, so a solver who has
   learnt to read one has to be able to read the other: the same parts in the
   same order, carrying the same badges on the same axes. They are built by
   different languages — renderPicker() in app.js, hub_page() in
   tools/build_seo_pages.py — so neither file can state that they agree. The
   order below is the one written-down description of a row and both are checked
   against it; what is compared is what each one actually renders.

   Three differences are deliberate and are asserted as such below, so that they
   stay decisions rather than drift:
     * no progress on the archive — a static page has no per-solver state;
     * the archive badges BOTH coverage states, the app only the exception,
       because the picker lists annotated puzzles and the archive lists all;
     * the date is written long on the archive and short in the picker, which
       is a 430px panel: "Saturday 3 October 2026" there, "Sat 3 Oct 2026" here. */
{
  const AXES = ["series", "difficulty", "coverage", "source", "progress"];
  const PARTS = ["p-num", "p-setter", "p-meta", "p-tags"];

  const partsOf = (html) =>
    [...html.matchAll(/<span class="(p-num|p-setter|p-meta|p-tags)"/g)].map((m) => m[1]);
  // The coverage badge and the source badge are both .badge.auto — style.css's
  // rule is one colour per axis, not per badge — so those two alone are told
  // apart by what they say.
  const axisOf = (cls, text) =>
    /\bp-prog\b/.test(cls) ? "progress"
      : /\bseries\b/.test(cls) ? "series"
      : /\bdiff\b/.test(cls) ? "difficulty"
      : /unverified/i.test(text) ? "source" : "coverage";
  const axesOf = (html) => {
    const tags = (html.match(/<span class="p-tags">([\s\S]*)$/) || ["", ""])[1];
    return [...tags.matchAll(/<span class="((?:badge|p-prog)[^"]*)"[^>]*>([^<]*)</g)]
      .map((m) => axisOf(m[1], m[2]));
  };

  const pickerRowHTML = pickerRows().map((li) => li.children[0].innerHTML);
  // The hub lists series and years, never puzzles; the rows are on the
  // per-series-year listings it links, and every one of those is read. The
  // pages link puzzles from their prose and pager too, so rows are taken from
  // the list itself rather than from every <li> that holds a link.
  const hub = readBuilt("puzzles/index.html");
  assert(!/class="s-index"/.test(hub),
    "the archive hub carries no puzzle rows: as one list of every puzzle it was 7 MB");
  const listingPaths = [...new Set([...hub.matchAll(
    /href="https:\/\/cryptic\.paultarjan\.com\/(puzzles\/series\/[a-z]+\/(?:\d{4}|undated)\/)"/g)]
    .map((m) => m[1]))];
  const listedIds = [];
  const archiveRowHTML = listingPaths.flatMap((rel) => {
    const page = readBuilt(rel + "index.html");
    assert(page.length < 300 * 1024,
      `${rel} is ${Math.round(page.length / 1024)} KB; a listing page stays under 300 KB`);
    const list = (page.match(/<ul class="s-index">([\s\S]*?)<\/ul>/) || ["", ""])[1];
    const rows = list.match(/<li><a [\s\S]*?<\/a><\/li>/g) || [];
    rows.forEach((r) => listedIds.push((r.match(/\/puzzles\/([^/"]+)\/"/) || [])[1]));
    return rows;
  });
  // Two clicks from the hub to any puzzle: each one with solutions is on
  // exactly one listing the hub links, and each reprint of one is a row of its
  // own under the reprinting paper, linking the original.
  {
    const want = allPuzzles.filter((p) => p.hasSolutions).map((p) => p.id)
      .concat(allReprints.filter((r) => r.original.hasSolutions).map((r) => r.reprintOf))
      .sort();
    const got = [...listedIds].sort();
    const listed = new Set(listedIds);
    assert(got.length === want.length && got.every((id, i) => id === want[i]),
      `the hub's listings hold every puzzle with solutions once and each reprint row once: `
        + `${got.length} rows, ${want.length} puzzles and reprints, missing `
        + want.filter((id) => !listed.has(id)).slice(0, 5).join(", "));
  }
  assert(pickerRowHTML.length && archiveRowHTML.length,
    `both lists render rows: picker ${pickerRowHTML.length}, archive ${archiveRowHTML.length}`);

  const archiveAxes = new Set();
  for (const [name, rows] of [["picker", pickerRowHTML], ["archive", archiveRowHTML]]) {
    const parts = [...new Set(rows.map((h) => partsOf(h).join(",")))];
    assert(parts.length === 1 && parts[0] === PARTS.join(","),
      `every ${name} row is ${PARTS.join(", ")} in that order, got: ` + parts.join(" | "));
    // Every row of both, not a sample: which badges a row carries depends on the
    // puzzle, so the rare combination is exactly the one an eye never reaches.
    rows.forEach((h) => {
      const axes = axesOf(h);
      if (name === "archive") axes.forEach((a) => archiveAxes.add(a));
      const ranks = axes.map((a) => AXES.indexOf(a));
      assert(!ranks.includes(-1) && ranks.every((r, i) => i === 0 || r > ranks[i - 1]),
        `a ${name} row's badges run ${AXES.join(" → ")}, got ${axes.join(" → ")}: ` + h);
    });
  }

  /* And the order above stays honest only while every name in it is a badge
     something still renders. What the archive should show is not a fixture, it
     is a question the index answers, so it is asked of the index — a paper whose
     answers stop needing the unverified badge must retire the axis here too,
     rather than leaving a name that describes a row that no longer exists. */
  {
    const listed = allPuzzles.filter((p) => p.hasSolutions);
    const want = new Set(["series", "coverage"]);   // every archive row has both
    if (listed.some((p) => p.difficulty)) want.add("difficulty");
    if (listed.some((p) => p.solutionsUnofficial)) want.add("source");
    assert([...archiveAxes].sort().join(",") === [...want].sort().join(","),
      "the archive's badges are the ones the index says it has: rendered " +
      [...archiveAxes].sort().join(",") + ", expected " + [...want].sort().join(","));
    // Progress is the picker's alone and depends on what this solver has typed,
    // so it is asked of the template rather than of a row.
    assert(/class="p-prog/.test(appSrc),
      "the picker row still carries progress, which is why 'progress' is in AXES");
    assert(AXES.every((a) => want.has(a) || a === "progress"),
      "AXES names only axes a row actually carries: " + AXES.join(", "));
  }

  // The deliberate three, asserted so they stay decisions rather than drift.
  assert(!archiveRowHTML.join("").includes("p-prog"),
    "the archive carries no progress: a static page has no per-solver state");
  assert(archiveRowHTML.some((h) => h.includes("full hints")) &&
         archiveRowHTML.some((h) => h.includes("answers only")),
    "the archive badges both coverage states, because it lists both");
  assert(!pickerRowHTML.join("").includes("full hints"),
    "and the picker badges only the exception, because it lists only one of them");

  // ...and both name that state in the SAME words. One fact — we hold this
  // puzzle's solutions and nobody has annotated it — is written three times:
  // twice in app.js (the row/title badge and the degraded hint panel) and once
  // in tools/build_seo_pages.py. The words are "answers only" and nothing but
  // this holds them together: the app's wording is read out of its own source
  // and matched against what the archive page actually rendered, so changing
  // either surface alone fails here, naming both.
  const appCoverageWords = [...appSrc.matchAll(/<span class="badge auto"(?: title="[^"]*")?>([^<]+)<\/span>/g)]
    .map((m) => m[1]).filter((w) => !/unverified/i.test(w));
  const archiveCoverageWords = [...new Set(
    [...archiveRowHTML.join("").matchAll(/<span class="badge auto"[^>]*>([^<]+)</g)]
      .map((m) => m[1]).filter((w) => !/unverified/i.test(w)))];
  assert(appCoverageWords.length >= 2 && new Set(appCoverageWords).size === 1,
    "app.js badges the un-annotated state in more than one wording: "
      + appCoverageWords.join(" | "));
  assert(archiveCoverageWords.length === 1 &&
         archiveCoverageWords[0] === appCoverageWords[0],
    "app and archive disagree on the un-annotated wording: app says "
      + JSON.stringify(appCoverageWords[0]) + ", archive says "
      + archiveCoverageWords.map((w) => JSON.stringify(w)).join("/"));
  assert(appCoverageWords[0] === "answers only",
    'both surfaces agree, but on the wrong words: "answers only" is the decided '
      + "copy, they say " + JSON.stringify(appCoverageWords[0]));
}

/* --- and the wide archive row is one line, because it says which line ---

   Four things sit on that line and CSS Grid decides where each lands. Both
   halves of this are invisible to a headless DOM and only show up as a screen
   full of rubble, which is how they shipped. */
{
  const css = fs.readFileSync(path.join(ROOT, "style.css"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const rulesIn = (text) => [...text.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((m) => ({ sel: m[1].trim().replace(/\s+/g, " "), body: m[2] }));
  // The last declaration wins, which is what the media query relies on.
  const prop = (rules, sel, name) => {
    const hit = rules.filter((r) => r.sel === sel)
      .map((r) => (r.body.match(new RegExp(name + "\\s*:\\s*([^;]+)")) || [])[1])
      .filter(Boolean).pop();
    return hit ? hit.trim() : null;
  };
  const media = [...css.matchAll(/@media([^{]+)\{((?:[^{}]|\{[^{}]*\})*)\}/g)];
  const wideBlock = media.find((m) => /\.s-index\s*\{/.test(m[2]));
  assert(wideBlock, "style.css still has a wide branch for the archive list");
  const wide = rulesIn(wideBlock[2]);
  const base = rulesIn(css.replace(/@media[^{]+\{(?:[^{}]|\{[^{}]*\})*\}/g, ""));
  const PARTS = ["p-num", "p-setter", "p-meta", "p-tags"];
  const colOf = (cls) => Number(prop(wide, ".s-index ." + cls, "grid-column")
    || prop(base, "." + cls, "grid-column"));
  const rowOf = (cls) => prop(wide, ".s-index ." + cls, "grid-row");

  /* Grid's auto-placement cursor never moves backwards (sparse packing, CSS
     Grid §8.5): an item whose column is behind the cursor does not go back to
     it, it starts a NEW ROW. The date is column 4 and comes before the badges
     in the markup, so badges that named only column 3 were given a second line
     under a row that had just been told to be one line. Simulated here rather
     than described, because the markup order and the column numbers are written
     in two different files and either one may move. */
  {
    const order = PARTS.filter((cls) => !rowOf(cls));
    let cursor = 0;
    const pushed = order.filter((cls) => {
      const col = colOf(cls);
      const back = col < cursor;
      cursor = col;
      return back;
    });
    assert(!pushed.length,
      `${pushed.join(", ")} sits in a column the auto-placement cursor has already ` +
      "passed, so grid starts a new row for it — give it a grid-row, or put it " +
      "in markup order: " + PARTS.map((c) => `${c}=col ${colOf(c)}`).join(", "));
  }

  /* And no track on this list may be sized by its contents. The list is twelve
     thousand rows long, so a content-sized track is as wide as its single worst
     row and every other row pays: one 47-character copyright line in a setter
     field took 272px of a 728px list away from the badges beside it. .p-setter
     carries an ellipsis for exactly this, and an `auto` track never lets it
     fire. */
  {
    const tracks = (() => {
      const out = []; let depth = 0, cur = "";
      for (const ch of (prop(wide, ".s-index", "grid-template-columns") || "")) {
        if (ch === "(") depth++;
        if (ch === ")") depth--;
        if (ch === " " && !depth) { if (cur) out.push(cur); cur = ""; } else cur += ch;
      }
      if (cur) out.push(cur);
      return out;
    })();
    const columns = PARTS.map(colOf);
    // One more than the row's parts: the archive row's "answers" link.
    assert(tracks.length === Math.max(...columns) + 1,
      `the wide list declares one track per column (${Math.max(...columns)} + answers), got ` +
      tracks.length + ": " + tracks.join(" "));
    const elastic = PARTS.filter((cls) =>
      /ellipsis/.test(prop(base, "." + cls, "text-overflow") || ""));
    assert(elastic.length, "some row part still truncates rather than pushing the row wide");
    elastic.forEach((cls) => {
      const track = tracks[colOf(cls) - 1];
      assert(track && !/^(auto|max-content|min-content)$/.test(track),
        `.${cls} truncates, but its track is '${track}' — a content-sized track is ` +
        "as wide as the worst row in the archive, so the ellipsis never fires");
    });
  }

  /* The narrow form is not a fallback, it is the design for a 430px panel (see
     the note above .p-tags): number and date pinned to opposite corners, badges
     on a line of their own. The picker uses it at every width and shares these
     base rules, so a change aimed at the archive lands there too. */
  assert(prop(base, ".p-tags", "grid-column") === "1 / -1",
    "narrow rows still give the badges a full-width line of their own");
  assert(prop(base, "#picker-list button, .s-index a", "grid-template-columns")
    === "auto 1fr auto",
    "and the shared two-line row is still three columns");
}

{
  // "current" is the row for the puzzle already open, which is listed whatever
  // its annotation state — don't hide the user's own work. Everything else in a
  // default list has to have earned its place.
  const others = pickerRows().filter((li) => !/current/.test(li.className || ""));
  const html = others.map((li) => li.children[0].innerHTML).join("");
  // No full-hints badge anywhere: since it only lists full hints there is no
  // need to show it. A label every row carries distinguishes nothing; the
  // badge marks the exception, not the norm.
  assert(!pickerHTMLNow().includes("full hints"),
    "picker rows carry a full-hints badge that says the same thing about every row");
  // Structural rather than textual, so deleting the badge can't quietly turn
  // this into a test of nothing: the listed numbers must BE the annotated ones.
  const annotatedNums = new Set(allPuzzles.filter((p) => p.annotated).map((p) => String(p.number)));
  const listedNums = others.map((li) => (li.children[0].innerHTML.match(/data-number="(\d+)"/) || [])[1]);
  const strays = listedNums.filter((n) => !annotatedNums.has(n));
  assert(listedNums.length && !strays.length,
    "un-annotated puzzles are listed by default: " + strays.join(", "));
  // The badge is the visible half of the same rule.
  assert(!html.includes("answers only"),
    "un-annotated puzzles are listed by default: " + pickerRows().length + " rows");
  assert(pickerRows().length < allPuzzles.length,
    "something is hidden, so the footer count means something");
  assert(/archive|search/i.test(registry["picker-more"].innerHTML),
    "the hidden ones are still signposted: " + registry["picker-more"].innerHTML);
  // And it is a shortlist, not the catalogue: every taught puzzle is a scroll,
  // not an answer to "what next".
  // Rows the solver has touched are exempt and don't count.
  const untouched = others.filter((li) => !/letters in|solved ✓/.test(li.children[0].innerHTML));
  assert(untouched.length <= 12,
    "the default list is a shortlist, not the archive: " + untouched.length + " untouched rows");
}
// filtering narrows, and matches setters as well as numbers
{
  const target = allPuzzles.find((p) => p.annotated && p.setter);
  // A digits term matches where a number starts, so it narrows as you type:
  // 1911 lists 19,117 too. Every row's number starts with the digits typed,
  // and the puzzle with exactly that number is among them.
  typeInPicker(String(target.number));
  const numRows = drainPicker().map((li) =>
    (li.children[0].innerHTML.match(/data-number="(\d+)"/) || [])[1] || "");
  const offNumber = numRows.filter((n) => !n.startsWith(String(target.number)));
  assert(numRows.length && !offNumber.length,
    "filtering by number finds the puzzles whose number starts with it and nothing else: "
    + target.number + " listed " + offNumber.slice(0, 5).join(", "));
  assert(numRows.includes(String(target.number)),
    "filtering by number lists the puzzle carrying exactly that number: " + target.id);
  // The number narrows; the number and the series together identify. A number
  // shared by two series has to come back as two rows there and one row here.
  pickerSearchFor(target.id);
  assert(drainPicker().length === 1 && rowHasNumber(pickerHTMLNow(), target.number),
    `number plus series finds exactly one puzzle: ${target.id}`);
  // And that number is the whole number. Every puzzle number of five digits or
  // fewer is a run of digits inside some longer one once an archive is this
  // deep, so the pair is found here rather than named: the shorter number must
  // not turn up the longer one. Structural, so it cannot decay into a test of
  // one puzzle that happens to have been re-numbered.
  const numbers = allPuzzles.map((p) => String(p.number));
  const short = numbers.find((n, i) => numbers.indexOf(n) === i
    && numbers.lastIndexOf(n) === i
    && numbers.some((m) => m.length > n.length && m.includes(n)));
  typeInPicker(short);
  const found = drainPicker().map((li) =>
    (li.children[0].innerHTML.match(/data-number="(\d+)"/) || [])[1]);
  assert(found.length === 1 && found[0].replace(/,/g, "") === short,
    "a number search matches whole numbers only, not digits inside a longer one: "
    + short + " found " + found.join(", "));
  typeInPicker(target.setter.toLowerCase());
  // A prolific setter has hundreds of puzzles and the one looked for need not be
  // in the first chunk of them, so this scrolls to the end before it looks.
  assert(drainPicker().some((li) => rowHasNumber(li.children[0].innerHTML, target.number)),
    "filtering by setter works: " + target.setter);
  typeInPicker("zzzznotasetter");
  assert(pickerRows().length === 1 && /picker-empty/.test(pickerRows()[0].className),
    "a filter that matches nothing says so rather than showing everything");
  // Taught puzzles lead a filtered list, the way they are the only thing in an
  // unfiltered one. The badge is the readable proxy for it: an unannotated row
  // carries "answers only" and an annotated row carries nothing, so the list is
  // right exactly when no badged row precedes an unbadged one.
  //
  // Driven through a series with no day dates, because a day-dated one passes
  // this without the ordering being there at all: annotating follows fetching,
  // so newest-first is annotated-first by accident. The book puzzles are
  // reprints holding only their book's `year`, so newest-first alone buries
  // their taught ones.
  const undated = allPuzzles.find((p) => p.date === undefined && p.annotated);
  if (undated) {
    typeInPicker(String(undated.series));
    const badged = drainPicker().map((li) => /answers only|hints via /.test(li.children[0].innerHTML));
    assert(badged.indexOf(false) === -1 || badged.lastIndexOf(false) < badged.indexOf(true)
      || badged.indexOf(true) === -1,
      "a filtered list puts the puzzles we have hints for first: " + undated.series
      + " listed " + badged.filter((b) => !b).length + " annotated among "
      + badged.length + " rows, first unannotated at " + badged.indexOf(true));
  }
  typeInPicker("");
}

/* --- a search that matches thousands draws a screenful and grows as you scroll ---

   "clicking the puzzle pill now takes a long time to swap, maybe make it
   infinite scroll?" (Paul, 2026-09-19). A Papers chip matches a whole
   newspaper — at 15,992 indexed puzzles the biggest is 8,393 of them — and
   every match used to be built on the tap that selected the chip: 16,786
   elements and 3.8 MiB of markup handed to the browser in one go, for a list
   that shows about a dozen rows at a time.

   Driven off the biggest paper rather than one named here, so the test
   follows the corpus instead of a word that was true the day it was written.

   The counts are checked against each other rather than against numbers
   written down: what the line says is below plus what is drawn must BE the
   match, and the match plus what it says does not match must be the whole
   archive. Two facts that a single count cannot tell apart — "keep scrolling"
   is answered by scrolling and "doesn't match" is answered by typing something
   else, and rolling them together would tell a solver looking at 24 of 8,393
   Guardian puzzles that 15,968 of them don't match. */
{
  if (registry["picker-panel"].classList.contains("hidden")) registry["btn-picker"].onclick();
  typeInPicker("");
  const sizes = {};
  allPuzzles.forEach((p) => { sizes[p.series] = (sizes[p.series] || 0) + 1; });
  const chip = Object.keys(sizes).sort((a, b) => sizes[b] - sizes[a])[0];
  choosePaper(chip);
  const more = () => registry["picker-more"].innerHTML;
  const drawn = pickerRows().length;
  assert(drawn === PICKER_CHUNK,
    `tapping "${chip}" draws ${PICKER_CHUNK} rows, not every match: ${drawn}`);
  const below = Number((/(\d+) more match/.exec(more()) || [])[1]);
  const unmatched = Number((/(\d+) other puzzle/.exec(more()) || [])[1]);
  assert(below > 0 && unmatched > 0,
    `the line under the list counts both what is below and what did not match: ${more()}`);

  // Scrolling is what brings the rest, and it is the LAST ROW DRAWN that is
  // watched — no sentinel node, so Enter on the search box still lands on a
  // puzzle at children[0] and every sweep above still sees puzzles only.
  const last = () => pickerRows()[pickerRows().length - 1];
  assert(global.watchersOf(last()) === 1,
    "the last row drawn is watched, so reaching it appends the next chunk");
  assert(global.intersect(last()) === 1 && pickerRows().length === drawn + PICKER_CHUNK,
    `scrolling to the bottom appends a chunk: ${drawn} -> ${pickerRows().length}`);
  assert(global.watchersOf(pickerRows()[drawn - 1]) === 0,
    "and the row that used to be last is let go, so one observer is live at a time");
  const top = pickerRows()[0].children[0];
  assert(typeof top.onclick === "function" && /p-num/.test(top.innerHTML),
    "the first child of the list is still a puzzle button, which is what Enter opens");

  // Nothing is unreachable: the whole match is still there to be scrolled to,
  // and the count said exactly how much of it was waiting.
  const all = drainPicker().length;
  assert(all === drawn + below,
    `the "more below" count was the truth: said ${below} below ${drawn} drawn, `
    + `scrolled to ${all}`);
  assert(all + unmatched === allPuzzles.length + allReprints.length,
    `and the "don't match" count is the rest of the archive: ${all} + ${unmatched} `
    + `vs ${allPuzzles.length} puzzles + ${allReprints.length} reprint rows`);
  assert(all > PICKER_CHUNK * 4,
    `the chip this was driven from matches far more than one screenful (${all}), `
    + "which is the case the chunking is for");
  assert(!/keep scrolling/.test(more()) && /other puzzle/.test(more()),
    `at the end the line stops offering more and still says what did not match: ${more()}`);

  // The default list is short by design and must not be chunked: the newest
  // RECENT_ROWS plus whatever the solver has open or unfinished is an answer to
  // "what next", not a thing to scroll.
  choosePaper("");
  assert(pickerRows().length <= PICKER_CHUNK && !/keep scrolling/.test(more()),
    `the default list arrives whole: ${pickerRows().length} rows, ${more()}`);
}

Object.assign(T, { allPuzzles, allReprints, chooseIn, choosePaper, openFromPicker, pickerRowFor,
  pickerRows, reopenForSweep, typeInPicker });
