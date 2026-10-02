#!/bin/bash
# Is `assembly` worked out from the blocks, and only with the clue's own operations?
#
#     bash tools/test_derive_assembly.sh
#
# tools/derive_assembly.py rebuilds the answer from the blocks' letters so the
# annotating model need not retype them. Each operation is tested from both
# sides: found when `type` names it, not found when it does not.
set -uo pipefail
cd "$(dirname "$0")/.."
out=$(PYTHONPATH=tools python3 - <<'PY'
import json, tempfile
from pathlib import Path
import derive_assembly as D
from apply_annotations import with_assembly

S = D.search


def say(name, ok):
    print(f"{name}={'yes' if ok else 'no'}")


say("charade_pieces_are_blocks", S(["SOD", "DEN"], "SODDEN", ["charade"]) == {"pieces": ["SOD", "DEN"]})
say("reversal_found", S(["RATS", "RE", "PUS"], "SUPERSTAR", ["reversal"]) == {
    "pieces": ["SUP", "ER", "STAR"], "reversals": [{"from": "RATSREPUS", "to": "SUPERSTAR"}]})
say("reversal_needs_its_type", S(["RATS", "RE", "PUS"], "SUPERSTAR", ["charade"]) is None)
say("container_found", S(["LID", "MITE"], "LIMITED", ["container"]) == {"pieces": ["LI", "MITE", "D"]})
say("container_inner_first", S(["MITE", "LID"], "LIMITED", ["container"]) == {"pieces": ["LI", "MITE", "D"]})
say("container_needs_its_type", S(["LID", "MITE"], "LIMITED", ["charade", "reversal"]) is None)
say("anagram_inside_charade", S(["F", "MADE", "A", "TORY"], "DEFAMATORY", ["anagram", "charade"]) == {
    "pieces": ["DEFAM", "A", "TORY"], "anagrams": [{"fodder": "F MADE", "gives": "DEFAM"}]})
say("bare_anagram_shuffles_all", S(["TEN", "ALS"], "SLANTE", ["anagram"]) == {
    "anagrams": [{"fodder": "TEN ALS", "gives": "SLANTE"}]})
say("anagram_needs_its_type", S(["TEN", "ALS"], "SLANTE", ["charade"]) is None)
say("reversed_container", S(["MAC", "U"], "CAUM", ["container", "reversal"]) is not None)
say("one_step_per_indicator", S(["AB", "CD"], "BADC", ["reversal"]) is None
    and S(["AB", "CD"], "BADC", ["reversal"], {"reversal": 2}) is not None)
say("every_typed_step_used", S(["PAMA", "AN"], "PANAMA", ["reversal", "container"]) == {
    "pieces": ["PA", "NA", "MA"], "reversals": [{"from": "AN", "to": "NA"}]})
say("container_inside_anagram", S(["HOPE", "PIES"], "HOSEPIPE", ["container", "anagram"]) == {
    "pieces": ["HO", "SEPI", "PE"], "anagrams": [{"fodder": "PIES", "gives": "SEPI"}]})
say("typed_step_must_be_used", S(["NEITHER"], "NEITHER", ["anagram"]) is None
    and S(["DR", "OWNS"], "DROWNS", ["anagram", "charade"]) is None
    and S(["TREE", "ATIS"], "TREATISE", ["anagram", "container"]) is None
    and S(["TOSCA", "NINI"], "TOSCANINI", ["charade", "reversal"]) is None)
say("palindrome_is_no_reversal", S(["SEY", "X"], "SEXY", ["reversal", "container"]) is None)
say("no_reversal_inside_a_reversal", S(["WISH", "OLF"], "WOLFISH", ["container", "reversal"],
                                       {"reversal": 3}) is None)
say("wrong_letters_no_build", S(["SOD", "DEN"], "SODDER", ["charade", "anagram"]) is None)


def ann(**kw):
    return {"type": ["charade"], "answer": "SODDEN",
            "blocks": [{"clueFragment": "a", "gives": "SOD"}, {"clueFragment": "b", "gives": "DEN"}], **kw}


say("missing_filled", D.complete(ann())["assembly"] == {"pieces": ["SOD", "DEN"]})
wrong = ann(assembly={"pieces": ["DEN", "SOD"]})
say("wrong_order_redone", D.complete(wrong)["assembly"] == {"pieces": ["SOD", "DEN"]}
    and wrong["assembly"]["pieces"] == ["DEN", "SOD"])
right = ann(assembly={"pieces": ["SO", "DDEN"]})
say("right_pieces_kept", D.complete(right) is right)
broken = ann(answer="SODDER")
say("failed_search_unchanged", D.complete(broken) is broken)
dd = ann(type=["double_definition"])
say("nothing_to_build_skipped", D.complete(dd) is dd)
say("anagram_whole_drops_pieces", D.complete({
    "type": ["anagram"], "answer": "SILENT", "blocks": [{"clueFragment": "x", "gives": "LISTEN"}],
    "assembly": {"pieces": ["LISTEN"]}})["assembly"] == {
    "anagrams": [{"fodder": "LISTEN", "gives": "SILENT"}]})
say("alteration_from_is_built", with_assembly(
    {"type": ["charade"], "answer": "X", "alteration": {"from": "SODDEN"},
     "blocks": [{"clueFragment": "a", "gives": "SOD"}, {"clueFragment": "b", "gives": "DEN"}]},
    {"solution": "X"})["assembly"] == {"pieces": ["SOD", "DEN"]})
PY
)
echo "$out"
if grep -q "=no" <<<"$out" || ! grep -q "=yes" <<<"$out"; then
  echo "FAIL"; exit 1
fi
echo "ok"
