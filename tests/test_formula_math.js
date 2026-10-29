/* The type rung's formula skeleton adds up, on every annotated clue.

   formulaOf (app.js) draws the answer as chips joined by operations:
   "definition (5) = hidden in as written 9 + as written 4". Each chip carries
   its letter count, so the line is arithmetic a solver can check, and Paul
   reported one that was not: a 9 and a 4 "added" to make a 5, the operation
   that takes letters out dropped. This evaluates every clue's formula as
   arithmetic over letter counts — what each operation can do to the count of
   what it is applied to — and fails on any whose answer length it cannot reach.

   An operation that keeps the count (anagram, reversal) keeps it; one that
   picks letters out (hidden, first letter, a cut of "some letters") gives
   anything from one letter to all of them; a sound, a swap or an unnamed
   operation could give any count, so it never fails a clue. A chip with no
   count (its piece gives nothing) makes the line unknowable, and it is skipped.

   Usage: node tests/test_formula_math.js [--list] [--out redo.json]
   (--list prints every failure; --out writes the bad-data clues as re-annotation rows) */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const SRC = fs.readFileSync(path.join(ROOT, "app.js"), "utf8");

// formulaOf and the helpers it calls, lifted out of app.js by source range so
// the check runs the app's own code, never a copy of it.
function region(fromMark, toMark) {
  const from = SRC.indexOf(fromMark);
  const to = SRC.indexOf(toMark, from);
  if (from < 0 || to <= from) throw new Error(`app.js no longer holds ${fromMark} … ${toMark}`);
  return SRC.slice(from, to);
}
function lineAt(mark) {
  const from = SRC.indexOf(mark);
  if (from < 0) throw new Error(`app.js no longer holds ${mark}`);
  return SRC.slice(from, SRC.indexOf("\n", from));
}
const appFormula = new Function("esc", "escClue", "LIST_SEP", [
  lineAt("const letterCount = "),
  region("function maskAnswer", "\n  // The letters a block may show"),
  region("function wholeWord", "\n  const senseBlocks = "),
  region("const WP_FUNCTION_WORDS", "\n  // \"Entered as SAPIR"),
  region("function formulaOf", "\n  // Build the rungs this particular clue deserves."),
  "return { formulaOf, buildingBlocks, letterCount };",
].join("\n"))((s) => String(s), (s) => String(s), " · ");

// The answer a clue's tree builds: alteration.from where the grid holds an altered
// entry (annOf in app.js merges `alteration` and `entered` in), else the answer.
const built = (ann) => (ann.alteration && ann.alteration.from) || ann.answer;
const INF = Infinity;
// What an operation word does to the letter count [lo, hi] of what follows it.
const KEEP = new Set(["anagram of", "reversal of", "cycled", "moved letters of", "palindrome of"]);
const PICK = new Set(["hidden in", "first letter of", "last letter of", "middle of", "outer letters of",
  "alternate letters of", "regular letters of", "selection from"]);
const opRange = (word, [lo, hi]) => {
  if (KEEP.has(word)) return [lo, hi];
  if (PICK.has(word)) return [Math.min(1, lo), hi];
  return [0, INF];
};
// The letters a cut phrase ("− last letter", "− 2 from the front and 1 from the back") takes.
const cutRange = (s) => {
  if (/some letters/.test(s)) return [1, INF];
  const m = /^− (\d+) from the front and (\d+) from the back$/.exec(s);
  if (m) return [+m[1] + +m[2], +m[1] + +m[2]];
  if (/^− first and last letters$/.test(s)) return [2, 2];
  const n = /^− (?:(\d+) )?[a-z ]*letters?$/.exec(s);
  if (n) return n[1] ? [+n[1], +n[1]] : [1, 1];
  return null;
};
const TERM_LETTERS = /^(?:(\d+) )?letters?$/;

// [lo, hi] for a formula's parts, or null when a chip has no count.
function evaluate(parts, counts) {
  let i = 0;
  const seq = () => {
    let lead = null;
    const t0 = parts[i];
    if (typeof t0 === "string" && !["(", ")", "+", "−", "inside", "with", "moved", "and"].includes(t0) && !t0.startsWith("− ") && !TERM_LETTERS.test(t0)) {
      lead = t0; i++;
    }
    let acc = term();
    if (!acc) return null;
    while (i < parts.length && parts[i] !== ")") {
      const sep = parts[i];
      if (typeof sep === "string" && sep.startsWith("− ")) {
        i++;
        const c = cutRange(sep);
        if (!c) return null;
        acc = [Math.max(0, acc[0] - c[1]), acc[1] - c[0]];
        continue;
      }
      i++;
      const b = term();
      if (!b) return null;
      // "A with B moved": B's letters are A's own, so the count stays A's.
      if (sep === "with" && parts[i] === "moved") { i++; continue; }
      if (sep === "+" || sep === "inside" || sep === "and") acc = [acc[0] + b[0], acc[1] + b[1]];
      else if (sep === "−") acc = [Math.max(0, acc[0] - b[1]), acc[1] - b[0]];
      else return null;
    }
    // A pick from a pick ("middle of (middle of selection 2)", a word stripped twice): the chip
    // counts the innermost pick's letters, which the outer pick does not bound.
    if (lead && PICK.has(lead) && acc.picked) return Object.assign([Math.min(1, acc[0]), INF], { picked: true });
    const got = lead ? opRange(lead, acc) : acc;
    return lead && PICK.has(lead) ? Object.assign([...got], { picked: true }) : got;
  };
  const term = () => {
    const t = parts[i++];
    if (typeof t === "number") return counts[t] ? [counts[t], counts[t]] : null;
    if (t === "(") {
      const r = seq();
      if (parts[i++] !== ")") return null;
      return r;
    }
    const m = typeof t === "string" && TERM_LETTERS.exec(t);
    if (m) return [m[1] ? +m[1] : 1, m[1] ? +m[1] : 1];
    return null;
  };
  const r = seq();
  return i === parts.length ? r : null;
}

// The words of a formula as the rung prints them, for messages.
const formulaText = (f) => `${f.lead} ${f.parts.map((p) => (typeof p === "number" ? f.chips[p] : p)).join(" ")}`;

// Why a clue's formula does not add up, or null when it does (or cannot be told).
function mathFault(ann) {
  if (!ann || !ann.answer) return null;
  const blocks = appFormula.buildingBlocks(ann);
  if (!blocks.length) return null;
  const f = appFormula.formulaOf(ann, blocks);
  const counts = blocks.map((b) => appFormula.letterCount(b.gives));
  if (counts.some((n) => !n)) return null;
  const want = appFormula.letterCount(built(ann));
  // A word masked because it is the answer ("inside" for LOOK INSIDE) is no
  // operation this can read; the line is left untold rather than called wrong.
  if (f.parts.some((p) => typeof p === "string" && p.includes("\u2026"))) return null;
  const r = evaluate(f.parts, counts);
  if (!r) return { text: formulaText(f), why: "unreadable" };
  if (want < r[0] || want > r[1]) return { text: formulaText(f), why: `${r[0]}..${r[1]}` };
  return null;
}

// Every puzzle the app can open, as the app gets it: the generated shims
// (puzzles/<id>.js, built by fetch_puzzle.py --reindex) hold each clue's view,
// blocks included, which the stored puzzle files do not.
function* puzzles() {
  const dir = path.join(ROOT, "puzzles");
  const names = fs.readdirSync(dir).filter((n) => /^[a-z0-9]+-[^/]*\.js$/i.test(n));
  if (!names.length) throw new Error("no puzzle shims in puzzles/: run python3 tools/fetch_puzzle.py --reindex");
  for (const n of names) {
    const window = { CRYPTIC_PUZZLES: {} };
    new Function("window", fs.readFileSync(path.join(dir, n), "utf8"))(window);
    yield* Object.values(window.CRYPTIC_PUZZLES);
  }
}

// Whether a tree holds a step filed without being checked (`unchecked`): its
// pieces need not make the answer at all, so its formula cannot add up. Those
// are the annotation's fault, listed for re-annotation, not the formula's.
const unchecked = (n) => !!n && (!!n.unchecked || (n.parts || []).some(unchecked));

// The letter count [lo, hi] the wordplay tree itself can give, read off the
// tree and the blocks, not the formula. When it cannot reach the answer's
// length the tree does not build the answer (a themed grid that adds a letter
// to every answer, a misread grid answer): bad data for re-annotation, which
// no formula can make add up, so it is reported and never fails the check.
const SELECTS = new Set(["first", "last", "middle", "outer", "alternate", "regular", "nth", "hidden"]);
const SUMS = new Set(["charade", "container", "anagram", "reversal", "cycling", "palindrome"]);
function treeRange(n, blocks) {
  const count = (s) => appFormula.letterCount(s);
  if (!n) return [0, INF];
  if (!n.op) {
    if (typeof n.gives === "string") return [count(n.gives), count(n.gives)];
    return "words" in n ? [count(n.words), count(n.words)] : [0, INF];
  }
  if (typeof n.gives === "string") return [count(n.gives), count(n.gives)];
  const parts = n.parts || [];
  const kids = parts.map((p) => treeRange(p, blocks));
  const sum = (ks) => ks.reduce((t, k) => [t[0] + k[0], t[1] + k[1]], [0, 0]);
  if (SUMS.has(n.op)) return sum(kids);
  if (n.op === "move") return kids[0] || [0, INF];
  if ((n.op === "deletion" || n.op === "composite") && kids.length > 1) {
    const w = kids[0], c = sum(kids.slice(1));
    return [Math.max(0, w[0] - c[1]), w[1] - c[0]];
  }
  if (SELECTS.has(n.op)) {
    // A pick from clue phrases is their blocks, which hold the letters picked.
    const picked = parts.map((leaf) => !leaf.op &&
      blocks.find((x) => x.clueFragment === leaf.words && x.gives && (x.select || n.op === "hidden")));
    if (parts.length && picked.every(Boolean)) {
      const k = picked.reduce((t, b) => t + count(b.gives), 0);
      return [k, k];
    }
    const s = sum(kids);
    // a pick of a pick: the inner pick's letters do not bound the outer one's (see evaluate)
    return [Math.min(1, s[0]), parts.some((q) => SELECTS.has(q.op)) ? INF : s[1]];
  }
  return [0, INF];
}
const treeMissesAnswer = (ann) => {
  const r = treeRange(ann.wordplay, ann.blocks || []);
  const want = appFormula.letterCount(built(ann));
  return want < r[0] || want > r[1];
};

// Paul's report (azed-2081 7A): a composite anagram drawn as "9 + 4" for a 5.
function fixtures() {
  const molar = { answer: "MOLAR", type: ["composite_anagram"], definitions: [{ text: "this —— possibly" }],
    wordplay: { op: "composite", parts: [{ words: "toil harms" }, { words: "this" }] },
    blocks: [{ clueFragment: "toil harms", gives: "TOILHARMS" }, { clueFragment: "this", gives: "THIS" }] };
  const f = appFormula.formulaOf(molar, appFormula.buildingBlocks(molar));
  const text = formulaText(f);
  const bad = [];
  if (mathFault(molar)) bad.push("azed-2081 7A does not add up: " + text);
  if (text !== "definition (5) = anagram of ( as written 9 − as written 4 )") bad.push("azed-2081 7A reads: " + text);
  // Accented letters are letters: MAÑANA is six.
  if (appFormula.letterCount("MAÑANA") !== 6) bad.push("MAÑANA counts " + appFormula.letterCount("MAÑANA"));
  return bad;
}

if (require.main === module) {
  const list = process.argv.includes("--list");
  const t0 = Date.now();
  const failures = fixtures().map((why) => ({ why }));
  const badData = [];
  let clues = 0;
  for (const p of puzzles()) {
    for (const e of p.entries || []) {
      if (!e.annotation || !(e.annotation.blocks || []).length) continue;
      clues++;
      const ann = e.alteration ? { ...e.annotation, alteration: e.alteration, entered: e.solution } : e.annotation;
      const fault = mathFault(ann);
      if (!fault) continue;
      const row = { id: p.id, entry: `${e.number}-${e.direction}`, clue: (e.clue || {}).text, answer: ann.answer, built: built(ann),
        op: (ann.wordplay || {}).op || "-", ...fault };
      (unchecked(ann.wordplay) || treeMissesAnswer(ann) ? badData : failures).push(row);
    }
  }
  if (list) for (const f of failures.concat(badData)) console.log(JSON.stringify(f));
  // --out <file>: the bad-data clues as re-annotation rows, the shape of
  // tools/data/shape_reannotate.json ({id: "<puzzle>#<number><a|d>", reason}).
  const out = process.argv.indexOf("--out");
  if (out > 0) {
    fs.writeFileSync(process.argv[out + 1], JSON.stringify(badData.map((r) => ({
      id: `${r.id}#${r.entry.replace(/-(a|d)\w*$/, "$1")}`,
      reason: `formulaMath: the tree does not build ${r.built}: ${r.text}` })), null, 0).replace(/\},\{/g, "},\n{") + "\n");
  }
  for (const f of failures.slice(0, 20)) console.error("FAIL: " + JSON.stringify(f));
  console.error(`${clues} clues with blocks: ${failures.length} formulas that do not add up, ` +
    `${badData.length} more whose trees do not build the answer, ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  process.exit(failures.length ? 1 : 0);
}

module.exports = { mathFault, evaluate, fixtures, treeMissesAnswer };
