#!/usr/bin/env bash
# tools/puzzle_tags.py tags what the file states and nothing it only suggests:
# each tag on a real puzzle that has it, and off the look-alike that does not.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import copy
import fetch_puzzle as fp
import puzzle_tags as pt

fails = 0
def check(name, ok, got=""):
    global fails
    fails += not ok
    print(("ok  " if ok else "FAIL"), name, "" if ok else got)

def real(pid):
    return fp.read_puzzle_file(fp.resolve_puzzle(pid))

def tagged(p):
    return pt.tags(p)

# --- pangrams carry their multiplicity ---
maize = real("independent-9740")
check("a quintuple pangram says quintuple", tagged(maize) == ["quintuple-pangram"], tagged(maize))
check("the multiples run on and stop at the last word",
      [pt.pangram_key(n) for n in (1, 2, 3, 8, 12)]
      == ["pangram", "double-pangram", "triple-pangram", "octuple-pangram", "octuple-pangram"])
check("every n-fold pangram implies pangram",
      all(pt.TAGS[pt.pangram_key(n)].get("implies") == "pangram" for n in range(2, 9)))
model = copy.deepcopy(maize)
model["solutions"] = {"origin": "model", "model": "claude-opus-5"}
check("a model's solve is not counted: one wrong letter is a false pangram",
      not any(t.endswith("pangram") for t in tagged(model)), tagged(model))
gap = copy.deepcopy(maize)
gap["entries"][0].pop("solution")
check("a grid with an unknown answer is no pangram",
      not any(t.endswith("pangram") for t in tagged(gap)), tagged(gap))
# Letters are counted per square: the Z shared by two crossing lights is one Z.
cross = {"dimensions": {"rows": 2, "cols": 2}, "solutions": {"origin": "published"},
         "entries": [{"number": 1, "direction": "across", "position": {"x": 0, "y": 0},
                      "length": 2, "clue": {"text": "x"}, "solution": "ZA"},
                     {"number": 1, "direction": "down", "position": {"x": 0, "y": 0},
                      "length": 2, "clue": {"text": "x"}, "solution": "ZB"}]}
check("a crossing square counts once", sorted(pt.grid_letters(cross).values()) == ["A", "B", "Z"])

# --- unclued: the setter's blank, not a feed's ---
check("cryptic-30098's blank 12-across is an unclued answer", "unclued" in tagged(real("cryptic-30098")))
check("a ring of unclued squares is unclued answers", "unclued" in tagged(real("cyclops-511")))
check("a puzzle whose feed lost most of its clues is not",
      "unclued" not in tagged(real("cryptic-22917")))
check("a blank with no count printed is not", "unclued" not in tagged(real("canberra-671014")))

# --- jigsaw: the preamble withholds where the answers go ---
check("a jigsaw-wise preamble is a jigsaw", "jigsaw" in tagged(real("cryptic-24331")))
check("clues in their answers' alphabetical order are a jigsaw",
      pt.is_jigsaw(real("cryptic-22297")))
check("interchangeable acrosses and downs are a jigsaw", pt.is_jigsaw(real("cryptic-23269")))
check("clues the paper printed with no grid numbers are a jigsaw, whatever the preamble says",
      pt.is_jigsaw({"cluesUnplaced": True, "preamble": "A special set of clues."})
      and pt.jigsaw_tag({"cluesUnplaced": True}) == "jigsaw")
check("(mirror) the same preamble without the field is not a jigsaw",
      not pt.is_jigsaw({"preamble": "A special set of clues."}))
check("a prize whose PDF lettered its clues is a jigsaw", "jigsaw" in tagged(real("cryptic-24433")))
check("a theme note is not a jigsaw", not pt.is_jigsaw(real("cryptic-22863")))
check("an alphabet puzzle with no such note is not", not pt.is_jigsaw(real("toughie-2768")))
check("no preamble is no jigsaw", not pt.is_jigsaw({"preamble": None}))
check("answers placed at atomic numbers keep the grid's numbers",
      "numbered-jigsaw" in tagged(real("cryptic-22297")) and "jigsaw" not in tagged(real("cryptic-22297")))
check("(mirror) a plain jigsaw-wise grid is unnumbered",
      "numbered-jigsaw" not in tagged(real("cryptic-24331")))
check("a numbered jigsaw is still a jigsaw", pt.TAGS["numbered-jigsaw"]["implies"] == "jigsaw")

# --- alphabetical ---
check("an alphabet jigsaw is alphabetical", "alphabetical" in tagged(real("cryptic-22387")))
check("so is an alphabetical with two spare answers", "alphabetical" in tagged(real("toughie-2768")))
check("a Jumbo is not, however many initials it covers",
      "alphabetical" not in tagged(real("timesjumbo-1394")))

# --- special rules: a rule-setting preamble, never an erratum ---
check("a themed preamble sets special rules", "special-rules" in tagged(real("ftcryptic-16861")))
check("a corrected clue does not", "special-rules" not in tagged(real("cryptic-27981")))
check("nor does a sponsorship note", "special-rules" not in tagged(real("cryptic-23450")))

# --- a nina the paper kept quiet: a blog quotes it, our grid spells it ---
import ninas
thanks = real("independent-8651")
said = "This would normally suggest a nina: around the perimeter we have A BIG THANK YOU TO ALL TEST SOLVERS."
check("a perimeter message a post quotes near 'nina' is found",
      (ninas.find(thanks, said) or ())[:2] == ("perimeter", "ABIGTHANKYOUTOALLTESTSOLVERS"),
      ninas.find(thanks, said))
check("the same words with nothing pointing at the grid are not a nina",
      ninas.find(thanks, "A BIG THANK YOU TO ALL TEST SOLVERS.") is None)
check("answers the blogger writes out side by side are not a nina",
      ninas.find(thanks, "No nina here. ATTAIN IDIOLECT BASEBALL") is None,
      ninas.find(thanks, "No nina here. ATTAIN IDIOLECT BASEBALL"))
check("an answer and the next word's first letter are not a nina",
      ninas.find(real("cryptic-26253"), "Any nina? 11 TURBINE Engine 12 ENCLAVE") is None)
check("the words in lower case are prose, not a quoted message",
      ninas.find(thanks, "A nina: around the perimeter we have a big thank you to all test solvers.") is None)
split = "A nina: around the perimeter A B I G THANK YOU TO ALL TEST SOLVERS."
check("letters a parsing splits off are not words of the message",
      (ninas.find(thanks, split) or ())[1:2] == ("THANKYOUTOALLTESTSOLVERS",), ninas.find(thanks, split))
check("a blogged nina in tools/data/ninas.json tags the puzzle",
      "hidden-message" in tagged(thanks))

# --- the grid's shape ---
check("a Listener is a barred grid", "barred" in tagged(real("listener-1")))
check("a published grid a half turn does not map onto is asymmetric",
      "asymmetric" in tagged(real("independent-9010")))
check("a symmetric grid is not asymmetric", "asymmetric" not in tagged(real("cryptic-30098")))
check("printed letters are letters given", "letters-given" in tagged(real("listener-93")))

# --- big grid: bigger than the series' usual size or the corpus's ---
areas = [(f"d-{i}", "daily", 225) for i in range(60)] + [("d-big", "daily", 529)] \
    + [("l-1", "weekly", 144), ("l-2", "weekly", 169), ("l-3", "weekly", 289)] \
    + [(f"j-{i}", "jumbo", 529) for i in range(4)] \
    + [(f"q-{i}", "quick", 169) for i in range(5)] + [("q-big", "quick", 225)]
check("bigger than the series' usual size is a big grid",
      {"d-big", "q-big"} <= pt.big_grids(areas), pt.big_grids(areas))
check("a jumbo series, bigger than the corpus's usual size every time, is all big grids",
      {f"j-{i}" for i in range(4)} <= pt.big_grids(areas))
check("a series with no usual size is held to the corpus's: only its grid past 15 by 15",
      {p for p in pt.big_grids(areas) if p.startswith("l-")} == {"l-3"}, pt.big_grids(areas))
check("a usual-sized grid is not big", not pt.big_grids(areas) & {"d-0", "q-0", "l-1"})

# --- the index carries them ---
row = fp.index_row(fp.resolve_puzzle("independent-9740"))
check("the index row carries the tags", row.get("tags") == ["quintuple-pangram"], row.get("tags"))
plain = fp.index_row(fp.resolve_puzzle("cryptic-30066"))
check("a row with nothing unusual has no tags key", "tags" not in plain, plain.get("tags"))
check("every label and blurb is a sentence without a count of the archive",
      all(not any(ch.isdigit() for ch in v["label"] + v["blurb"]) for v in pt.TAGS.values()))
raise SystemExit(fails)
PY
echo "all puzzle tag checks passed"
