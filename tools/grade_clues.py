#!/usr/bin/env python3
"""Build blind head-to-head packets: our clues against human ones, same answers.

The georgeho corpus holds 660k published clues with their answers, so for every
word we have set, real setters have set it too — often a dozen times. That makes
a controlled comparison possible: same answer, same enumeration, different
setter. The only variable left is the writing.

Blindness matters more than it looks. We cannot judge our own clues; we know
which are ours, and knowing is enough to bias the score. So this script strips
every trace of provenance and emits packets labelled A/B/C/D in a seeded shuffle.
A judge with no other context genuinely cannot tell. The key stays here, on our
side of the wall, and is only applied after the scores come back.

  python3 tools/grade_clues.py --clues tools/data/authored_A001_clues.json \
      --out tools/data/grading

Writes grading/packets/<ANSWER>.json (what the judge sees) and grading/key.json
(which label was ours). Never show the judge the key.
"""

import argparse
import json
import random
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path.home() / "cryptic-setter-data" / "georgeho" / "data.db"

# Blogs of the broadsheet dailies. Restricting to these keeps the comparison
# honest: we are measuring ourselves against professionally edited clues, not
# against the weakest thing in a 660k-row scrape.
GOOD_SOURCES = ("times_xwd_times", "fifteensquared", "bigdave44")

RIVALS_PER_ANSWER = 3


def clean(text):
    """Normalise a corpus clue enough that formatting cannot leak provenance."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip()


def enumeration(clue):
    m = re.search(r"\(([\d,\-\s]+)\)\s*$", clue)
    return m.group(1) if m else None


def usable(clue, answer):
    """Reject corpus rows that would make the packet unfair or unreadable."""
    if not clue or len(clue) < 12:
        return False
    if enumeration(clue) is None:
        return False
    # Some rows carry the answer inline, or blog annotation in braces.
    if re.search(rf"\b{re.escape(answer)}\b", clue, re.I):
        return False
    if any(ch in clue for ch in "{}[]<>"):
        return False
    # Cross-referenced clues ("see 4 down") cannot be solved standalone.
    if re.search(r"\b(see|and)\s+\d+\b", clue, re.I):
        return False
    return True


def fetch_rivals(db, answer, want, rng):
    rows = db.execute(
        "select clue from clues where upper(answer)=? and source in ({})".format(
            ",".join("?" * len(GOOD_SOURCES))
        ),
        (answer, *GOOD_SOURCES),
    ).fetchall()
    seen, pool = set(), []
    for (clue,) in rows:
        c = clean(clue)
        if not usable(c, answer):
            continue
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        pool.append(c)
    rng.shuffle(pool)
    return pool[:want]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clues", default="tools/data/authored_A001_clues.json")
    ap.add_argument("--out", default="tools/data/grading")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    ours = json.loads((ROOT / args.clues).read_text())
    db = sqlite3.connect(args.corpus)
    rng = random.Random(args.seed)

    out = ROOT / args.out
    (out / "packets").mkdir(parents=True, exist_ok=True)

    key, thin = {}, []
    for eid, spec in sorted(ours.items()):
        if eid.startswith("_"):
            continue
        answer = "".join(
            c for c in spec["annotation"]["answer"].upper() if c.isalpha()
        )
        mine = clean(spec["clue"])
        rivals = fetch_rivals(db, answer, RIVALS_PER_ANSWER, rng)
        if len(rivals) < RIVALS_PER_ANSWER:
            thin.append(f"{answer} ({len(rivals)} rivals)")
        if not rivals:
            continue

        clues = [{"text": mine, "_ours": True}] + [
            {"text": r, "_ours": False} for r in rivals
        ]
        rng.shuffle(clues)
        labels = "ABCDEFGH"
        packet = {
            "answer": answer,
            "enumeration": enumeration(mine),
            "clues": [
                {"label": labels[i], "clue": c["text"]} for i, c in enumerate(clues)
            ],
        }
        key[answer] = {
            "ours": next(labels[i] for i, c in enumerate(clues) if c["_ours"]),
            "entry": eid,
        }
        (out / "packets" / f"{answer}.json").write_text(
            json.dumps(packet, indent=1, ensure_ascii=False) + "\n"
        )

    (out / "key.json").write_text(json.dumps(key, indent=1) + "\n")
    print(f"wrote {len(key)} packets to {out / 'packets'}")
    if thin:
        # Say so out loud. A silently short packet would quietly weaken the
        # comparison for that word while the summary still read "20 answers".
        print("fewer rivals than asked for: " + "; ".join(thin))


if __name__ == "__main__":
    main()
