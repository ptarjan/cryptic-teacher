#!/usr/bin/env bash
# annotate_check takes a link word out of the block it sits in when exactly one
# edit does it cleanly, and leaves the rest, with the edit named, to the run.
# The annotations are first-check failures from real annotate transcripts.
#
#     bash tools/test_link_word_untangle.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import json, pathlib, tempfile
import annotate_check as C
import validate_annotations as V
from fetch_puzzle import read_puzzle_view, resolve_puzzle

fails = 0
def check(name, ok, got=None):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name + ("" if ok else f" — got {got!r}"))
    fails += not ok

def anagram(defn, ind, link, frag, gives, fodder, answer):
    return {"type": ["anagram"], "definitions": [{"text": defn}],
            "indicators": [{"text": ind, "for": "anagram",
                            "note": "the letters are rearranged into a new order here"}],
            "linkWords": [link], "blocks": [{"clueFragment": frag, "gives": gives, "note": "as written"}],
            "assembly": {"anagrams": [{"fodder": fodder, "gives": answer}]},
            "explanation": {"walkthrough": "An anagram of the fodder gives the answer.",
                            "definitionFit": "The definition means the answer in ordinary use."}}

def untangle(stem, eid, ann):
    pending = pathlib.Path(tempfile.mkdtemp()) / f"_ann_{stem}.json"
    pending.write_text(json.dumps({eid: ann}), encoding="utf-8")
    changed = C.untangle_link_words(resolve_puzzle(stem), pending)
    return changed, json.loads(pending.read_text(encoding="utf-8"))[eid]

# The link word is fodder: USGUNMANIS uses the letters of "is".
ann = anagram("meek", "deceptively", "is", "US gunman is", "USGUNMANIS", "USGUNMANIS", "UNASSUMING")
changed, out = untangle("quiptic-587", "14-down", ann)
check("a link word whose letters the block uses leaves linkWords",
      changed and out.get("linkWords") == [] and out["blocks"] == ann["blocks"], (changed, out))

# The block ran onto the link: RANDOMISE is DISARMONE, so "to" is trimmed off.
ann = anagram("Make arbitrary", "change", "to", "to disarm one", "TODISARMONE", "DISARMONE", "RANDOMISE")
changed, out = untangle("toughie-3771", "12-across", ann)
check("a fragment that ran onto the link is trimmed, its literal gives with it",
      changed and out["linkWords"] == ["to"]
      and out["blocks"][0]["clueFragment"] == "disarm one" and out["blocks"][0]["gives"] == "DISARMONE",
      (changed, out))

# "with" adds no letters to METFATAL: dropping it from linkWords would hide the
# block's slip, and no trim reaches it, so nothing is written.
ann = anagram("Living companion", "complication", "with", "met with fatal", "METFATAL", "METFATAL", "FLATMATE")
changed, out = untangle("quiptic-586", "15-down", ann)
check("a link word that gives the block nothing is not dropped", not changed and out == ann, (changed, out))

# A tie: on a cryptic definition, dropping "is" and trimming "is duped?" are
# both clean, and which is meant is a judgement.
ann = {"type": ["cryptic_definition"], "definitions": [{"text": "duped"}], "linkWords": ["is"],
       "blocks": [{"clueFragment": "The car's passenger, on a trip", "note": "surface reading of a car trip"},
                  {"clueFragment": "is duped?", "note": "the same idiom means having been tricked"}],
       "explanation": {"walkthrough": "The phrase literally describes a passenger, idiomatically a mark.",
                       "definitionFit": "Being taken for a ride means being duped."}}
changed, out = untangle("everyman-3320", "20-across", ann)
check("two equally clean edits: nothing is written", not changed and out == ann, (changed, out))

# A link word clear of every block is not touched.
ann = anagram("meek", "deceptively", "is", "US gunman", "USGUNMAN", "USGUNMAN", "UNASSUMING")
check("no conflict: no candidates", C.link_word_candidates({**ann, "linkWords": ["meek"]},
      "US gunman is deceptively meek") == [])

check("letters the fragment keeps without the link: it adds nothing",
      V.link_adds_nothing("met with fatal", "with", "METFATAL"))
check("letters only the link supplies: it is fodder",
      not V.link_adds_nothing("US gunman is", "is", "USGUNMANIS"))
check("a gives not drawn from the fragment: no claim either way",
      not V.link_adds_nothing("Carpet is", "is", "RUG"))

# A link word landing on a definition or indicator (check_link_word_is_clear_of_other_marks):
# committed annotations with the link words a real first check rejected put back.
def committed(stem, eid):
    # Through the view: from step 8 the corpus file is format v2, whose
    # annotation stores the tree and view() gives the legacy fields (linkWords).
    d = read_puzzle_view(resolve_puzzle(stem))
    e = next(e for e in d["entries"] if f"{e['number']}-{e['direction']}" == eid)
    return json.loads(json.dumps(e["annotation"]))

def clear(stem, eid, ann):
    pending = pathlib.Path(tempfile.mkdtemp()) / f"_ann_{stem}.json"
    pending.write_text(json.dumps({eid: ann}), encoding="utf-8")
    changed = C.clear_link_words(resolve_puzzle(stem), pending)
    return changed, json.loads(pending.read_text(encoding="utf-8"))[eid]

# An &lit: the whole clue is the definition, so "and" is no link.
ann = {**committed("everyman-3294", "13-down"), "linkWords": ["and"]}
changed, out = clear("everyman-3294", "13-down", ann)
check("an &lit's link word is dropped", changed and not out.get("linkWords"), (changed, out))

# "in which" across the indicator "in": the clear part, "which", stays.
ann = {**committed("quiptic-660", "6-down"), "linkWords": ["in which"]}
changed, out = clear("quiptic-660", "6-down", ann)
check("a link overlapping an indicator is trimmed to its clear words",
      changed and out.get("linkWords") == ["which"], (changed, out))

# "a cooking" across the definition "cooking utensil" goes; it is not trimmed to "a".
ann = {**committed("quiptic-551", "10-across"), "linkWords": ["with", "a cooking"]}
changed, out = clear("quiptic-551", "10-across", ann)
check("a link touching a definition is dropped, not trimmed",
      changed and out.get("linkWords") == ["with"], (changed, out))

ann = committed("quiptic-551", "10-across")
changed, out = clear("quiptic-551", "10-across", ann)
check("a link word clear of every mark is left alone", not changed and out == ann, (changed, out))

def msg(links, blocks):
    errs = []
    V.check_link_word_is_not_inside_a_block("1A", {"linkWords": links, "blocks": blocks},
                                            " ".join(b["clueFragment"] for b in blocks) + " x", errs)
    return errs[0] if errs else ""
m = msg(["with"], [{"clueFragment": "met with fatal", "gives": "METFATAL"}])
check("the message names the split", "split the block 'met with fatal' into 'met' and 'fatal'" in m, m)
m = msg(["is"], [{"clueFragment": "Carpet is", "gives": "RUG"}])
check("the message names the trimmed fragment", "the block is 'Carpet'" in m, m)
m = msg(["is"], [{"clueFragment": "A", "gives": "A"}, {"clueFragment": "is", "gives": "IS"}])
check("the message names a block that is the link word", "is the link word itself" in m, m)
raise SystemExit(fails)
PY
