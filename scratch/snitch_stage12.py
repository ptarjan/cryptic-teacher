"""Stage 12: blog-fact candidates, screened on both sets.

    STAGE10_ROWS=~/.cache/cryptic-stage10-shipped.json nice -n 19 python3 scratch/snitch_stage10.py dump
    nice -n 19 python3 scratch/snitch_stage12.py dump   # candidates onto a copy of them
    nice -n 19 python3 scratch/snitch_stage12.py test   # every candidate, both sets, held out, + margin

Base rows are stage 10's dump under the shipped index; this only swaps each
row's candidates, then reuses stage 10's test and margin. Every candidate reads
tools/data/blog_facts/ (the blogger's markup plus letter_facts.py's inferred
fills), which covers unannotated puzzles too, so each applies to the fresh set.
A puzzle with fewer than FLOOR clues carrying the fact gets None (base kept).
Signs fixed in CANDIDATES before measuring:
  def_at_end        share of single-definition clues whose definition ends
                    the clue rather than opens it: solvers try the first
                    words as the definition first, and a trailing definition
                    leaves the misleading surface subject up front (+1)
  abbrev_blocks     share of wordplay blocks that are 1-2 letters standing
                    for a longer clue word (E = English, T = trotters): the
                    stock crosswordese lookups a regular reads straight off,
                    so a clue built from them is formulaic (easier, -1)
  indicators_per_clue  indicators the facts mark per clue with any facts:
                    more operations to spot and apply (+1)
  def_length_ratio  mean letters of a single definition span over the
                    answer's letters, the whole-clue (cryptic) definitions
                    excluded: a longer definition describes more and is
                    easier to recognise (easier, -1)

Result (2026-09-27): none adopted. Held-out mean rho, base annotated .499 /
fresh .331 / Sunday .453, margin .159 (coverage ~98% of both sets):
  def_at_end          .480 / .317 / .387, margin .079  (raw ~0 on both)
  abbrev_blocks       .493 / .335 / .386, margin .082  (fresh 2/3 thirds, raw -.08 fresh)
  indicators_per_clue .481 / .321 / .435, margin .133
  def_length_ratio    .507 / .346 / .435, margin .182  (best: up on both means and
                      the margin, but loses annotated third 1 (.463 -> .456) and
                      fresh third 3 (.333 -> .332) and Sunday falls)
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
from fetch_puzzle import read_puzzle_file
import puzzle_paths

BASE = Path(os.environ.get("STAGE10_ROWS") or Path.home() / ".cache" / "cryptic-stage10-shipped.json")
CACHE = Path(os.environ.get("STAGE12_ROWS") or Path.home() / ".cache" / "cryptic-stage12-rows.json")
CANDIDATES = {"def_at_end": +1, "abbrev_blocks": -1, "indicators_per_clue": +1,
              "def_length_ratio": -1}
FLOOR = 8


def letters(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def cand(puz, facts):
    ents = {e["id"]: e for e in puz["entries"] if e.get("solution")}
    if not ents or not facts:
        return None
    ends, blocks, abbr, inds, ratios = [], 0, 0, [], []
    for eid, f in facts.items():
        e = ents.get(eid)
        if not e:
            continue
        clue = D.ENUMERATION.sub("", e.get("clue") or "").strip()
        if not clue or re.match(r"(?i)see\b", clue):
            continue
        inds.append(len(f.get("indicators") or []))
        for b in f.get("blocks") or []:
            blocks += 1
            got, src = letters(b[0]), letters(b[1])
            abbr += 1 <= len(got) <= 2 and len(src) > len(got)
        defs = [d for d in f.get("definition") or [] if d]
        if len(defs) != 1:
            continue
        dl, cl = letters(defs[0]), letters(clue)
        if not dl or dl == cl:
            continue
        start, end = cl.startswith(dl), cl.endswith(dl)
        if start != end:
            ends.append(end)
        sol, _ = D.answer_words(e)
        if sol:
            ratios.append(len(dl) / len(sol))
    mean = lambda xs: sum(xs) / len(xs) if len(xs) >= FLOOR else None
    return {"def_at_end": mean(ends), "abbrev_blocks": abbr / blocks if blocks >= FLOOR else None,
            "indicators_per_clue": mean(inds), "def_length_ratio": mean(ratios)}


def dump():
    rows = json.loads(BASE.read_text())
    facts = S4.blog_facts()
    for r in rows:
        r["cand"] = cand(read_puzzle_file(puzzle_paths.find(r["pid"])), facts.get(r["pid"]))
    CACHE.write_text(json.dumps(rows))
    tr = [r for r in rows if r["series"] == "times" and r["nitch"] is not None]
    for k in CANDIDATES:
        for name, sel in (("annotated", lambda r: r["index"] is not None), ("fresh", lambda r: not r["annotated"])):
            sub = [r for r in tr if sel(r)]
            got = sum(1 for r in sub if r["cand"] and r["cand"].get(k) is not None)
            print(f"{k:22s} {name:9s} coverage {got}/{len(sub)}")
    print(len(rows), "rows")


if __name__ == "__main__":
    cmd = sys.argv[1]
    S10.CACHE, S10.CANDIDATES = CACHE, CANDIDATES
    if cmd == "dump":
        dump()
    elif cmd == "test":
        S10.test(sys.argv[2:] or list(CANDIDATES))
