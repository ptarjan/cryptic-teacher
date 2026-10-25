/* The clue's formula: a picture under the type rung, the taps under the
   building blocks rung.

     node tools/test_formula_hint.js

   Paul: "Should what kind of clue this is show the formula? And make pick any
   part of it?" then "is this now just another way of doing building blocks?
   And if so should it be in that part?" So the type rung draws the formula with
   every piece blank (role and letter count only) and nothing to tap; the
   blocks rung draws the same formula whose chips are the taps. A piece is the
   blocks rung's own (app.js pickPiece / the question), so:

   1. blankPicture: the type rung's formula is there, its chips name a role and
      a count, hold nothing of the answer, and are not buttons.
   2. onlyInBlocks: no chip is tappable until the blocks rung is open; the
      "The building blocks" button is how it opens.
   3. chipAsksFirst / fillsIn: in the blocks rung a chip with a question asks it
      (free, or a plain take that adds no hint beyond the rung's own); a chip
      taken fills in with its piece's letters, in any order.
   4. noRepeat: a piece taken by chip is not asked again by "next building
      block", and the rung lists every piece once finished.
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

function open(storage) {
  const d = boot({ query: "?p=" + ID, storage: storage || { "ct:nux": "9" }, twoTap: true });
  const reg = d.registry;
  const puz = global.window.CRYPTIC_PUZZLES[ID];
  const row = () => reg["hint-next"].children;
  const body = () => reg["hint-body"].innerHTML;
  const asking = () => body().includes('class="hint-step guess"');
  const hints = () => Number((/<strong>(\d+)<\/strong> hints used/.exec(reg["scorebar"].innerHTML) || [])[1]);
  const armedBtn = () => row().find((b) => b.textContent === ARMED);
  // Every formula in the panel: the type rung's, then the blocks rung's.
  const formulas = () => body().match(/<div class="formula">[\s\S]*?<\/div>/g) || [];
  const typeFormula = () => formulas()[0] || "";
  const formula = () => formulas()[formulas().length - 1] || "";
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
  return { d, reg, puz, row, body, asking, hints, armedBtn, formula, typeFormula, tapChip, settle, take, chipsLeft, chipsGot };
}

const candidates = open().puz.entries.filter((e) => {
  const a = e.annotation;
  return a && (a.blocks || []).length >= 3 && (a.indicators || []).length && (a.definitions || []).length
    && (a.type || []).length && e.solution;
});

let done = false;
for (const e of candidates.slice(0, 80)) {
  let t = open();
  t.reg["clue-" + entryId(e)].listeners.click[0]();
  const id = entryId(e);
  if (!t.take(/kind of clue/i)) continue;
  const f = t.typeFormula();
  if (!f) continue;
  const n = (f.match(/formula-chip/g) || []).length;
  const answer = String(e.solution).toUpperCase().replace(/[^A-Z]/g, "");

  // 1
  check(n >= 3 && /formula-lead">(definition|answer) \(\d+\) =</.test(f) && /formula-chip">(piece|fodder|sound)( \d+)?</.test(f),
    `blankPicture (${id}): ${n} chips, each a role and a count: ${f.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ")}`);
  check(!f.toUpperCase().replace(/[^A-Z]/g, " ").split(" ").includes(answer),
    `blankPicture (${id}): the formula does not carry the answer`);
  check(!/class="gives"/.test(f) && !/<button|data-piece/.test(f), `blankPicture (${id}): no letters and no buttons in the type rung's formula`);

  // 2
  const h0 = t.hints();
  t.tapChip(0);
  check(t.hints() === h0 && !/The building blocks/.test(t.body()),
    `onlyInBlocks (${id}): a chip tap with the blocks rung shut does nothing and charges nothing`);
  t.take(/indicator/i);
  t.take(/definition/i);
  check(!/data-piece/.test(t.body()) && t.row().some((b) => /The building blocks/.test(b.textContent || "")),
    `onlyInBlocks (${id}): no tappable chip anywhere, and the blocks button is still the way in`);
  // Open the rung and take only its first piece (settle would walk them all).
  const ob = t.row().find((x) => x.onclick && !x.disabled && /The building blocks/.test(x.textContent || ""));
  if (!ob) continue;
  ob.onclick();
  if (t.armedBtn()) t.armedBtn().onclick();
  else if (t.asking()) {
    t.reg["guess-tell"].onclick();
    if (t.asking()) t.reg["guess-tell"].onclick();
  }
  check(/The building blocks/.test(t.body()) && t.chipsGot() > 0,
    `onlyInBlocks (${id}): opening the rung shows the formula in it, filled as the pieces come out`);
  // Most clues here ask one matching question that settles every piece, so
  // wind the save back to ONE piece out and reload: the rest are in the box.
  flushTimers(5000);
  const sk = Object.keys(t.d.storage).find((k) => /blocksAt/.test(t.d.storage[k]));
  if (!sk) continue;
  const sv = JSON.parse(t.d.storage[sk]);
  Object.keys(sv.blocksAt).forEach((k) => { sv.blocksAt[k] = 1; });
  sv.piecesPicked = {};
  const seed = Object.assign({}, t.d.storage);
  seed[sk] = JSON.stringify(sv);
  t = open(seed);
  t.reg["clue-" + entryId(e)].listeners.click[0]();
  const h1 = t.hints();
  const g0 = t.chipsGot();
  check(g0 === 1 && t.chipsLeft() === n - 1,
    `fillsIn (${id}): one piece out fills one chip, the rest are still buttons (${g0} got, ${t.chipsLeft()} left of ${n})`);
  if (g0 !== 1) continue;

  // 3: the LAST piece first, out of order.
  t.tapChip(n - 1);
  const asked = t.asking();
  if (asked) {
    check(t.hints() === h1 && t.chipsGot() === g0,
      `chipAsksFirst (${id}): a chip with a question asks it and charges nothing`);
    t.settle();
  } else if (t.armedBtn() || /arm-cost/.test(t.formula())) {
    check(t.formula().includes(ARMED), `chipAsksFirst (${id}): a costly chip arms and says so on itself`);
    t.tapChip(n - 1);
  }
  check(t.chipsGot() === g0 + 1 && t.hints() === h1,
    `fillsIn (${id}): the last chip is taken, adding no hint beyond the rung: ${h1} -> ${t.hints()}`);
  const got = (t.formula().match(/formula-chip got">([^<]*)</) || [])[1] || "";
  check(got && !/^(piece|fodder|sound)( \d+)?$/.test(got) && t.formula().match(/formula-chip got">[^<]+</g).length === g0 + 1,
    `fillsIn (${id}): a taken chip reads as its piece's text, not its blank (${got})`);
  t.tapChip(g0);
  t.settle();
  check(t.chipsGot() === g0 + 2 && t.hints() === h1,
    `fillsIn (${id}): a second chip, in the middle, adds no hint`);
  const next = t.row().find((b) => /^Next building block · /.test(b.textContent || ""));
  check(next && next.textContent === `Next building block · ${g0 + 2} of ${n}`,
    `noRepeat (${id}): next building block is the first piece not out: ${next && next.textContent}`);

  // The rest by the rung's own button: still no new hint.
  for (let g = 0; g < n + 2; g++) {
    const b = t.row().find((x) => x.onclick && !x.disabled && /^Next building block · /.test(x.textContent || ""));
    if (!b) break;
    b.onclick();
    t.settle();
  }
  check(t.hints() === h1 && t.chipsLeft() === 0 && t.chipsGot() === n,
    `noRepeat (${id}): every piece out by either road, still the rung's own hint: ${h1} -> ${t.hints()}`);
  const listed = (t.body().match(/<li>/g) || []).length;
  check(listed >= n, `noRepeat (${id}): the blocks rung lists the pieces (${listed} items for ${n} pieces)`);

  // 5
  flushTimers(5000);
  const saved = Object.keys(t.d.storage).filter((k) => /^ct:/.test(k) && /piecesPicked/.test(t.d.storage[k]));
  const mask = saved.length ? Object.values(JSON.parse(t.d.storage[saved[0]]).piecesPicked || {})[0] : 0;
  check((mask & (1 << (n - 1))) !== 0,
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
