/* The type rung shows the clue's formula, and any piece of it can be tapped.

     node tools/test_formula_hint.js

   Paul: "Should what kind of clue this is show the formula? And make pick any
   part of it?" Under the family line the rung draws the formula with every
   piece blank (role and letter count only); a tap takes that one piece, in
   any order. A piece is the blocks rung's own (app.js pickPiece), so:

   1. blankPieces: the formula is there, its chips name a role and a count, and
      it holds nothing of the answer.
   2. lockedByTier: until the definition and indicators are up, the chips are
      disabled and a tap does nothing, charges nothing.
   3. firstChipArms / oneChargeOnly: the first chip taken costs a hint behind the
      two-tap confirm, in any order; every later chip, and the rest of the rung
      by its own button, adds nothing.
   4. noRepeat: a piece taken by chip is not asked again by "next building block",
      and the rung lists every piece once finished.
   5. saved / merged: the pick survives a reload, and a sync merge ORs two
      devices' picks together. */
"use strict";
const { boot } = require("./fake_dom.js");
const { mergeSaves } = require("../sync/merge.js");

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
  const armedBtn = () => row().find((b) => b.textContent === ARMED);
  const formula = () => (/<div class="formula">[\s\S]*?<\/div>/.exec(body()) || [""])[0];
  // The body's click handler is the one that reads data-piece, as for rule chips.
  const tapChip = (i) => reg["hint-body"].listeners.click[0]({ target: { dataset: { piece: String(i) } } });
  const settle = () => {
    for (let g = 0; g < 4; g++) {
      if (armedBtn()) armedBtn().onclick();
      else if (asking()) reg["guess-tell"].onclick();
    }
  };
  // Take the rung whose button matches, buying it outright.
  const take = (re) => {
    const b = row().find((x) => x.onclick && !x.disabled && re.test(x.textContent || ""));
    if (!b) return false;
    b.onclick();
    settle();
    return true;
  };
  const chipsLeft = () => (formula().match(/data-piece="\d+"/g) || []).length;
  const chipsGot = () => (formula().match(/formula-chip got/g) || []).length;
  return { d, reg, puz, row, body, asking, hints, armedBtn, formula, tapChip, settle, take, chipsLeft, chipsGot };
}

const candidates = open().puz.entries.filter((e) => {
  const a = e.annotation;
  return a && (a.blocks || []).length >= 3 && (a.indicators || []).length && (a.definitions || []).length
    && (a.type || []).length && e.solution;
});

let done = false;
for (const e of candidates.slice(0, 12)) {
  const t = open();
  t.reg["clue-" + entryId(e)].listeners.click[0]();
  const id = entryId(e);
  // The type rung first, so the formula is up while the tiers are still shut.
  if (!t.take(/kind of clue/i)) continue;
  const f = t.formula();
  if (!f) continue;
  const n = t.chipsLeft();
  const answer = String(e.solution).toUpperCase().replace(/[^A-Z]/g, "");

  // 1
  check(n >= 3 && /formula-lead">(definition|answer) \(\d+\) =</.test(f) && /data-piece="0"[^>]*>(piece|fodder|sound)( \d+)?</.test(f),
    `blankPieces (${id}): ${n} chips, each a role and a count: ${f.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ")}`);
  check(!f.toUpperCase().replace(/[^A-Z]/g, " ").split(" ").includes(answer),
    `blankPieces (${id}): the formula does not carry the answer`);
  check(!/class="gives"/.test(f), `blankPieces (${id}): no letters in the blank formula`);

  // 2
  const h0 = t.hints();
  check(/data-piece="0"[^>]* disabled/.test(f), `lockedByTier (${id}): chips are disabled while the spotting rungs are down`);
  t.tapChip(0);
  check(t.hints() === h0 && t.chipsGot() === 0 && !/The building blocks/.test(t.body()),
    `lockedByTier (${id}): a tap on a locked chip does nothing and charges nothing`);

  t.take(/indicator/i);
  t.take(/definition/i);
  if (/data-piece="0"[^>]* disabled/.test(t.formula())) continue;
  const h1 = t.hints();

  // 3: the LAST piece first, out of order. The first tap only arms.
  t.tapChip(n - 1);
  // A last piece whose letters are all printed in the clue is free by
  // elimination (blocksFree) and takes one tap; that road has its own test.
  if (t.chipsGot() === 1) continue;
  check(t.hints() === h1 && t.chipsGot() === 0 && /arm-cost/.test(t.formula()) && t.formula().includes(ARMED),
    `firstChipArms (${id}): the first tap arms the chip and charges nothing`);
  t.tapChip(n - 1);
  check(t.hints() === h1 + 1 && t.chipsGot() === 1,
    `firstChipArms (${id}): the second tap takes it and charges one: ${h1} -> ${t.hints()}`);
  check(/The building blocks/.test(t.body()) && (t.body().match(/<li>/g) || []).length >= 1,
    `oneChargeOnly (${id}): the blocks rung is up with the piece in it`);
  t.tapChip(1);
  check(t.hints() === h1 + 1 && t.chipsGot() === 2,
    `oneChargeOnly (${id}): a second chip, in the middle, adds no hint`);
  const next = t.row().find((b) => /^Next building block · /.test(b.textContent || ""));
  check(next && next.textContent === `Next building block · 1 of ${n}`,
    `noRepeat (${id}): next building block is the first piece not out: ${next && next.textContent}`);

  // The rest by the rung's own button: still just the one hint.
  for (let g = 0; g < n + 2; g++) {
    const b = t.row().find((x) => x.onclick && !x.disabled && /^Next building block · /.test(x.textContent || ""));
    if (!b) break;
    b.onclick();
    t.settle();
  }
  check(t.hints() === h1 + 1 && t.chipsLeft() === 0 && t.chipsGot() === n,
    `oneChargeOnly (${id}): every piece out by either road, still one hint: ${h1} -> ${t.hints()}`);
  const listed = (t.body().match(/<li>/g) || []).length;
  check(listed >= n, `noRepeat (${id}): the blocks rung lists the pieces (${listed} items for ${n} pieces)`);

  // 5
  flushTimers(5000);
  const saved = Object.keys(t.d.storage).filter((k) => /^ct:/.test(k) && /piecesPicked/.test(t.d.storage[k]));
  const mask = saved.length ? Object.values(JSON.parse(t.d.storage[saved[0]]).piecesPicked || {})[0] : 0;
  check((mask & (1 << (n - 1))) !== 0 && (mask & 2) !== 0,
    `saved (${id}): the picks are in the save (mask ${mask})`);
  done = true;
  break;
}
check(done, "found a clue with a formula and three pieces to walk");

// 5: the merge keeps both devices' picks.
{
  const a = { v: 1, puzzles: { 1: { piecesPicked: { "1a": 0b001 }, updated: 5 } } };
  const b = { v: 1, puzzles: { 1: { piecesPicked: { "1a": 0b100 }, updated: 9 } } };
  check(mergeSaves(a, b).puzzles[1].piecesPicked["1a"] === 0b101 && mergeSaves(b, a).puzzles[1].piecesPicked["1a"] === 0b101,
    "merged: picks from two devices are ORed together, whichever way round");
}

console.log(failures ? `${failures} FAILURE(S)` : "all passed");
process.exit(failures ? 1 : 0);
