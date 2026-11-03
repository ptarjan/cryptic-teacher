// The search suggestions and the paper and difficulty menus.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { FULL, allPuzzles, allReprints, assert, chooseIn, choosePaper, inSlice, pickerRows, registry,
  typeInPicker } = T;
// --- the search suggests the words, and every one of them finds something ---
// The numbers are easy to type and too many to list; the setters are the
// opposite on both counts, which is what the dropdown is for. A suggestion that
// returns an empty list would be worse than none, so each one is typed in.
//
// And it stays SHUT until two letters are in. A list offered up front hides the
// puzzles it is there to search.
//
// Read off the chips in the panel, not off a datalist: a datalist popup is
// native UI the page cannot place — on iPad it opens nowhere near the box.
// Asserting on chips is also the only way a test can see WHERE the suggestions
// are.
{
  const suggestions = () =>
    [...registry["picker-filters"].innerHTML.matchAll(/class="badge term"[^>]*>([^<]*)</g)]
      .map((m) => m[1]);
  registry["btn-picker"].onclick();
  assert(suggestions().length === 0,
    "focusing the search offers nothing, so nothing is drawn over the list: "
      + suggestions().join(" "));
  typeInPicker("e");
  assert(suggestions().length === 0,
    "nor does one letter, which matches most of the vocabulary: " + suggestions().join(" "));

  // Probed with the openings of the words themselves, taken from the index, so
  // this cannot pass by suggesting a vocabulary the rows do not have.
  const openings = new Set();
  (window.CRYPTIC_INDEX.puzzles || []).forEach((p) => {
    if (p.setter && p.setter.length >= 2) openings.add(p.setter.slice(0, 2).toLowerCase());
  });
  // Every distinct opening in CI. Locally a fixed slice of them, because each
  // probe re-filters every row and the rule under test — a suggestion
  // that finds nothing is worse than no suggestion — is about one probe at a
  // time, so the hundredth setter is re-proving what the first proved.
  const probes = new Set(["so", "un"].concat(
    FULL ? [...openings].filter(inSlice) : [...openings].sort().slice(0, 12)));
  const offered = new Set();
  probes.forEach((q) => {
    typeInPicker(q);
    const opts = suggestions();
    assert(opts.length > 0, `"${q}" completes to something`);
    // There is no cap in app.js on how many completions a query can return —
    // pickerSuggestTerms() just filters the whole vocabulary and hands it all
    // back — so no count is asserted. What IS real and worth protecting:
    // every offered term actually completes what was typed, case
    // insensitively, and none of them repeats.
    opts.forEach((t) => assert(t.toLowerCase().includes(q),
      `"${t}" was offered for "${q}", so it must actually contain it: ` + opts.join(" ")));
    assert(new Set(opts).size === opts.length,
      `"${q}"'s completions are not offered twice: ` + opts.join(" "));
    opts.forEach((t) => offered.add(t));
  });
  assert(offered.size >= 5, "the search offers something to complete: " + offered.size);
  assert(![...offered].some((t) => /^\d+$/.test(t)),
    "and not the numbers, which would bury every word in the list: " + [...offered].join(" "));
  ["solved", "unfinished"].forEach((t) => assert(offered.has(t),
    `"${t}" is offered, because it is a filter and not just a thing to read: `
      + [...offered].join(" ")));
  offered.forEach((t) => {
    typeInPicker(t);
    assert(registry["picker-list"].children.length > 0,
      `the search suggests "${t}" and "${t}" finds puzzles`);
  });
  typeInPicker("");
  registry["btn-picker-close"].onclick();
}

// --- the paper and difficulty menus: every paper, grouped by group ---
// Every series in the index is an option, under its group from the index's
// own `groups` table, and a group with two or more series has an "All"
// option at its head. An option's value is the series keys it
// stands for, so choosing one filters on the key and never on the paper's name:
// "times" is a word inside "times quick" and "sunday times", and choosing the
// Times must list the Times alone.
{
  registry["btn-picker"].onclick();
  const menu = registry["picker-paper"].innerHTML;
  const papers = window.CRYPTIC_INDEX.groups || {};
  const n = {};
  // A paper's count is its own puzzles plus the reprints it printed.
  [...allPuzzles, ...allReprints].forEach((p) => { n[p.series] = (n[p.series] || 0) + 1; });
  assert(Object.keys(n).every((s) => s in papers),
    "index.json's `groups` names every series in the index");
  // A Sunday sister paper files under its weekday paper, not "Other papers".
  [["sundaytimes", "Times"], ["everyman", "Guardian"]].forEach(([s, g]) => {
    if (n[s]) assert(papers[s] === g, `${s} is in the ${g} group: ${papers[s]}`);
  });
  const groups = [...menu.matchAll(/<optgroup label="([^"]*)">([\s\S]*?)<\/optgroup>/g)]
    .map((m) => ({ label: m[1].replace(/&amp;/g, "&"),
                   values: [...m[2].matchAll(/value="([^"]*)"/g)].map((v) => v[1]) }));
  const single = groups.flatMap((g) => g.values).filter((v) => !v.includes(","));
  assert(single.slice().sort().join() === Object.keys(n).sort().join(),
    `every series in the index is one option in the paper menu, once: ${single.join(" ")}`);
  const byPub = {};
  Object.keys(n).forEach((s) => { (byPub[papers[s] || ""] = byPub[papers[s] || ""] || []).push(s); });
  Object.keys(byPub).filter((pub) => pub && byPub[pub].length > 1).forEach((pub) => {
    const g = groups.find((x) => x.label === pub);
    if (!assert(g, `${pub} prints ${byPub[pub].join(", ")}, so it has a group of its own`)) return;
    assert(g.values[0].split(",").sort().join() === byPub[pub].sort().join(),
      `${pub}'s group opens with an "All" option for exactly its series: ${g.values[0]}`);
    assert(g.values.slice(1).sort().join() === byPub[pub].sort().join(),
      `and then lists each of them: ${g.values.join(" ")}`);
  });

  // Each option matches exactly its own series' puzzles. Counted off the line
  // under the list (drawn + "more match"), which the chunking test above holds
  // to the scrolled truth, so no option has to be scrolled to its end here.
  const matched = () => pickerRows().length
    + Number((/(\d+) more match/.exec(registry["picker-more"].innerHTML) || [0, 0])[1]);
  groups.flatMap((g) => g.values).forEach((v) => {
    choosePaper(v);
    const want = v.split(",").reduce((t, k) => t + n[k], 0);
    assert(matched() === want, `choosing "${v}" matches its ${want} puzzles and reprints: ${matched()}`);
  });
  // The mirror of the name-matching bug: the Times option is the Times alone,
  // though "times" is inside the name of every Times paper.
  if (n.times && (n.timesquick || n.sundaytimes)) {
    choosePaper("times");
    assert(matched() === n.times && pickerRows().every((li) => /badge series[^>]*>times</.test(li.children[0].innerHTML)),
      `choosing the Times lists its ${n.times} alone, not every paper with "times" in its name: ${matched()}`);
  }

  // The bands, easiest first, off the percentiles.
  const at = {};
  allPuzzles.forEach((p) => {
    const d = p.difficulty;
    if (!d || !d.band || d.percentile === null || d.percentile === undefined) return;
    const b = d.band.toLowerCase();
    if (at[b] === undefined || d.percentile < at[b]) at[b] = d.percentile;
  });
  const bands = Object.keys(at).sort((a, b) => at[a] - at[b]);
  const bandMenu = [...registry["picker-band"].innerHTML.matchAll(/value="([^"]*)"/g)].map((m) => m[1]);
  assert(bandMenu.join(" ") === " " + bands.join(" "),
    `the difficulty menu is "any" then every band, easiest first: ${bandMenu.join("|")}`);

  // --- and they combine, with each other and with the box ---
  // "I can choose Everyman brutal": the paper and the band intersect, and a
  // typed term narrows that further rather than replacing it.
  const biggest = Object.keys(n).sort((a, b) => n[b] - n[a])[0];
  const band = bands.find((b) => allPuzzles.some((p) => p.series === biggest
    && p.difficulty && p.difficulty.band.toLowerCase() === b));
  if (assert(band, `some band has ${biggest} puzzles`)) {
    choosePaper(biggest);
    chooseIn("picker-band", band);
    const both = allPuzzles.filter((p) => p.series === biggest
      && p.difficulty && p.difficulty.band.toLowerCase() === band).length;
    assert(matched() === both,
      `${biggest} + ${band} matches the ${both} puzzles that are both: ${matched()}`);
    assert(registry["picker-paper"].classList.contains("on"),
      "a menu set to anything but all is marked as a filter in force");
    const one = allPuzzles.find((p) => p.series === biggest && p.date !== undefined
      && p.difficulty && p.difficulty.band.toLowerCase() === band);
    if (one) {
      const day = one.date;
      typeInPicker(day);
      assert(matched() > 0 && matched() <= both,
        `typing "${day}" narrows the chosen paper and band: ${matched()} of ${both}`);
    }
    // Closing and reopening the picker keeps the menus as they were chosen.
    registry["btn-picker-close"].onclick();
    registry["btn-picker"].onclick();
    assert(registry["picker-paper"].value === biggest && registry["picker-band"].value === band,
      `the menus keep their choice across a close and reopen: ${registry["picker-paper"].value}|${registry["picker-band"].value}`);
    choosePaper("");
    chooseIn("picker-band", "");
  }
  typeInPicker("");
  registry["btn-picker-close"].onclick();
}
