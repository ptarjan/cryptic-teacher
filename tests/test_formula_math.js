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

   Usage: node tests/test_formula_math.js [--list]   (--list prints every failure) */
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
    return lead ? opRange(lead, acc) : acc;
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
  const want = appFormula.letterCount(ann.answer);
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

// Puzzles whose stored answers their trees do not build (Genius alteration
// grids, misread grid answers such as azed-2033's APOLLSINARIS): bad data for
// the fixers (tools/fix_shape_suspects.py), not a formula fault. Remove an id
// once its puzzle is repaired; a puzzle not listed is held to the full check.
const TREE_MISSES_ANSWER = new Set([
  "azed-2033", "azed-2151", "azed-2209", "azed-2232", "azed-2363", "azed-2587", "azed-2695", "azed-2729",
  "azed-2750", "cryptic-21783", "cryptic-21837", "cryptic-22183", "cryptic-22272", "cryptic-22391",
  "cryptic-23340", "cryptic-24963", "cryptic-25867", "cryptic-26430", "cryptic-26842", "cryptic-27124",
  "cryptic-28002", "cryptic-28075", "cryptic-28410", "cryptic-28468", "cryptic-28500", "cryptic-28632",
  "cryptic-29485", "cryptic-29657", "cryptic-30058", "cyclops-268", "cyclops-537", "everyman-3453",
  "everyman-3467", "everyman-3780", "ftcryptic-16323", "ftcryptic-17410", "genius-1", "genius-101", "genius-11",
  "genius-111", "genius-138", "genius-140", "genius-142", "genius-143", "genius-145", "genius-163",
  "genius-164", "genius-169", "genius-177", "genius-196", "genius-197", "genius-199", "genius-218",
  "genius-221", "genius-222", "genius-236", "genius-247", "genius-250", "genius-263", "genius-38", "genius-4",
  "genius-71", "independent-11348", "independent-11389", "independent-11679", "indysunday-1331",
  "listener-3999", "nation-3504", "quiptic-1079", "quiptic-1263", "sundaytel-2938", "sundaytimes-4678",
  "sundaytough-63", "telegraph-30698", "telegraph-31240", "times-28367", "times-28780", "times-29398",
  "timesclub-20217", "timesjumbo-1603", "toughie-2194"
]);

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
      const ann = e.annotation;
      const fault = mathFault(ann);
      if (!fault) continue;
      const row = { id: p.id, entry: `${e.number}-${e.direction}`, clue: (e.clue || {}).text, answer: ann.answer,
        op: (ann.wordplay || {}).op || "-", ...fault };
      (unchecked(ann.wordplay) || TREE_MISSES_ANSWER.has(p.id) ? badData : failures).push(row);
    }
  }
  if (list) for (const f of failures.concat(badData)) console.log(JSON.stringify(f));
  for (const f of failures.slice(0, 20)) console.error("FAIL: " + JSON.stringify(f));
  console.error(`${clues} clues with blocks: ${failures.length} formulas that do not add up, ` +
    `${badData.length} more on unchecked trees or listed bad-data puzzles, ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  process.exit(failures.length ? 1 : 0);
}

module.exports = { mathFault, evaluate, fixtures };
