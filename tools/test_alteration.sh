#!/bin/bash
# Does the write gate hold an entry's `alteration` to the letters it claims?
#
#     bash tools/test_alteration.sh
#
# A Listener whose preamble alters answers before entry files the grid's
# letters as `solution` and the clue's own word as `alteration.from`; each
# step's op has to turn the word before it into the word after. Every op is
# held to one mapping it must accept and one it must refuse, then a real
# puzzle carrying an alteration is written through refuse_bad_write and broken
# one way at a time, and an annotation is held to building `from`, not the entry.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import copy
import fetch_puzzle as fetcher
import puzzle_integrity, puzzle_schema
import validate_annotations as va

OPS = puzzle_integrity.ALTERATION_OPS
CASES = {  # op: (accepted, refused)
    "reversal": (("FOETOR", "ROTEOF"), ("FOETOR", "FOETOR")),
    "anagram": (("CANOPY", "PYCANO"), ("CANOPY", "CANOPE")),
    "move": (("TRITE", "RITTE"), ("TRITE", "ETIRT")),
    "deletion": (("BASIN", "BAI"), ("BASIN", "BIA")),
    "insertion": (("BAI", "BAIT"), ("BAI", "TIAB")),
    "substitution": (("SALON", "TALON"), ("SALON", "TALONS")),
}
for op, (good, bad) in CASES.items():
    print(f"OP {op}", OPS[op](*good), OPS[op](*bad))

real = fetcher.read_puzzle_file(fetcher.resolve_puzzle("listener-1"))
e = next(e for e in real["entries"] if len(e["solution"]) >= 4)
good = copy.deepcopy(real)
good["preamble"] = "Answers are entered reversed."
g = next(x for x in good["entries"] if x["number"] == e["number"] and x["direction"] == e["direction"])
g["alteration"] = {"from": e["solution"][::-1], "steps": [{"op": "reversal"}]}


def verdict(p):
    try:
        puzzle_integrity.refuse_bad_write(puzzle_schema.order(p))
        return "accepted"
    except ValueError as err:
        return " | ".join(f"{k}" for k, _, w in err.flags)


def broken(name, change):
    p = copy.deepcopy(good)
    change(p)
    print(name, verdict(p))


def alt(p):
    return next(x for x in p["entries"] if "alteration" in x)["alteration"]


print("GOOD", verdict(good))
broken("WRONGOP", lambda p: alt(p)["steps"].__setitem__(0, {"op": "deletion"}))
broken("NOPREAMBLE", lambda p: p.pop("preamble"))
broken("LASTGIVES", lambda p: alt(p)["steps"][0].__setitem__("gives", e["solution"]))
broken("CHAINOK", lambda p: alt(p).__setitem__("steps", [
    {"op": "insertion", "gives": e["solution"][::-1] + "S"},
    {"op": "deletion", "gives": e["solution"][::-1]}, {"op": "reversal"}]))
broken("CHAINNOGIVES", lambda p: alt(p).__setitem__("steps", [{"op": "insertion"}, {"op": "deletion"}]))
broken("BADOPNAME", lambda p: alt(p)["steps"].__setitem__(0, {"op": "jumble"}))

# The annotation's pieces build the clue's word, not the entry.
w = g["alteration"]["from"]
ann = {"type": ["charade"], "answer": e["solution"], "definitions": [],
       "blocks": [{"clueFragment": "x", "gives": w}],
       "assembly": {"pieces": [w[:2], w[2:]]}}
for pieces, name in (([w[:2], w[2:]], "FROM"), ([e["solution"][:2], e["solution"][2:]], "ENTRY")):
    p = copy.deepcopy(good)
    t = next(x for x in p["entries"] if "alteration" in x)
    t["annotation"] = dict(ann, assembly={"pieces": pieces})
    errors = va.validate_puzzle(p)[1]
    print("PIECES", name, any("pieces" in x and "join to" in x for x in errors))
PY
)

for op in reversal anagram move deletion insertion substitution; do
  same "$op accepts its mapping and refuses a wrong one" "$(grep "^OP $op " <<<"$out")" "OP $op True False"
done
same "a correct alteration is written" "$(grep '^GOOD' <<<"$out")" "GOOD accepted"
same "an op that does not map the word is refused" "$(grep '^WRONGOP' <<<"$out")" "WRONGOP ALTERED"
same "no preamble, no alteration" "$(grep '^NOPREAMBLE' <<<"$out")" "NOPREAMBLE ALTERED"
same "the last step's result is the solution, not a gives" "$(grep '^LASTGIVES' <<<"$out")" "LASTGIVES ALTERED"
same "a chain of steps through gives is accepted" "$(grep '^CHAINOK' <<<"$out")" "CHAINOK accepted"
same "a middle step without gives is refused" "$(grep '^CHAINNOGIVES' <<<"$out")" "CHAINNOGIVES ALTERED"
same "an op outside the enum is refused" "$(grep '^BADOPNAME' <<<"$out")" "BADOPNAME ALTERED | SCHEMA"
same "pieces building the clue's word pass" "$(grep '^PIECES FROM' <<<"$out")" "PIECES FROM False"
same "pieces building the entry fail" "$(grep '^PIECES ENTRY' <<<"$out")" "PIECES ENTRY True"

[ "$fails" -eq 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
