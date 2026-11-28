/* Paul 10-30: "When you finish a hint ring it should go to the next." Finishing
   a rung with a right answer (or crossing off the whole anagram wheel) asks the
   ladder's next question; it never opens a rung that would cost a hint.

     node tests/test_ladder_advance.js */
"use strict";
const src = require("../tools/app_src").read(__dirname + "/..");
const a = src.indexOf("  function nextQuestion"), b = src.indexOf("  // Opens the rung and ends the guess");
const code = src.slice(a, b);
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

function next(w) {
  const f = new Function("w", `
    let guessing = w.guessing || null;
    const groupSolved = () => !!w.solved, annOf = () => ({}), isShown = (e, k) => w.shown.includes(k),
      piecesLeft = () => w.left || 0, nextPiece = () => w.piece || 0, leadPiece = () => w.piece || 0, ladderSteps = () => w.steps.map((key) => ({ key })), ladderFor = ladderSteps,
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
check(next({ ...base, shown: ["definition"], asks: ["definition"] }) === null, "nothing further askable: no question, nothing opened");
check(next({ ...base, shown: ["definition"], asks: ["blocks"] }).rung === "blocks", "indicators has nothing to ask but blocks does: the blocks question is asked");
check(next({ ...base, shown: ["definition", "type"], asks: ["blocks"], locked: ["indicators"] }).rung === "blocks", "a locked or unaskable rung is skipped, not stopped at");
check(next({ ...base, shown: ["definition", "indicators", "type"], asks: [] }) === null, "no askable rung left asks nothing");
check(next({ ...base, shown: ["definition"], locked: ["indicators", "type", "blocks"] }) === null, "rungs that are all locked are not asked");
check(next({ ...base, solved: true }) === null, "a solved clue (every leg of a linked one: groupSolved) is not quizzed");
check(next({ ...base, guessing: {} }) === null, "no new question over one already on the table");
check(/if \(right\) goOn\(e, guessing_rung, guessing_choice\);\s*else if \(!verdict\) advanceLadder\(e\)/.test(src),
  "finishGuess: right and told advance to a free question (goOn / advanceLadder), wrong stays put");
check(/function goOn[\s\S]*?if \(advanceLadder\(e\)\) return;/.test(src), "goOn is the one place a right answer advances the ladder");
check(/ring\.dealt && ring\.letters\.length/.test(src), "a fully crossed-off wheel advances too");
// Paul 11-27: after a wrong answer the tab in front, its content and every button
// must belong to one step. A wrong answer opens nothing and keeps the question.
const fg = src.slice(src.indexOf("  function finishGuess"), src.indexOf("  function earnedRungs"));
const missPath = fg.slice(fg.indexOf("if (verdict && !right) {"), fg.indexOf("if (right && !rungsMissed"));
check(/guessing = \{ key: guessing\.key, rung, step: guessing\.step, picked: guessing\.picked\.slice\(\)/.test(missPath) && /return;/.test(missPath),
  "a wrong answer keeps the same question on the table with the picks kept");
check(!/showHint|settlePiece|goOn/.test(missPath), "a wrong answer opens no step and goes on to nothing");
check(/rungsMissed\.add/.test(missPath) && /!rungsMissed\.has/.test(fg), "a step that was missed can never be marked worked out");
check(/Not quite[^`]*try again/.test(src), "the wrong-answer line tells the solver to try again");
process.exit(failures ? 1 : 0);
