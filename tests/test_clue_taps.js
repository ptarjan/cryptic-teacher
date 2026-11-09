/* Paul 11-08: "I want to be able to select words right off the bat without a
   click and then the definition without a click etc." and "the wheel for
   removing letters" (tap selects a tile, a second tap or Backspace crosses it off).

     node tests/test_clue_taps.js

   1. arrives: picking a clue asks its first free question at once, so the
      clue's words are tappable with no button tapped, and nothing is charged.
   2. once: "Skip for now" or "Just tell me" is not undone by the next render;
      only coming back to the clue asks again.
   3. typing: the answer can still be typed while the question is up, and a clue
      solved that way keeps its "no hints" star; a solved clue is not quizzed.
   4. wheel: tapRingTile/ringBackspace, lifted out of the app source. */
"use strict";
const { boot } = require("../tools/fake_dom.js");
const src = require("../tools/app_src").read(__dirname + "/..");

let failures = 0;
const check = (ok, msg) => { console.log((ok ? "ok   " : "FAIL ") + msg); if (!ok) failures++; };
const entryId = (e) => e.number + "-" + e.direction;
const ID = "quiptic-1396";

function open() {
  const d = boot({ query: "?p=" + ID, storage: { "ct:nux": "9" } });
  const reg = d.registry;
  const kd = d.docListeners["keydown"][0];
  return {
    reg,
    puz: global.window.CRYPTIC_PUZZLES[ID],
    pick: (e) => reg["clue-" + entryId(e)].listeners.click[0](),
    key: (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] }),
    asking: () => reg["hint-body"].innerHTML.includes('class="hint-step guess"'),
    tappable: () => reg["hint-clue"].classList.contains("picking") && /id="gw-\d+"/.test(reg["hint-clue"].innerHTML),
    hints: () => Number((/<strong>(\d+)<\/strong> hints used/.exec(reg["scorebar"].innerHTML) || [])[1]),
  };
}

// --- 1: arriving asks ---
const t = open();
const cands = t.puz.entries.filter((e) => e.annotation && e.solution && !e.offGrid && !e.linkedTo);
let e = null;
for (const c of cands) {
  t.pick(c);
  if (t.asking() && t.tappable()) { e = c; break; }
}
check(!!e, "some clue asks its question, words tappable, the moment it is picked");
const other = cands.find((c) => c !== e);
if (e && other) {
  check(t.tappable(), `arrives (${entryId(e)}): the clue's words are tappable with no extra tap`);
  check(t.hints() === 0, `arrives (${entryId(e)}): asking charged nothing (${t.hints()} hints used)`);
  check(/<strong>0<\/strong>\//.test(t.reg["hint-meter"].innerHTML), `arrives (${entryId(e)}): meter still reads 0 hints shown`);

  // --- 2: once per arrival ---
  t.reg["guess-later"].onclick();
  check(!t.asking(), "once: Skip for now puts the question away");
  t.key(e.solution[0]);
  check(!t.asking(), "once: a later render on the same clue does not ask again");
  t.key("Backspace");
  t.pick(other);
  t.pick(e);
  check(t.asking(), "once: coming back to the clue asks again");
  t.reg["guess-tell"].onclick();
  check(!t.asking() && t.hints() === 1, `once: Just tell me opens the rung (1 hint) and asks nothing next: ${t.hints()}`);
  t.key(e.solution[0]);
  check(!t.asking(), "once: still nothing asked after Just tell me");

  // --- 3: typing alongside ---
  const u = open();
  u.pick(e);
  check(u.asking(), "typing: the question is up");
  for (const ch of e.solution) u.key(ch);
  check(/clue-done clean/.test(u.reg["hint-clue"].innerHTML),
    `typing: the answer typed with the question up solves the clue with no hints (star): ${u.hints()} hints`);
  check(!u.asking(), "typing: a solved clue is not quizzed");
  u.pick(other);
  u.pick(e);
  check(!u.asking(), "typing: nor when you come back to it");
}
const arrive = (/function arriveAt[\s\S]*?\n  \}/.exec(src) || [""])[0];
check(/advanceLadder\(e\)/.test(arrive) && /nextQuestion\(e\)/.test(arrive),
  "arriving asks through nextQuestion/advanceLadder, the same free-question-only chain as a right answer");
check(/n\.rung === "blocks" && isShown\(e, "blocks"\)/.test(arrive),
  "arriving never asks the next piece of an open blocks rung (it would name the piece's letters)");
check(/line\.id === "welcome" \|\| line\.id === "ladder"/.test(arrive),
  "arriving asks nothing while the tour is teaching the row of hint buttons");

// --- 4: the letter wheel ---
const a = src.indexOf("  function tapRingTile"), b = src.indexOf("  // ---------- typing into the ring");
check(a > 0 && b > a, "tapRingTile is in the app source");
function wheel(letters) {
  const w = { advanced: 0, popped: 0 };
  const f = new Function("w", `
    let ring = { letters: w.letters, struck: {}, sel: null };
    const ringShelf = { paid: ring };
    const currentEntry = () => ({}), advanceLadder = () => { w.advanced++; },
      renderHintPanel = () => {}, removeLastRingLetter = () => { w.popped++; };
    ${src.slice(a, b)}
    return { ring, tap: tapRingTile, back: ringBackspace };`);
  return Object.assign(w, f(Object.assign(w, { letters })));
}
{
  const w = wheel(["A", "B", "C"]);
  w.tap("0");
  check(w.ring.sel === "0" && !w.ring.struck[0], "wheel: one tap selects the tile and crosses nothing off");
  w.tap("1");
  check(w.ring.sel === "1" && !w.ring.struck[0] && !w.ring.struck[1], "wheel: tapping another tile moves the selection");
  w.tap("1");
  check(w.ring.struck[1] && w.ring.sel === null, "wheel: a second tap on the selected tile crosses it off");
  w.tap("1");
  check(!w.ring.struck[1] && w.ring.sel === null, "wheel: a crossed-off tile comes back on one tap");
  w.tap("2");
  w.back();
  check(w.ring.struck[2] && w.ring.sel === null && w.popped === 0, "wheel: Backspace crosses off the selected tile");
  w.back();
  check(w.popped === 1, "wheel: Backspace with nothing selected deletes the last typed letter as before");
  check(w.advanced === 0, "wheel: not finished, so nothing advances");
  w.tap("0"); w.tap("0"); w.tap("1"); w.tap("1");
  check(w.advanced === 1, "wheel: crossing off the last tile finishes the wheel and asks the next question");
}
check(/tapRingTile\(i\)/.test(src) && /"Backspace"\) \{ ringBackspace\(\)/.test(src),
  "the tile's tap and the ring's Backspace go through tapRingTile / ringBackspace");
check(/\$\{chosen\(idx\) \? " sel" : ""\}/.test(src), "the selected tile is drawn with .sel");

const css = require("fs").readFileSync(__dirname + "/../style.css", "utf8");
const sel = (/\.ana-tile\.sel \{([^}]*)\}/.exec(css) || [])[1] || "";
check(/background: var\(--cell-sel, var\(--sel\)\)/.test(sel), "the selected tile is filled like the cursor, with a colour defined outside #grid");
check(!/transform/.test(sel), "and sets no transform, which would move the tile off its place in the ring");

console.log(failures ? `${failures} FAILURE(S)` : "all passed");
process.exit(failures ? 1 : 0);
