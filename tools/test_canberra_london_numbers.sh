#!/bin/bash
# Does tools/canberra_london_numbers.py name the London number of a Canberra
# reprint only when the clues match a Times reading, or when two matched
# Canberra days bracket it with exactly as many days as numbers; refuse a
# span whose counts disagree; leave a re-run out of order alone; skip Quick
# crosswords and anything after January 1982; and date a bracketed number
# only when the London printed days agree too?
#
#     bash tools/test_canberra_london_numbers.sh
#
# Everything is a synthetic cache in a temp dir; nothing reads the corpus.
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "tools")
import canberra_london_numbers as c

tmp = Path(sys.argv[1])
cache, src = tmp / "trove", tmp / "src"
src.mkdir()

def words(n):
    """24 clues of letters-only words, distinct for each puzzle number."""
    sp = lambda x: "".join(chr(97 + int(d)) for d in str(x))
    return [f"q{sp(n)} r{sp(k)} s{sp(n)}{sp(k)} t{sp(k)}" for k in range(24)]

# London: 13001 Thu 2 Jan 1975, 13004 Mon 6 Jan (Fri and Sat between), 13006 Wed 8 Jan.
for n, d in [(13001, "1975-01-02"), (13004, "1975-01-06"), (13006, "1975-01-08")]:
    (src / f"times-{n}.json").write_text(json.dumps({"id": f"times-{n}", "number": n, "date": d,
        "entries": [{"clue": {"text": w}} for w in words(n)]}))

def article(aid, date, title, clues):
    d = cache / aid
    d.mkdir(parents=True)
    dd = __import__("datetime").date.fromisoformat(date)
    (d / "meta.json").write_text(json.dumps({"id": aid, "title": f"{dd.day:02d} {dd.strftime('%b')} {dd.year} - {title} - Trove"}))
    (d / "ocr.txt").write_text("CRYPTIC CROSSWORD ACROSS " + " ".join(f"{k} {w} (5)." for k, w in enumerate(clues)))

article("1", "1975-02-10", "CRYPTIC CROSSWORD", words(13001))
article("2", "1975-02-11", "CRYPTIC CROSSWORD", words(99002))   # unmatched
article("3", "1975-02-12", "CRYPTIC CROSSWORD", words(99003))   # unmatched
article("4", "1975-02-13", "CRYPTIC CROSSWORD", words(13004))
article("5", "1975-02-14", "CRYPTIC CROSSWORD", words(13001))   # a re-run, out of order
article("6", "1975-02-15", "CRYPTIC CROSSWORD", words(99006))   # unmatched, between a re-run and 13006
article("7", "1975-02-17", "CRYPTIC CROSSWORD", words(13006))
article("8", "1975-02-11", "QUICK CROSSWORD", words(13004))     # a Quick: never a reprint
article("9", "1983-05-02", "CRYPTIC CROSSWORD", words(13006))   # after LAST_REPRINT
article("10", "1975-02-18", "CRYPTIC CROSSWORD", words(13006)[:3])  # too few counts to be a cryptic

reads = c.readings([src])
arts = c.articles(cache)
assert sorted(a[0] for a in arts) == ["1", "2", "3", "4", "5", "6", "7"], [a[0] for a in arts]
found = c.match(arts, reads)
assert found == {"1": 13001, "4": 13004, "5": 13001, "7": 13006}, found
nums = c.number(arts, found, reads)
assert nums["2"] == {"date": "1975-02-11", "number": 13002, "how": "bracketed", "londonDate": "1975-01-03"}, nums["2"]
assert nums["3"] == {"date": "1975-02-12", "number": 13003, "how": "bracketed", "londonDate": "1975-01-04"}, nums["3"]
assert "6" not in nums, nums.get("6")
assert nums["7"]["how"] == "matched" and nums["7"]["londonDate"] == "1975-01-08"

# A bracket whose London printed days disagree with its numbers has no date.
(src / "times-13004.json").write_text((src / "times-13004.json").read_text().replace("1975-01-06", "1975-01-07"))
nums = c.number(arts, found, c.readings([src]))
assert nums["2"]["number"] == 13002 and nums["2"]["londonDate"] is None, nums["2"]

# A bracket longer than max_span is refused.
assert "2" not in c.number(arts, found, reads, max_span=2)

# The CLI: the map, and the ids whose number has no reading.
assert c.main(["--cache", str(cache), "--source", str(src)]) == 0
assert set(c.load(cache / "london_numbers.json")) == {"1", "2", "3", "4", "5", "7"}
print("ok   canberra_london_numbers: match, bracket, refusals, dates, map")
PY
ids=$(python3 tools/canberra_london_numbers.py --cache "$tmp/trove" --source "$tmp/src" --ids scanless | tr '\n' ' ')
[ "$ids" = "2 3 " ] || { echo "FAIL --ids scanless: got [$ids]"; exit 1; }
echo "ok   --ids scanless lists only the bracketed articles"
