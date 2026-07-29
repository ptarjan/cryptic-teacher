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
    enum = enumeration(clue)
    if enum is None:
        return False
    # The enumeration must add up to the answer we are comparing against. The
    # corpus stores multi-word answers unspaced, so a (4,6) PACESETTER clue is
    # filed under an answer that starts with PACE and sails through a naive
    # answer match — then a judge sees a ten-letter clue in a four-letter
    # packet, scores it as broken, and the comparison for that word is junk.
    parts = [int(n) for n in re.findall(r"\d+", enum)]
    if sum(parts) != len(answer):
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
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    ours = json.loads((ROOT / args.clues).read_text())
    db = sqlite3.connect(args.corpus)
    rng = random.Random(args.seed)

    out = ROOT / args.out

    key, thin, packets = {}, [], []
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
