#!/usr/bin/env bash
# tools/showcase.py picks only what a file states: each detector on a real
# puzzle that has the feature and off the look-alike that does not.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import fetch_puzzle as fp
import showcase as sc

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

def real(pid):
    return fp.read_puzzle_file(fp.resolve_puzzle(pid))

def facts(pid):
    return sc.facts(real(pid), None)

# --- a hidden message counts only when the note says where to look ---
for pid in ("quiptic-733", "cyclops-820", "cryptic-23113"):
    check(f"{pid}'s note announces a hidden message", facts(pid)["message"])
# "hidden in the clue" is wordplay, and an erratum mentions no grid at all.
for pid in ("cryptic-22863", "cryptic-25416", "cryptic-24355"):
    check(f"{pid} is no hidden message", not facts(pid)["message"])

# --- jigsaws ---
check("an alphabetical jigsaw is a jigsaw", facts("cryptic-24331")["jigsaw"])
check("a theme note is not a jigsaw", not facts("cryptic-22863")["jigsaw"])

# --- records ---
quote = real("cryptic-23801")
check("a quotation over seven lights is one 65-letter answer",
      sc.longest_answer(quote) == (65, 7), sc.longest_answer(quote))
slip = copy.deepcopy(quote)
for e in slip["entries"]:
    if e.get("group") and len(e["group"]) > 1:
        e["clue"]["enumeration"] = "3"
check("a count that disagrees with its squares sets no record",
      sc.longest_answer(slip)[0] < 65, sc.longest_answer(slip))
check("the 90-clue Jumbo counts 90 clues", facts("timesjumbo-1423")["answers"] == 90,
      facts("timesjumbo-1423")["answers"])
check("a book's year is not a print date", not facts("book-1052")["dated"])
check("a book's number is volume and position, not an issue",
      not facts("book-1052")["counted"])
check("a date-keyed number is not an issue", not facts("metro-20260902")["counted"])

# --- selection ---
def fake(i, series, **kw):
    f = {"id": f"{series}-{i}", "series": series, "number": i, "day": i, "dated": True,
         "answers": 28, "longest": None, "tags": [], "message": False, "jigsaw": False,
         "difficulty": None, "counted": True}
    f.update(kw)
    return f
pool = ([fake(i, "cryptic", message=True, jigsaw=True) for i in range(1, 9)]
        + [fake(i, "cyclops", message=True) for i in range(1, 3)])
got = sc.sections(pool)
ids = [f["id"] for _, _, _, cards in got for f, _ in cards]
check("a puzzle shows in one section only", len(ids) == len(set(ids)), ids)
msg = next(cards for slug, _, _, cards in got if slug == "hidden-message")
check("no series takes more than its share of a section",
      sum(f["series"] == "cryptic" for f, _ in msg) == 3, [f["id"] for f, _ in msg])
check("a section with nothing to show is left out",
      "pangrams" not in [slug for slug, *_ in got])

print("\n%d failure(s)" % fails)
raise SystemExit(fails > 0)
PY
