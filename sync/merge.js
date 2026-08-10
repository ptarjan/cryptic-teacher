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
  // Two devices can only disagree here if you typed different guesses into the
  // same square. A revealed letter is not a guess, it is the answer, so it wins
  // outright; otherwise the more recent guess wins, and if even the clocks tie
  // we pick the lexicographically larger one — arbitrary, but the same
  // arbitrary choice on both sides, which is what stops the two ends of a sync
  // from disagreeing forever.
  function pickLetter(av, at, bv, bt) {
    if (av === undefined) return bv;
    if (bv === undefined) return av;
    const ar = av.length > 1, br = bv.length > 1;
    if (ar !== br) return ar ? av : bv;
    if (at !== bt) return at > bt ? av : bv;
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

    const al = isObj(a.letters) ? a.letters : {};
    const bl = isObj(b.letters) ? b.letters : {};
    const letters = eachKey(al, bl, (k) => pickLetter(al[k], at, bl[k], bt));

    const ah = isObj(a.hintsShown) ? a.hintsShown : {};
    const bh = isObj(b.hintsShown) ? b.hintsShown : {};
    const hintsShown = eachKey(ah, bh, (k) => unionRungs(ah[k], bh[k]));

    // Reveals are spent, not earned: if one device burned three letters on this
    // clue that happened, and the merge must not hand them back.
    const ar = isObj(a.revealsUsed) ? a.revealsUsed : {};
    const br = isObj(b.revealsUsed) ? b.revealsUsed : {};
    const revealsUsed = eachKey(ar, br, (k) => Math.max(num(ar[k]), num(br[k])));

    // How many rungs were up when the clue first fell. "First" has no meaning
    // across two clocks, so take the better score. It is the answer you would
    // get if you had done all of this on one machine and solved it on the try
    // that went well, and unlike max it cannot be made worse by syncing.
    const as = isObj(a.solvedWith) ? a.solvedWith : {};
    const bs = isObj(b.solvedWith) ? b.solvedWith : {};
    const solvedWith = eachKey(as, bs, (k) => {
      const av = as[k], bv = bs[k];
      return av === undefined ? bv : bv === undefined ? av : Math.min(num(av), num(bv));
    });

    return { letters, hintsShown, revealsUsed, solvedWith, updated: Math.max(at, bt) };
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
