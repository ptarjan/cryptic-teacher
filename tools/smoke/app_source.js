// Pieces of the app read out of its source and exercised on their own.
// Part of tools/smoke_test.js: required in order, on the harness' shared object.
"use strict";
const T = require("./harness");
const { ROOT, assert, htmlEsc, stripTags } = T;
// Which blocks are building blocks and what each shows, read out of app.js, so
// the test and the app cannot disagree about which piece is which.
const APP_BLOCKS = (() => {
  const src = require("../app_src").read(ROOT);
  const from = src.indexOf("function wholeWord");
  const end = src.indexOf("const buildingBlocks", from);
  const to = src.indexOf("\n", end);
  assert(from > 0 && end > from, "blockLetters, senseBlock and buildingBlocks are still in app.js to be read");
  return new Function(src.slice(from, to) + "\n  return { blockLetters, senseBlock, buildingBlocks };")();
})();
// A count in words stays in the clue's text as printed ("(11, two words)",
// tools/enumeration.py WORDED), and it is still the enumeration, so it is never
// a word to tap: a wrong-definition tap on "words)" graded a count as a clue word.
{
  const src = require("../app_src").read(ROOT);
  const from = src.indexOf("function clueTokens");
  const to = src.indexOf("\n  }\n", from) + 4;
  const clueTokens = new Function(src.slice(from, to) + "\nreturn clueTokens;")();
  const words = (t) => clueTokens(t).map((x) => x.text).join("|");
  assert(words("Scotch to bear including permit (11, two words)") === "Scotch|to|bear|including|permit",
    "a trailing count in words is not a pickable word: " + words("Scotch to bear including permit (11, two words)"));
  assert(words("Bar (two words) at sea") === "Bar|(two|words)|at|sea",
    "and words in brackets mid-clue still are: " + words("Bar (two words) at sea"));
}
// A definition that ends the clue is at the end even with a "?" after it: the
// definition rung called "disconnect" in "Can everyone initially disconnect?"
// mid-clue, with "?" quoted as the wordplay after it.
{
  const src = require("../app_src").read(ROOT);
  const from = src.indexOf("function defPlace");
  const to = src.indexOf("\n  }\n", from) + 4;
  const defPlace = new Function("cpToIdx", "esc", src.slice(from, to) + "\nreturn defPlace;")((s, n) => n, (s) => s);
  const said = defPlace("Can everyone initially disconnect?", { text: "disconnect", at: 23 }, []);
  assert(/right at the end/.test(said), "a definition before a closing ? ends the clue: " + said);
}
// A definition's optional end word is optional with punctuation stuck to it:
// a token is split on spaces, so the definition quoted in azed-2344 25d ends on
// "in'", and the closing quote made "in" a word that carries meaning. Every
// mark a definition can sit inside or after is checked here, not the corpus
// sweep below, which only finds a quoted case when a sample happens to hold one.
{
  const src = require("../app_src").read(ROOT);
  const from = src.indexOf("const EDGE_WORDS");
  const to = src.indexOf("\n  }\n", src.indexOf("function edgeTokens", from)) + 4;
  const edgeTokens = new Function(src.slice(from, to) + "\nreturn edgeTokens;")();
  const edges = (clue, def) => {
    const toks = clue.split(/\s+/).map((text) => ({ text }));
    const start = clue.indexOf(def);
    const first = clue.slice(0, start).split(/\s+/).filter(Boolean).length
      - (/\S$/.test(clue.slice(0, start)) ? 1 : 0);
    const span = toks.map((_, n) => n).slice(first, first + def.split(/\s+/).length);
    return edgeTokens(span, toks).map((n) => toks[n].text).sort().join("|");
  };
  const cases = [
    ["A label stuck in middle of cheese: 'It's right to tuck in'", "It's right to tuck in", "in'"],
    ["A label stuck in middle of cheese: ‘It’s right to tuck in’", "It’s right to tuck in", "in’"],
    ["Cheese: \"right to tuck in\"!", "right to tuck in", "in\"!"],
    ["Cheese (right to tuck in)", "right to tuck in", "in)"],
    ["'The right to tuck' cheese", "The right to tuck", "'The"],
    ["Cheese, (the right to tuck in.)", "the right to tuck in", "(the|in.)"],
  ];
  for (const [clue, def, want] of cases) {
    assert(edges(clue, def) === want,
      `the optional ends of "${def}" in ${clue} are ${want}: ${edges(clue, def)}`);
  }
  // A word's own apostrophe still counts: "it's" is not the edge word "its".
  assert(edges("Cheese right it's", "right it's") === "",
    "an apostrophe inside a word keeps it a word that carries meaning: " + edges("Cheese right it's", "right it's"));
}
// The walkthrough rung steps through the wordplay tree: each indicator named,
// each intermediate result shown (worked out from the siblings when the tree
// does not store it), and a liberty named when an indicator is not next to its
// fodder. Fixtures are the three clues Paul could not follow.
{
  const src = require("../app_src").read(ROOT);
  const from = src.indexOf("const WP_FUNCTION_WORDS");
  const to = src.indexOf("\n  // \"Entered as SAPIR", from);
  assert(from > 0 && to > from, "wordplaySteps is still in app.js to be read");
  const wordplaySteps = new Function("esc", "escClue", "LIST_SEP", src.slice(from, to) + "\nreturn wordplaySteps;")(htmlEsc, htmlEsc, " · ");
  const text = (h) => stripTags(h, "").replace(/&#39;/g, "'").replace(/&amp;/g, "&");
  const dominate = wordplaySteps({ op: "container",
    indicators: [{ text: "getting into", at: 13, note: "getting into says the jumbled letters enter the building" }],
    parts: [{ words: "13 millennium 11", at: 26, gives: "DOME", note: "the naff Millennium project was the Dome" },
      { op: "anagram", indicators: [{ text: "Wildly", at: 0, note: "wildly says the letters are thrown about" }],
        parts: [{ words: "anti", at: 7, note: "taken as written" }] }] },
    "DOMINATE", "Wildly anti, getting into 13 millennium 11? That's 8", []);
  const dom = dominate.lines.map(text);
  assert(dom.length === 3, "DOMINATE shows DOME, the anagram and the container: " + dom.join(" | "));
  assert(/→ DOME/.test(dom[0]), "DOMINATE: the 13 millennium 11 piece gives DOME: " + dom[0]);
  assert(/Wildly — rearrange the letters of ANTI → INAT/.test(dom[1]),
    "DOMINATE: the anagram node gets its derived result INAT: " + dom[1]);
  assert(/getting into — put INAT inside DOME → DOMINATE/.test(dom[2]),
    "DOMINATE: INAT goes inside DOME: " + dom[2]);
  assert(dominate.liberties.length === 0, "DOMINATE takes no liberty: " + dominate.liberties);

  const enthral = wordplaySteps({ op: "charade", parts: [
    { op: "deletion", indicators: [{ text: "non", at: 10, note: "non says the standard is absent" }],
      parts: [{ words: "parent", at: 23 }, { words: "standard", at: 14, gives: "PAR", note: "par is the standard score" }] },
    { words: "time", at: 35, gives: "HR", note: "hr is the abbreviation for hour" },
    { words: "other things", at: 44, gives: "AL", note: "al. is short for alia" }] },
    "ENTHRAL", "Fascinate non-standard parent with time for other things", []);
  const ent = enthral.lines.map(text);
  assert(ent.some((l) => /“time” → HR/.test(l)) && ent.some((l) => /“other things” → AL/.test(l)),
    "ENTHRAL names HR (time) and AL (other things): " + ent.join(" | "));
  assert(ent.some((l) => /non — take PAR out of PARENT → ENT/.test(l)), "ENTHRAL: the deletion leaves ENT: " + ent.join(" | "));
  assert(/join ENT \+ HR \+ AL in order → ENTHRAL/.test(ent[ent.length - 1]), "ENTHRAL ends joining the pieces into the answer: " + ent[ent.length - 1]);

  const ewe = wordplaySteps({ op: "anagram", indicators: [{ text: "may come to", at: 13, note: "letters that come to another word become it once rearranged" }],
    parts: [{ words: "wee", at: 4, note: "taken as written" }] }, "EWE", "The wee lamb may come to this.", []);
  assert(ewe.lines.length === 1 && /may come to — rearrange the letters of WEE → EWE/.test(text(ewe.lines[0])),
    "EWE names the indicator may come to: " + ewe.lines.map(text));
  assert(ewe.liberties.length === 1 &&
    ewe.liberties[0] === "This clue takes a liberty: 'may come to' isn't next to its fodder (it is separated by 'lamb').",
    "times-8 56d takes the liberty of an indicator apart from its fodder: " + ewe.liberties);
  // A joining word in the gap is no liberty, and an insertion that fits two ways shows no guessed result.
  const near = wordplaySteps({ op: "anagram", indicators: [{ text: "wild", at: 0 }],
    parts: [{ words: "wee", at: 8 }] }, "EWE", "wild is wee", []);
  assert(near.liberties.length === 0, "a joining word between indicator and fodder is no liberty: " + near.liberties);
  const twice = wordplaySteps({ op: "container", indicators: [{ text: "in", at: 5 }],
    parts: [{ words: "abab", at: 0, gives: "ABAB" }, { op: "anagram", indicators: [{ text: "odd", at: 8 }], parts: [{ words: "ab", at: 12 }] }] },
    "ABABAB", "abab in odd ab", []);
  assert(!/→/.test(text(twice.lines[0])), "an insertion that fits two ways shows no guessed result: " + twice.lines.map(text).join(" | "));
}

Object.assign(T, { APP_BLOCKS });
