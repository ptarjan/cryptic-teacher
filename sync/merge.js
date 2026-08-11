/* Merging two saves of the same puzzles, without a "which device wins?" prompt.

   Solving a crossword is monotone: you fill squares in, you put hint rungs up,
   you reveal letters. Nothing gets un-done except a deliberate reset. So two
   devices that drifted apart do not actually conflict — each just knows some
   things the other does not, and the merge is a union.

   Every rule below is commutative and associative (union, max, min, and a
   tiebreak on a timestamp that is part of the data). That is the whole point:
   the browser merges what it pulled into what it has, the Worker merges what
   was pushed into what it stored, and neither has to care what order the
   devices showed up in, or whether one of them was offline for a week.

   Shared by the browser and the Worker so there is exactly one copy of the
   rules — a second copy would drift, and the failure mode is silently losing
   someone's solve. Loaded as a plain <script> in the page and imported by the
   Worker, hence the UMD wrapper. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CTMerge = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
  const num = (v) => (typeof v === "number" && isFinite(v) ? v : 0);

  // Every map the merge builds is written in sorted key order. The rules are
  // already order-independent in meaning, but JSON is not: iterating a's keys
  // then b's puts them in a different order depending on which side you were
  // standing, and the two devices would then hold byte-different files that say
  // the same thing. That is enough to defeat every "did anything change?"
  // comparison in the client and to make the Worker rewrite KV on every push.
  function eachKey(a, b, fn) {
    const seen = Object.create(null);
    const keys = Object.keys(isObj(a) ? a : {}).concat(Object.keys(isObj(b) ? b : {}))
      .filter((k) => (seen[k] ? false : (seen[k] = 1)));
    keys.sort();
    const out = {};
    keys.forEach((k) => { out[k] = fn(k); });
    return out;
  }

  // Union of two arrays of rung keys, de-duplicated and sorted. Which rungs are
  // up is a set, not a sequence — app.js only ever asks this list for its length
  // and whether it contains a given rung, and the panel draws the rungs in
  // ladder order regardless — so sorting costs nothing and buys the byte-for-byte
  // identical result on both devices that eachKey is after.
  function unionRungs(a, b) {
    const out = [];
    const seen = Object.create(null);
    [].concat(Array.isArray(a) ? a : [], Array.isArray(b) ? b : []).forEach((k) => {
      if (typeof k === "string" && !seen[k]) { seen[k] = 1; out.push(k); }
    });
    return out.sort();
  }

  // A letter is "A", or "A!" if it was revealed rather than worked out.
  //
  // The first version of this treated an absent square as "this device knows
  // nothing about it" and let the other side's letter through. That is only
  // half of what absence means. Rubbing a letter out also leaves the square
  // absent, so a deletion could never win: you cleared two squares, the other
  // device still had them, and the merge politely put them back — for ever,
  // because pushing your own save never removed them from the server either
  // (Paul, 2026-08-10).
  //
  // So absence is no longer read from the letters map alone. Each square
  // carries its own stamp in `letterAt`, written whenever that square changes,
  // INCLUDING when it is emptied. A stamp with no letter is a deletion, and it
  // travels like any other edit: the most recent thing you did to a square is
  // what both devices end up showing.
  //
  // Only when the two stamps are identical does anything else matter, and then
  // a revealed letter beats a guess (it is the answer, not an opinion) and
  // otherwise the lexicographically larger wins — arbitrary, but the same
  // arbitrary choice on both sides, which is what stops the two ends of a sync
  // from disagreeing forever.
  function pickLetter(av, at, bv, bt) {
    if (at !== bt) return at > bt ? av : bv;
    if (av === undefined) return bv;
    if (bv === undefined) return av;
    const ar = av.length > 1, br = bv.length > 1;
    if (ar !== br) return ar ? av : bv;
    return av >= bv ? av : bv;
  }

  function mergePuzzle(a, b) {
    // No shortcut for "only one side has this puzzle": returning that side
    // unchanged hands back whatever shape it happened to arrive in, and the
    // next merge normalises it, so merging twice would produce a different
    // file from merging once. Everything goes through the same rules, so the
    // output is canonical no matter what came in.
    a = isObj(a) ? a : {};
    b = isObj(b) ? b : {};
    const at = num(a.updated), bt = num(b.updated);

    // "Reset puzzle" is the one thing a solver does that is not an edit to some
    // particular square — it is an edit to all of them at once, including the
    // ones this device never filled in and so has no stamp for. Rather than
    // manufacture a stamp per square, the reset is recorded as a single moment,
    // and anything older than the newest reset either side knows about is
    // dropped. Without this, resetting on the laptop just meant the iPad
    // refilled the grid.
    const clearedAt = Math.max(num(a.clearedAt), num(b.clearedAt));

    const aAt = isObj(a.letterAt) ? a.letterAt : {};
    const bAt = isObj(b.letterAt) ? b.letterAt : {};
    // Saves written before per-square stamps existed fall back to the one time
    // the whole puzzle carries. Coarse, but it is the truth about that data —
    // and it self-corrects the first time either device touches the square.
    const stamp = (m, k, whole) => (typeof m[k] === "number" && isFinite(m[k]) ? m[k] : whole);

    const al = isObj(a.letters) ? a.letters : {};
    const bl = isObj(b.letters) ? b.letters : {};
    const everyAt = eachKey(
      { ...al, ...aAt }, { ...bl, ...bAt },
      (k) => Math.max(stamp(aAt, k, al[k] === undefined ? 0 : at),
                      stamp(bAt, k, bl[k] === undefined ? 0 : bt))
    );
    const letters = {}, letterAt = {};
    Object.keys(everyAt).forEach((k) => {
      // A stamp from before the last reset is not history worth keeping: the
      // square was emptied, and dropping the stamp too is what stops letterAt
      // growing a permanent record of every square ever typed in.
      if (everyAt[k] < clearedAt) return;
      letterAt[k] = everyAt[k];
      const v = pickLetter(al[k], stamp(aAt, k, al[k] === undefined ? 0 : at),
                           bl[k], stamp(bAt, k, bl[k] === undefined ? 0 : bt));
      if (v !== undefined) letters[k] = v;
    });

    // Hints and scores have no per-key stamps — they only ever grow, so they
    // never needed one. A reset is the exception, and the whole side is judged
    // by when it last saved: a device that has not been touched since the reset
    // has nothing to contribute that the reset did not mean to throw away.
    const liveA = at >= clearedAt, liveB = bt >= clearedAt;
    const ah = liveA && isObj(a.hintsShown) ? a.hintsShown : {};
    const bh = liveB && isObj(b.hintsShown) ? b.hintsShown : {};
    const hintsShown = eachKey(ah, bh, (k) => unionRungs(ah[k], bh[k]));

    // Reveals are spent, not earned: if one device burned three letters on this
    // clue that happened, and the merge must not hand them back.
    const ar = liveA && isObj(a.revealsUsed) ? a.revealsUsed : {};
    const br = liveB && isObj(b.revealsUsed) ? b.revealsUsed : {};
    const revealsUsed = eachKey(ar, br, (k) => Math.max(num(ar[k]), num(br[k])));

    // How many rungs were up when the clue first fell. "First" has no meaning
    // across two clocks, so take the better score. It is the answer you would
    // get if you had done all of this on one machine and solved it on the try
    // that went well, and unlike max it cannot be made worse by syncing.
    const as = liveA && isObj(a.solvedWith) ? a.solvedWith : {};
    const bs = liveB && isObj(b.solvedWith) ? b.solvedWith : {};
    const solvedWith = eachKey(as, bs, (k) => {
      const av = as[k], bv = bs[k];
      return av === undefined ? bv : bv === undefined ? av : Math.min(num(av), num(bv));
    });

    return { letters, letterAt, hintsShown, revealsUsed, solvedWith,
             clearedAt, updated: Math.max(at, bt) };
  }

  /* Envelope: { v: 1, puzzles: { "<id>": <save> }, last: { id, updated } }.
     `last` is which puzzle you had open, which is genuinely last-write-wins —
     it is a cursor, not progress, and losing it costs one click. */
  function mergeSaves(a, b) {
    a = isObj(a) ? a : {};
    b = isObj(b) ? b : {};
    const ap = isObj(a.puzzles) ? a.puzzles : {};
    const bp = isObj(b.puzzles) ? b.puzzles : {};
    const puzzles = eachKey(ap, bp, (id) => mergePuzzle(ap[id], bp[id]));
    const al = isObj(a.last) ? a.last : null;
    const bl = isObj(b.last) ? b.last : null;
    const last = !al ? bl : !bl ? al : (num(bl.updated) > num(al.updated) ? bl : al);
    const out = { v: 1, puzzles };
    if (last && last.id) out.last = { id: String(last.id), updated: num(last.updated) };
    return out;
  }

  return { mergeSaves, mergePuzzle, unionRungs, pickLetter };
});
