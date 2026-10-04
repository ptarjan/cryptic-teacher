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

# --- the grid's shape ---
check("a Listener is a barred grid", "barred" in tagged(real("listener-1")))
check("a published grid a half turn does not map onto is asymmetric",
      "asymmetric" in tagged(real("independent-9010")))
check("a symmetric grid is not asymmetric", "asymmetric" not in tagged(real("cryptic-30098")))
check("printed letters are letters given", "letters-given" in tagged(real("listener-93")))

# --- big grid needs a series with a usual size ---
areas = [(f"d-{i}", "daily", 225) for i in range(9)] + [("d-big", "daily", 529)] \
    + [("l-1", "weekly", 144), ("l-2", "weekly", 169), ("l-3", "weekly", 289)]
check("bigger than the series' usual size is a big grid, and a series with no usual size has none",
      pt.big_grids(areas) == {"d-big"}, pt.big_grids(areas))

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
