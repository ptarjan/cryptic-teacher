/* A building block that would cost a hint takes two taps; a free one takes one.

     node tests/test_block_confirm.js

   Paul: "If a building blocks can't be free it should make me click twice to
   confirm I want it." app.js blocksCost says when a tap on the blocks rung
   charges: the group is unsolved and the tap opens the rung outright, or "Show
   me" on a blocks question opens it or takes back one already earned.

   1. firstTapArms: that tap relabels "Just tell me" (in the question) "Tap again · 1 hint" and
      charges nothing; the second tap reveals and charges one.
   2. timeoutDisarms: left alone for the arm window, the button goes back.
   3. elsewhereDisarms: a click on anything else puts it back too.
   4. freeIsOneTap: on a solved clue a step still shut is a free tab: one tap opens it, unarmed. */
"use strict";
const { boot } = require("../tools/fake_dom.js");

const ID = "cryptic-30066";
const ARMED = "Tap again · 1 hint";
const entryId = (e) => e.number + "-" + e.direction;

let failures = 0;
const check = (ok, msg) => {
  console.log((ok ? "ok   " : "FAIL ") + msg);
  if (!ok) failures++;
};

function open() {
  const d = boot({ query: "?p=" + ID, storage: { "ct:nux": "9" }, twoTap: true });
  const reg = d.registry;
  const puz = global.window.CRYPTIC_PUZZLES[ID];
  const kd = d.docListeners["keydown"][0];
  const key = (k) => kd({ key: k, preventDefault() {}, shiftKey: false, target: reg["kbd"] });
  const row = () => reg["hint-rungs"].children;
  const body = () => reg["hint-body"].innerHTML;
  const asking = () => body().includes('class="hint-step guess"');
  const hints = () => Number((/<strong>(\d+)<\/strong> hints?\b/.exec(reg["scorebar"].innerHTML) || [])[1]);
  const blocksBtn = () => row().find((b) => b.onclick && !b.disabled && /building blocks/i.test(b.textContent || ""));
  // The help button lives in the question (or, with no question, in the next
  // step's card), both in #hint-body, and carries the armed text. The help bar
  // (#hint-escape) holds Reveal letter and More only.
  const bar = () => reg["hint-escape"].innerHTML;
  const tell = () => body();
  const tellIsArmed = () => /id="guess-tell"[^>]*class="[^"]*arm-cost/.test(tell()) && tell().includes(ARMED);
  const armedBtn = () => (tellIsArmed() ? reg["guess-tell"] : null);
  const tellArmed = () => tellIsArmed() && /data-arm="blocks-tell"/.test(tell());
  const blocksOpen = () => /The building blocks(<span class="step-won">[^<]*<\/span>)?<\/span>/.test(body().replace(/<div class="(hint-step guess|help-next)"[\s\S]*$/, ""));
  return { d, reg, puz, key, row, body, asking, hints, blocksBtn, armedBtn, tellArmed, blocksOpen, bar, tell };
}

// Up the ladder to the blocks rung, buying each spotting rung outright.
function climbToBlocks(t, e) {
  t.reg["clue-" + entryId(e)].listeners.click[0]();
  for (let guard = 0; guard < 8 && !t.blocksBtn(); guard++) {
    const b = t.row().find((x) => x.onclick && !x.disabled && /^\d+ · /.test(x.textContent || ""));
    if (!b) return false;
    b.onclick();
    if (t.armedBtn()) t.armedBtn().onclick();
    if (t.asking()) { t.reg["guess-tell"].onclick(); if (t.asking()) t.reg["guess-tell"].onclick(); }
  }
  return !!t.blocksBtn();
}

const blocky = open().puz.entries.filter((e) => e.annotation && (e.annotation.blocks || []).length);
let asked = 0, outright = 0;
for (const e of blocky) {
  const t = open();
  if (!climbToBlocks(t, e)) continue;
  const id = entryId(e);
  const before = t.hints();
  t.blocksBtn().onclick();
  if (t.asking()) {
    // The rung asks first, and asking is free; "Just tell me" is the paid tap.
    if (asked++) continue;
    check(t.hints() === before, `firstTapArms (${id}): opening the question costs nothing`);
    t.reg["guess-tell"].onclick();
    check(t.tellArmed() && t.asking() && t.hints() === before,
      `firstTapArms (${id}): the first "Just tell me" arms, still asking, still ${before} hints`);
    flushTimers(4000);
    check(!t.tellArmed() && />Just tell me \u00b7 1 hint</.test(t.tell()),
      `timeoutDisarms (${id}): the button reads "Just tell me" and its price again`);
    t.reg["guess-tell"].onclick();
    t.d.docListeners["click"].forEach((f) => f({ target: t.reg["hint-meter"] }));
    flushTimers(0);
    check(!t.tellArmed(), `elsewhereDisarms (${id}): a click elsewhere puts it back`);
    // A click whose propagation is stopped below the document still reaches the
    // capture listener, and the redraw follows the state change, not the event.
    t.reg["guess-tell"].onclick();
    t.d.docListeners["click"][0]({ target: t.reg["hint-meter"] });
    flushTimers(0);
    check(!t.tellArmed(), `elsewhereDisarms (${id}): the capture listener alone disarms and redraws`);
    t.reg["guess-tell"].onclick();
    t.reg["guess-tell"].onclick({ detail: 2 });
    check(t.tellArmed(), `firstTapArms (${id}): the second click of a double-click confirms nothing`);
    t.reg["guess-tell"].onclick({ detail: 1 });
    check(!t.asking() && t.blocksOpen() && t.hints() === before + 1,
      `firstTapArms (${id}): the second tap reveals the blocks and charges one: ${before} -> ${t.hints()}`);
  } else {
    // A piece whose letters are all printed in the clue (anagram fodder) opens on
    // one tap, unarmed and free (blocksFree); only a rung that arms is a purchase.
    if (!t.armedBtn() && t.hints() === before) continue;
    if (outright++) continue;
    check(t.armedBtn() && !t.blocksOpen() && t.hints() === before,
      `firstTapArms (${id}): the rung's "Show me" arms and charges nothing`);
    flushTimers(4000);
    check(!t.armedBtn() && t.blocksBtn(), `timeoutDisarms (${id}): "Show me" reads as itself again`);
    t.blocksBtn().onclick();
    t.armedBtn().onclick();
    check(t.blocksOpen() && t.hints() === before + 1,
      `firstTapArms (${id}): the second tap reveals the blocks and charges one`);
  }
}
check(asked + outright > 0, `found a clue whose blocks can cost (asked ${asked}, outright ${outright})`);

// --- 4: solved, the rest of the ladder is free and takes one tap ---
// The first such clue that is not one leg of a linked group: a leg typed in
// alone leaves its group unsolved, and the ladder still charges for that.
{
  let done = false;
  for (const e of blocky.filter((x) => x.solution)) {
    const t = open();
    t.reg["clue-" + entryId(e)].listeners.click[0]();
    const solvedN = () => Number((/Solved <strong>(\d+)\//.exec(t.reg["scorebar"].innerHTML) || [])[1]);
    const s0 = solvedN();
    for (const ch of e.solution) t.key(ch);
    // A leg typed in alone leaves its group unsolved (the score is not frozen).
    if (!(solvedN() > s0)) continue;
    // Solved: the steps still shut stay on the track as free tabs, like the
    // open ones; no help button and no separate "How it works" button.
    const tabs = () => t.reg["hint-track"].children;
    const pieces = tabs().find((b) => b.onclick && b.textContent === "Pieces" && /\bavail\b/.test(b.className || ""));
    if (!pieces) continue;
    const before = t.hints();
    check(!t.blocksOpen() && !/id="guess-tell"|id="hx-how"|arm-cost/.test(t.bar() + t.tell())
      && pieces.getAttribute && pieces.getAttribute("role") === "tab",
      `freeIsOneTap (${entryId(e)}): before the tap Pieces is shut, a tab, and nothing in the bar costs: ${t.bar()}`);
    pieces.onclick();
    check(!t.armedBtn() && t.blocksOpen() && t.hints() === before,
      `freeIsOneTap (${entryId(e)}): one tap on the tab opens it, unarmed, no charge (armed ${!!t.armedBtn()}, blocksOpen ${t.blocksOpen()}, hints ${before} -> ${t.hints()})`);
    check(tabs().some((b) => b.textContent === "Pieces" && /\bopen\b/.test(b.className || "") && /\bsel\b/.test(b.className || "")),
      `freeIsOneTap (${entryId(e)}): and its tab is now the open, selected one: ${tabs().map((b) => b.className).join("|")}`);
    done = true;
    break;
  }
  check(done, "freeIsOneTap: found a solved clue with Pieces still shut");
}

console.log(failures ? `${failures} FAILURE(S)` : "all passed");
process.exit(failures ? 1 : 0);
