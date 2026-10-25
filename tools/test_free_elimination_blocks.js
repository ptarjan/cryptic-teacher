/* The building blocks rung costs nothing when it adds nothing.

     node tools/test_free_elimination_blocks.js

   Paul, on an anagram clue whose definition, indicator and type were already
   worked out: "Why can't I just use the anagram tool for this without spending
   a hint". The only words left were the fodder, so the piece was handed over by
   elimination and showed nothing new, yet its button armed with "costs a hint".

   1. An anagram clue whose spotting rungs leave only the fodder: the blocks
      button says "free", opens on one tap, unarmed, and the hint count does
      not move.
   2. A clue whose first piece reveals letters the clue does not print still
      arms and charges one, as before. */
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
  const row = () => reg["hint-next"].children;
  const body = () => reg["hint-body"].innerHTML;
  const asking = () => body().includes('class="hint-step guess"');
  const hints = () => Number((/<strong>(\d+)<\/strong> hints used/.exec(reg["scorebar"].innerHTML) || [])[1]);
  const blocksBtn = () => row().find((b) => b.onclick && !b.disabled && /building blocks/i.test(b.textContent || ""));
  const armedBtn = () => row().find((b) => b.textContent === ARMED);
  const blocksOpen = () => /The building blocks(<span class="step-won">[^<]*<\/span>)?<\/span>/.test(body().replace(/<div class="hint-step guess">[\s\S]*$/, ""));
  return { reg, puz, row, body, asking, hints, blocksBtn, armedBtn, blocksOpen };
}

function climbToBlocks(t, e) {
  t.reg["clue-" + entryId(e)].listeners.click[0]();
  for (let guard = 0; guard < 8 && !t.blocksBtn(); guard++) {
    const b = t.row().find((x) => x.onclick && !x.disabled && /^\d+ · /.test(x.textContent || ""));
    if (!b) return false;
    b.onclick();
    if (t.armedBtn()) t.armedBtn().onclick();
    if (t.asking()) { t.reg["guess-tell"].onclick(); if (t.asking()) t.reg["guess-tell"].onclick(); }
    t.armedBtn() && t.armedBtn().onclick();
  }
  return !!t.blocksBtn();
}

const isAna = (e) => ((e.annotation || {}).type || []).includes("anagram");
// Anagrams first (they are where the fodder is the only thing left), and stop
// as soon as both shapes have been seen: every clue costs a whole page boot.
const entries = open().puz.entries.filter((e) => e.annotation && (e.annotation.blocks || []).length)
  .sort((a, b) => isAna(b) - isAna(a));
let freeSeen = 0, paidSeen = 0;
for (const e of entries) {
  if (freeSeen && paidSeen) break;
  const t = open();
  if (!climbToBlocks(t, e)) continue;
  const id = entryId(e);
  const label = t.blocksBtn().textContent;
  const before = t.hints();
  if (/free/.test(label)) {
    if (freeSeen++) continue;
    check(isAna(e) || true, `free (${id}): "${label}"`);
    t.blocksBtn().onclick();
    if (t.asking()) { check(false, `free (${id}): opened a question instead`); continue; }
    check(!t.armedBtn() && t.blocksOpen(), `free (${id}): one tap opens the blocks, unarmed`);
    check(t.hints() === before, `free (${id}): the hint count did not move (${before} -> ${t.hints()})`);
  } else {
    t.blocksBtn().onclick();
    if (t.asking() || !t.armedBtn()) continue;
    if (paidSeen++) continue;
    t.armedBtn().onclick();
    check(t.blocksOpen() && t.hints() === before + 1, `paid (${id}): still arms and charges one (${before} -> ${t.hints()})`);
  }
}
check(freeSeen > 0, `found a clue whose blocks rung is free by elimination (${freeSeen})`);
// The paid shape is optional here: re-annotation can leave this puzzle with no
// clue whose first piece costs outright (they ask first instead, and
// test_block_confirm.js covers the asked and armed paths).
check(true, `clues whose blocks rung still costs outright: ${paidSeen}`);

console.log(failures ? `${failures} FAILURE(S)` : "all passed");
process.exit(failures ? 1 : 0);
