/* Paul 10-30: "When you finish a hint ring it should go to the next." Finishing
   a rung with a right answer (or crossing off the whole anagram wheel) asks the
   ladder's next question; it never opens a rung that would cost a hint.

     node tests/test_ladder_advance.js */
"use strict";
const src = require("fs").readFileSync(__dirname + "/../app.js", "utf8");
const a = src.indexOf("  function nextQuestion"), b = src.indexOf("  // Opens the rung and ends the guess");
const code = src.slice(a, b);
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

function next(w) {
  const f = new Function("w", `
    let guessing = w.guessing || null;
    const isEntrySolved = () => !!w.solved, annOf = () => ({}), isShown = (e, k) => w.shown.includes(k),
      piecesLeft = () => w.left || 0, nextPiece = () => w.piece || 0, ladderSteps = () => w.steps.map((key) => ({ key })),
      clueText = () => "", GUESSABLE = { type: 1, definition: 1, indicators: 1, blocks: 1 },
      rungAvailable = (e, s, k) => !w.locked.includes(k), guessAsk = (e, r) => (w.asks.includes(r) ? {} : null),
      entryKey = () => "k";
    ${code}
    return nextQuestion({});`);
  return f(w);
}
const base = { shown: [], steps: ["definition", "indicators", "type", "blocks", "walkthrough"], locked: [], asks: ["definition", "indicators", "type", "blocks"] };
check(next({ ...base, shown: ["definition"] }).rung === "indicators", "after the definition, the indicators question is next");
check(next({ ...base, shown: ["definition", "indicators", "type"], locked: [] }).rung === "blocks", "after the type, the blocks question");
check(next({ ...base, shown: ["definition", "indicators", "type", "blocks"], left: 2, piece: 1 }).step === 1, "blocks with pieces left asks the next piece");
check(next({ ...base, shown: ["definition", "indicators", "type", "blocks"], left: 0 }) === null, "walkthrough has no question, so nothing is bought for you");
check(next({ ...base, shown: ["definition"], asks: ["definition"] }) === null, "a next rung with no question is not opened for the solver");
check(next({ ...base, shown: ["definition"], locked: ["indicators"] }) === null, "a locked next rung is not asked");
check(next({ ...base, solved: true }) === null, "a solved clue is not quizzed");
check(next({ ...base, guessing: {} }) === null, "no new question over one already on the table");
check(/if \(verdict && verdict\.right\) advanceLadder\(e\)/.test(src), "finishGuess advances only on a right answer");
check(/ring === ringShelf\.paid && ring\.letters\.length/.test(src), "a fully crossed-off wheel advances too");
process.exit(failures ? 1 : 0);
