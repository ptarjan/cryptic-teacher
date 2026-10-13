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
# A selection the words give more than one way (Wigan middle: G or IGA) under
# an unchecked step: no answer steers it there, so it keeps the filed letters
# (tls-1128 13A; timesjumbo-1591 28D "in opera house" last NAE, not E).
for name, a_, e_, frag, want_ in (
        ("a selection with several readings under an unchecked step keeps its filed letters",
         ann(["container", "charade", "letter_selection"], "LITIGANT", "defendant?", 41,
             [blk("Literary", "LIT"), blk("Wigan", "IGA", select="middle"), blk("books", "NT")],
             [("caseless", "letter_selection"), ("about", "container")]),
         entry("LITIGANT", "Literary books about caseless Wigan defendant?"), "Wigan", "IGA"),
        ("a last-letters selection under an unchecked step keeps its filed letters",
         ann(["container", "charade", "letter_selection"], "LADONNAEMOBILE", "Aria", 0,
             [blk("boy", "LAD"), blk("on"), blk("in opera house", "NAE", select="last"), blk("phone", "MOBILE")],
             [("ultimately", "letter_selection"), ("captured by", "container")]),
         entry("LADONNAEMOBILE", "Aria in opera house ultimately captured by boy on phone", "2,5,1,6"),
         "in opera house", "NAE")):
    run(name, a_, e_, "normalised", ["unchecked step kept"],
        tree_check=lambda t, e_=e_, frag=frag, want_=want_: [
            b.get("gives") for b in annotation.view(t, e_)["blocks"] if b.get("clueFragment") == frag] == [want_])
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
new = run("answer spaced against its enumeration is respaced to it, not refused",
          ann(["charade"], "WAR PAINT", "Make-up", 0, [blk("conflict", "WAR"), blk("colour", "PAINT")]),
          entry("WARPAINT", "Make-up conflict colour", "8"), "normalised", ["answer respaced to the enumeration"])
check("the contradicting spacing is not kept", "spelling" not in new, new)
new = run("a spacing that is the enumeration's own is kept when the entry has no separators",
          ann(["charade"], "OPEN-AIR", "Outdoor", 0, [blk("free", "OPEN"), blk("tune", "AIR")]),
          entry("OPENAIR", "Outdoor free tune", "4-3"), "exact")
check("that spacing is the spelling", new.get("spelling") == "OPEN-AIR", new)
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
          entry("STEEL", "Steel, silver, silicon or scandium, say?"), "exact",
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

# The residue of the 10-13 dry run.
two = [{"text": "Maybe squash", "at": 0}, {"text": "plant variant?", "at": 13}]
run("a double definition's block differs from its definition only by punctuation",
    ann(["double_definition"], "SPORT", "", 0, [blk("Maybe squash", "SPORT"), blk("plant variant", "SPORT")],
        definitions=two),
    entry("SPORT", "Maybe squash plant variant?"), "normalised", ["double definition gives the answer"])
run("a double definition filing one definition as its only block",
    ann(["double_definition"], "GEL", "", 0, [blk("Posh female")],
        definitions=[{"text": "Posh female", "at": 0}, {"text": "set", "at": 12}]),
    entry("GEL", "Posh female set"), "normalised", ["double definition blocks recomputed"])
run("a double definition block that is no definition is redone",
    ann(["double_definition"], "KNOCK", "", 0,
        [blk("Criticise", "KNOCK"), blk("minor injury", "KNOCK"), blk("time at the crease", "KNOCK")],
        definitions=[{"text": "Criticise", "at": 0}, {"text": "minor injury", "at": 10}]),
    entry("KNOCK", "Criticise minor injury in time at the crease"), "failed",
    ["double definition block that is no definition"])
run("a double definition with one definition is redone",
    ann(["double_definition"], "CASE", "Legal action", 0, [blk("Legal action")]),
    entry("CASE", "Legal action"), "failed", ["double definition with one definition"])
run("a preamble step stored as a double definition's type is dropped from it",
    ann(["double_definition", "reversal"], "TUO", "", 0, [blk("Cry heard by 28"), blk("not in court")],
        definitions=[{"text": "Cry heard by 28", "at": 0}, {"text": "not in court", "at": 21}]),
    entry("TUO", "Cry heard by 28 when not in court?"), "normalised", ["double definition step type dropped"])
run("a double definition's pun-step indicator hangs on its definitions",
    ann(["double_definition", "deletion"], "USHER", "", 0, [blk("Direct"), blk("officious librarian")],
        [("in Bow", "deletion")],
        definitions=[{"text": "Direct", "at": 0}, {"text": "officious librarian", "at": 11}]),
    entry("USHER", "Direct and officious librarian in Bow?"), "normalised",
    ["double definition step indicators on the definitions"],
    tree_check=lambda n: "wordplay" not in n and n["definitions"][1].get("indicators"))
new = run("an entry with no key keeps the annotation's answer as its spelling",
          ann(["charade"], "WAR PAINT", "Make-up", 0, [blk("conflict", "WAR"), blk("colour", "PAINT")]),
          {**entry("", "Make-up conflict colour", "3,5"), "solution": None}, "exact")
check("no-key spelling", new.get("spelling") == "WAR PAINT", new)
run("a selection block that gives no letters gives what the selection makes of its words",
    ann(["deletion", "letter_selection"], "APPAL", "shock", 42,
        [blk("Attraction", "APPEAL"), blk("source of electric", select="first")],
        [("avoiding", None), ("source of", None)]),
    entry("APPAL", "Attraction in avoiding source of electric shock"), "normalised")
run("a blank-for indicator on a leaf with a selection and a sound takes the next stored type",
    ann(["letter_selection", "homophone"], "ENVY", "Jealousy", 0,
        [blk("leading characters in Nouvelle Vague", "ENVY", select="first", soundsLike="EN VEE")],
        [("leading characters in", None), ("picked up", None)]),
    entry("ENVY", "Jealousy picked up from leading characters in Nouvelle Vague?"), "normalised")

# migrate_puzzle: the bad clue is dropped for the burn, the rest converted.
good = ann(["charade"], "WAR PAINT", "Make-up", 0, [blk("conflict", "WAR"), blk("colour", "PAINT")])
bad = ann(["double_definition"], "CASE", "Legal action", 0, [blk("Legal action")])
pz = {"id": "cryptic-1", "name": "Cryptic crossword No 1", "series": "cryptic", "entries": [
    {**entry("WARPAINT", "Make-up conflict colour", "3,5"), "annotation": good},
    {**entry("CASE", "Legal action", "4"), "number": 2, "annotation": bad},
    {**entry("ABC", "No hint yet", "3"), "number": 3}]}
out, redo = C.migrate_puzzle(pz)
check("migrate_puzzle redoes only the bad clue", list(redo) == ["cryptic-1/2-across"]
      and "annotation" not in out["entries"][1] and "annotation" not in out["entries"][2], (redo, out))
check("migrate_puzzle converts the rest and leaves the input alone",
      "wordplay" in out["entries"][0]["annotation"] and pz["entries"][1]["annotation"] is bad)
check("migrate_puzzle writes a whole v2 file: no name or series", "name" not in out and "series" not in out, out.keys())
check("migrate_puzzle leaves a v2 file as it is", C.migrate_puzzle(out) == (out, {}))
alts = {"id": "cryptic-2", "name": "Cryptic crossword No 2", "series": "cryptic", "entries": [
    {**entry("WARPAINT", "Make-up conflict colour", "3,5"), "alsoLeads": [{"annotation": bad}]}],
    "offGrid": [{"clue": {"text": "Make-up conflict colour", "enumeration": "3,5"}, "solution": "WARPAINT",
                 "annotation": good}]}
out, redo = C.migrate_puzzle(alts)
check("migrate_puzzle reaches alsoLeads and offGrid annotations", list(redo) == ["cryptic-2/1-across"]
      and "annotation" not in out["entries"][0]["alsoLeads"][0]
      and "wordplay" in out["offGrid"][0]["annotation"], (redo, out))
check("tree_counts counts checked and unchecked trees", C.tree_counts(out) == (1, 0), C.tree_counts(out))
# An alsoLeads answer is spaced by its own clue, not its leader's (genius-209
# 22A): the leader's separators belong to its other group, and read from the
# puzzle they made the alsoLeads group look separated, so its stored spacing
# was dropped and view() gave WARPAINT.
see = lambda n, s: {"number": n, "direction": "down", "solution": s, "clue": {"text": "See 1 across"}}
lead = {"id": "genius-9", "name": "Genius 9", "series": "genius", "entries": [
    {**entry("WAR", "Fight zone", "3,4", [(3, ",")]), "group": ["1-across", "2-down"],
     "alsoLeads": [{"clue": {"text": "Make-up conflict colour", "enumeration": "3,5"}, "group": ["1-across", "3-down"],
                    "annotation": ann(["charade"], "WAR PAINT", "Make-up", 0, [blk("conflict", "WAR"), blk("colour", "PAINT")])}]},
    see(2, "ZONE"), see(3, "PAINT")]}
out, redo = C.migrate_puzzle(lead)
got = annotation.view_puzzle(out)["entries"][0]["alsoLeads"][0].get("annotation", {}).get("answer")
check("an alsoLeads answer keeps its own clue's spacing", not redo and got == "WAR PAINT", (redo, got))

# Step 8's tighten blockers (10-13). A palindrome over the answer alone has no
# parts, and a file stores no empty list: the pruned tree still views
# (everyman-3919 10A gave "KeyError: 'parts'").
import puzzle_schema
a = ann(["double_definition", "palindrome"], "BEEB", "Broadcaster", 0,
        [blk("Broadcaster", note="first meaning"), blk("Auntie", note="second meaning")],
        [("put another way", "palindrome")],
        definitions=[{"text": "Broadcaster", "at": 0}, {"text": "Auntie", "at": 30}])
e = entry("BEEB", "Broadcaster; put another way, Auntie")
got, ks, new = C.check(a, e)
pruned = puzzle_schema.prune({"id": "x-1", "number": 1, "entries": [{**e, "annotation": new}]})["entries"][0]["annotation"]
try:
    v = annotation.view(pruned, e)
    check("a palindrome with no parts views once pruned", "parts" not in pruned["wordplay"]
          and v["type"] == ["double_definition", "palindrome"], (pruned, v["type"]))
except Exception as x:
    check("a palindrome with no parts views once pruned", False, repr(x))

# A setter's slip (tools/data/setter_error.json): the legacy assembly names an
# anagram whose fodder lacks the letters it gives. It becomes one unchecked
# anagram over the fodder as printed, which view() lists, even where a block
# hid the slip by respelling its words (quiptic-32 13D: "Elf oil" filed as ELFOIF).
a = ann(["anagram"], "KISS OF LIFE", "First aid", 0,
        [blk("skis", "SKIS"), blk("Elf oil", "ELFOIF")], [("spill", "anagram")],
        assembly={"anagrams": [{"fodder": "SKISELFOIL", "gives": "KISSOFLIFE"}]})
got, ks, new = C.check(a, entry("KISSOFLIFE", "First aid required after skis become involved in Elf oil spill",
                                "4,2,4", [(4, ","), (6, ",")]))
v = new and annotation.view(new, entry("KISSOFLIFE", "First aid required after skis become involved in Elf oil spill",
                                       "4,2,4", [(4, ","), (6, ",")]))
check("a setter's slip is an unchecked anagram of the printed fodder",
      new and new["wordplay"]["op"] == "anagram" and new["wordplay"].get("unchecked")
      and v["assembly"]["anagrams"] == [{"fodder": "SKISELFOIL", "gives": "KISSOFLIFE"}]
      and [b["gives"] for b in v["blocks"]] == ["SKIS", "ELFOIL"], (got, ks, new and new["wordplay"], v and v.get("assembly")))
# The rest of the wordplay is still rebuilt round the slip, and checked
# (azed-2473 17D: BR(E)A + PAINTS giving STPIN, not an anagram of everything).
a = ann(["container", "anagram"], "BREAST PIN", "What'll fix corsage", 0,
        [blk("gay deceiver", "BRA"), blk("east", "E"), blk("paints", "STPIN")],
        [("in", "container"), ("Variety of", "anagram")],
        assembly={"anagrams": [{"fodder": "PAINTS", "gives": "STPIN"}]})
e = entry("BREASTPIN", "What'll fix corsage from east in gay deceiver? Variety of paints")
got, ks, new = C.check(a, e)
check("the wordplay round a slip is rebuilt and checked",
      new and w.render({**new["wordplay"], "parts": new["wordplay"]["parts"][:1]}).startswith("ins")
      and [n["op"] for n in C._walk(new["wordplay"]) if n.get("unchecked")] == ["anagram"],
      (got, ks, new and new["wordplay"]))
# A slip that gives the whole answer beside a block filed as the letter it
# lacks (ftcryptic-18035 21A: "Large" as N, "no clue word supplies one"): that
# block is the annotator's comment, kept as a note that gives no letters.
a = ann(["anagram"], "POLYTUNNEL", "long tent with beds", 24,
        [blk("Large", "N"), blk("opulently", "OPULENTLY")], [("fitted", "anagram")],
        assembly={"anagrams": [{"fodder": "OPULENTLY", "gives": "POLYTUNNEL"}]})
e = entry("POLYTUNNEL", "Large, opulently fitted long tent with beds")
got, ks, new = C.check(a, e)
v = new and annotation.view(new, e)
check("a block making up a slip's missing letter rides along as a note",
      v and [b.get("gives") for b in v["blocks"]] == [None, "OPULENTLY"]
      and v["assembly"]["anagrams"] == [{"fodder": "OPULENTLY", "gives": "POLYTUNNEL"}], (got, ks, v and v["blocks"]))
# Blocks giving other letters than the slip lacks contradict the row: redo.
a = ann(["anagram"], "POLYTUNNEL", "long tent with beds", 24,
        [blk("Large", "L"), blk("opulently", "OPULENTLY")], [("fitted", "anagram")],
        assembly={"anagrams": [{"fodder": "OPULENTLY", "gives": "POLYTUNNEL"}]})
got, ks, new = C.check(a, e)
check("a slip the blocks contradict is redone", got == "failed" and "setter's slip and blocks disagree" in ks, (got, ks))

# A double definition's block note is its `meaning`; a definition's own note
# stays on the definitions rung, also when the definition had no block
# (times-29410 26A's note "read as FLY BY NIGHT").
a = ann(["double_definition"], "FLY-BY-NIGHT", "Debtor absconding", 0,
        [blk("on the red-eye", note="a red-eye is an overnight flight")],
        definitions=[{"text": "Debtor absconding", "at": 0, "note": "read as FLY BY NIGHT"},
                     {"text": "on the red-eye", "at": 18}])
e = entry("FLYBYNIGHT", "Debtor absconding on the red-eye?", "3-2-5", [(3, "-"), (5, "-")])
got, ks, new = C.check(a, e)
v = new and annotation.view(new, e)
check("a definition's note is never a block's", v and v["blocks"] == [
    {"clueFragment": "Debtor absconding"}, {"clueFragment": "on the red-eye", "note": "a red-eye is an overnight flight"}],
    (got, ks, v and v["blocks"]))

# Linked answers: the lead prints the whole group's enumeration (Guardian),
# or each leg's own length (Private Eye), or reads in another order.
def leg(num, d, sol, text=None, enum=None, seps=(), group=None):
    e = {"number": num, "direction": d, "solution": sol,
         "clue": {**({"text": text} if text else {"missing": True}), **({"enumeration": enum} if enum else {}),
                  **({"separators": [{"at": a, "mark": m} for a, m in seps]} if seps else {})}}
    return {**e, **({"group": group} if group else {})}

lead = leg(18, "down", "THENIGHT", "Culling", "3,5,2,3,4,6", [(3, ","), (8, ",")],
           ["18-down", "9-across", "24-down", "3-down"])
p = {"id": "cryptic-21913", "entries": [lead, leg(9, "across", "OFTHE", "See 18", "5"),
     leg(24, "down", "LONG", "See 18", "4", [(2, ",")]), leg(3, "down", "KNIVES", "See 18", "6")]}
check("a lead's enumeration spaces the whole linked answer (not each leg's stray separators)",
      annotation.display_answer(lead, p) == "THE NIGHT OF THE LONG KNIVES", annotation.display_answer(lead, p))
lead = leg(8, "down", "WORK", "(& 24dn.) Labour stony", "4", group=["8-down", "24-down"])
p = {"id": "cyclops-550", "entries": [lead, leg(24, "down", "OFART", "see 8dn.", "5")]}
check("legs that print their own lengths break between lights",
      annotation.display_answer(lead, p) == "WORK OFART", annotation.display_answer(lead, p))
got, ks, new = C.check(ann(["anagram"], "WORK OF ART", "Labour", 9, [blk("stony", "WORKOFART")]), lead, p)
check("... and the stored spacing is the spelling: the enumeration can't give it",
      new and new.get("spelling") == "WORK OF ART" and annotation.view(new, lead, p)["answer"] == "WORK OF ART",
      (got, ks, new))
lead = leg(5, "across", "WONDER", "Di Prince", "6,5", group=["5-across", "5-down"])
p = {"id": "cryptic-24331", "entries": [lead, leg(5, "down", "WOMAN", "See 5 across", "5")]}
check("a lead's break where the lights meet needs no separator",
      annotation.display_answer(lead, p) == "WONDER WOMAN", annotation.display_answer(lead, p))
lead = leg(18, "across", "FIRE", "Spirit", "9", group=["18-across", "22-down"])
p = {"id": "cryptic-22050", "entries": [lead, leg(22, "down", "WATER", "See 18", "5")]}
check("one word over two lights stays one word",
      annotation.display_answer(lead, p) == "FIREWATER", annotation.display_answer(lead, p))
lead = leg(10, "across", "ROOK", "Chessman", "5,4", [(5, ",")], ["10-across", "11-across"])
p = {"id": "cryptic-25358", "entries": [lead, leg(11, "across", "SPAWN", "See 10")]}
check("a light may end mid-word: the lead's enumeration still spaces the whole",
      annotation.display_answer(lead, p) == "ROOKS PAWN", annotation.display_answer(lead, p))
# Mephisto: a bare count is one word or a hyphenated one (Chambers), so
# the stored hyphen stands; "(10, two words)" is filed as separators.
got, ks, new = C.check(ann(["charade"], "L-PLATES", "Learner's signs", 0, [blk("left", "L"), blk("dishes", "PLATES")]),
                       entry("LPLATES", "Learner's signs left dishes", "7"), {"id": "mephisto-2964", "entries": []})
check("Mephisto prints letter counts for hyphenated words: the hyphen is kept",
      got != "failed" and new.get("spelling") == "L-PLATES", (got, ks, new))
e = entry("SQUAREROOT", "Satisfying grub", "6,4", [(6, ",")])
check("... and its printed word break still spaces the answer",
      annotation.spaced("SQUAREROOT", e, {"id": "mephisto-3078"}) == "SQUARE ROOT")

raise SystemExit(fails > 0)
PY
