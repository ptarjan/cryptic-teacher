"""Stage 11: clue-surface and answer-form candidates, screened on both sets.

    STAGE10_ROWS=~/.cache/cryptic-stage10-shipped.json nice -n 19 python3 scratch/snitch_stage10.py dump
    nice -n 19 python3 scratch/snitch_stage11.py dump   # candidates onto a copy of them
    nice -n 19 python3 scratch/snitch_stage11.py test   # every candidate, both sets, held out, + margin

Base rows are stage 10's dump under the shipped index (clue_count in); this
only swaps each row's candidates, then reuses stage 10's test and margin.
Signs fixed in CANDIDATES before measuring:
  surface_words     mean words per clue surface: more text to parse and
                    more places to hide the definition
  multiword_answers share of answers the enumeration splits: the word breaks
                    are given away, and phrases fall to crossers (easier, -1)
  homophone_share   share of clues with a sound indicator or Spooner
  exclaim_share     share of clues ending "!", the usual &lit / all-in-one flag
  inflected_answers share of single-word answers that are an inflection (-S,
                    -ED, -ING, -ER, -EST) of a lexicon word: the ending falls
                    to the crossers and the wordplay usually builds it as a
                    tacked-on piece (easier, -1)

Result (2026-09-27): none adopted. Held-out mean rho, base annotated .499 /
fresh .331 / Sunday .453, margin .159:
  surface_words     .483 / .318 / .335, margin .138  (raw +.22, but redundant)
  multiword_answers .459 / .246 / .416, margin .204  (raw +.19: prior sign wrong)
  homophone_share   .477 / .292 / .450, margin .137
  exclaim_share     .498 / .329 / .431, margin .096
  inflected_answers .478 / .323 / .441, margin .204
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scratch"))
import difficulty as D
import snitch_stage10 as S10
from fetch_puzzle import read_puzzle_file
import puzzle_paths

BASE = Path(os.environ.get("STAGE10_ROWS") or Path.home() / ".cache" / "cryptic-stage10-shipped.json")
CACHE = Path(os.environ.get("STAGE11_ROWS") or Path.home() / ".cache" / "cryptic-stage11-rows.json")
CANDIDATES = {"surface_words": +1, "multiword_answers": -1, "homophone_share": +1,
              "exclaim_share": +1, "inflected_answers": -1}
SOUND = re.compile(r"(?i)\b(sounds?|sounding|heard|hear|say|said|reportedly|reported|"
                   r"aloud|audibly|audible|spoken|speaking|vocal(ly)?|radio|broadcast|"
                   r"on the air|listeners?|audience|out loud|oral(ly)?|pronounced|"
                   r"spooner(ism)?|spooner's)\b")
ENDINGS = (("ING", ("", "E")), ("ED", ("", "E")), ("EST", ("", "E")), ("ER", ("", "E")),
           ("ES", ("",)), ("S", ("",)))


def inflected(word, rank):
    w = word.upper()
    for end, adds in ENDINGS:
        e = end
        if len(w) - len(e) >= 3 and w.endswith(e):
            stem = w[: -len(e)]
            cands = [stem + a for a in adds]
            if len(stem) >= 2 and stem[-1] == stem[-2]:
                cands.append(stem[:-1])
            if e in ("ED", "ER", "EST", "ES") and stem.endswith("I"):
                cands.append(stem[:-1] + "Y")
            if any(c in rank for c in cands):
                return True
    return False


def cand(puz, rank):
    ents = [e for e in puz["entries"] if e.get("solution")]
    if not ents:
        return None
    words, sound, bang, real = [], 0, 0, 0
    multi, infl, single = 0, 0, 0
    for e in ents:
        sol, parts = D.answer_words(e)
        multi += len(parts) > 1
        if len(parts) == 1 and sol:
            single += 1
            infl += inflected(sol, rank)
        raw = e["clue"].get("text", "").strip()
        clue = D.ENUMERATION.sub("", raw).strip()
        if not clue or re.match(r"(?i)see\b", clue):
            continue
        real += 1
        words.append(len(clue.split()))
        sound += bool(SOUND.search(clue))
        bang += clue.rstrip("\"'’” ").endswith("!")
    if not real:
        return None
    return {"surface_words": sum(words) / real, "multiword_answers": multi / len(ents),
            "homophone_share": sound / real, "exclaim_share": bang / real,
            "inflected_answers": infl / single if single >= 10 else None}


def dump():
    rows = json.loads(BASE.read_text())
    rank = D.ranks()
    for r in rows:
        r["cand"] = cand(read_puzzle_file(puzzle_paths.find(r["pid"])), rank)
    CACHE.write_text(json.dumps(rows))
    print(len(rows), "rows")


if __name__ == "__main__":
    cmd = sys.argv[1]
    S10.CACHE, S10.CANDIDATES = CACHE, CANDIDATES
    if cmd == "dump":
        dump()
    elif cmd == "test":
        S10.test(sys.argv[2:] or list(CANDIDATES))
