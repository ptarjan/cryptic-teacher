#!/usr/bin/env python3
"""Build blind head-to-head packets: our clues against human ones, same answers.

puzzles/ holds a million published clues with their answers, in the
publishers' own text, so for every word we have set, real setters have set it
too, often dozens of times. That makes a controlled comparison possible: same
answer, same enumeration, different setter. The only variable left is the
writing.

The rivals used to come from a blog scrape (georgeho), and the scrape showed:
A001's field held an anagram with no indicator, a hidden word with no
indicator and a clue with no derivation. Now they are drawn from tracked
puzzles, annotated ones first because the validator has proved them sound,
and at most one per series until the pool runs out, so no one paper's house
style is the whole field. key.json records each rival's puzzle and entry.

Blindness matters more than it looks. We cannot judge our own clues; we know
which are ours, and knowing is enough to bias the score. So this script strips
every trace of provenance and emits packets labelled A/B/C/D in a seeded shuffle.
A judge with no other context genuinely cannot tell. The key stays here, on our
side of the wall, and is only applied after the scores come back.

  python3 tools/grade_clues.py --clues tools/data/authored_A001_clues.json \
      --out tools/data/grading

Writes grading/packets/<ANSWER>.json (what the judge sees) and grading/key.json
(which label was ours). Never show the judge the key.

Every round is also archived under grading/runs/<runid>/, and that is not
housekeeping. We once ran a round, scored it, edited a few clues, re-ran this
script, and lost the first round entirely: the re-run overwrote key.json, and
because the A/B/C/D shuffle had moved, the surviving scores could no longer be
joined to any key. The numbers were fine. Nobody could ever again say which
clue they belonged to. That killed the untouched-clue control and with it the
only reason the second round's comparison meant anything.

Note the shuffle moved even though the seed did not. The rng is consumed as the
packets are built, so changing which rivals one answer draws shifts every draw
after it. "Same seed, same packets" is only true if the inputs are byte-identical,
which is exactly the assumption an edit breaks.

So the run id is a hash of the packet contents. Identical inputs land in the
same run directory; any change at all gets a new one. grading/packets and
grading/key.json stay as the convenience copy of the newest run, but they are
now derived - copies of an archive that keeps every round re-scorable. A result
nobody can re-derive is not a result.
"""

import argparse
import hashlib
import json
import random
import re
import shutil
import unicodedata
from pathlib import Path

import enumeration  # tools/enumeration.py; tools/ is this script's own directory
from puzzle_paths import puzzle_files
from groups import entry_id

ROOT = Path(__file__).resolve().parent.parent
RIVALS_PER_ANSWER = 3


def clean(text):
    """Normalise a corpus clue enough that formatting cannot leak provenance."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip()


def published_clues(answers):
    """Every published clue in puzzles/ for these answers: {answer: [rival]}.

    A rival is its printed text plus where it came from. Cross-references ("See
    4 down") and the non-leading lights of a linked answer are left out: they
    cannot be solved standalone."""
    pool = {a: [] for a in answers}
    for path in puzzle_files():
        p = json.loads(Path(path).read_text())
        if p.get("series") == "authored":
            continue
        for e in p.get("entries") or []:
            if e.get("solution") not in pool or not (e.get("clue") or {}).get("text"):
                continue
            text = clean(enumeration.printed(e["clue"]))
            if re.search(r"\b(see|and)\s+\d+\b", text, re.I):
                continue
            pool[e["solution"]].append({"text": text, "series": p["series"],
                                        "puzzle": p["id"], "entry": entry_id(e),
                                        "annotated": bool(e.get("annotation"))})
    return pool


def pick_rivals(pool, want, rng):
    """Annotated before unannotated, one per series before a second from any."""
    seen, rivals = set(), []
    for r in pool:
        if r["text"].lower() not in seen:
            seen.add(r["text"].lower())
            rivals.append(r)
    rng.shuffle(rivals)
    rivals.sort(key=lambda r: not r["annotated"])
    picked, series_used = [], set()
    for r in rivals:
        if len(picked) < want and r["series"] not in series_used:
            picked.append(r)
            series_used.add(r["series"])
    for r in rivals:
        if len(picked) < want and r not in picked:
            picked.append(r)
    return picked


def run_id(packets):
    """Fingerprint a round by what the judges will actually see.

    Covers every answer and every clue text in label order, so re-running with
    unchanged clues gives the same id and the same run directory, while any
    edit gives a new one. The labels are hashed on purpose: two rounds with the
    same clues but a different A/B/C/D are different rounds, and must never be
    allowed to share a key.
    """
    h = hashlib.sha1()
    for p in sorted(packets, key=lambda p: p["answer"]):
        h.update(p["answer"].encode())
        for c in p["clues"]:
            h.update(b"\x1f")
            h.update(c["label"].encode())
            h.update(c["clue"].encode())
        h.update(b"\x1e")
    return h.hexdigest()[:12]


def write_round(dest, packets, key, rid):
    """Write packets + key into dest, replacing whatever was there.

    Replacing rather than merging: a leftover packet from an older round would
    sit in the directory carrying a different run id, and the next judging pass
    would quietly be a mixture of two rounds.
    """
    if (dest / "packets").exists():
        shutil.rmtree(dest / "packets")
    (dest / "packets").mkdir(parents=True, exist_ok=True)
    for p in packets:
        (dest / "packets" / f"{p['answer']}.json").write_text(
            json.dumps(p, indent=1, ensure_ascii=False) + "\n"
        )
    (dest / "key.json").write_text(json.dumps(key, indent=1) + "\n")
    (dest / "run.txt").write_text(rid + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clues", default="tools/data/authored_A001_clues.json")
    ap.add_argument("--out", default="tools/data/grading")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    ours = json.loads((ROOT / args.clues).read_text())
    rng = random.Random(args.seed)

    out = ROOT / args.out

    answers = {"".join(c for c in spec["annotation"]["answer"].upper() if c.isalpha())
               for eid, spec in ours.items() if not eid.startswith("_")}
    pool = published_clues(answers)

    key, thin, packets = {}, [], []
    for eid, spec in sorted(ours.items()):
        if eid.startswith("_"):
            continue
        answer = "".join(
            c for c in spec["annotation"]["answer"].upper() if c.isalpha()
        )
        mine = clean(enumeration.printed(spec["clue"]))
        rivals = pick_rivals(pool[answer], RIVALS_PER_ANSWER, rng)
        if len(rivals) < RIVALS_PER_ANSWER:
            thin.append(f"{answer} ({len(rivals)} rivals)")
        if not rivals:
            continue

        clues = [{"text": mine, "_ours": True}] + [
            {"text": r["text"], "_ours": False, "_from": r} for r in rivals
        ]
        rng.shuffle(clues)
        labels = "ABCDEFGH"
        packet = {
            "answer": answer,
            "enumeration": spec["clue"].get("enumeration"),
            "clues": [
                {"label": labels[i], "clue": c["text"]} for i, c in enumerate(clues)
            ],
        }
        key[answer] = {
            "ours": next(labels[i] for i, c in enumerate(clues) if c["_ours"]),
            "entry": eid,
            "rivals": {labels[i]: {k: c["_from"][k] for k in ("puzzle", "entry", "annotated")}
                       for i, c in enumerate(clues) if not c["_ours"]},
        }
        packets.append(packet)

    rid = run_id(packets)
    for p in packets:
        # Judge-visible, and safe to be. It is an opaque hex digest of the
        # packet contents: no ordering, no provenance, nothing about which
        # clue is ours or where any clue came from. Its only job is to let
        # score_grading find the key that belongs to these exact packets.
        p["run"] = rid

    write_round(out / "runs" / rid, packets, key, rid)
    # The convenience copy: what a judging session picks up by default. Derived
    # from the archive above, and safe to lose.
    write_round(out, packets, key, rid)

    print(f"wrote {len(key)} packets to {out / 'packets'} (run {rid})")
    print(f"archived at {out / 'runs' / rid}")
    if thin:
        # Say so out loud. A silently short packet would quietly weaken the
        # comparison for that word while the summary still read "20 answers".
        print("fewer rivals than asked for: " + "; ".join(thin))


if __name__ == "__main__":
    main()
