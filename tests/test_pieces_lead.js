/* Paul 11-27 (genius-273 13A THEOREM): the Pieces question leads with the first
   piece not out that can be asked about, so a wordless first piece (the O the
   grid supplies) never leaves the step with no question; and a told step puts
   the next free question up. */
"use strict";
const src = require("../tools/app_src").read(__dirname + "/..");
let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };

const a = src.indexOf("  const nextPiece"), b = src.indexOf("  // Forwards only, and it is the reveal");
const code = src.slice(a, b);
function lead(pieces, askable, out) {
  return new Function("pieces", "askable", "out", `
    const blockPieces = () => pieces, pieceOut = (e, i) => out.includes(i),
      guessAsk = (e, r, i) => (askable.includes(i) ? {} : null);
    ${code}
    return leadPiece({});`)(pieces, askable, out);
}
const theorem = ["THERE", "O", "M"];
check(lead(theorem, [0, 2], []) === 0, "THEOREM: the first piece (THERE) leads");
check(lead(theorem, [0, 2], [0]) === 2, "THEOREM: with THERE out, the wordless O is passed over and M leads");
check(lead(["O", "THERE", "M"], [1, 2], []) === 1, "wordless piece first: the next askable piece leads");
check(lead(["O", "THERE"], [], []) === 0, "nothing askable: falls back to the first piece not out");
check(lead(theorem, [0, 2], [0, 1, 2]) === -1, "all out: -1, as nextPiece");

const fg = src.slice(src.indexOf("  function finishGuess"), src.indexOf("  function earnedRungs"));
check(/else if \(!verdict\) advanceLadder\(e\)/.test(fg), "a told step (Just tell me) puts the next question up");
const sm = src.slice(src.indexOf("  function showMeTap"), src.indexOf("  function fillHTML"));
check(/openStep\(on, t\.rung, t\.step\);\s*advanceLadder\(on\)/.test(sm), "Show me on an unopened step puts the next question up");
for (const [name, text] of [["nextQuestion", src.slice(src.indexOf("  function nextQuestion"), src.indexOf("  function advanceLadder"))],
  ["helpTarget", src.slice(src.indexOf("  function helpTarget"), src.indexOf("  function chosenStep"))],
  ["settlePiece", src.slice(src.indexOf("  function settlePiece"), src.indexOf("  // Tiers, not a chain"))]]) {
  check(/leadPiece\(e\)/.test(text) && !/nextPiece\(e\)/.test(text), name + " uses leadPiece");
}
process.exit(failures ? 1 : 0);
