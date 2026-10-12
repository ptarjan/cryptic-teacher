#!/bin/bash
# Is a blog post whose answers fit no grid held as its clues alone, and does
# the solve's fill file it on the grid those answers cross in?
#
#     bash tools/test_blog_clues_only.sh
#
# A filed georgeho puzzle (sundaytel-2660) is turned back into the blog record
# it came from, then spoiled the ways a blogger spoils one: an answer at the
# wrong length, a blank one. file_blog_puzzles.hold_clues holds its clues in a
# scratch clues_only/, with the blog's answers along only as `blogAnswer`.
# clues_only.builder takes it (the backfill queues it), and the published
# answers, as a solve would give them, promote it to the published grid. The
# blog's wrong answer is named by cross_check and changes nothing. A post that
# skips a number, or a clue, is not held: the clue is the one thing no solve
# derives.
set -u
cd "$(dirname "$0")/.." || exit 1

python3 - <<'EOF'
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "tools")
import clues_only
import file_blog_puzzles as fbp
import puzzle_integrity
import puzzle_paths
import times_grids as tg

fails = []
TOOL = "tools/file_georgeho_puzzles.py"
source = json.loads(puzzle_paths.find("sundaytel-2660").read_text())
order = {"across": 0, "down": 1}
published = sorted(source["entries"], key=lambda e: (e["number"], order[e["direction"]]))


def blog_record(drop=None):
    entries = [{"number": e["number"], "direction": e["direction"],
                "answer": e["solution"], "clue": e["clue"]["text"]
                + (f" ({e['clue']['enumeration']})" if e["clue"].get("enumeration") else ""),
                "enumeration": e["clue"].get("enumeration")}
               for e in published if (e["number"], e["direction"]) != drop]
    return {"post_id": "sundaytel-2660", "series": "sundaytel", "number": 99660,
            "link": source["source"]["url"], "date": source["date"], "entries": entries}


rec = blog_record()
first = rec["entries"][0]
first["answer"] += "S"                       # the wrong length for its count
rec["entries"][3]["answer"] = ""             # blank
import datetime
date = datetime.date.fromisoformat(source["date"])
record, problems = fbp.hold_clues(rec, "sundaytel", date, source.get("setter"), TOOL,
                                  source["dimensions"]["cols"])
if problems:
    fails.append(f"a whole clue list was not held: {problems}")
try:
    puzzle_integrity.refuse_bad_clues_only(record)
except puzzle_integrity.RefusedWrite as e:
    fails.append(f"the held record breaks the schema: {e}")
scratch = Path(tempfile.mkdtemp()) / "clues_only"
path = clues_only.write(record, scratch)
if clues_only.read(record["id"], scratch)["clues"]["across"][0].get("blogAnswer") != first["answer"]:
    fails.append("the blog's answer did not go along as blogAnswer")
if "blogAnswer" in clues_only.read(record["id"], scratch)["clues"]["across"][3 if published[3]["direction"] == "across" else 0] \
        and published[3]["direction"] == "across":
    fails.append("a blank blog answer was carried as one")
if clues_only.builder(record) is not clues_only.BUILDERS[(TOOL, None)]:
    fails.append("no builder takes a held blog post, so the backfill would never solve it")
if record["id"] not in [r["id"] for r in clues_only.solvable(scratch)]:
    fails.append("the held blog post is not in the solve queue")
for tool in clues_only.BLOG_FILERS:
    if clues_only.builder({**record, "source": {**record["source"], "acquiredBy": tool}}) is None:
        fails.append(f"no builder for {tool}'s held posts")

# The solve's fill: the published answers, in clue order.
fill = {d: [e["solution"] for e in published if e["direction"] == d] for d in ("across", "down")}
puzzle, problems = clues_only.promote(record, fill)
if problems:
    fails.append(f"the solve's answers did not promote it: {problems}")
else:
    got = {(e["number"], e["direction"]): (e["position"], e["length"]) for e in puzzle["entries"]}
    want = {(e["number"], e["direction"]): (e["position"], e["length"]) for e in published}
    if got != want:
        fails.append("the promoted grid is not the published one")
    if puzzle["solutions"] != {"origin": "unsolved"} or any(e.get("solution") for e in puzzle["entries"]):
        fails.append("promote wrote answers: apply_solution writes the solve's, never the blog's")
    if puzzle["source"].get("gridOrigin") != "reconstructed":
        fails.append("the promoted puzzle does not say its grid was reconstructed")
differ = fbp.cross_check(record, fill)
if differ != [f"across light 1 {published[0]['solution']}/{first['answer']}"]:
    fails.append(f"cross_check did not name the blog's wrong answer alone: {differ}")

# A skipped number, or a clue with no words, is not held.
gap = blog_record(drop=(published[1]["number"], published[1]["direction"]))
if published[1]["number"] not in {e["number"] for e in gap["entries"]}:
    _, problems = fbp.hold_clues(gap, "sundaytel", date, None, TOOL, 15)
    if not any("no clue numbered" in p for p in problems):
        fails.append(f"a post skipping a number was held: {problems}")
blank_clue = blog_record()
blank_clue["entries"][2]["clue"] = "(5)"
_, problems = fbp.hold_clues(blank_clue, "sundaytel", date, None, TOOL, 15)
if not any("no clue text" in p for p in problems):
    fails.append(f"a light with no clue text was held: {problems}")

# A linked answer the post prints whole is held as its lights: the clue on
# the first, "See N" on the rest, with no lengths.
whole = blog_record()
a, b = whole["entries"][0], whole["entries"][1]
whole["entries"] = whole["entries"][2:]
whole["unsplit"] = [{"lights": [[a["number"], a["direction"]], [b["number"], b["direction"]]],
                     "answer": a["answer"] + b["answer"], "clue": "Linked clue (7,5)",
                     "enumeration": "7,5"}]
held_whole, problems = fbp.hold_clues(whole, "sundaytel", date, None, TOOL, 15)
firsts = [held_whole["clues"][a["direction"]][0]["clue"]["text"],
          [l["clue"]["text"] for l in held_whole["clues"][b["direction"]] if l["clue"]["text"].startswith("See")]]
if problems or firsts[0] != "Linked clue" or len(firsts[1]) != 1 \
        or not firsts[1][0].startswith(f"See {a['number']}") \
        or "length" in held_whole["clues"][a["direction"]][0]:
    fails.append(f"a linked answer printed whole was not held as its lights: {problems} {firsts}")

if fails:
    print("FAIL test_blog_clues_only:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok test_blog_clues_only: a spoiled blog post held clues-only, queued, and promoted "
      "to its published grid by the solve's answers; the blog's cross-checks only")
EOF
