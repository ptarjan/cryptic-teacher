"use strict"; // app part 6 of 7 (the picker and the puzzle lifecycle). Classic script sharing the page scope with its siblings; see tools/app_src.js.
  // ---------- picker ----------
  // Difficulty comes from tools/difficulty.py, which rates a puzzle against the
  // rest of the collection rather than in the abstract — see its header for why
  // an absolute rating is not something the data supports. The tooltip carries
  // that caveat, because a bare word like "Brutal" reads as a fact, and the
  // badge itself opens /difficulty/, which explains the rest (pickerRow()).
  const DIFFICULTY_PAGE = "difficulty/";
  function difficultyBadge(p) {
    const d = p.difficulty;
    if (!d) return "";
    const pct = d.percentile === null || d.percentile === undefined ? "" :
      ` — harder than ${d.percentile}% of rated puzzles here`;
    const basis = (d.basis || []).join(", ");
    // The SNITCH rates the Times: the index carries the interquartile NITCH of
    // each band's rated puzzles per series, and only bands with enough of them.
    const nitch = ((INDEX.snitchRanges || {})[p.series] || {})[d.band];
    const snitch = nitch ? ` ${d.band} puzzles in this series typically score SNITCH ${nitch.q1}–${nitch.q3}.` : "";
    return bandPill(d.band, d.band.toLowerCase() + pct + ". Based on " + basis
      + ", compared with the other puzzles on this site." + snitch
      + " Tap the badge for how difficulty is rated.");
  }
  // A difficulty band, the one way the app draws one: build_seo_pages.py
  // diff_badge() draws the same pill on the archive pages.
  function bandPill(band, title) {
    const b = esc(String(band).toLowerCase());
    return `<span class="badge diff diff-${b}"${title ? ` title="${esc(title)}"` : ""}>${b}</span>`;
  }

  // What is unusual about a puzzle (pangram, barred grid, special rules…), as
  // tools/puzzle_tags.py read it off the file. Labels and blurbs come from the
  // index, so a tag added there is named and explained here with no table to
  // keep in step.
  function tagBadges(p) {
    const info = INDEX.tags || {};
    return (p.tags || []).filter((k) => info[k]).map((k) =>
      `<span class="badge feature" title="${esc(info[k].blurb)}">${esc(info[k].label)}</span>`).join("");
  }
  // A tag includes the weaker one it `implies`: a double pangram is a pangram.
  // tools/puzzle_tags.has_tag is the same test, which /showcase/ picks by.
  function hasTag(p, t) {
    const info = INDEX.tags || {};
    return (p.tags || []).some((k) => k === t || (info[k] && info[k].implies === t));
  }
  // Badge the exception, never the norm: a "full hints" badge on every row
  // would say the same thing about every row, which is saying nothing. Annotated
  // is what a listed puzzle IS, so there is no full-hints badge in the app; the
  // badge exists only to warn you when the one in front of you isn't. The
  // archive page (tools/build_seo_pages.py) badges both, correctly — it lists
  // every puzzle, so there the two states are a real distinction.
  //
  // Not ours comes in two kinds. `blog` names the blog whose write-up some
  // clues' hints are read off (has_blog_hints in tools/fetch_puzzle.py, the
  // index's `blog`), and then the puzzle has hints, just not ours; only with
  // no blog either is it "answers only".
  function hintsBadge(annotated, blog) {
    if (annotated) return "";
    if (blog) return `<span class="badge auto blog" title="We haven't written our own hints for this puzzle yet. Its hints come from the ${esc(blog)} write-up: the definitions, clue types and pieces it marked, with some of what it left out worked out from the letters. Each clue links to the full explanation there, and a clue it marked nothing on has no hints yet.">hints via ${esc(blog)}</span>`;
    return `<span class="badge auto" title="No hints for this puzzle yet: you can check your letters and reveal answers, but nothing is explained">answers only</span>`;
  }

  // Shares the coverage axis (neutral) with the hints badge on purpose: both
  // answer "what has this site actually got for this puzzle", and the badge
  // colour rule in style.css is one colour per axis, not per badge.
  function sourceBadge(p) {
    return p.solutionsUnofficial
      ? `<span class="badge auto" title="The paper hasn't published its answers yet. These are our own answers: they fit every crossing, but nobody has confirmed them.">unverified answers</span>`
      : "";
  }

  // Every series says what it is. There is no default: a row with no chip reads
  // as a row we forgot to label, not as "the usual one", and the smoke test
  // fails on a series in the index with no entry here — that is what keeps this
  // table complete as papers are added.
  //
  // This text is prose for a human choosing what to attempt next, which is why
  // it lives here and not in tools/series.py with the machine-readable facts.
  // [what the chip says, why]. The label is not the series key: keys are
  // storage ("indysunday"), not English.
  // The why says what the series is known for, never a count or a puzzle
  // number: we hold part of each archive. tools/app_tables.py refuses one.
  const SERIES_BADGE = {
    cryptic: ["guardian", `The Guardian's daily cryptic, Monday to Saturday, known for its
      named setters and their personalities: one day a gentle Vulcan, the next a
      Paul full of puns or a fiendish Enigmatist. It is the most liberal of the
      big dailies: themes, jokes and words hidden in the grid are common, and the rules bend for a
      good surface, so learning a setter's habits pays off.`],
    quiptic: ["quiptic", `Guardian Quiptic — the Guardian's puzzle for newcomers,
      published Mondays. The same kinds of clue as the daily cryptic, without the
      tricks: plain definitions, familiar words, standard indicators that are easy
      to spot, and few of the daily's themes or in-jokes.`],
    everyman: ["everyman", `Everyman — the Observer's Sunday cryptic, set under one
      house name. Known for consistency and strict fairness: classic clues with
      the definition at one end, smooth surfaces and no obscure words, which makes
      it a favourite step up from beginner puzzles to the dailies.`],
    independent: ["independent", `The Independent's daily cryptic, Monday to
      Saturday, known for its adventurous streak: themes and messages hidden in the
      grid turn up often. About as hard as the Guardian, with a regular team
      of named setters — Phi, Quince, Eccles, Hippogryph — so if you like one,
      their habits are worth learning.`],
    cyclops: ["cyclops", `Cyclops — Private Eye's cryptic, every two weeks, and the
      only one here that swears. The wordplay is strictly fair, but the clues read
      as jokes about whoever is in the news, so solving leans on the last two
      weeks' headlines as much as on the dictionary.`],
    nation: ["nation", `The Nation's weekly cryptic, the oldest in the United
      States: British-style clues with American spelling and a political
      magazine's sense of humour, by Frank W. Lewis and later Joshua Kosman and
      Henri Picciotto. The clues come from the magazine's own pages; the grid
      is rebuilt from them.`],
    metro: ["metro", `Metro's daily cryptic — the free London paper's commuter
      puzzle, on a small 13x13 grid and much easier than the big papers: short
      clues, everyday words, and a solve that fits a train ride. A good place to
      start if the Guardian's daily still feels impossible.`],
    globeandmail: ["globe & mail", `The Globe and Mail's daily cryptic — reprinted
      from the Times of London's smaller 13x13 puzzles rather than its 15x15 ones:
      neat, precise clues in the Times style, no obscure words, and a solve you
      can finish over a coffee.`],
    times: ["times", `The Times's daily cryptic, Monday to Saturday: the benchmark
      other papers are measured against. Setters are anonymous and the house
      style is strict and precise: exact definitions, sound grammar, nothing in
      poor taste and nothing unfair, with the odd less familiar word that the
      wordplay always pins down. The Times doesn't put its grid or answers
      online, so the grid here is rebuilt from the write-up on the “Times for the
      Times” blog, and the answers are that blog's.`],
    timesquick: ["times quick", `The Times Quick Cryptic, weekdays: a 13x13 grid made
      as a way in to the daily, with short clues, everyday words and the daily's
      standards of fairness. Grid rebuilt and answers taken from the “Times for
      the Times” blog. The newest ones are listed under the Globe and Mail, which
      reprints it.`],
    timesjumbo: ["times jumbo", `The Times Jumbo Cryptic, Saturdays: a big 23x23 grid
      with about sixty clues in the daily's precise style, for a long weekend
      solve and a test of stamina. Grid rebuilt and answers
      taken from the “Times for the Times” blog.`],
    sundaytimes: ["sunday times", `The Sunday Times cryptic — a separate paper with
      its own weekly puzzle. Unlike the daily its setters are named, and the
      clues are a little more playful and inventive while keeping the Times's
      fairness. Grid rebuilt and answers taken from the “Times for the Times”
      blog.`],
    timesclub: ["times club", `The Times Crossword Club's Monthly Special: a
      15x15 cryptic made for club members, tougher than the daily, with rarer
      words and longer, more intricate wordplay that still plays fair. Grid
      rebuilt and answers taken from the “Times for the Times” blog.`],
    tls: ["TLS", `The Times Literary Supplement's weekly crossword, by named
      setters: a cryptic steeped in books, with authors, characters and
      quotations in the answers and clues that reward a well-read solver.
      Grid rebuilt and answers taken from the “Times for the Times” blog.`],
    mephisto: ["mephisto", `The Sunday Times Mephisto: the Times's hardest
      cryptic, on a 12x12 barred grid where thick bars end the answers instead
      of black squares, and every cell holds a letter. Its answers are the rare
      and old words of the Chambers dictionary, so each clue's wordplay has to
      spell out a word you may never have met, letter by letter. Setters are
      named. The bars are rebuilt and the answers taken from the “Times for the
      Times” blog.`],
    azed: ["azed", `The Observer's Azed: a barred puzzle on a 12x12 grid
      where thick bars end the answers instead of black squares and every cell
      holds a letter, all set by one man under the name Azed. Its answers come
      from the Chambers dictionary, rare and old words among them, and its
      clues are famously sound: the wordplay always spells the word out
      fairly. The bars are rebuilt and the answers taken from fifteensquared.`],
    genius: ["genius", `The Guardian's Genius: a monthly prize puzzle on an
      ordinary blocked grid, but every one has a trick its preamble explains,
      such as answers left undefined, letters dropped from the clues or a
      theme the solver must find. Its setters are the paper's hardest. The
      clues and grid come from the Guardian's printable copy, the answers
      from fifteensquared.`],
    listener: ["listener", `The Listener crossword, the oldest of the thematic
      puzzles: a barred grid with a preamble that sets a trick, printed first by
      the BBC's magazine it is named for and, since that closed, by the Times
      on Saturdays. The
      earliest ones are general-knowledge puzzles rather than cryptics. Grid,
      bars and answers come from the Listener Team's archive at
      listenercrossword.com, and only puzzles whose answers go into the grid
      unchanged are here.`],
    canberra: ["canberra times", `The Canberra Times's daily cryptic, which
      reprinted the London Times's puzzle, so these are older Times cryptics as
      Australians solved them. Clues and grid are read off
      the newspaper's page scans in the National Library of Australia's Trove
      archive; the answers are worked out here.`],
    ftcryptic: ["FT", `The Financial Times cryptic, Monday to Saturday, from a
      stable of named setters — Io, Mudd, Julius, Jason — many of them familiar
      from other papers under other names (Mudd is the Guardian's Paul). Pitched
      about where the Guardian is, with witty surfaces and the odd financial
      theme. The FT doesn't put its grid online, so the grid here is rebuilt from
      the fifteensquared blog's write-up, and the answers are that blog's.`],
    telegraph: ["telegraph", `The Daily Telegraph's back-page cryptic, Monday to
      Saturday, known for smooth, approachable clues and a steady difficulty:
      setters are not named, and many solvers learn on it. The Telegraph keeps
      its archive behind a paywall, so the grid here is rebuilt from the
      write-up on the Big Dave blog, and the answers are that blog's.`],
    toughie: ["toughie", `The Telegraph Toughie, weekdays: the paper's harder
      puzzle, from named setters such as Elgar and Dada, with more obscure words,
      bolder wordplay and long, intricate clues; Elgar's are among the hardest in
      any daily paper. Grid rebuilt and answers taken from the Big Dave blog.`],
    sundaytel: ["sunday telegraph", `The Sunday Telegraph cryptic — a separate paper's
      weekly puzzle in the back-pager's smooth, approachable style, and about as
      hard. Grid rebuilt and answers taken from the Big Dave blog.`],
    sundaytough: ["sunday toughie", `The Sunday Telegraph's Toughie, weekly: a
      harder Sunday puzzle from a small team of named setters, with the
      weekday Toughie's bolder wordplay. Grid rebuilt and answers taken from the
      Big Dave blog.`],
    indysunday: ["indy sunday", `The Independent on Sunday's cryptic, with its own
      weekly numbering: the daily's setters and its adventurous style, themes and
      hidden grid messages included, and about as hard.`],
    book: ["book", `Puzzles from printed crossword books, most of them now
      out of print. Each is named by its book and its number in that book,
      and dated by the year the book came out. Books print their solutions
      only as pictures of filled grids, so the answers here are our own solve.`],
  };


  function seriesBadge(p) {
    return seriesChip(p.series || "cryptic");
  }

  // The pill for one series key. The picker rows and the notify list both name
  // papers, and a paper a solver has learnt to recognise in one of them has to
  // look the same in the other.
  function seriesChip(series) {
    const badge = SERIES_BADGE[series];
    if (!badge) return "";  // guarded by the smoke test; never the normal path
    return `<span class="badge series" title="${badge[1]}">${badge[0]}</span>`;
  }

  // What the picker lists, and why it isn't everything.
  //
  // This is a teaching site, so a puzzle with no hand-written annotations can't
  // do the thing the site is for: you can type letters into it and check them,
  // and that's all. Listing those alongside the taught ones would make the one
  // dialog whose job is "what should I do next" answer mostly with things that
  // won't teach you anything, and the ratio worsens every night, because
  // fetching is daily and annotating is one puzzle per run.
  //
  // Nor is it everything that IS annotated: the answer would be a catalogue you
  // scroll. So the default is the newest RECENT_ROWS, plus
  // whatever the solver has open or has left unfinished.
  //
  // Hidden is not gone. A query searches EVERY puzzle, annotated or not, so
  // typing a number you know still finds it; the archive page lists them all;
  // and ?p=<n> opens any of them. A finished grid drops out of the default list
  // rather than sitting in it forever: it is the one puzzle you have no reason
  // to open next, and "solved" is a search term for the days you do.
  const RECENT_ROWS = 12;
  // "Have I finished this one?" — the question a list of puzzles has to
  // answer before it can answer anything else. It is computed here rather than
  // stored: the saved letters are simply held against the solutions. A stored
  // `done` flag would be a second copy of a fact the data already knows, and
  // sync/merge.js would then have to have an opinion about merging it.
  //
  // The solutions are only fetched for puzzles with letters saved, which is why
  // the `!filled` test comes first: it is also what makes loadStartedPuzzles a
  // short list rather than the whole catalogue.
  //
  // Filled-but-wrong deliberately reads as unfinished rather than as "12 wrong":
  // the check buttons are for that, and a row in the picker is not the place to
  // tell someone their grid is broken.
  function pickerStatus(p) {
    const id = p.reprintOf || p.id;
    const prog = savedProgress()[id];
    const puz = window.CRYPTIC_PUZZLES[id];
    const letters = (prog && (!puz || fitsGrid(prog, puz)) && prog.letters) || {};
    const filled = Object.keys(letters).filter((k) => !k.endsWith("-offgrid")).length;
    if (!filled || !puz) return { filled, total: 0, done: false };
    const want = {};   // "x,y" -> the letter that belongs there
    puz.entries.forEach((e) => {
      for (let i = 0; i < e.length; i++) want[squareOf(e, i)] = e.solution ? e.solution[i] : null;
    });
    // Squares only an unclued light covers are in the grid too; printed ones are
    // given, never saved, so they are not the solver's to fill.
    (puz.unclued || []).forEach((u) => u.cells.forEach(({ x, y }, i) => {
      const k = x + "," + y;
      if (!want[k]) want[k] = u.solution ? u.solution[i] : null;
    }));
    (puz.printed || []).forEach(({ x, y }) => { delete want[x + "," + y]; });
    const squares = Object.keys(want);
    // letters[k] is "A" or "A!" — a revealed letter still counts as done. You
    // used the escape hatch; the scorebar inside the puzzle is where that costs
    // you something.
    const done = squares.length > 0 && !onPaper(id)
      && squares.every((k) => want[k] && letters[k] && letters[k][0] === want[k])
      // An off-grid clue's whole answer is one value, under its entry id.
      && offGridEntries(puz).every((e) => e.solution && (letters[entryId(e)] || "").replace("!", "") === e.solution);
    return { filled, total: squares.length, done };
  }
  // The date and the day it fell on. A weekday is not decoration on a cryptic:
  // the Guardian's week has a shape — Monday gentle, Friday and Saturday's prize
  // hard — so "what day is this from" is a difficulty cue people read before
  // they start. Always COMPUTED from the date, never
  // stored: a saved weekday is a second copy of the date, and second copies
  // disagree. `date` is a calendar day, "YYYY-MM-DD", which new Date() reads as
  // UTC midnight: getUTCDay, or a solver west of Greenwich gets the day before.
  //
  // A book puzzle holds its book's `year` and no `date`: the imprint prints no
  // day, so there is no weekday to show and iso is the year alone.
  //
  // `words` is the day as the archive pages print it, "3 October 2026", and
  // `shortWords` the row's "3 Oct 2026" (tools/series.py display_number);
  // `iso` stays for search, since that is what a solver might paste.
  const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];
  // A calendar day in words, the one way the app prints one.
  function dayWords(y, m, d, short) {
    return `${d} ${short ? MONTHS[m].slice(0, 3) : MONTHS[m]} ${y}`;
  }
  // Between the items of every list the app prints (tools/build_abbreviations.py LIST_SEP).
  const LIST_SEP = " · ";
  function localDay(t) { return dayWords(t.getFullYear(), t.getMonth(), t.getDate(), true); }
  function puzzleDate(p) {
    if (p.year !== undefined) {
      const y = String(p.year);
      return { iso: y, day: "", short: "", words: y, shortWords: y };
    }
    if (!p.date) return { iso: "", day: "", short: "", words: "", shortWords: "" };
    const t = new Date(p.date);
    const day = WEEKDAYS[t.getUTCDay()] || "";
    const [y, m, d] = [t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate()];
    return { iso: p.date, day, short: day.slice(0, 3),
             words: dayWords(y, m, d, false), shortWords: dayWords(y, m, d, true) };
  }
  // The puzzle heading's name and date. A date-keyed paper (the Canberra
  // Times) prints no number, so the file's name already holds the day
  // ("Canberra Times cryptic crossword, Monday 6 January 1992 (English
  // cryptic)") and the heading appended it a second time. Where the name
  // carries the puzzle's own day, take it out of the name and show it once,
  // short, after the " · ": "Canberra Times cryptic crossword (English
  // cryptic) · Mon 6 Jan 1992". Any other name keeps the day in full.
  function headingParts(name, p) {
    const when = puzzleDate(p);
    const full = when.day ? when.day + " " + when.words : when.words;
    if (!when.iso || p.year !== undefined) return { name, date: full };
    const t = new Date(p.date);
    const [y, m, d] = [t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate()];
    const re = new RegExp(`,?\\s*(?:(?:${WEEKDAYS.join("|")}),?\\s+)?${d} ${MONTHS[m]} ${y}`, "i");
    if (!re.test(name)) return { name, date: full };
    return { name: name.replace(re, "").replace(/\s+/g, " ").trim(),
             date: when.short + " " + when.shortWords };
  }
  // The half of a puzzle's search text that cannot change while the page is
  // open: every word in it is read off INDEX, which is loaded once and never
  // written to. Built on first use and kept for the life of the page — nothing
  // invalidates it, because nothing can make it wrong.
  //
  // Kept because it is the search: rebuilding one per puzzle in the index on
  // every keystroke and every chip tap would cost tens of ms before a single row
  // was drawn, a quarter of it the `new Date` in puzzleDate.
  // A plain object, not a Map, though it holds every id in the index and that
  // puts it in dictionary mode — which is the argument for a Map, and the
  // measurement goes the other way: 20M lookups cost 423 ms against the object
  // and 991 ms against the Map. It is read once per row per render, so that IS
  // the search.
  let staticHay = {};
  function pickerStaticHay(p) {
    const had = staticHay[p.id];
    if (had !== undefined) return had;
    const dd = puzzleDate(p);
    // Both spellings of the number: the site writes "No 30,074" everywhere, and
    // a solver copying that in shouldn't get nothing back.
    //
    // The weekday is searchable because the row shows it — showing "Sat" in the
    // row and then not matching "saturday" would be the worse half of the
    // feature. Both the series key and the name on its chip: "cryptic" is what
    // the file is called, "guardian" is what the paper is, and the one the row
    // shows has to be the one that matches.
    const series = p.series || "cryptic";
    return (staticHay[p.id] = [p.number, String(p.number).replace(/(\d)(\d{3})$/, "$1,$2"),
      displayNumber(p), p.setter, dd.iso, dd.words, dd.day,
      series, (SERIES_BADGE[series] || [""])[0],
      p.difficulty ? p.difficulty.band : "",
      ...(p.tags || []).map((k) => ((INDEX.tags || {})[k] || {}).label || "")].join(" ").toLowerCase());
  }
  // "solved" and "started" are searchable for the same reason the row shows
  // them: "which ones have I already done" is a filter, not just a thing to read
  // off one row at a time. They are the only part of the haystack that moves
  // while the page is open, so they are added here instead of being baked into
  // the cache above — and only for the puzzles that have letters saved, which is
  // a handful, rather than asked of every puzzle in the index.
  function pickerHaystack(p) {
    if (!savedProgress()[p.reprintOf || p.id]) return pickerStaticHay(p);
    const st = pickerStatus(p);
    return pickerStaticHay(p) + (st.done ? " solved done" : " started unfinished");
  }
  // What the panel offers as you type. Only the terms a solver could not be
  // expected to have spelled right from memory — setters and weekdays — plus the
  // two status filters. Papers and bands have menus of their own. Numbers are
  // deliberately absent: there would be too many, burying every word in the
  // list, and a number you can remember you can already type.
  //
  // Built from the index rather than listed, so a setter cannot appear in the
  // suggestions without appearing in the rows, or the other way round.
  //
  // Nothing is offered until two letters are in. The whole list on an empty box
  // buries the panel it is there to search, on an iPhone. Two
  // letters cuts the terms to a handful, and by then the suggestion is
  // about a word already being spelled — which is when a completion is worth
  // anything.
  //
  // Offered as chips, not through the input's list= attribute. A datalist popup
  // is native UI the page cannot place, and no CSS can move it. A chip row is
  // laid out by the panel, so where it appears is decided here and is the same
  // everywhere.
  const PICKER_SUGGEST_MIN = 2;
  let pickerTerms = null;
  function pickerSuggestTerms(q) {
    if (q.length < PICKER_SUGGEST_MIN) return [];
    if (pickerTerms === null) {
      const seen = { solved: 1, unfinished: 1 };
      INDEX.puzzles.forEach((p) => {
        [p.setter, puzzleDate(p).day].forEach((t) => { if (t) seen[t] = 1; });
      });
      pickerTerms = Object.keys(seen).sort((a, b) => a.localeCompare(b));
    }
    return pickerTerms.filter((t) => t.toLowerCase().includes(q));
  }

  // head-live's per-paper, band and tag counts, while the list is still only
  // the newest rows (a progressive boot); null once every row is here.
  function headCounts() {
    return (INDEX.partial && INDEX.idx && INDEX.idx.live && INDEX.idx.live.counts) || null;
  }
  let pickerBands = null;
  function pickerBandList() {
    if (pickerBands) return pickerBands;
    const at = {};
    if (headCounts()) Object.keys(headCounts().bands || {}).forEach((b) => { at[b] = Infinity; });
    INDEX.puzzles.forEach((p) => {
      const d = p.difficulty;
      if (!d || !d.band || d.percentile === null || d.percentile === undefined) return;
      if (at[d.band] === undefined || d.percentile < at[d.band]) at[d.band] = d.percentile;
    });
    pickerBands = Object.keys(at).sort((a, b) => at[a] - at[b]).map((b) => b.toLowerCase());
    return pickerBands;
  }

  // The two menus under the search box, built from the index alone.
  //
  // Papers are grouped by index.json's `groups` table, which is tools/series.py's
  // `group` (the publisher unless a series says otherwise, as the Sunday Times
  // says Times): a series added there lands in its group with nothing to edit
  // here. A group with two or more series gets an "All" option at its head;
  // the single-series ones share one group, because a heading over one option
  // is only a longer way to say its name.
  // Biggest first at every level, because how much there is to solve is the
  // useful order when the question is which one to try. The notify list takes
  // the same order, so a paper sits in the same place in both.
  //
  // An option's value is the comma-joined series keys it stands for, so the
  // filter reads a key set straight off the menu and never matches a paper by
  // its name: "times" as a search term is inside "times quick" and "sunday
  // times", and a filter must not be.
  const titleCase = (s) => s.replace(/(^|\s)\S/g, (c) => c.toUpperCase());
  // What the picker searches and files under papers: every listed puzzle and a
  // row per reprint, which is the original's row under the reprinting paper's
  // series, number, date and id, and opens the original. Both lists are
  // newest-first, so the reprints merge in by date and sit among their paper's
  // own puzzles where its print date puts them.
  let pickable = null;
  function pickerPuzzles() {
    if (pickable) return pickable;
    // A book's reprint row carries the book's year instead of a date.
    const reprints = (INDEX.reprints || []).filter((r) => BY_ID[r.reprintOf])
      .map((r) => {
        const row = Object.assign({}, BY_ID[r.reprintOf], {
          id: r.id, series: r.series, number: r.number, name: r.name, reprintOf: r.reprintOf });
        delete row.date; delete row.year;
        if (r.date !== undefined) row.date = r.date;
        if (r.year !== undefined) row.year = r.year;
        return row;
      });
    // The index's order: newest day (a year is its 1 January), then highest number.
    const day = (p) => p.date || (p.year !== undefined ? `${p.year}-01-01` : "");
    const before = (r, p) => day(r) > day(p) || (day(r) === day(p) && r.number > p.number);
    pickable = [];
    let i = 0;
    INDEX.puzzles.forEach((p) => {
      while (i < reprints.length && before(reprints[i], p)) pickable.push(reprints[i++]);
      pickable.push(p);
    });
    pickable.push(...reprints.slice(i));
    return pickable;
  }
  function paperGroups() {
    const papers = INDEX.groups || {};
    const n = {};
    if (headCounts()) {
      // Only the newest rows are here: the head says how many each paper has.
      Object.assign(n, headCounts().series);
      (INDEX.reprints || []).forEach((r) => { n[r.series] = (n[r.series] || 0) + 1; });
    } else {
      pickerPuzzles().forEach((p) => { const s = p.series || "cryptic"; n[s] = (n[s] || 0) + 1; });
    }
    const size = (keys) => keys.reduce((t, s) => t + n[s], 0);
    const biggest = (a, b) => size(b) - size(a);
    const byPub = {};
    Object.keys(n).forEach((s) => { (byPub[papers[s] || ""] = byPub[papers[s] || ""] || []).push(s); });
    const multi = Object.keys(byPub).filter((pub) => pub && byPub[pub].length > 1)
      .map((pub) => byPub[pub].sort((a, b) => n[b] - n[a]))
      .sort(biggest);
    const single = Object.keys(n).filter((s) => !multi.some((g) => g.includes(s)))
      .sort((a, b) => n[b] - n[a]);
    return { papers, n, size, multi, single };
  }
  let paperMenu = null;
  function paperMenuHTML() {
    if (paperMenu !== null) return paperMenu;
    const { papers, size, multi, single } = paperGroups();
    const opt = (keys, label) => `<option value="${keys.join(",")}">${esc(label)} (${
      size(keys).toLocaleString("en-GB")})</option>`;
    const seriesOpt = (s) => opt([s], titleCase((SERIES_BADGE[s] || [s])[0]));
    paperMenu = `<option value="">Paper</option>`
      + multi.map((g) => `<optgroup label="${esc(papers[g[0]])}">`
        + opt(g, "All " + papers[g[0]]) + g.map(seriesOpt).join("") + "</optgroup>").join("")
      + (single.length ? `<optgroup label="${multi.length ? "Other papers" : "Papers"}">`
        + single.map(seriesOpt).join("") + "</optgroup>" : "");
    return paperMenu;
  }
  // The list grew: every memo above was made from the shorter one.
  function resetListCaches() {
    staticHay = {};
    pickerTerms = null;
    pickerBands = null;
    pickable = null;
    paperMenu = null;
  }
  function bandMenuHTML() {
    return `<option value="">Difficulty</option>`
      + pickerBandList().map((b) => `<option value="${esc(b)}">${esc(titleCase(b))}</option>`).join("");
  }
  // Only the tags some listed puzzle carries, in the index's order: an option
  // that matches nothing is a dead end. Each reads as its /showcase/ heading
  // does (tools/showcase.feature_spec): the label with a capital first letter.
  function tagMenuHTML() {
    const info = INDEX.tags || {};
    const counted = headCounts() ? headCounts().tags || {} : null;
    const used = Object.keys(info).filter((t) => (counted ? counted[t] > 0 : false) || INDEX.puzzles.some((p) => hasTag(p, t)));
    const name = (s) => s[0].toUpperCase() + s.slice(1);
    return `<option value="">Feature</option>`
      + used.map((t) => `<option value="${esc(t)}">${esc(name(info[t].label))}</option>`).join("");
  }
  // The rows the three menus allow, or null when all say "all".
  function pickerFilter() {
    const paper = ($("picker-paper") || {}).value || "";
    const band = ($("picker-band") || {}).value || "";
    const tag = ($("picker-tag") || {}).value || "";
    if (!paper && !band && !tag) return null;
    const keys = new Set(paper.split(","));
    return (p) => (!paper || keys.has(p.series || "cryptic"))
      && (!band || (!!p.difficulty && String(p.difficulty.band).toLowerCase() === band))
      && (!tag || hasTag(p, tag));
  }

  function pickerRows(q) {
    // Every term has to match somewhere, so "imogen 2026" narrows rather than
    // widens — the useful behaviour when the list is long enough to need a
    // filter at all.
    // A menu set to anything but "all" is a query too, answered the same way.
    const terms = q.split(/\s+/).filter(Boolean);
    const keep = pickerFilter();
    // Offline, the list is what this device can open: the saved puzzles only,
    // newest first, searched and filtered as ever.
    const heldOnly = offlineList();
    if (heldOnly && !terms.length && !keep) return pickerPuzzles().filter((p) => !p.reprintOf && heldOnly(p));
    if (terms.length || keep) {
      // A run of digits is a NUMBER, and a number is not the digits sitting
      // inside a longer one: Globe and Mail 3,368 is inside Guardian cryptic
      // 23,368, so typing the number printed on the page you are looking at
      // would return two unrelated puzzles. A digits-only term has to start where
      // a number starts, which still narrows as you type — "233" opens 23,368 and
      // not 3,368 — and leaves every other term matching anywhere, because
      // "imogen" inside a setter's name is exactly what a search is for.
      const matchers = terms.map((t) => (/^\d+$/.test(t)
        ? new RegExp("(^|[^\\d])" + t) : null));
      const hits = pickerPuzzles().filter((p) => {
        if (keep && !keep(p)) return false;
        if (heldOnly && !heldOnly(p)) return false;
        const hay = pickerHaystack(p);
        return terms.every((t, i) => (matchers[i] ? matchers[i].test(hay)
                                                  : hay.includes(t)));
      });
      // Taught first, and the index's own order within each half. The default
      // view lists only annotated puzzles, so a filtered view that buries them
      // is the same list making a different promise.
      //
      // A dated series hides the problem: annotating follows fetching, so
      // newest-first already puts the taught ones near the top. A series with
      // no dates gets none of that. The book puzzles are reprints with no
      // publication date, which sorts them below every dated puzzle and orders
      // them among themselves by number — so the annotated ones would sit deep
      // in their own paper's list.
      return hits.filter((p) => p.annotated).concat(hits.filter((p) => !p.annotated));
    }
    // INDEX.puzzles is latest-first, so the cap counts down from today. The two
    // exemptions are the solver's own place and don't count against it.
    //
    // Both exemptions are known BY ID before the walk starts — savedProgress()
    // is the short list of puzzles with letters saved, and P is one puzzle — so
    // the walk stops the moment it has its RECENT_ROWS and has passed every
    // exemption it was looking for, instead of filtering every row to
    // produce a dozen every time the panel is drawn.
    //
    // Restricted to ids the index actually knows, because the stop condition
    // depends on the set emptying: progress saved for a puzzle that has since
    // left the corpus would otherwise hold the walk open to the last row.
    const want = new Set();
    if (P && BY_ID[P.id]) want.add(P.id);
    Object.keys(savedProgress()).forEach((id) => {
      if (BY_ID[id] && !pickerStatus(BY_ID[id]).done) want.add(id);
    });
    const out = [];
    let recent = 0;
    for (const p of INDEX.puzzles) {
      if (want.has(p.id)) { want.delete(p.id); out.push(p); }
      else if (p.annotated && recent < RECENT_ROWS) { recent += 1; out.push(p); }
      if (recent >= RECENT_ROWS && !want.size) break;
    }
    return out;
  }

  // One row. Pulled out of renderPicker so the list can be built a chunk at a
  // time rather than all at once.
  function pickerRow(p) {
    const li = document.createElement("li");
    const opens = p.reprintOf || p.id;
    if (P && opens === P.id) li.className = "current";
    const st = pickerStatus(p);
    // Offline, the list says which puzzles this device can open.
    const held = offlineHas(p);
    if (held === false) li.className = (li.className + " no-offline").trim();
    const dd = puzzleDate(p);
    // Abbreviated, and the weekday leads. The row is tight — see the note
    // below about the nowrap element shoving the line — and "Sat" in front is
    // read at a glance where a trailing full "Saturday" would just be length.
    const d = dd.short ? `${dd.short} ${dd.shortWords}` : dd.shortWords;
    // The date column carries the date on every row. A date-keyed paper prints
    // no number, so its title slot names the paper instead ("Canberra Times"),
    // as hub_row in build_seo_pages.py does.
    const title = isDateNumbered(p) ? DATE_NUMBERED[p.series] : displayNumber(p);
    const btn = document.createElement("button");
    // Order here is the grid's, not the eye's: the badges are markup-last but
    // render on their own second line (see .p-tags in style.css). Progress
    // sits with them because it is a status like they are, and because
    // gluing it onto the date made the one nowrap element in the row long
    // enough to shove everything else off the line.
    btn.innerHTML = `<span class="p-num" data-number="${p.number}">${title}</span>
        <span class="p-setter">${esc(p.setter || "")}</span>
        <span class="p-meta">${d}</span>
        <span class="p-tags">${seriesBadge(p)}${difficultyBadge(p)}${hintsBadge(p.annotated, p.blog)}${sourceBadge(p)}${tagBadges(p)}
          ${!st.filled ? ""
            : st.done ? `<span class="p-prog done" title="Every square filled in and correct">solved ✓</span>`
            : `<span class="p-prog">${st.filled}${st.total ? "/" + st.total : ""} letters filled</span>`}${held ? `<span class="p-prog">saved offline</span>` : ""}</span>`;
    // The row is one button, so the difficulty badge cannot be an <a> inside
    // it; a tap on the badge goes to the page explaining it instead.
    btn.onclick = (ev) => {
      if (ev && ev.target && ev.target.closest && ev.target.closest(".badge.diff")) {
        location.href = DIFFICULTY_PAGE;
        return;
      }
      if (held === false) {
        setHTML($("picker-note"), "You’re offline and that puzzle isn’t saved on this device. Puzzles marked “saved offline” will open.");
        return;
      }
      openPuzzle(opens); togglePicker(false);
    };
    li.appendChild(btn);
    return li;
  }

  // How many rows go in before the list has to be scrolled, and how many more
  // each time the bottom of it comes into view.
  //
  // A search matches as many puzzles as it matches — the "guardian" chip
  // matches thousands — and building every one of them on the tap that selected
  // the chip would mean parsing and laying out thousands of elements in one go.
  // The eye can see about a dozen.
  //
  // Comfortably more than RECENT_ROWS, so the default list — the newest twelve
  // plus whatever you have open or unfinished — is never a chunked one.
  const PICKER_CHUNK = 24;
  // The observer watching the last row drawn, or null. Exactly one at a time:
  // each render throws away the list the last one was watching.
  let pickerWatch = null;

  function renderPicker() {
    const ul = $("picker-list");
    ul.innerHTML = "";
    const q = (($("picker-search") || {}).value || "").trim().toLowerCase();
    // Completions for the word being typed. Tapping one ADDS its words to the
    // box and tapping it again takes them out, so it is a way back out as well
    // as in; aria-pressed rings the ones already there. Matched lower-cased,
    // because a setter is offered as "Arachne" and the box is a lower-case query.
    const picked = q.split(/\s+/).filter(Boolean);
    const wordsOf = (w) => w.toLowerCase().split(/\s+/).filter(Boolean);
    const isOn = (w) => wordsOf(w).every((x) => picked.indexOf(x) >= 0);
    const suggest = pickerSuggestTerms(q);
    setHTML($("picker-filters"), suggest.length
      ? `<span class="muted small-note">Matching</span>` + suggest.map((w, i) =>
        `<button type="button" id="ps-${i}" class="badge term" aria-pressed="${isOn(w)}">${esc(w)}</button>`).join("")
      : "");
    suggest.forEach((w, i) => {
      const el = $("ps-" + i);
      if (!el) return;
      el.onclick = () => {
        const mine = wordsOf(w);
        $("picker-search").value = (isOn(w) ? picked.filter((x) => mine.indexOf(x) < 0)
          : picked.concat(mine.filter((x) => picked.indexOf(x) < 0))).join(" ");
        renderPicker();
      };
    });
    ["picker-paper", "picker-band", "picker-tag"].forEach((id) => $(id).classList.toggle("on", !!$(id).value));
    // A chosen feature says what it means: choosing it is the asking.
    const tagInfo = (INDEX.tags || {})[($("picker-tag") || {}).value || ""];
    const offlineNow = !!offlineList();
    setHTML($("picker-note"), offlineNow
      ? `You’re offline: these are the ${offlineFiles.size} puzzle${offlineFiles.size === 1 ? "" : "s"} saved on this device.`
      : tagInfo ? esc(tagInfo.blurb) : "");
    const filtered = !!(q || pickerFilter());
    const rows = pickerRows(q);
    // This render is throwing away the list the last observer was watching.
    if (pickerWatch) { pickerWatch.disconnect(); pickerWatch = null; }
    let drawn = 0;
    // The line under the list says two different things and has to keep them
    // apart. "More below" is about scrolling; "don't match" is about searching,
    // and the answer to it is to type something else. Rolling them into one
    // count would tell a solver who can see 24 of thousands of matching puzzles
    // that the undrawn ones "don’t match", which is a lie.
    const sayRest = () => {
      const unmatched = pickerPuzzles().length - rows.length;
      const below = rows.length - drawn;
      const bits = [];
      if (below) bits.push(`${below} more match${below > 1 ? "es" : ""} — keep scrolling.`);
      if (offlineNow) bits.push("The rest open once you’re back online.");
      else if (unmatched) bits.push(filtered
        ? `${unmatched} other puzzle${unmatched > 1 ? "s" : ""} don’t match.`
        : `${unmatched} more — search by puzzle number, setter (the puzzle’s author) or day, type “solved” in the search box to see the ones you finished, or `
          + `<a href="${at("puzzles/")}">browse the whole archive</a>.`);
      setHTML($("picker-more"), bits.join(" "));
    };
    if (!rows.length) {
      const li = document.createElement("li");
      li.className = "picker-empty";
      li.innerHTML = `<span class="muted">${offlineNow && !filtered ? "No puzzles are saved on this device yet."
        : `Nothing matches${q ? ` “${esc(q)}”` : ""}.`}</span>`;
      ul.appendChild(li);
      sayRest();
      return;
    }
    // Without an IntersectionObserver nothing can tell us the bottom has been
    // reached, so the whole list goes in at once — slow on a search that
    // matches thousands, but better than a list that stops short with no way
    // to go on.
    const chunk = typeof IntersectionObserver === "function" ? PICKER_CHUNK : rows.length;
    const drawMore = () => {
      const upto = Math.min(rows.length, drawn + chunk);
      while (drawn < upto) ul.appendChild(pickerRow(rows[drawn++]));
      sayRest();
      if (pickerWatch) { pickerWatch.disconnect(); pickerWatch = null; }
      if (drawn >= rows.length) return;
      // Watching the last row drawn rather than a sentinel node: a sentinel
      // would be a child of #picker-list that is not a puzzle, and everything
      // that reads this list — Enter on the search box takes children[0] —
      // would have to learn about it.
      //
      // rootMargin so the next chunk is built while the bottom row is still a
      // panel-height away, rather than after the scroll has already hit the end.
      //
      // Against the PANEL, not the viewport. The panel is the scroller — see
      // `.panel { max-height: 70vh; overflow: auto }` in style.css — and a
      // rootMargin only grows the root's own rectangle: with the default root
      // the margin would be applied to the window and then clipped back by the
      // panel it is inside, so the lookahead would silently be no lookahead and
      // rows would arrive only once the scroll had already stopped on them.
      pickerWatch = new IntersectionObserver((seen) => {
        if (seen.some((r) => r.isIntersecting)) { loadAllNow(); drawMore(); }
      }, { root: $("picker-panel"), rootMargin: "400px" });
      pickerWatch.observe(ul.children[ul.children.length - 1]);
    };
    drawMore();
  }
  // The panels all live in one slot — same corner, same z-index, see .panel in
  // style.css — so two open at once is two panels drawn on top of each other,
  // and the DOM order decides which one you see. The picker is last in
  // index.html, so pressing Sync with the picker up opened the sync panel
  // underneath it, and the button would look broken.
  //
  // Opening one therefore closes the others, and every opener goes through
  // here, so no panel can overlap another by forgetting to.
  const PANELS = ["sync-panel", "notify-panel", "picker-panel", "fb-panel", "stats-panel"];
  function closePanel(id) {
    // Whatever the panel was doing to the outside world stops when it goes
    // away. The scanner holds the camera, so a panel closed by another one
    // opening has to release it just as the ✕ does.
    if (id === "sync-panel") stopScan();
    $(id).classList.add("hidden");
  }
  // Returns whether the panel ended up open, which is the caller's cue to fill
  // it in — rendering a panel nobody can see is wasted work.
  function showPanel(id, show) {
    const want = (show === undefined) ? $(id).classList.contains("hidden") : show;
    if (!want) { closePanel(id); return false; }
    PANELS.forEach((other) => { if (other !== id) closePanel(other); });
    $(id).classList.remove("hidden");
    return true;
  }

  function isTouchPrimary() {
    return !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  }

  // The home-screen app's Puzzles and Stats tabs are pages: each has its own
  // hash (#picker, #stats), pushed when it opens or closes so the back gesture
  // walks between them, and applied again on popstate/hashchange. Browser tabs
  // keep the panels as they were and touch no history.
  const isAppMode = () => !!(document.documentElement && document.documentElement.classList &&
    document.documentElement.classList.contains("standalone"));
  const tabHash = () => !$("picker-panel").classList.contains("hidden") ? "#picker"
    : !$("stats-panel").classList.contains("hidden") ? "#stats" : "";
  let applyingRoute = false;
  function syncRoute() {
    const h = window.history;
    if (applyingRoute || !isAppMode() || !h || !h.pushState) return;
    const want = tabHash();
    if (want === (location.hash || "")) return;
    try { h.pushState(null, "", location.pathname + location.search + want); } catch (e) { /* no history */ }
  }
  function applyRoute() {
    if (!isAppMode()) return;
    applyingRoute = true;
    try {
      const h = location.hash || "";
      if (h === "#picker") togglePicker(true);
      else if (h === "#stats") toggleStats(true);
      else { showPanel("picker-panel", false); showPanel("stats-panel", false); }
    } finally { applyingRoute = false; }
  }

  function togglePicker(show) {
    const open = togglePickerPanel(show);
    syncRoute();
    return open;
  }
  function togglePickerPanel(show) {
    const el = $("picker-panel");
    const want = showPanel("picker-panel", show);
    // The search box starts empty, but the menus keep what they were last set
    // to: someone working through one paper at one difficulty opens a puzzle,
    // comes back for the next, and should not have to set them again. They are ringed "on" while set (renderPicker), which is what
    // tells a narrowed list from puzzles gone missing. A value the rebuilt menu
    // no longer offers falls back to "", each menu's "all".
    const box = $("picker-search");
    if (want) {
      // A page opens at its top: the panel kept the scroll it had when it was
      // closed, so the list came back already at its end and the next drag up
      // had nowhere to go but the page behind.
      el.scrollTop = 0;
      if (box) { box.value = ""; }
      const kept = store.get("ct:picker", null) || {};
      setHTML($("picker-paper"), paperMenuHTML());
      setHTML($("picker-band"), bandMenuHTML());
      setHTML($("picker-tag"), tagMenuHTML());
      $("picker-paper").value = kept.paper || "";
      $("picker-band").value = kept.band || "";
      $("picker-tag").value = kept.tag || "";
      renderPicker();
      offlineRefresh(() => { if (!el.classList.contains("hidden")) renderPicker(); });
      probeNet();
      // The progress numbers need the answers, and a sync pull may have handed
      // this browser progress on a puzzle whose file it has never fetched.
      loadStartedPuzzles(() => {
        if (!el.classList.contains("hidden")) renderPicker();
      });
      // Focus the search box for a keyboard user only. On a touch device the
      // focus raises the soft keyboard over the list before anyone has chosen
      // to search; tapping the box still focuses it.
      if (box && box.focus && !isTouchPrimary()) box.focus();
      loadAllSoon();
    }
    return want;
  }

  // ---------- puzzle lifecycle ----------
  // The address bar is what gets copied. Whichever puzzle is on the screen is
  // the one a share has to hand over, so opening one rewrites the URL — otherwise
  // the bar would say the site root, which drops the reader on last night's
  // puzzle, or a stale ?p= from the link they arrived by, which is worse
  // because it looks deliberate.
  //
  // replaceState, not push: switching puzzles is choosing what to look at, not
  // navigating, and a back button that walked the picker backwards would make
  // leaving the site take one press per puzzle browsed.
  //
  // Only when the reader CHOSE this puzzle, though. Booting on the remembered
  // one is not a choice, and a bare site root that rewrites itself
  // would leave the homepage declaring a puzzle as its canonical, de-indexing
  // it. The front door stays the front door until somebody picks.
  // The solver goes on screen, and the boot placeholder index.html put up
  // (html.ct-boot: a grid-shaped box, crawler links and footer held back)
  // comes down in the same frame.
  function showApp() {
    $("app").classList.remove("hidden");
    const root = document.documentElement;
    if (root && root.classList) root.classList.remove("ct-boot");
  }

  let canonicalHome = null;
  function homeUrl() {
    if (canonicalHome === null) {
      const link = document.querySelector('link[rel="canonical"]');
      canonicalHome = link ? link.href : location.origin + "/";
      // Kept on this page's own origin when that is http(s) (a test server, a
      // preview): the service worker registers only from its own origin, and
      // a fetch to the production host would be cross-origin there.
      const u = new URL(canonicalHome);
      if (/^https?:$/.test(location.protocol) && location.origin !== u.origin) canonicalHome = location.origin + u.pathname;
    }
    return canonicalHome;
  }

  // Every URL the app builds is resolved against the front door, never against
  // the address bar. Opening a puzzle rewrites the bar to /puzzles/<id>/, so a
  // relative "puzzles/..." then resolves one level deeper —
  // /puzzles/<id>/puzzles/... — and 404s, for the archive link at the foot of
  // the picker and for the script tag of the NEXT puzzle opened.
  function at(rel) { return new URL(rel, homeUrl()).href; }

  // The same goes for the icons and manifest linked in <head>: index.html writes
  // them relative, and once the bar is /puzzles/<id>/ the browser asks for
  // /puzzles/<id>/favicon.svg and 404s. Pin them to the front door now.
  document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"], link[rel="manifest"]').forEach((l) => {
    const h = l.getAttribute("href");
    if (h) l.setAttribute("href", at(h));
  });

  // The same rule for what goes in the address bar, every form of it: a bare
  // "?p=<b>" resolves against the bar too, and with the bar at /puzzles/<a>/
  // gives /puzzles/<a>/?p=<b> — a bar still naming a, which reloads and shares
  // as a. Kept on this page's own origin, because the canonical
  // names the production host and replaceState throws on any other.
  function addressUrl(rel) {
    const u = new URL(rel, homeUrl());
    return location.origin && location.origin !== u.origin
      ? location.origin + u.pathname + u.search : u.href;
  }
  // Safari throws once replaceState is called too often. A URL that did not
  // update must not take the puzzle switch down with it, so the throw is
  // caught here, the one place the bar is written, and reported.
  // Browsers allow about 100 calls per 10 seconds. Normal use never gets near
  // that, so writes go straight through until 80 have landed in the window;
  // after that only the latest URL is kept and written once the window frees up.
  const addressWrites = [];
  let addressPending = null;
  let addressTimer = null;
  function setAddress(url) {
    if (!window.history || !window.history.replaceState) return;
    const now = Date.now();
    while (addressWrites.length && now - addressWrites[0] > 10000) addressWrites.shift();
    if (addressWrites.length >= 80) {
      addressPending = url;
      if (!addressTimer) {
        addressTimer = setTimeout(() => {
          addressTimer = null;
          const u = addressPending;
          addressPending = null;
          if (u) setAddress(u);
        }, 1000);
      }
      return;
    }
    addressWrites.push(now);
    try { window.history.replaceState(null, "", url); }
    catch (e) { console.warn("address bar not updated to " + url + ": " + ((e && e.message) || e)); }
  }

  // What the address bar should say, which is what gets pasted. A crawler
  // fetching ?p=30114 gets the app shell and the shell's single og:image, so
  // every link anyone has ever shared previewed as the same card; /puzzles/30114/
  // is a real page carrying that puzzle's own. Only for a puzzle that HAS one —
  // an unannotated puzzle has no static page, and ?p= is then the only address
  // that opens anything.
  function shareUrl(id, ref) {
    const p = BY_ID[id];
    if (hasPage(p)) {
      return addressUrl(`puzzles/${p.id}/${ref ? `?c=${ref}` : ""}`);
    }
    return addressUrl(`?p=${encodeURIComponent(id)}${ref ? `&c=${ref}` : ""}`);
  }

  let urlNamesPuzzle = !!new URLSearchParams(location.search).get("p");
  function pointUrlAtPuzzle(id) {
    const p = BY_ID[id];
    urlNamesPuzzle = true;
    setAddress(shareUrl(id, null));
    // A reload fetches whatever the address bar now says, which is the static
    // write-up. This flag tells that page's <head> this tab was solving here, so
    // it sends the reload back to the app (app_return in tools/build_seo_pages.py).
    try { sessionStorage.setItem(`ct:app:${id}`, "1"); } catch (e) { /* no storage: a reload shows the write-up */ }
    // ?p=30054 is one app URL among thousands, and declaring the homepage as its
    // canonical would fold every share and every link to a specific puzzle into
    // the site root. The page that
    // deserves that credit is the write-up at /puzzles/30054/, which says the same
    // things without needing JavaScript. Point at it, but only when it exists:
    // an unannotated puzzle has no static page, and the homepage is then honest.
    //
    // The canonical alone is a hint Google overrides: it indexes ?p= as a
    // duplicate of the write-up and can pick it over the write-up. So an app
    // URL for a puzzle with a write-up is noindex, as is any unlisted puzzle.
    // robots.txt cannot do this: a URL blocked from crawling is never fetched,
    // so Google never sees the noindex and keeps it indexed.
    const noindex = !!(p && (p.unlisted || hasPage(p)));
    let robots = document.querySelector('meta[name="robots"]');
    if (noindex && !robots) {
      robots = document.createElement("meta");
      robots.name = "robots";
      robots.content = "noindex";
      document.head.appendChild(robots);
    } else if (robots && !noindex) {
      robots.remove();
    }
    const link = document.querySelector('link[rel="canonical"]');
    if (!link) return;
    // Resolved against the ORIGINAL canonical, captured once: after the first
    // switch link.href is itself a /puzzles/<n>/ URL, and resolving the next
    // puzzle against that nests one inside the other.
    link.href = hasPage(p)
      ? new URL(`puzzles/${p.id}/`, homeUrl()).href : homeUrl();
  }

  // "The Globe and Mail printed this as No 3,146 on 10 July 2026: it is the
  // Times quick cryptic crossword No 3,146, from the Times of 22 May 2026."
  // One sentence per paper that reprinted the puzzle, all from the index.
  const thePaper = (s, the) => { const name = (INDEX.papers || {})[s] || ""; return /^the /i.test(name) ? name : `${the} ${name}`; };
  function reprintNote(id) {
    const p = BY_ID[id];
    return (REPRINTS_OF[id] || []).map((r) => {
      const when = puzzleDate(p).words;
      // A book has no paper of its own (INDEX.papers says ""): it is named by its number.
      const lead = r.year !== undefined ? `Reprinted as ${displayNumber(r)} (${r.year})`
        : `${thePaper(r.series, "The")} printed this as ${displayNumber(r)} on ${puzzleDate(r).words}`;
      return `${lead}: it is the ${p.name}${when ? `, from ${thePaper(p.series, "the")} of ${when}` : ""}.`;
    }).join(" ");
  }

  function openPuzzle(id, chosen = true) {
    const puzzle = window.CRYPTIC_PUZZLES[id];
    // Not fetched yet: fetch it and come back. Once. If it still isn't here the
    // file is gone, and every caller can go on treating this as "open it".
    if (!puzzle) {
      if (puzzleLoad[id] !== 1) loadPuzzle(id, () => openPuzzle(id, chosen));
      return;
    }
    P = puzzle;
    // A phone raises its number pad for a numerical puzzle, its letters otherwise.
    $("kbd").setAttribute("inputmode", P.numeric ? "numeric" : "text");
    meta = BY_ID[id] || { annotated: false };
    jigsaw = isJigsaw(meta);
    gridNumbers = !(meta.tags || []).includes("jigsaw");
    pick = null;
    store.set("ct:last", id);
    if (chosen) pointUrlAtPuzzle(id);
    buildModel();
    hintsShown = {}; hintsEarned = {}; hintLevels = {}; revealsUsed = {}; blocksAt = {}; piecesPicked = {};
    solvedWith = {}; timing = {};
    // Forget the last puzzle's completeness, so the first render of this one
    // only records where it stands. Opening a puzzle you finished last week is
    // not something to celebrate.
    wasComplete = null;
    tallyDrawn = false;
    forgetVotes();
    // Forget the last puzzle's clue too, so syncClueUrl always writes the new
    // one. It compares refs, not puzzles, and "1A" left over from the puzzle
    // just closed reads as no change if the new one also opens on "1A" —
    // silently dropping &c= from the new puzzle's URL.
    urlClue = null;
    $("celebrate").classList.add("hidden");
    // Nothing in the air belongs to a grid that is no longer open.
    { const parts = celebrateParts(); if (parts) burstState(parts.burst, ""); }
    restoreState();
    // Started with the setting on: on paper from its first letter.
    if (paper.on && !savedProgress()[id] && paperable()) setOnPaper(id, true);
    sealArrivedProgress();
    beacon("open");
    reportVisit();
    // ?c=3D opens on that clue. A whole 15x15 is a lot to hand someone who has
    // never solved a cryptic, and it is also just what sharing wants: the answer
    // to "which one are you stuck on" should be a link, not a number to hunt for.
    // Unknown or absent falls back to the first clue rather than erroring — a
    // link that has outlived its puzzle should still open the puzzle.
    const asked = linkedClueSpent ? "" : linkedClue;
    linkedClueSpent = true;
    const first = entries.find((e) => tag(e) === asked) || entries[0];
    cur = { x: first.position.x, y: first.position.y, dir: first.direction };
    leadPick = null;
    showApp();
    // The day spelled out in full here, where there is room for it, and where a
    // solver about to start wants to know whether they picked a Monday or a
    // Saturday prize before they wonder why it is fighting back.
    const when = puzzleDate(meta);
    const setter = P.setter || "";
    const heading = headingParts(P.name, meta);
    $("puzzle-title").innerHTML =
      esc(heading.name) +
      (setter ? ` — set by <em>${esc(setter)}</em>` : "") +
      (when.words ? ` <span class="muted">· ${heading.date}</span>` : "") +
      (meta.annotated ? "" : " " + hintsBadge(false, P.blog && entries.some((e) => e.blog) && P.blog.name)) +
      // Prize puzzles publish their answers about a week late, and this site
      // solves them in the meantime rather than leaving its newest puzzle
      // hintless (tools/apply_solution.py). Every letter the checker marks wrong
      // is then measured against a machine's answer, not the paper's, and
      // someone being told they are wrong deserves to know who is telling them
      // — which the picker's own badge already says, in the same words.
      (meta.solutionsUnofficial ? " " + sourceBadge(meta) : "") +
      (meta.tags ? " " + tagBadges(meta) : "");
    // A themed puzzle's special instructions, printed above the clues as the
    // paper prints them: some answers are defined by nothing else.
    $("puzzle-preamble").textContent = P.preamble || "";
    $("puzzle-preamble").classList.toggle("hidden", !P.preamble);
    $("puzzle-style").classList.toggle("hidden", meta.style !== "straight");
    const reprinted = reprintNote(id);
    $("puzzle-reprint").textContent = reprinted;
    $("puzzle-reprint").classList.toggle("hidden", !reprinted);
    renderGrid();
    renderClues();
    const checkable = canCheck();
    ["chk-letter", "chk-entry", "chk-grid"].forEach((id2) => { $(id2).disabled = !checkable; });
    refreshAll();
    // A link that named a clue came for its hints: on a phone the panel is below
    // the grid, so bring it up with the rungs in reach.
    const panel = asked && tag(first) === asked ? $("hint-panel") : null;
    if (panel && panel.scrollIntoView && isTouchPrimary())
      panel.scrollIntoView({ block: "center" });
  }

  // Finishing a puzzle is celebrated, not just a scorebar number going from 27 to 28.
  // Two rules keep it from becoming noise: it fires on the TRANSITION only, in
  // the session that earned it — reopening a finished puzzle is not an
  // achievement and must not set off fireworks at you — and the fireworks are
  // not the point, the scoreline is. Somebody who solved 28 clues, 9 of them cold, in
  // 41 minutes is owed those three numbers in one sentence.
  let wasComplete = null;      // null = not measured yet on this puzzle
  function checkComplete() {
    const complete = entries.length > 0 && entries.every(isEntrySolved) && uncluedSolved();
    const earned = wasComplete === false && complete;
    wasComplete = complete;
    if (earned) {
      beacon("done");
      // A solved grid changes which puzzles come next: top the saved batch up.
      savedCache = null;
      setTimeout(() => offlineAuto(true), 2000);
    }
    celebrate(complete, earned);
  }
  // The finish box is two children, built once and never replaced: the burst and
  // the scoreline. Only the scoreline is ever redrawn: the vote tally arriving
  // from /v redraws it whenever it arrives, and would delete a burst mid-flight
  // if they shared one innerHTML string.
  // A function whose job is a sentence must not be able to reach the fireworks,
  // and the way to guarantee that is for them not to be in what it writes.
  let celebrateEls = null;
  function celebrateParts() {
    const box = $("celebrate");
    if (!box) return null;
    if (!celebrateEls || celebrateEls.box !== box) {
      const burst = document.createElement("div");
      burst.className = "fireworks";
      const line = document.createElement("div");
      line.className = "scoreline";
      box.appendChild(burst);
      box.appendChild(line);
      celebrateEls = { box, burst, line };
    }
    return celebrateEls;
  }

  // `earned` is only the fireworks. The sentence shows whenever the grid is full,
  // including on a finished puzzle reopened next week — it is a fact about the
  // puzzle, not an event, and there is nothing to dismiss. Written once per
  // completion rather than on every render:
  // the minutes figure would otherwise tick over as you sat there and the
  // sentence would rewrite itself under you.
  let tallyDrawn = false;

  // "Your hints by clue type": the hints in the tally line, grouped by the
  // device of the clue they were spent on, each linked to its lesson section,
  // so the finish names what to go and read. Derived from the saved ladder
  // state (hintsShown, hintsEarned, revealsUsed in ct:<id>), so it is there on
  // a reopened finished puzzle and on every synced device without storing
  // anything new. A clue counts once, under its most specific device (a charade
  // that also has a container counts as the container), so the hints add up to
  // the tally's hint total and the clues to its clues-with-help figure.
  function recapCounts() {
    const used = {}, seen = {};
    entries.forEach((e) => {
      const key = entryKey(e);
      if (seen[key]) return;
      seen[key] = true;
      const ann = annOf(e);
      const hints = hintsCharged(e);
      if (!ann || !(hints > 0 || revealsUsed[key] > 0)) return;
      const ts = (ann.type || []).filter((t) => DEVICE_RULES[t]);
      const t = ts.find((x) => x !== "charade") || ts[0];
      if (!t) return;
      used[t] = used[t] || { hints: 0, clues: 0 };
      used[t].hints += hints;
      used[t].clues++;
    });
    return Object.entries(used).sort((a, b) => b[1].hints - a[1].hints || b[1].clues - a[1].clues || a[0].localeCompare(b[0]));
  }
  function recapHTML() {
    const used = recapCounts();
    if (!used.length) return "";
    const n = (k, w) => `${k} ${w}${k === 1 ? "" : "s"}`;
    return `<div class="recap"><p class="recap-head">Your hints by clue type</p><ul>${used.map(([t, u]) =>
      `<li><a class="learn-link" href="${learnHref(DEVICE_RULES[t].learn)}">${esc(TYPES[t].label)}</a>` +
      ` <span class="muted">${n(u.hints, "hint")} · ${n(u.clues, "clue")}</span></li>`).join("")}</ul></div>`;
  }

  function celebrate(complete, earned) {
    const parts = celebrateParts();
    if (!parts) return;
    const box = parts.box;
    box.classList.toggle("hidden", !complete);
    if (!complete) {
      tallyDrawn = false;
      // A grid that stops being full takes whatever is still in the air with it.
      if (burstInFlight(parts.burst)) burstState(parts.burst, "");
      return;
    }
    if (tallyDrawn && !earned) return;
    tallyDrawn = true;
    const total = entries.filter((e) => !leaderOf[entryId(e)]).length;
    const counted = {};
    let noHints = 0, helped = 0, levels = 0;
    entries.forEach((e) => {
      const key = entryKey(e);
      if (counted[key]) return;
      counted[key] = true;
      const rungs = hintsCharged(e);
      levels += rungs;
      if (!rungs && !(revealsUsed[key] > 0)) noHints++;
      else helped++;
    });
    const mins = Math.round((timing.solvedMs || timing.activeMs || 0) / 60000);
    const bits = [`<strong>${total}</strong> clues`];
    if (noHints) bits.push(`<strong>${noHints}</strong> with no hint at all`);
    if (helped) bits.push(`<strong>${helped}</strong> with help (${levels} hint${levels === 1 ? "" : "s"})`);
    else bits.push("not one hint used");
    if (mins) bits.push(`<strong>${mins}</strong> minute${mins === 1 ? "" : "s"} at it`);
    parts.line.innerHTML = `<p class="shout">Finished — you completed the whole grid.</p>`
      + `<p class="tally">${bits.join(LIST_SEP)}</p>`
      + recapHTML()
      + voteRowHTML(voteTarget(null), "How was the puzzle?", "Enjoyed it", "Not really");
    wireVotes(parts.line, () => celebrate(true, false));
    // The box sits between the title and the grid, so where it is at the moment
    // the last letter goes in depends on where the page is: on a phone or a
    // narrow window the solver has scrolled down to the grid with the keyboard
    // up, and the box is off the TOP of the band; on a tablet the whole page
    // fits and the box is already on screen, so there is no travel at all.
    // Both are handled here, and neither is assumed: the placement scrolls only
    // when the box is outside the band, and fireBurst() waits for the box to be
    // seen rather than for a scroll that may never happen.
    // Only on the transition. Reopening a finished puzzle must not yank the page
    // around, for the same reason it does not throw fireworks.
    if (earned) { fireBurst(parts.burst, noHints === Object.keys(counted).length); scrollToHintPanel("celebrate", "celebrate"); }
  }

  // Where the burst is, in one word, on the element itself. Four outcomes would
  // otherwise leave pixel-identical nothing — never lit, burned while the box was
  // off screen, burned where someone was looking, thrown away unseen — so open
  // the box in an inspector and the class says which of the four happened.
  // "hold" is also what the stylesheet gates the animation on.
  //
  // Only "hold" and "lit" have anything in the air, so every other state empties
  // the shells out of the page rather than leaving them frozen at opacity 0 for
  // the next reader of the DOM to puzzle over.
  const BURST_STATES = ["hold", "lit", "spent", "missed"];
  const burstInFlight = (burst) =>
    burst.classList.contains("hold") || burst.classList.contains("lit");
  // One observer at a time, and only while a burst is actually waiting to be
  // seen. The .fireworks node is built once and reused by every finish in the
  // session, so an observer left watching it is still there when the next burst
  // arrives: finish enough puzzles without the box ever coming on screen and the
  // node collects one per finish, each firing on a burst that is not its own.
  // "hold" is the only state that is waiting for anything, so every other state
  // takes the watcher down with it — including the empty one, which is how
  // opening another puzzle stops watching for a burst that no longer exists.
  let burstWatch = null;
  function stopWatchingBurst() {
    if (burstWatch) { burstWatch.disconnect(); burstWatch = null; }
  }
  function burstState(burst, state) {
    BURST_STATES.forEach((c) => burst.classList.remove(c));
    if (state) burst.classList.add(state);
    if (state !== "hold") stopWatchingBurst();
    if (state !== "hold" && state !== "lit") burst.innerHTML = "";
  }

  // A firework nobody was looking at is not a firework. Sparks that started the
  // instant the markup was written would burn while the page was still
  // travelling to the box, and the scroll can eat most of the show.
  //
  // So the shells are written held, and the stylesheet gives a spark its
  // animation only once the hold comes off — not an animation paused at birth,
  // because a paused animation still has a start time and WebKit is under no
  // obligation to rewind it for us. No hold, no animation; hold off, a fresh
  // 0%. That is the only arrangement in which a burst held for a minute still
  // burns from the beginning when it is finally let go.
  //
  // Two things decide whether anyone ever sees them:
  //
  // How much of the box counts as seen: a sliver (the observer's threshold is
  // 0.01). A large fraction is a lot to ask at the one moment the on-screen
  // keyboard is up — the last letter of the puzzle has just been typed — and the
  // box could sit visibly on the screen and never trip the observer.
  //
  // What happens when it is never seen. A firework either goes off where
  // someone is looking or it does not go off: the observer keeps waiting, and
  // the long stop throws the shells away rather than burning them into an empty
  // screen, marked "missed" so the throwing-away is on the record.
  const FIREWORK_ABANDON_MS = 60000;
  // Ten shells, one after another, at spots spread across the box so it fills
  // rather than one patch flashing ten times. Fixed, not random, so the show is
  // the same every time and a test can count it.
  const SHELLS = [
    { x: 14, y: 30 }, { x: 50, y: 62 }, { x: 84, y: 26 }, { x: 32, y: 48 },
    { x: 68, y: 40 }, { x: 22, y: 70 }, { x: 58, y: 22 }, { x: 88, y: 64 },
    { x: 40, y: 32 }, { x: 74, y: 56 },
  ].map((sh, n) => ({ ...sh, delay: n * 0.32 }));
  // The last shell's delay, its 1.5s burn, and a beat. After this there is
  // nothing left to look at, so the shells come out of the page.
  const BURST_MS = Math.ceil((Math.max(...SHELLS.map((sh) => sh.delay)) + 1.5) * 1000) + 300;
  // Every timer this arms names the burst it belongs to. The node is reused —
  // clear a solved grid and solve it again and the same div holds the new
  // shells — so a minute-long abandon timer left over from the last burst would
  // otherwise land on this one and mark a burst that is happily in the air as
  // one nobody ever saw.
  let burstRun = 0;
  function fireBurst(burst, clean) {
    const run = ++burstRun;
    const mine = () => run === burstRun;
    // The last burst's watcher, if it is somehow still waiting: a burst that is
    // replaced was never seen, and nothing is owed to it.
    stopWatchingBurst();
    // The last letter leaves the phone's keyboard up over the show: drop it.
    const typing = document.activeElement;
    if (typing && typing !== document.body && typeof typing.blur === "function") typing.blur();
    burstState(burst, "hold");
    burst.innerHTML = shellsHTML();
    const go = () => {
      if (!mine() || !burst.classList.contains("hold")) return;
      burstState(burst, "lit");
      finishFireworks(clean);
      setTimeout(() => {
        if (mine() && burst.classList.contains("lit")) burstState(burst, "spent");
      }, BURST_MS);
    };
    if (typeof IntersectionObserver !== "function") return go();
    burstWatch = new IntersectionObserver((rows) => {
      if (rows.some((r) => r.isIntersecting)) go();
    }, { threshold: 0.01 });
    burstWatch.observe(burst);
    setTimeout(() => {
      if (mine() && burst.classList.contains("hold")) burstState(burst, "missed");
    }, FIREWORK_ABANDON_MS);
  }

  // Bursts that go off once, staggered across the box. Each spark carries the
  // vector it flies along as custom properties and one keyframe in style.css
  // flies all of them: the angles are computed here so the spread is even,
  // which is the difference between a firework and a handful of dots.
  // prefers-reduced-motion turns the whole thing off and leaves the sentence.
  function shellsHTML(sparks = 14) {
    const shells = SHELLS.map((sh) => {
      const bits = Array.from({ length: sparks }, (_, i) => {
        const a = (i / sparks) * Math.PI * 2;
        const r = 46 + (i % 3) * 14;
        return `<span class="spark" style="--dx:${(Math.cos(a) * r).toFixed(1)}px;` +
          `--dy:${(Math.sin(a) * r).toFixed(1)}px;` +
          `animation-delay:${sh.delay.toFixed(2)}s"></span>`;
      }).join("");
      return `<span class="shell" style="left:${sh.x}%;top:${sh.y}%">${bits}</span>`;
    }).join("");
    return shells;
  }

  function refreshAll() {
    refreshGrid();
    refreshClues();
    renderHintPanel();
    renderScore();
    nuxDraw();
    checkComplete();
    checkHalfFilled();
    syncClueUrl();
  }

  // The address bar follows the clue, so "look at 3 down" is a link.
  //
  // Driven from refreshAll rather than from selectEntry because a clue gets
  // chosen half a dozen ways — tapping a cell, the arrow keys, tab, the clue
  // list — and only one of them goes through selectEntry. Guarded on the ref
  // actually changing, because refreshAll also runs on every keystroke and
  // Safari rate-limits replaceState hard enough that a fast solver would hit
  // the ceiling and lose the lot.
  //
  // Only ever a refinement of a URL that already names a puzzle: the bare
  // site root has to stay the front door, for the reason spelled out
  // at the top of this section.
  let urlClue = null;
  function syncClueUrl() {
    const e = currentEntry();
    const ref = e && !jigsaw ? tag(e) : null;
    if (ref === urlClue) return;
    urlClue = ref;
    if (!urlNamesPuzzle || !ref || !meta || !meta.id) return;
    setAddress(shareUrl(meta.id, ref));
  }

