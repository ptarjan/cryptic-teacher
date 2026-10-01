#!/bin/bash
# Where a puzzle came from is `source`, whose answers it holds is `solutions`,
# and who wrote its hints is `annotatedBy` — one key each, nothing said twice.
#
#     bash tools/test_puzzle_source.sh
#
# Tests both halves: every write lands the three blocks in that shape (and
# nothing else says the same thing), and provenance.check refuses a `solutions`
# whose detail does not back its `origin`.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import json, tempfile
from pathlib import Path
import fetch_puzzle as fetcher
import provenance
import puzzle_integrity
import puzzle_schema
# Two lights are not a whole puzzle; the write gate has its own test,
# tools/test_puzzle_invariants.sh.
puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None


def entry(eid, num, solution="ANSWERED"):
    return {"id": eid, "number": num, "direction": "across",
            "position": {"x": 0, "y": num - 1}, "length": 8,
            "clue": "A clue with words in it (8)", "solution": solution,
            "group": [eid]}


data = {"id": "crosswords/prize/30066", "number": 30066,
        "name": "Prize crossword No 30,066", "creator": {"name": "Tramp"},
        "date": 1784764800000, "dimensions": {"rows": 15, "cols": 15},
        "entries": [entry("1-across", 1, ""), entry("2-across", 2, "")]}

with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "cryptic-30066.json"
    fetcher.write_puzzle_file(path, fetcher.convert(data))
    p = fetcher.read_puzzle_file(path)
    print("KEYS", ",".join(k for k in p if k != "entries"))
    print("SOURCE", ",".join(p["source"]), p["source"]["url"])
    print("UNSOLVED", json.dumps(p["solutions"]))

    # A model solve names its model; the origin follows from the detail.
    for e in p["entries"]:
        e["solution"] = "GUESSEDX"
    p = provenance.with_solution_detail(
        p, {"model": "claude-opus-5-5", "date": "2026-09-28",
            "check": "2 entries, 0 crossings, 0 conflicts"})
    p["source"]["acquiredOn"] = "2026-09-01"
    fetcher.write_puzzle_file(path, p)
    p = fetcher.read_puzzle_file(path)
    print("MODEL", p["solutions"]["origin"], ",".join(p["solutions"]))

    # A write-up's answers arrive on a fresh fetch, which states only the
    # detail; the model fill they replace is remembered.
    data["entries"] = [entry("1-across", 1), entry("2-across", 2)]
    fresh = provenance.with_solution_detail(fetcher.convert(data), {
        "blog": "fifteensquared", "url": "https://fifteensquared.net/x/",
        "date": "2026-09-28", "check": "2 entries verified"})
    fetcher.write_puzzle_file(path, fresh)
    p = fetcher.read_puzzle_file(path)
    print("WRITEUP", p["solutions"]["origin"], p["solutions"].get("previousOrigin"))

    # The paper prints its key: a fresh fetch carries no detail, so the answers
    # are the publisher's, the guess is remembered, the arrival date is kept.
    data["entries"] = [entry("1-across", 1), entry("2-across", 2)]
    fetcher.write_puzzle_file(path, fetcher.convert(data))
    p = fetcher.read_puzzle_file(path)
    print("PUBLISHED", json.dumps(p["solutions"]), p["source"]["acquiredOn"])
    print("SCHEMA", puzzle_schema.validate(p))
    print("FIXPOINT", provenance.stamp(p, p["source"]["acquiredBy"]) == p)
    # The old keys are not part of the shape.
    old = {**p, "sourceUrl": p["source"]["url"], "provenance": {}}
    print("OLDKEYS", len([x for x in puzzle_schema.validate(old)
                          if "sourceUrl" in x or "provenance" in x]))


def refused(solutions, want):
    p = {"id": "cryptic-30066", "number": 30066, "series": "cryptic", "dimensions": {"cols": 15, "rows": 15},
         "source": {"publisher": "Guardian", "url": "https://x/",
                    "retrievedFrom": "publisher",
                    "acquiredBy": "tools/fetch_puzzle.py",
                    "acquiredOn": "2026-09-01", "gridOrigin": "published"},
         "solutions": solutions, "entries": [entry("1-across", 1)]}
    return any(want in f for f in provenance.check(p))


WRITEUP = {"origin": "writeup", "blog": "fifteensquared", "url": "https://f/",
           "date": "2026-09-01", "check": "1 entry"}
print("OK_WRITEUP", provenance.check({
    "id": "cryptic-30066", "number": 30066, "series": "cryptic", "dimensions": {"cols": 15, "rows": 15},
    "source": {"publisher": "Guardian", "url": "https://x/",
               "retrievedFrom": "publisher", "acquiredBy": "tools/fetch_puzzle.py",
               "acquiredOn": "2026-09-01", "gridOrigin": "published"},
    "solutions": WRITEUP, "entries": [entry("1-across", 1)]}))
print("R_DETAIL", refused({"origin": "published", "date": "2026-09-01"}, "only back"))
print("R_NOBLOG", refused({k: v for k, v in WRITEUP.items() if k != "blog"},
                          "has no blog"))
print("R_BOTH", refused({**WRITEUP, "model": "m"}, "both a blog and a model"))
print("R_REPEAT", refused({"origin": "published", "previousOrigin": "published"},
                          "repeats origin"))
print("R_BADBLOG", refused({**WRITEUP, "blog": "somewhere"}, "solutions.blog"))
PY
)
echo "a fetched puzzle writes source, solutions and nothing that repeats them"
same "top-level keys, in order" "$(grep '^KEYS ' <<<"$out")" \
  "KEYS id,number,series,name,setter,date,dimensions,source,solutions"
same "source holds the url and how it was read" "$(grep '^SOURCE ' <<<"$out")" \
  "SOURCE publisher,url,retrievedFrom,acquiredBy,acquiredOn,gridOrigin https://www.theguardian.com/crosswords/prize/30066"
same "no answers: origin unsolved, no detail" "$(grep '^UNSOLVED ' <<<"$out")" \
  'UNSOLVED {"origin": "unsolved"}'
echo "the detail keys decide the origin"
same "a model solve" "$(grep '^MODEL ' <<<"$out")" \
  "MODEL model origin,model,date,check"
same "a write-up replaces it and the guess is remembered" \
  "$(grep '^WRITEUP ' <<<"$out")" "WRITEUP writeup model"
same "the paper's key replaces it and the guess is remembered" \
  "$(grep '^PUBLISHED ' <<<"$out")" \
  'PUBLISHED {"origin": "published", "previousOrigin": "model"} 2026-09-01'
same "the written file meets the schema" "$(grep '^SCHEMA ' <<<"$out")" "SCHEMA []"
same "a second stamp changes nothing" "$(grep '^FIXPOINT ' <<<"$out")" "FIXPOINT True"
same "the schema refuses sourceUrl and provenance" "$(grep '^OLDKEYS ' <<<"$out")" "OLDKEYS 2"
echo "provenance.check refuses solutions its detail does not back"
same "a full writeup passes" "$(grep '^OK_WRITEUP ' <<<"$out")" "OK_WRITEUP []"
for r in R_DETAIL R_NOBLOG R_BOTH R_REPEAT R_BADBLOG; do
  same "$r" "$(grep "^$r " <<<"$out")" "$r True"
done

[ "$fails" -eq 0 ] && echo "PASS" || { echo "$fails failure(s)"; exit 1; }
