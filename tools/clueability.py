#!/usr/bin/env python3
"""How easy is a word to write a cryptic clue FOR?

The point: a grid fill that is legal is not the same as a grid fill that is
settable. If the filler only optimises for "these words interlock", it happily
hands the setter an entry like ENTRUSTED — a common enough word with almost no
wordplay purchase — or, worse, an obscurity nobody can define fairly. Real
setters bin a fill for exactly that reason, so clueability belongs INSIDE the
fill, not in a review afterwards. See tools/AUTHORING.md.

Source data is the Lufz lexicon via tools/data/lexicon.tsv (see
tools/build_lexicon.js): UKACD18 cleaned up, ordered by Wikipedia-derived
importance, with CMUdict pronunciations. Two consequences worth knowing:

  * the lexicon INDEX is the fairness signal — rank 300 is a word every solver
    knows, rank 150,000 is one they don't;
  * homophones are grouped on real pronunciations, so "sounds like" is a
    phonetic fact here, not a spelling guess.

The hooks scored, in rough order of how much a setter values them:

  anagram      the letters spell something else, or something else plus a
               standard abbreviation (the anagram+charade hybrid)
  charade      splits into 2-3 pieces that are each a word or a standard
               crossword abbreviation (CARPET = CAR + PET)
  container    the word is X wrapped round Y, both known pieces
  homophone    another word shares its pronunciation
  reversal     the whole word reversed is a word (STRESSED/DESSERTS), or it
               contains a reversed word
  deletion     one letter added to, or removed from, another word
  hidden       weak: hiding an answer is mostly a property of the CLUE, not the
               answer, so this only measures whether the letter runs are
               ordinary enough to bury in a surface without looking spelled out
  senses       weakest of all: a proxy for "has several meanings", i.e. can
               support a double definition. We have no sense inventory, so this
               blends importance with the size of the word's morphological
               family (EARTH has forty relatives in the lexicon, ERIC has two).
               A nudge, never a reason.

Plus a fairness floor that is not a hook at all: the word has to be one a solver
plausibly knows. An unclueable obscurity is worse than a boring common word.

The pieces a hook may use are themselves restricted to reasonably well known
words plus tools/data/abbreviations.json. A charade whose second half is
AASVOGEL is not a hook.

Usage:
  python3 tools/clueability.py --word CARPET      explain one word's hooks
  python3 tools/clueability.py --build            (re)build the cache
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
DATA = TOOLS / "data"
LEXICON = DATA / "lexicon.tsv"
ABBREV_FILE = DATA / "abbreviations.json"
CACHE = DATA / "clueability.tsv"

# Bump when the scoring changes, so a stale cache is rebuilt rather than trusted.
CACHE_VERSION = 7

# Hook weights, out of 100. Deliberately unequal: an anagram or a charade is a
# clue you can definitely write, a reversal only sometimes, and the last two are
# hints rather than hooks (see the module docstring).
W_ANAGRAM = 20
W_NEAR_ANAGRAM = 8
W_CHARADE = 20
W_CONTAINER = 14
W_HOMOPHONE = 10
W_REVERSAL_FULL = 10
W_REVERSAL_PART = 4
W_DELETION = 8
W_HIDDEN = 4
W_SENSES = 10

# Words at least this familiar may be used as charade/container pieces, may be
# an anagram partner, and so on. Rank ~70,000 in Lufz; below that a solver
# cannot be expected to spot the piece, so it is not really a hook.
PIECE_FLOOR = 8


def familiarity(rank, total):
    """Lexicon rank -> 0-100. Log scale, because importance is Zipfian: on a
    linear scale "the" would be 100 and everything else 0."""
    if rank <= 0:
        return 0
    return max(0, min(100, int(round(100 * (1 - math.log(rank) / math.log(total))))))


def load_lexicon(path=LEXICON, british_only=True):
    """Returns (fam {word: familiarity 0-100}, phones {word: phone key},
    family {word: stem-group size}). Empty if the lexicon has not been fetched —
    callers must handle that.

    british_only drops spellings the Lufz "Britain" region replaces. This is not
    pedantry: the first fill produced by this tool answered KILOMETERS in a
    Guardian-style grid, which a British solver would (rightly) call an error."""
    if not path.exists():
        return {}, {}, {}
    lines = path.read_text(encoding="utf-8").splitlines()
    body = lines[1:] if lines and lines[0].startswith("#lufz") else lines
    total = max(len(body), 2)
    fam, phones, family = {}, {}, {}
    for line in body:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        w, rank, gb = parts[0], int(parts[1]), parts[2]
        if british_only and gb == "0":
            continue
        fam[w] = familiarity(rank, total)
        family[w] = int(parts[3])
        if len(parts) > 4 and parts[4]:
            phones[w] = parts[4]
    return fam, phones, family


def load_abbreviations(path=ABBREV_FILE):
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["abbreviations"]


class Clueability:
    """Precomputes the indexes every hook test needs, then scores words."""

    def __init__(self, fam, phones, family, abbrevs, piece_floor=PIECE_FLOOR):
        self.fam = fam
        self.family = family
        self.abbrevs = set(abbrevs)
        # Pieces a solver can be expected to recognise. Single letters are only
        # pieces if they are abbreviations (A, I, O, R…), never because some
        # word list contains "b".
        self.known = {w for w, s in fam.items() if s >= piece_floor}
        self.pieces = {w for w in self.known if len(w) >= 2} | self.abbrevs
        # sorted-letters -> count, so "is this an anagram of something?" is a
        # dict lookup rather than a scan.
        self.anagrams = {}
        for w in self.known:
            k = "".join(sorted(w))
            self.anagrams[k] = self.anagrams.get(k, 0) + 1
        # phone key -> count, from CMUdict: a real homophone test.
        self.homophones = {}
        for w in self.known:
            p = phones.get(w)
            if p:
                self.homophones[p] = self.homophones.get(p, 0) + 1
        self.phones = phones
        # Trigram commonness, for the (weak) hidden-word signal.
        self.trigrams = {}
        for w in self.known:
            for i in range(len(w) - 2):
                t = w[i:i + 3]
                self.trigrams[t] = self.trigrams.get(t, 0) + 1
        self.abbrev_sorted = sorted({(a, "".join(sorted(a))) for a in self.abbrevs})

    # -- individual hooks -------------------------------------------------

    def has_anagram(self, w):
        return self.anagrams.get("".join(sorted(w)), 0) > (1 if w in self.known else 0)

    def has_near_anagram(self, w):
        """Letters minus a standard abbreviation still anagram to a word — the
        very common "anagram of X, plus H for hard" construction."""
        counts = {}
        for ch in w:
            counts[ch] = counts.get(ch, 0) + 1
        for _, ab in self.abbrev_sorted:
            rem = dict(counts)
            for ch in ab:
                if rem.get(ch, 0) == 0:
                    break
                rem[ch] -= 1
            else:
                rest = "".join(sorted("".join(c * n for c, n in rem.items())))
                if len(rest) >= 3 and self.anagrams.get(rest):
                    return True
        return False

    def has_homophone(self, w):
        p = self.phones.get(w)
        return bool(p) and self.homophones.get(p, 0) > 1

    def charade_splits(self, w, limit=4):
        """Splits into 2 or 3 recognisable pieces. Returns up to `limit` of them
        so a later clue-writing stage can read the options straight off."""
        out = []
        n = len(w)
        for i in range(1, n):
            a, b = w[:i], w[i:]
            if a in self.pieces and b in self.pieces:
                out.append((a, b))
                if len(out) >= limit:
                    return out
        for i in range(1, n - 1):
            if w[:i] not in self.pieces:
                continue
            for j in range(i + 1, n):
                a, b, c = w[:i], w[i:j], w[j:]
                if b in self.pieces and c in self.pieces:
                    out.append((a, b, c))
                    if len(out) >= limit:
                        return out
        return out

    def container_splits(self, w, limit=3):
        """w = OUTER round INNER: outer is w with a middle chunk removed."""
        out = []
        n = len(w)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                inner, outer = w[i:j], w[:i] + w[j:]
                if len(inner) >= 2 and inner in self.pieces and outer in self.pieces:
                    out.append((outer, inner))
                    if len(out) >= limit:
                        return out
        return out

    def reversal(self, w):
        """2 = the whole word reverses to a word, 1 = it swallows a reversed
        word, 0 = nothing to reverse."""
        if w[::-1] in self.known and w[::-1] != w:
            return 2
        for size in range(len(w) - 1, 3, -1):
            for i in range(len(w) - size + 1):
                s = w[i:i + size]
                if s != s[::-1] and s[::-1] in self.known:
                    return 1
        return 0

    def deletion(self, w):
        """One letter shorter, or one letter longer, than a known word."""
        for i in range(len(w)):
            if w[:i] + w[i + 1:] in self.known:
                return True
        for i in range(len(w) + 1):
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if w[:i] + ch + w[i:] in self.known:
                    return True
        return False

    def hidden(self, w):
        """Fraction of trigrams that are commonplace. A word made of ordinary
        letter runs (…ATION…) can be buried in a surface; QWERTZ cannot. The
        weakest structural signal here, weighted accordingly."""
        tris = [w[i:i + 3] for i in range(len(w) - 2)]
        if not tris:
            return 0.0
        return sum(1 for t in tris if self.trigrams.get(t, 0) >= 5) / len(tris)

    # -- combined ---------------------------------------------------------

    def analyse(self, w):
        fam = self.fam.get(w, 0)
        charades = self.charade_splits(w)
        containers = self.container_splits(w)
        rev = self.reversal(w)
        hid = self.hidden(w)
        hooks = {
            "anagram": self.has_anagram(w),
            "family": self.family.get(w, 1),
            "near_anagram": self.has_near_anagram(w),
            "homophone": self.has_homophone(w),
            "charade": charades,
            "container": containers,
            "reversal": rev,
            "deletion": self.deletion(w),
            "hidden": hid,
            "familiarity": fam,
        }
        score = 0
        if hooks["anagram"]:
            score += W_ANAGRAM
        if hooks["near_anagram"]:
            score += W_NEAR_ANAGRAM
        if hooks["homophone"]:
            score += W_HOMOPHONE
        # More splits is genuinely better (more ways to clue it), but with
        # diminishing returns — three charades is not three times one.
        score += W_CHARADE * min(len(charades), 3) / 3
        score += W_CONTAINER * min(len(containers), 2) / 2
        score += W_REVERSAL_FULL if rev == 2 else (W_REVERSAL_PART if rev else 0)
        if hooks["deletion"]:
            score += W_DELETION
        score += W_HIDDEN * hid
        # Double-definition proxy. Morphological family size beats raw frequency
        # here: EARTH has forty relatives in the lexicon and a dozen senses,
        # while ERIC has two (ERIC, ERICS) because it is really a name wearing a
        # lowercase hat. Blended with familiarity so a common word with few
        # derived forms (TEMPO, SAMBA) is not punished twice.
        fams = min(fam, 40) / 40
        kin = min(hooks["family"], 12) / 12
        score += W_SENSES * (0.5 * fams + 0.5 * kin)
        return min(100, int(round(score))), hooks

    def flags(self, hooks):
        return "".join([
            "A" if hooks["anagram"] else "",
            "N" if hooks["near_anagram"] else "",
            "C" if hooks["charade"] else "",
            "X" if hooks["container"] else "",
            "P" if hooks["homophone"] else "",
            "R" if hooks["reversal"] == 2 else ("r" if hooks["reversal"] else ""),
            "D" if hooks["deletion"] else "",
            "H" if hooks["hidden"] >= 0.5 else "",
        ]) or "-"


def build_cache(min_len=3, max_len=15, min_familiarity=PIECE_FLOOR, verbose=True):
    """Score every plausibly fillable word once, into tools/data/clueability.tsv.

    Derived data, so it is gitignored: a minute to rebuild, and a stale cache
    that disagrees with the scorer would be worse than no cache."""
    fam, phones, family = load_lexicon()
    if not fam:
        raise SystemExit(f"{LEXICON} missing — run: bash tools/fetch_lexicon.sh")
    cl = Clueability(fam, phones, family, load_abbreviations())
    t0 = time.time()
    targets = sorted(w for w, s in fam.items()
                     if s >= min_familiarity and min_len <= len(w) <= max_len)
    rows = []
    for i, w in enumerate(targets):
        score, hooks = cl.analyse(w)
        rows.append(f"{w}\t{score}\t{fam[w]}\t{cl.flags(hooks)}")
        if verbose and i % 10000 == 0 and i:
            print(f"  scored {i}/{len(targets)}…", file=sys.stderr)
    CACHE.write_text(
        f"#clueability v{CACHE_VERSION}\twords={len(rows)}\n" + "\n".join(rows) + "\n",
        encoding="ascii")
    if verbose:
        print(f"wrote {CACHE} — {len(rows)} words in {time.time() - t0:.1f}s",
              file=sys.stderr)
    return cl


def load_cache():
    """Returns {word: (clue_score, familiarity, flags)} or None if unusable."""
    if not CACHE.exists():
        return None
    lines = CACHE.read_text(encoding="ascii").splitlines()
    if not lines or not lines[0].startswith(f"#clueability v{CACHE_VERSION}\t"):
        return None
    out = {}
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) == 4:
            out[parts[0]] = (int(parts[1]), int(parts[2]), parts[3])
    return out or None


def scores(rebuild=False):
    """The filler's entry point: cached clueability, built on first use."""
    if not rebuild:
        cached = load_cache()
        if cached:
            return cached
    build_cache()
    return load_cache()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word", help="explain the hooks for one word")
    ap.add_argument("--build", action="store_true", help="rebuild the cache")
    ap.add_argument("--top", type=int, help="show the N best-hooked words of a length")
    ap.add_argument("--length", type=int, default=8)
    args = ap.parse_args()

    if args.word:
        fam, phones, family = load_lexicon()
        cl = Clueability(fam, phones, family, load_abbreviations())
        w = args.word.strip().upper()
        score, hooks = cl.analyse(w)
        print(f"{w}: clueability {score}/100, familiarity {hooks['familiarity']}/100 "
              f"[{cl.flags(hooks)}]")
        for k in ("anagram", "near_anagram", "homophone", "reversal", "deletion",
                  "family"):
            print(f"  {k}: {hooks[k]}")
        print(f"  hidden (trigram commonness): {hooks['hidden']:.2f}")
        for a in hooks["charade"]:
            print(f"  charade: {' + '.join(a)}")
        for outer, inner in hooks["container"]:
            print(f"  container: {outer} round {inner}")
        return 0

    if args.build:
        build_cache()
        return 0

    tbl = scores()
    best = sorted(((v[0], k) for k, v in tbl.items() if len(k) == args.length), reverse=True)
    for s, w in best[:args.top or 20]:
        print(f"{s:3d}  {w}  [{tbl[w][2]}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
