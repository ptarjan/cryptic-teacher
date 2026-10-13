#!/usr/bin/env bash
# Does tools/convert_v2.py turn today's annotations into wordplay trees that
# lose nothing: view() of the tree gives back the stored blocks, indicators,
# definitions and type (or names the accepted difference), a step the blocks
# can't rebuild stays an unchecked node, and an answer that contradicts its
# enumeration is refused?
#
#     bash tools/test_convert_v2.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import annotation
import convert_v2 as C
import wordplay as w

fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else detail)

def entry(solution, clue, enum="", seps=()):
    return {"number": 1, "direction": "across", "solution": solution,
            "clue": {"text": clue, **({"enumeration": enum} if enum else {}),
                     **({"separators": [{"at": a, "mark": m} for a, m in seps]} if seps else {})}}

def blk(frag, gives=None, note="n", **kw):
    b = {"clueFragment": frag, **({"gives": gives} if gives else {}), "note": note}
    b.update(kw)
    return b

def ann(types, answer, defn, at, blocks, inds=(), **kw):
    a = {"type": types, "answer": answer, "definitions": [{"text": defn, "at": at}],
         "blocks": blocks, "explanation": {"walkthrough": "w"}}
    if inds:
        a["indicators"] = [{"text": t, "for": f, "note": "why"} for t, f in inds]
    a.update(kw)
    return a

def unchecked(tree):
    return [n for n in C._walk(tree) if n.get("unchecked")]

# The fixtures carry no assembly, linkWords or applied-order type: those
# derived fields are recomputed, which is not what these cases are about.
FIXTURE = {"assembly recomputed", "type order", "linkWords recomputed"}

def run(name, a, e, status, kinds=(), tree_check=None):
    got, ks, new = C.check(a, e)
    ks = ks - FIXTURE
    if got == "normalised" and not ks:
        got = "exact"
    ok = got == status and all(k in ks for k in kinds)
    if ok and tree_check:
        ok = tree_check(new)
    check(name, ok, f"{got} {sorted(ks)} {new and new.get('wordplay')}")
    return new

# A deletion of the block that follows: del([accept]BUY, [you]U), checked.
run("deletion of the next block",
    ann(["charade", "deletion"], "LOOBY", "Fool", 0,
        [blk("can", "LOO"), blk("accept", "BUY"), blk("you", "U")], [("losing", "deletion")],
        linkWords=["is"]),
    entry("LOOBY", "Fool is can accept losing you"), "exact",
    tree_check=lambda t: not unchecked(t["wordplay"]) and t["wordplay"]["parts"][1]["op"] == "deletion")
# Beheading: the removed letter is no block, so it is bare letters.
run("deletion of letters no block names",
    ann(["deletion"], "AVID", "Great", 0, [blk("biblical king", "DAVID")], [("beheaded", "deletion")]),
    entry("AVID", "Great biblical king beheaded"), "exact",
    tree_check=lambda t: t["wordplay"]["parts"][1] == {"gives": "D"})
# Scattered letters: no tree rebuilds it, so the step stays unchecked, blocks intact.
new = run("a deletion the blocks can't rebuild stays unchecked",
          ann(["deletion"], "IMPLY", "Suggest", 0,
              [blk("impolitely", "IMPOLITELY"), blk("Eliot's characters", "ELIOT")], [("being dropped", "deletion")]),
          entry("IMPLY", "Suggest impolitely Eliot's characters being dropped"), "normalised", ["unchecked step kept"],
          tree_check=lambda t: t["wordplay"].get("unchecked") and t["wordplay"]["op"] == "deletion")
check("an unchecked node renders as a form the parser refuses",
      w.render(new["wordplay"]).startswith("?del"), w.render(new["wordplay"]))
try:
    w.parse(w.render(new["wordplay"]))
    check("the expression can't write an unchecked node", False, "parsed")
except w.WordplayError:
    check("the expression can't write an unchecked node", True)
# Inner block filed first: the tree stores the container outer first.
run("container filed inner first becomes outer first",
    ann(["container"], "IN VITRO", "outside the body", 0,
        [blk("six", "VI"), blk("opening", "INTRO")], [("swallowing", "container")]),
    entry("INVITRO", "outside the body opening swallowing six", "2,5", [(2, ",")]),
    "normalised", ["container outer first"],
    tree_check=lambda t: t["wordplay"]["op"] == "container" and t["wordplay"]["parts"][0]["words"] == "opening")
# A selection from a synonym can't be checked: an unchecked selection keeps `select`.
run("a selection the words don't give stays unchecked with its select",
    ann(["charade", "letter_selection"], "EVEN", "Level", 0,
        [blk("first lady", "E", select="first"), blk("vehicle", "VEN")], [("first", "letter_selection")]),
    entry("EVEN", "Level first lady vehicle"), "normalised", ["unchecked step kept"])
# A selection the words do give is a checked op.
run("a selection the words give is checked",
    ann(["charade", "letter_selection"], "SOVAL", "Volley", 0,
        [blk("symbol", "S", select="first"), blk("oval", "OVAL")], [("originally", "letter_selection")]),
    entry("SOVAL", "Volley symbol originally oval"), "exact",
    tree_check=lambda t: not unchecked(t["wordplay"]))
# A double definition: the definition's own note stays, the block note is its meaning.
a = {"type": ["double_definition"], "answer": "RAISIN", "explanation": {"walkthrough": "w"},
     "definitions": [{"text": "Growin'", "at": 0, "note": "dropped g"}, {"text": "fruit", "at": 8}],
     "blocks": [{"clueFragment": "Growin'", "note": "first meaning: raising"},
                {"clueFragment": "fruit", "note": "second meaning: a dried grape"}]}
new = run("double definition keeps the definition note apart from the block note", a,
          entry("RAISIN", "Growin' fruit"), "normalised", ["double definition meaning kept apart"])
check("the definition's own note is kept", new["definitions"][0].get("note") == "dropped g"
      and new["definitions"][0].get("meaning") == "first meaning: raising", new["definitions"])
# A hidden reversal filed with the letters after the reversal.
run("hidden letters filed after the reversal are stored before it",
    ann(["hidden_word", "reversal"], "EBONY", "Wood", 0, [blk("say no before", "EBONY")],
        [("Some", "hidden_word"), ("going round", "reversal")]),
    entry("EBONY", "Wood Some say no before going round"), "normalised", ["gives before the op"])
# Answers: spaced against the enumeration is refused; with no enumeration it is a fact.
run("answer spaced against its enumeration is refused",
    ann(["charade"], "WAR PAINT", "Make-up", 0, [blk("conflict", "WAR"), blk("colour", "PAINT")]),
    entry("WARPAINT", "Make-up conflict colour", "8"), "failed", ["answer contradicts enumeration"])
new = run("no enumeration: the stored spacing is kept as spelling",
          ann(["charade"], "RIG OUT", "Dress", 0, [blk("fix", "RIG"), blk("away", "OUT")]),
          entry("RIGOUT", "Dress fix away"), "exact")
check("spelling holds the spacing", new.get("spelling") == "RIG OUT", new)
got, ks, new = C.check(ann(["charade"], "WELL-EARNED", "Thoroughly deserved", 0,
                           [blk("fine", "WELL"), blk("got", "EARNED")]),
                       entry("WELLEARNED", "Thoroughly deserved fine got", "10"), {"id": "azed-1743", "entries": []})
check("Azed prints letter counts only: the hyphen is kept as spelling",
      got != "failed" and new.get("spelling") == "WELL-EARNED", (got, ks, new))
run("an apostrophe is kept as spelling",
    ann(["charade"], "CAT-O'-NINE-TAILS", "Whip", 0,
        [blk("pet", "CAT"), blk("old", "O"), blk("number", "NINE"), blk("narratives", "TAILS")]),
    entry("CATONINETAILS", "Whip pet old number narratives", "3-1-4-5", [(3, "-"), (4, "-"), (8, "-")]), "exact")
# Two definitions and wordplay: the tree holds both, and view() gives the
# double definition back with the wordplay's type.
two = [{"text": "Entirely", "at": 0}, {"text": "without a catch", "at": 9}]
run("a double definition with wordplay as well",
    ann(["double_definition", "charade"], "CLEAN", "", 0, [blk("Circle", "C"), blk("angling", "LEAN")],
        definitions=two),
    entry("CLEAN", "Entirely without a catch. Circle angling will admit that"), "exact",
    tree_check=lambda n: len(n["definitions"]) == 2 and n["wordplay"]["op"] == "charade")
run("two definitions are a double definition when the stored type left it out",
    ann(["charade"], "CLEAN", "", 0, [blk("Circle", "C"), blk("angling", "LEAN")], definitions=two),
    entry("CLEAN", "Entirely without a catch. Circle angling will admit that"), "normalised",
    ["type recomputed (+double_definition)"])
run("a double definition whose blocks each give the whole answer",
    ann(["double_definition"], "GEL", "", 0, [blk("Posh female", "GEL"), blk("set", "GEL")],
        definitions=[{"text": "Posh female", "at": 0}, {"text": "set", "at": 12}]),
    entry("GEL", "Posh female set"), "normalised", ["double definition gives the answer"],
    tree_check=lambda n: "wordplay" not in n)
run("a definition heard as another word keeps its homophone",
    ann(["double_definition", "homophone"], "CANE", "", 0,
        [blk("A variety of sugar"), blk("beet", "CANE", soundsLike="BEAT")], [("we're told", "homophone")],
        definitions=[{"text": "A variety of sugar", "at": 0}, {"text": "beet", "at": 19}]),
    entry("CANE", "A variety of sugar-beet, we're told"), "normalised",
    tree_check=lambda n: any(x.get("op") == "homophone" for x in C._walk(n["wordplay"])))

# A palindrome checks the letters of what it governs.
run("a palindrome round the whole wordplay",
    ann(["charade", "palindrome"], "NIP IN", "Call briefly", 0, [blk("Ulster", "NI"), blk("fix", "PIN")],
        [("works either way", "palindrome")]),
    entry("NIPIN", "Call briefly for Ulster fix that works either way", "3,2", [(3, ",")]), "exact",
    tree_check=lambda n: n["wordplay"]["op"] == "palindrome" and not unchecked(n["wordplay"]))
run("a palindrome of the part that reads both ways",
    ann(["charade", "palindrome"], "SIEVE", "Riddle", 0,
        [blk("special", "S"), blk("one", "I"), blk("woman", "EVE")], [("reflective", "palindrome")]),
    entry("SIEVE", "Riddle, special one, posed by reflective woman"), "exact",
    tree_check=lambda n: w.render(n["wordplay"]) == "[special]S + [one]I + pal<reflective>([woman]EVE)")
run("a palindrome that is all the wordplay keeps its notes as unchecked leaves",
    ann(["palindrome"], "ABBA", "camel-hair coat", 11, [blk("camel-hair coat")], [("Reversible", "palindrome")]),
    entry("ABBA", "Reversible camel-hair coat"), "normalised", ["unchecked step kept"],
    tree_check=lambda n: n["wordplay"]["op"] == "palindrome")
run("a palindrome type the answer does not have fails",
    ann(["palindrome"], "ABBY", "camel-hair coat", 11, [blk("camel-hair coat")], [("Reversible", "palindrome")]),
    entry("ABBY", "Reversible camel-hair coat"), "failed", ["tree does not give the answer"])

# Double definition and &lit indicators steer the definitions, not the
# letters: they hang on the nearest definition, and view() gives their `for`.
new = run("a double definition's indicator hangs on a definition",
          ann(["double_definition"], "STEEL", "", 0, [blk("Steel"), blk("silver, silicon or scandium")],
              [("say", "double_definition")],
              definitions=[{"text": "Steel", "at": 0}, {"text": "silver, silicon or scandium", "at": 7}]),
          entry("STEEL", "Steel, silver, silicon or scandium, say?"), "normalised",
          ["double definition meaning kept apart"],
          tree_check=lambda n: n["definitions"][1].get("indicators", [{}])[0].get("text") == "say")
run("an &lit indicator hangs on the definition",
    ann(["charade", "and_lit"], "IONA", "Island connected with Columba ultimately?", 0,
        [blk("Island", "I"), blk("connected with", "ON"), blk("Columba ultimately", "A")],
        [("ultimately", "and_lit")]),
    entry("IONA", "Island connected with Columba ultimately?"), "exact",
    tree_check=lambda n: n["definitions"][0].get("indicators") == [{"text": "ultimately", "note": "why"}])

# Lost content is a failure, never a normalisation.
a = ann(["anagram"], "UNSOILED", "Immaculate", 0, [blk("delusion", "DELUSION")], [("crazy", "anagram")])
new, _ = C.convert(a, entry("UNSOILED", "Immaculate crazy delusion"))
new["wordplay"]["indicators"][0]["note"] = "changed"
v = annotation.view(new, entry("UNSOILED", "Immaculate crazy delusion"))
check("a changed indicator note is a failure", "indicators lost" in C.compare(a, new, v)[1])

# Names: the facts a stored name holds beyond display_name.
for pid, name, want in [
    ("cryptic-30134", "Prize crossword No 30,134", ({"prize": True}, None)),
    ("listener-3999", "Listener crossword No 3,999: Tobacco", ({"title": "Tobacco"}, None)),
    ("canberra-920427", "Canberra Times cryptic crossword, Monday 27 April 1992 (English cryptic)",
     ({"label": "English cryptic"}, None)),
    ("times-29000", "Times cryptic crossword No 29,000", ({}, None)),
    ("indysunday-1118", "Independent sunday cryptic crossword No 1,118", ({}, "name normalised (indysunday)")),
]:
    got = C.puzzle_names({"id": pid, "name": name})
    check(f"puzzle_names {pid}", got == want, got)

raise SystemExit(fails > 0)
PY
