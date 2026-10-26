/* The word chips under a clue and the highlights in its heading cut a
   hyphenated word at the same places: a compound is one chip ("Drug-free")
   unless an annotation fragment starts or ends at its hyphen (the indicator
   "free" in "Drug-free period"), and then both are cut there. Reads clueTokens
   and clueCuts out of app.js, so it cannot drift from the app.

     node tests/test_clue_tokens.js */
"use strict";
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
const from = src.indexOf("function clueTokens");
const to = src.indexOf("const tokensOfClue", from);
let frags = [];
const { clueTokens, clueCuts } = new Function("placedFragments",
  src.slice(from, to) + "\nreturn { clueTokens, clueCuts };")(() => frags);

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const words = (t, f) => { frags = f || []; return clueTokens(t, clueCuts({})).map((x) => x.text).join("|"); };
const at = (t, s) => ({ i: t.indexOf(s), text: s });

const T = "Drug-free period, end of well-known Post–match";
check(words(T) === "Drug-free|period,|end|of|well-known|Post–match", "no fragment splits a compound: " + words(T));
check(words(T, [at(T, "free")]).startsWith("Drug-|free|period,"), "indicator 'free' cuts Drug-free after the hyphen: " + words(T, [at(T, "free")]));
check(words(T, [at(T, "Drug-free")]).startsWith("Drug-free|period,"), "a fragment naming the whole compound keeps it whole");
check(words(T, [at(T, "well-known")]).includes("|well-known|"), "a whole compound elsewhere stays whole");
check(words(T, [at(T, "Post"), at(T, "match")]).endsWith("|Post–|match"), "en-dashed compound cuts the same way: " + words(T, [at(T, "Post"), at(T, "match")]));
const C = "Clock-maker's tools";
check(words(C, [at(C, "Clock-maker")]) === "Clock-maker's|tools", "apostrophe'd compound is one word when the fragment is the compound");
{
  const t = "Drug-free period";
  frags = [at(t, "free")];
  const edges = new Set(clueTokens(t, clueCuts({})).flatMap((x) => [x.i, x.i + x.text.length]));
  check(edges.has(frags[0].i) && edges.has(frags[0].i + 4), "both edges of 'free' are chip edges");
}
process.exit(failures ? 1 : 0);
