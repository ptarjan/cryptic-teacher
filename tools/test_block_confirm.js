/* A building block that would cost a hint takes two taps; a free one takes one.

     node tools/test_block_confirm.js

   Paul: "If a building blocks can't be free it should make me click twice to
   confirm I want it." app.js blocksCost says when a tap on the blocks rung
   charges: the group is unsolved and the tap opens the rung outright, or "Just
   tell me" on a blocks question opens it or takes back one already earned.

   1. firstTapArms: that tap relabels its button "Tap again to reveal · costs a
      hint" and charges nothing; the second tap reveals and charges one.
   2. timeoutDisarms: left alone for the arm window, the button goes back.
   3. elsewhereDisarms: a click on anything else puts it back too.
   4. freeIsOneTap: on a solved clue the blocks rung opens on one tap, unarmed. */
"use strict";
const { boot } = require("./fake_dom.js");

const ID = "cryptic-30066";
const ARMED = "Tap again to reveal · costs a hint";
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
  const row = () => reg["hint-next"].children;
  const body = () => reg["hint-body"].innerHTML;
  const asking = () => body().includes('class="hint-step guess"');
  const hints = () => Number((/<strong>(\d+)<\/strong> hints used/.exec(reg["scorebar"].innerHTML) || [])[1]);
  const blocksBtn = () => row().find((b) => b.onclick && !b.disabled && /building blocks/i.test(b.textContent || ""));
  const armedBtn = () => row().find((b) => b.textContent === ARMED);
  const tellArmed = () => body().includes(ARMED) && /data-arm="blocks-tell" class="[^"]*arm-cost/.test(body());
  const blocksOpen = () => /The building blocks(<span class="step-won">[^<]*<\/span>)?<\/span>/.test(body().replace(/<div class="hint-step guess">[\s\S]*$/, ""));
  return { d, reg, puz, key, row, body, asking, hints, blocksBtn, armedBtn, tellArmed, blocksOpen };
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
    check(!t.tellArmed() && /Just tell me/.test(t.body()),
      `timeoutDisarms (${id}): the button reads "Just tell me" again`);
    t.reg["guess-tell"].onclick();
    t.d.docListeners["click"].forEach((f) => f({ target: t.reg["hint-meter"] }));
    flushTimers(0);
    check(!t.tellArmed(), `elsewhereDisarms (${id}): a click elsewhere puts it back`);
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
      `firstTapArms (${id}): the rung button arms and charges nothing`);
    flushTimers(4000);
    check(!t.armedBtn() && t.blocksBtn(), `timeoutDisarms (${id}): the rung reads as itself again`);
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
    for (const ch of e.solution) t.key(ch);
    const b = t.blocksBtn();
    if (!b) continue;
    const before = t.hints();
    b.onclick();
    check(!t.armedBtn() && t.blocksOpen() && t.hints() === before,
      `freeIsOneTap (${entryId(e)}): one tap opens the blocks, unarmed, no charge`);
    done = true;
    break;
  }
  check(done, "freeIsOneTap: found a solved clue offering its blocks");
}

console.log(failures ? `${failures} FAILURE(S)` : "all passed");
process.exit(failures ? 1 : 0);
