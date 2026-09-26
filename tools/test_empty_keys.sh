#!/bin/bash
# Does a puzzle file carry keys that say nothing?
#
#     bash tools/test_empty_keys.sh
#
# Our puzzle shape was copied from the Guardian's API object, and two of its
# keys came along whether or not they held anything: `separatorLocations`, an
# empty object on 81% of entries, and `annotation`, null on 98% of them. Across
# 466,889 entries that was 16.4 MB — 10.5% of the corpus — spent saying nothing,
# and paid for again on every clone, every CI checkout and every page build.
#
# So they follow the rule `clueItalics`, `group` and `clueMissing` already do:
# written when they carry data, left out when they do not. That only works if an
# absent key reads exactly like an empty one, which is what this tests on both
# sides — the writers must not emit the empty form, and the readers must take
# the absence as empty rather than throwing on it.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

echo "a fetched puzzle writes neither key when neither holds anything"
out=$(PYTHONPATH=tools python3 - <<'PY'
import json, tempfile
from pathlib import Path
import fetch_puzzle as fetcher
import puzzle_integrity
# Two lights in an empty grid are not a whole puzzle; the write gate has its own test, tools/test_puzzle_invariants.sh.
puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None


def guardian_entry(eid, num, seps=None):
    return {"id": eid, "number": num, "direction": "across",
            "position": {"x": 0, "y": num - 1}, "length": 8,
            "clue": f"A clue with words in it ({'4,4' if seps else '8'})",
            "separatorLocations": seps or {}, "solution": "ANSWERED",
            "group": [eid]}


data = {"id": "crosswords/cryptic/30066", "number": 30066,
        "name": "Cryptic crossword No 30,066", "creator": {"name": "Tramp"},
        "date": 1784764800000, "dimensions": {"rows": 15, "cols": 15},
        "entries": [guardian_entry("1-across", 1),
                    guardian_entry("2-across", 2, {",": [4]})]}
puzzle = fetcher.convert(data)
by = {e["id"]: e for e in puzzle["entries"]}
print("PLAIN", "separatorLocations" in by["1-across"], "annotation" in by["1-across"])
print("BREAK", json.dumps(by["2-across"].get("separatorLocations")))
# Dropping a key must not shuffle the ones that stay, or the diff over 16,000
# files is unreadable and no one can check it.
print("ORDER", ",".join(by["2-across"]))

# The file is the payload, so what comes back off disk has to be what went
# down — absent keys and all — and the bytes must hold neither empty form.
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / "cryptic-30066.json"
    fetcher.write_puzzle_file(path, puzzle)
    text = path.read_text(encoding="utf-8")
    back = fetcher.read_puzzle_file(path)
    print("TRIP", back["entries"] == puzzle["entries"])
    print("NOEMPTY", '"separatorLocations": {}' in text, '"annotation": null' in text)

# An annotation that could not be written is an absent key, not a null one.
# grade_model_fill throws away an annotation written off a wrong answer; before
# this it wrote the null back, which is how the null got onto solved puzzles.
# Its ledger is stubbed: this is a test, and a test must not file a miss
# against tools/data/blind_misses.json that no solve ever made.
fetcher.record_misses = lambda *a, **k: None
entries = [{"id": "1-across", "clue": "x (5)", "solution": "WRONG",
            "annotation": {"type": "anagram"}}]
fetcher.grade_model_fill({"id": "cryptic-1", "entries": entries},
                         {"1-across": "RIGHT"})
print("BLANKED", "annotation" in entries[0])
PY
)
same "no separatorLocations and no annotation on a plain entry" \
  "$(grep '^PLAIN ' <<<"$out")" "PLAIN False False"
same "but a real word break is still written" \
  "$(grep '^BREAK ' <<<"$out")" 'BREAK {",": [4]}'
same "and the surviving keys keep their order" "$(grep '^ORDER ' <<<"$out")" \
  "ORDER id,number,direction,position,length,clue,separatorLocations,solution"
same "a puzzle written without the keys round-trips off disk" \
  "$(grep '^TRIP ' <<<"$out")" "TRIP True"
same "and the bytes on disk hold neither empty form" \
  "$(grep '^NOEMPTY ' <<<"$out")" "NOEMPTY False False"
same "blanking an annotation removes the key rather than nulling it" \
  "$(grep '^BLANKED ' <<<"$out")" "BLANKED False"

echo "the readers take an absent key as an empty one"
# Not asked of the source but of the functions: a real puzzle with both keys
# stripped from every entry, through the readers that weigh them. A KeyError or
# an AttributeError anywhere here is the bug this whole change could have had.
out=$(PYTHONPATH=tools python3 - <<'PY'
from pathlib import Path
import fetch_puzzle as fetcher
import difficulty, build_seo_pages, make_og_card, craft_report

puz = fetcher.read_puzzle_file(Path("puzzles/cryptic-30066.json"))
for e in puz["entries"]:
    e.pop("separatorLocations", None)
    e.pop("annotation", None)
print("DEVICE", difficulty.device(puz))
print("OBSCURE", difficulty.obscurity(puz, difficulty.ranks()) is not None)
print("CLUEHTML", bool(build_seo_pages.clue_html(puz["entries"][0])))
print("CARD", make_og_card.plan(puz["entries"][0]))
print("CRAFT", craft_report.annotated(puz))
print("COVERAGE", fetcher.clue_coverage(puz)["present"] > 0)
print("ANNOTATED", fetcher.puzzle_is_annotated(puz))
PY
)
same "difficulty finds no device rather than crashing" "$(grep '^DEVICE ' <<<"$out")" "DEVICE None"
same "difficulty still scores obscurity" "$(grep '^OBSCURE ' <<<"$out")" "OBSCURE True"
same "the crawlable page still renders the clue" "$(grep '^CLUEHTML ' <<<"$out")" "CLUEHTML True"
same "the social card declines the clue rather than throwing" \
  "$(grep '^CARD ' <<<"$out")" "CARD None"
same "craft_report sees no annotated entries" "$(grep '^CRAFT ' <<<"$out")" "CRAFT []"
same "clue coverage is unaffected" "$(grep '^COVERAGE ' <<<"$out")" "COVERAGE True"
same "and the puzzle reads as un-annotated, which is what it is" \
  "$(grep '^ANNOTATED ' <<<"$out")" "ANNOTATED False"

echo "app.js reads both keys through a guard"
# app.js is the reader that matters most and cannot be imported here, so its
# guards are read out of the source. A bare e.separatorLocations[...] or
# e.annotation.type throws on every puzzle this repo now ships.
# separatorLocations is read in exactly one place and must land in a variable
# that has already been defaulted; an absent key indexed directly throws.
reads=$(grep -cE '\be\.separatorLocations\b' app.js)
guarded=$(grep -cE '\be\.separatorLocations \|\| \{\}' app.js)
same "app.js reads separatorLocations only through a || {}" "$reads" "$guarded"
# annotation needs no such guard anywhere: an absent key reads `undefined` and
# every use in the app is a truthiness test, which undefined and null both fail
# identically. The one thing that would tell them apart is an identity check,
# so that is what is forbidden here rather than a shape the code never has.
strict=$(grep -cE "annotation\s*(===|!==)\s*null|['\"]annotation['\"]\s+in\b|hasOwnProperty\(['\"]annotation" \
  app.js tools/smoke_test.js tools/make_hint_packets.js | grep -v ':0$' | wc -l | tr -d ' ')
same "nothing in the app tells a null annotation from an absent one" "$strict" "0"

echo "and the corpus carries neither empty form"
# The whole point of the exercise, asked of the files rather than of the code
# that writes them: 21.5 MB came out of puzzles/ on 2026-09-19 and nothing is
# allowed to put it back, one nightly fetch at a time. Read as bytes, because
# both strings are unambiguous at this indent and parsing 135 MB to learn it
# would be the slow way round.
found=$(grep -rlF --include='*.json' \
  -e '"separatorLocations": {}' -e '"annotation": null' puzzles \
  | head -5 | tr '\n' ' ')
same "no puzzle file writes an empty separatorLocations or a null annotation" \
  "${found:-none}" "none"

if [ "$fails" -gt 0 ]; then echo "empty_keys: $fails check(s) failed"; exit 1; fi
echo "empty_keys: all checks passed"
