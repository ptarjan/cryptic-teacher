/* The building blocks formula says the letters, in brackets that group right.

     node tests/test_formula_fill.js

   Paul, on three clues of times-29692 (11-08):
     18A ADENOID   "A + DEN + ( anagram of ID + O ) the brackets seem wrong"
     18D ANTBEAR   "swap in Anthea + letter + letter ) + ( last letter of R ) The
                   math didn't put in the letters"
     14D IRON CROSS "why didn't they fill in definition (9) = IRON + ( anagram of
                   ( corps − 1 letter ) ) + ( first letter of S )"
   So: an op word binds to the one term after it, and a term of more than one
   piece is bracketed ("anagram of ( ID + O )"); a letter the clue supplies, the
   letters a cut drops and what each step makes are told as letters once the
   chips they go with are out ("CORPS − P → CORS"); a pick's chip shows the word
   picked from ("first letter of SEEK → S", never "first letter of S"); and the
   type rung's blank picture still says only roles and counts.

   The annotations are the views annotation.py makes of those three clues
   (tree trimmed to op / words / gives / yields), and the code is the app's own
   formulaOf and formulaHTML, lifted out of the source. */
"use strict";
const path = require("path");
const { appFormula, blank, mathFault } = require("./test_formula_math.js");
const SRC = require("../tools/app_src").read(path.join(__dirname, ".."));

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

// formulaHTML, with the panel state it reads stubbed: which pieces are out.
const from = SRC.indexOf("  function formulaHTML");
const to = SRC.indexOf("\n  // ---------- a building block that costs", from);
if (from < 0 || to < 0) throw new Error("app.js no longer holds formulaHTML");
let out = new Set();
const formulaHTML = new Function("esc", "groupSolved", "pieceOut", "armedFor", "ARMED_TEXT", "piecesLeft",
  SRC.slice(from, to) + "\nreturn formulaHTML;")(
  (s) => String(s), () => false, (e, i) => out.has(i), () => false, "armed", () => 1);
const text = (html) => html.replace(/<p[\s\S]*?<\/p>/g, "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
const render = (f, shown, interactive = true) => { out = new Set(shown); return text(formulaHTML({}, f, interactive)); };

const CLUES = {
  "14D IRON CROSS": {
    ann: { answer: "IRON CROSS", type: ["deletion", "anagram", "letter_selection", "charade"], definitions: [{ text: "medal" }],
      blocks: [{ clueFragment: "Press", gives: "IRON", note: "to iron is to press clothes" }, { clueFragment: "corps", gives: "CORPS" },
        { clueFragment: "seek", gives: "S", select: "first", note: "first letter" }],
      wordplay: { op: "charade", parts: [{ words: "Press", gives: "IRON" },
        { op: "anagram", yields: "CROS", parts: [{ op: "deletion", yields: "CORS", parts: [{ words: "corps" }, { gives: "P" }] }] },
        { op: "first", yields: "S", parts: [{ words: "seek" }] }] },
      assembly: { pieces: ["IRON", "CROS", "S"], anagrams: [{ fodder: "CORS", gives: "CROS" }] } },
    full: "definition (9) = IRON + ( anagram of ( CORPS − P → CORS ) → CROS ) + ( first letter of SEEK → S )",
    blank: "definition (9) = synonym 4 + anagram of ( as written 5 − 1 letter ) + first letter of selection 1",
    // corps alone out: the cut and what it leaves are told; the anagram's solve waits for every piece.
    some: [[1], "definition (9) = synonym 4 + anagram of ( CORPS − P → CORS ) + first letter of selection 1"],
  },
  "18A ADENOID": {
    ann: { answer: "ADENOID", type: ["anagram", "charade"], definitions: [{ text: "regarding biological tissue" }],
      blocks: [{ clueFragment: "American", gives: "A", note: "A is a standard abbreviation for american" },
        { clueFragment: "study", gives: "DEN", note: "a den is a private study" },
        { clueFragment: "papers", gives: "ID", note: "ID is identity papers" },
        { clueFragment: "over", gives: "O", note: "O is the cricket abbreviation for an over" }],
      wordplay: { op: "charade", parts: [{ words: "American", gives: "A" }, { words: "study", gives: "DEN" },
        { op: "anagram", yields: "OID", parts: [{ words: "papers", gives: "ID" }, { words: "over", gives: "O" }] }] },
      assembly: { pieces: ["A", "DEN", "OID"], anagrams: [{ fodder: "IDO", gives: "OID" }] } },
    full: "definition (7) = A + DEN + ( anagram of ( ID + O ) → OID )",
    blank: "definition (7) = abbreviation 1 + synonym 3 + anagram of ( synonym 2 + abbreviation 1 )",
    some: [[2, 3], "definition (7) = abbreviation 1 + synonym 3 + anagram of ( ID + O )"],
  },
  "18D ANTBEAR": {
    ann: { answer: "ANTBEAR", type: ["substitution", "letter_selection", "charade"], definitions: [{ text: "Voracious eater with big nose" }],
      blocks: [{ clueFragment: "Anthea", gives: "ANTHEA" }, { clueFragment: "Turner", gives: "R", select: "last", note: "last letter" }],
      wordplay: { op: "charade", parts: [
        { op: "substitution", yields: "ANTBEA", parts: [{ words: "Anthea" }, { gives: "H" }, { gives: "B" }] },
        { op: "last", yields: "R", parts: [{ words: "Turner" }] }] },
      assembly: { pieces: ["ANTBEA", "R"] } },
    full: "definition (7) = ( ANTHEA with B for H → ANTBEA ) + ( last letter of TURNER → R )",
    blank: "definition (7) = ( as written 6 with letter for letter ) + last letter of selection 1",
    some: [[0], "definition (7) = ( ANTHEA with B for H → ANTBEA ) + last letter of selection 1"],
  },
};

const balanced = (s) => {
  let d = 0;
  for (const c of s) { d += c === "(" ? 1 : c === ")" ? -1 : 0; if (d < 0) return false; }
  return d === 0;
};

for (const [name, c] of Object.entries(CLUES)) {
  const blocks = appFormula.buildingBlocks(c.ann);
  const f = appFormula.formulaOf(c.ann, blocks);
  const all = blocks.map((_, i) => i);
  const full = render(f, all);
  check(full === c.full, `${name} filled: ${full}`);
  check(balanced(full) && !/\bletters?\b(?! of)/.test(full), `${name} filled: brackets balance and no placeholder "letter"`);
  const pic = render(f, [], false);
  check(pic === c.blank, `${name} type rung picture: ${pic}`);
  check(render(f, []) === c.blank, `${name} blocks rung, nothing out: the same blank picture`);
  const some = render(f, c.some[0]);
  check(some === c.some[1], `${name} pieces ${c.some[0]} out: ${some}`);
  // The count arithmetic test_formula_math.js holds the corpus to still reads it.
  check(!mathFault(c.ann), `${name}: the blank picture adds up to the answer's length`);
  check(blank(f.parts).every((p) => typeof p === "number" || typeof p === "string"), `${name}: blank() leaves chips and words only`);
}

// A step filed unchecked keeps its op word and its parts, no claims about roles:
// "swap in ( RAN + DO + MIRROR )", not "RAN with MIRROR for DO".
{
  const ann = { answer: "RANDOM ERROR", type: ["substitution"], definitions: [{ text: "x" }],
    blocks: [{ clueFragment: "organised", gives: "RAN" }, { clueFragment: "party", gives: "DO" }, { clueFragment: "tabloid", gives: "MIRROR" }],
    wordplay: { op: "substitution", unchecked: true, gives: "RANDOMERROR",
      parts: [{ words: "organised", gives: "RAN" }, { words: "party", gives: "DO" }, { words: "tabloid", gives: "MIRROR" }] } };
  const f = appFormula.formulaOf(ann, appFormula.buildingBlocks(ann));
  const full = render(f, [0, 1, 2]);
  check(full === "definition (11) = swap in ( RAN + DO + MIRROR )", `unchecked substitution: ${full}`);
}

console.log(failures ? `${failures} failed` : "all ok");
process.exit(failures ? 1 : 0);
