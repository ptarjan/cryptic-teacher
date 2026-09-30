"""Stage 13: the YouTube solvers' per-clue winners as puzzle components.

    STAGE10_ROWS=~/.cache/cryptic-stage13-base.json nice -n 19 python3 scratch/snitch_stage10.py dump
    nice -n 19 python3 scratch/snitch_stage13.py dump   # candidates onto a copy of them
    nice -n 19 python3 scratch/snitch_stage13.py test   # every candidate, both sets, held out, + margin

scratch/solver_clues.py found, per clue and held out by puzzle, that answer
length is the one clue fact the index lacks that tracks the solvers' waits
(+.18 alone; the per-clue composite +.142 -> +.180 with it at 0.25), and that
the annotation's block count (wordplay pieces) beats machinery. A per-clue
fact only reaches the index as a puzzle mean, so these are screened here by
the adoption rule. Signs fixed before measuring:
  answer_length   mean letters per answer, cross-references ("See 5") out:
                  a long answer waits longest for its crossers (+1)
  long_answers    share of answers of 10+ letters (+1)
  blocks_per_clue mean wordplay blocks per annotated clue (+1, annotated only)

Result (2026-09-30): none adopted. Base on a fresh dump, held-out mean rho:
annotated .415 (n=744) / fresh .338 (n=1860) / Sunday .407, margin .160.
  answer_length    .395 / .319 / .351, margin .109; raw -.036 / -.048
  long_answers     .383 / .316 / .390, margin .077
  blocks_per_clue  .406 / (annotated only) / .378, margin .219; raw +.132
  machinery -> blocks_per_clue (swap)  .402 / Sunday .400, margin .178
Length runs the WRONG way between puzzles: within a puzzle the long answers
are solved last (they wait for crossers), but a grid of long answers is no
slower overall, and Times for the Times commenters barely call long answers
hard (+.034 per clue). The solvers' length signal is solving order, not
difficulty the NITCH sees.
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
import snitch_stage4 as S4
import snitch_stage10 as S10
from fetch_puzzle import puzzle_is_annotated, read_puzzle_file
import puzzle_paths

BASE = Path(os.environ.get("STAGE10_ROWS") or Path.home() / ".cache" / "cryptic-stage13-base.json")
CACHE = Path(os.environ.get("STAGE13_ROWS") or Path.home() / ".cache" / "cryptic-stage13-rows.json")
CANDIDATES = {"answer_length": +1, "long_answers": +1, "blocks_per_clue": +1}
LONG = 10


def cand(puz):
    lens, blocks = [], []
    for e in puz["entries"]:
        sol, _ = D.answer_words(e)
        clue = e["clue"].get("text", "").strip()
        if not sol or not clue or re.match(r"(?i)see\b", clue):
            continue
        lens.append(len(sol))
        ann = e.get("annotation") or {}
        if ann.get("type"):
            blocks.append(len(ann.get("blocks") or []))
    if not lens:
        return None
    return {"answer_length": sum(lens) / len(lens),
            "long_answers": sum(n >= LONG for n in lens) / len(lens),
            "blocks_per_clue": sum(blocks) / len(blocks) if blocks and puzzle_is_annotated(puz) else None}


def dump():
    rows = S4.load_rows(BASE)
    for r in rows:
        r["cand"] = cand(read_puzzle_file(puzzle_paths.find(r["pid"])))
    CACHE.write_text(json.dumps(rows, default=str))
    print(len(rows), "rows")


def swap(old, new, w=0.25):
    """The annotated set with component `old` replaced by candidate `new` at
    the same weight: rows' z of `old` out, the candidate's row z in."""
    rows = S4.load_rows(CACHE)
    xs = [r["cand"][new] for r in rows if r["cand"] and r["cand"].get(new) is not None]
    m = sum(xs) / len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** .5
    for r in rows:
        if r["index"] is None:
            r["new"] = None
            continue
        z, tot = dict(r["z"]), S4.full_w(r)
        acc = r["index"] * tot
        if old in z:
            acc -= D.WEIGHTS[old] * z[old]
            tot -= D.WEIGHTS[old]
        v = (r["cand"] or {}).get(new)
        if v is not None:
            acc += w * (v - m) / sd
            tot += w
        r["new"] = acc / tot
    sel = S4.SETS["annotated"][2]
    print(f"{old} -> {new}: times {S4.fmt(S4.heldout(rows, 'new', sel))}")
    print(f"{'':{len(old) + len(new) + 6}s}sunday {S4.fmt(S4.heldout(rows, 'new', sel, 'sundaytimes'))}"
          f"  margin {S10.margin(rows, 'new'):+.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    S10.CACHE, S10.CANDIDATES = CACHE, CANDIDATES
    if cmd == "dump":
        dump()
    elif cmd == "test":
        S10.test(sys.argv[2:] or list(CANDIDATES))
    elif cmd == "swap":        # swap machinery blocks_per_clue
        swap(sys.argv[2], sys.argv[3])
