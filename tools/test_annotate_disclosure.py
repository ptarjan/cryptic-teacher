#!/usr/bin/env python3
# Do the annotation rules arrive where they are broken?
#
#     python3 tools/test_annotate_disclosure.py
#
# tools/annotate_prompt.md keeps only what no check can see. Every other rule
# lives in the message of the check that catches it, and a few pieces of advice
# are printed by tools/annotate_check.py only in the state that makes them
# matter. That trade only holds if the checks fire on the broken shape and stay
# quiet on the right one, so each is tested from both sides here. The blog
# lookup most of all: it must appear once only the last few clues are null, and
# never earlier, never on a blind run and never for a series nobody blogs.
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)
fails = 0


def same(name, got, want):
    global fails
    if got == want:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name}\n    want {want}\n    got  {got}")
        fails += 1


def count(pattern, path, flags=0):
    """grep -c: how many lines of path match."""
    rx = re.compile(pattern, flags)
    return str(sum(1 for ln in Path(path).read_text().split("\n") if rx.search(ln)))


PROG = r'''import copy
import annotate_check as AC
import validate_annotations as V


def entry(eid, clue="Some words here (4)", sol="ABCD", group=None, **kw):
    num, _, d = eid.partition("-")
    e = {"number": int(num), "direction": d, "clue": {"text": clue},
         "solution": sol, **kw}
    if group:
        e["group"] = group
    return e


def say(name, ok):
    print(f"{name}={'yes' if ok else 'no'}")


# Linked groups: the leader holds the group and the whole annotation; every
# continuation carries neither.
def stored(gives="ABCD", words="words here"):
    """A stored annotation for the clue "Some words here": a definition and a one-leaf tree."""
    return {"definitions": [{"text": "Some", "at": 0}],
            "wordplay": {"words": words, "gives": gives, "at": 5}}


lead_ann = dict(stored("ABCDEFGH"), explanation={"walkthrough": "w"})
g = ["1-across", "2-down"]
good = {"id": "t-1", "number": 1, "entries": [
    entry("1-across", group=g, annotation=lead_ann),
    entry("2-down", sol="EFGH")]}
errs = []
V.check_groups(good, errs)
say("linked_leader_quiet", not errs)

annotated_cont = copy.deepcopy(good)
annotated_cont["entries"][1]["annotation"] = dict(lead_ann)
errs = []
V.check_groups(annotated_cont, errs)
say("annotated_continuation_flagged",
    any(e.startswith("2-down:") and "no annotation" in e for e in errs))

errs, warns = [], []
V.check_every_clue_is_annotated(good["entries"], errs, warns)
ungrouped = copy.deepcopy(good)
del ungrouped["entries"][0]["group"]
lone_errs, warns = [], []
V.check_every_clue_is_annotated(ungrouped["entries"], lone_errs, warns)
say("bare_continuation_not_flagged", not any(e.startswith("2D:") for e in errs)
    and any(e.startswith("2D:") for e in lone_errs))

grouped_cont = copy.deepcopy(good)
grouped_cont["entries"][1]["group"] = g
errs = []
V.check_groups(grouped_cont, errs)
say("grouped_continuation_flagged",
    any(e.startswith("2-down:") and "starts on 1-across, whose clue is a clue of its own" in e
        for e in errs))

# A fragment retyped with straight quotes where the clue has curly ones.
clue = "Setter’s back (4)"
say("hint_names_clue_spelling",
    "'Setter’s'" in V.verbatim_hint("Setter's", clue))
say("hint_without_lookalike_says_copy",
    "character for character" in V.verbatim_hint("Nowhere", clue))

# A block quotes the clue it explains: a fragment the clue lacks fails.
frag = copy.deepcopy(good)
frag["entries"][0]["annotation"] = dict(stored("ABCDEFGH", "sis trumpeted"))
del frag["entries"][0]["annotation"]["wordplay"]["at"]
say("fragment_not_in_clue_fails",
    any("'sis trumpeted' is not in the clue" in e for e in V.validate_puzzle(frag)[1]))

# A hole is the annotating run's failure; in the committed corpus it is a
# clue queued to be annotated again, not a broken build.
hole = [entry("1-across", annotation=stored()), entry("2-across")]
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns)
say("hole_fails_the_run", bool(errs))
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns, corpus=True)
say("hole_queued_in_corpus", not errs and any("queued" in w for w in warns))

# A tree that does not give its answer is dropped from the view and named by
# its wordplay error; it is not also "no annotation" (toughie-2626 1D, 10-23:
# MOBIUS's tree gave MOBIUSSTRIP, and the run spent five turns looking for
# the 1-down it had written).
wrong = {"id": "t-2", "number": 2, "entries": [
    entry("1-across", annotation=stored()), entry("2-across", annotation=stored("ZZZZ"))]}
_, errs, _ = V.validate_puzzle(wrong)
say("wrong_tree_not_called_blank",
    any(e.startswith("2A: wordplay:") for e in errs)
    and not any("no annotation. Every clue" in e for e in errs))

# A half-written file (the downs not reached yet) gets one line naming every
# blank, not the paragraph once per clue; the audit still names its check.
import annotate_audit
half = [entry("1-across", annotation=stored()), entry("1-down"),
        entry("2-down"), entry("3-down", solutionConfidence="LIKELY")]
errs, warns = [], []
V.check_every_clue_is_annotated(half, errs, warns)
tmpl = annotate_audit.load_templates(open(V.__file__).read())
say("blanks_one_line", len(errs) == 1 and errs[0].startswith("1D,2D,3D: no annotation")
    and "half-written" in errs[0] and "3D: a model's LIKELY fill" in errs[0]
    and annotate_audit.rule_name("  ERROR: " + errs[0], tmpl) == "check_every_clue_is_annotated")
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns)
say("one_blank_not_called_half_written", len(errs) == 1 and errs[0].startswith("2A: ")
    and "half-written" not in errs[0])

# The clue is the source's: an annotated clue whose words differ from the
# committed file's fails; one retyped with other punctuation does not.
import fetch_puzzle
import puzzle_paths
from groups import entry_id
committed = puzzle_paths.find("sundaytimes-5067")
held = fetch_puzzle.read_puzzle_file(committed)
lead = next(e for e in held["entries"] if e.get("annotation"))
reworded, retyped = copy.deepcopy(held), copy.deepcopy(held)
next(e for e in reworded["entries"] if entry_id(e) == entry_id(lead))["clue"]["text"] = "Invented " + lead["clue"]["text"]
next(e for e in retyped["entries"] if entry_id(e) == entry_id(lead))["clue"]["text"] = lead["clue"]["text"].replace(" ", "  ") + "!"
errs = []
V.check_clue_unchanged(reworded, committed, errs)
say("reworded_clue_fails", len(errs) == 1 and "\"printedClue\": [" in errs[0])
errs = []
V.check_clue_unchanged(retyped, committed, errs)
say("retyped_clue_passes", not errs)
# A correction filed in SOURCE_CLUE_WRONG lands with its annotation in one run;
# any other rewording of that light still fails.
key = (held["id"], entry_id(lead))
fetch_puzzle.SOURCE_CLUE_WRONG[key] = (lead["clue"]["text"], "Invented " + lead["clue"]["text"], "test")
errs = []
V.check_clue_unchanged(reworded, committed, errs)
say("filed_correction_passes_annotated", not errs)
other = copy.deepcopy(held)
next(e for e in other["entries"] if entry_id(e) == entry_id(lead))["clue"]["text"] = "Rewritten " + lead["clue"]["text"]
errs = []
V.check_clue_unchanged(other, committed, errs)
say("unfiled_rewording_of_filed_light_fails", len(errs) == 1)
# An OCR'd clue (a scan's reading) takes a correction of a misread letter or
# two, never a rewording.
ocr_held = copy.deepcopy(reworded)
ocr_held["source"]["retrievedFrom"] = "newspaper"
errs = []
V.check_clue_unchanged(ocr_held, committed, errs)
say("ocr_rewording_filed_fails", len(errs) == 1 and "OCR" in errs[0])
text = lead["clue"]["text"]
misread = text[:-1] + ("x" if text[-1] != "x" else "y")
fetch_puzzle.SOURCE_CLUE_WRONG[key] = (text, misread, "OCR misread: test")
ocr_fixed = copy.deepcopy(held)
ocr_fixed["source"]["retrievedFrom"] = "newspaper"
next(e for e in ocr_fixed["entries"] if entry_id(e) == entry_id(lead))["clue"]["text"] = misread
errs = []
V.check_clue_unchanged(ocr_fixed, committed, errs)
say("ocr_misread_filed_passes", not errs)
del fetch_puzzle.SOURCE_CLUE_WRONG[key]

# features: absent warns (and counts against the ratchet), present is quiet.
w = []
V.check_features("1A", {}, "Some words", [], w)
say("features_absent_warns", any("no features" in x for x in w))
say("features_counted_by_ratchet", V.count_backlog(w)["features"] == 1)
w = []
V.check_features("1A", {"features": {"misdirectedWord": None, "joke": None,
                                     "answerInScene": False,
                                     "aptDefinition": False}}, "Some words", [], w)
say("features_present_quiet", not w)

# surface: absent on a picture-painting clue warns and counts against the
# ratchet; a short clue, a pure definition, or a present surface is quiet.
w = []
V.check_surface("1A", {"type": ["charade"]}, "Behaved antisocially and gave birth", w)
say("surface_absent_warns", len(w) == 1 and "no explanation.surface" in w[0])
say("surface_counted_by_ratchet", V.count_backlog(w)["explanation.surface"] == 1)
# The ratchet counts clues: noting one of a clue's two indicators splits one
# warning into one per missing note, and must not count the clue twice.
say("note_backlog_counts_clues", V.count_backlog(
    ["7D: indicator 'in' has no note", "7D: indicator 'lifting' has no note",
     "9A: no indicator notes"])["indicators.note"] == 2)
# A block's missing note is its own field: it must not be counted as an
# indicator note (which sent annotators to the wrong field), and a fragment
# that is its own letters needs none.
w = []
V.check_blocks_carry_notes([{"number": 1, "direction": "across", "annotation": {"blocks": [
    {"clueFragment": "worker", "gives": "ANT"}, {"clueFragment": "a", "gives": "A"},
    {"clueFragment": "in", "gives": "IN"}, {"clueFragment": "setter", "gives": "ME", "note": "x"}]}}], w)
c = V.count_backlog(w)
say("block_note_own_field", len(w) == 1 and c["blocks.note"] == 1 and c["indicators.note"] == 0
    and "notes" in w[0] and "'worker'" in w[0])
# A block with no clue words has no fragment to key a note on, and the
# no-clueFragment check already speaks for it: no second, unanswerable line.
w = []
V.check_blocks_carry_notes([{"number": 9, "direction": "down", "annotation": {"blocks": [
    {"gives": "EDGE"}, {"clueFragment": "", "gives": "EDGE"}]}}], w)
say("fragmentless_block_no_note_line", not w)
# A sound clue with no soundsLike: the error names this clue's block and the wp to write.
e = []
V.check_sound_names_its_source("1A", {"type": ["homophone"], "answer": "PACK", "blocks": [
    {"clueFragment": "bundle", "gives": "PACK"}]}, e, [])
say("sound_error_names_the_block", len(e) == 1 and "'bundle' > 'PACK'" in e[0]
    and "sound<indicator>([bundle]HEARD, PACK)" in e[0])
w = []
V.check_surface("1A", {"type": ["charade"]}, "Flat pack", w)
V.check_surface("1A", {"type": ["double_definition"]}, "Seize part of a finger", w)
V.check_surface("1A", {"type": ["charade"], "explanation": {"surface": "A bad week."}},
                "Behaved antisocially and gave birth", w)
say("surface_optional_quiet", not w)


# The blog lookup, from annotate_check's notes.
def puzzle(series="cryptic", nulls=0, total=30, solutions=True):
    es = []
    for i in range(total):
        e = entry(f"{i + 1}-across", sol="ABCD" if solutions else "")
        if i >= nulls:
            e["annotation"] = stored()
        es.append(e)
    return {"id": f"{series}-99999", "number": 99999, "entries": es}


def blog_line(p):
    return [n for n in AC.notes(p) if n.startswith("Stuck on")]


say("blog_hidden_when_many_null", not blog_line(puzzle(nulls=12)))
say("blog_hidden_when_all_done", not blog_line(puzzle(nulls=0)))
last = blog_line(puzzle(nulls=3))
say("blog_shown_for_last_few", bool(last) and "fifteensquared Guardian 99999" in last[0])
say("blog_hidden_when_blind", not blog_line(puzzle(nulls=2, solutions=False)))
say("blog_hidden_without_a_blog", not blog_line(puzzle(series="metro", nulls=2)))
times = blog_line(puzzle(series="times", nulls=1))
say("times_names_its_own_blog", bool(times) and "timesforthetimes.co.uk" in times[0])

# A cryptic definition and a LIKELY letter get their advice; plain clues none.
p = puzzle()
say("plain_puzzle_no_notes", not AC.notes(p))
p["entries"][0]["annotation"] = {
    "definitions": [{"text": "Some words here", "at": 0}],
    "wordplay": {"op": "cryptic", "parts": [{"words": "Some", "at": 0, "note": "a"},
                                            {"words": "words here", "at": 5, "note": "b"}]}}
p["entries"][1]["solutionConfidence"] = "LIKELY"
ns = AC.notes(p)
say("cd_note", any("1-across typed `cryptic definition`" in n for n in ns))
say("likely_note", any(n.startswith("2-across have LIKELY") for n in ns))

# The run reads a copy without the blog URL; the apply still writes the real
# file, whose solutions detail survives it.
import json, tempfile
from pathlib import Path
import apply_annotations
import puzzle_integrity
from groups import entry_id
# Thirty unplaced lights are not a whole puzzle; the write gate has its own test, tools/test_puzzle_invariants.py.
puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None
blog = "https://fifteensquared.net/2025/08/02/cyclops-99998-x/"
real = puzzle(series="cyclops", nulls=30)
real.update(id="cyclops-99998", number=99998,
            source={"url": "https://www.private-eye.co.uk/crossword"},
            solutions={"origin": "writeup", "blog": "fifteensquared", "url": blog})
path = Path(tempfile.mkdtemp()) / "cyclops-99998.json"
path.write_text(json.dumps(real))
view = AC.write_view(path)
try:
    text = view.read_text()
    say("view_has_no_url", "http" not in text and "fifteensquared" not in text)
    say("view_keeps_solutions",
        all(" | ABCD | " in l for l in json.loads(text)["entries"]))
finally:
    view.unlink()
# A jigsaw's view says so: the run must know the answers go wherever they fit.
jig_path = path.parent / "cyclops-99997.json"
jig_path.write_text(json.dumps({**real, "id": "cyclops-99997", "cluesUnplaced": True}))
jig_view = AC.write_view(jig_path)
try:
    say("view_says_jigsaw", json.loads(jig_view.read_text()).get("cluesUnplaced") is True)
finally:
    jig_view.unlink()
charade = {"def": "Some", "wp": "[words]AB + [here]CD"}
apply_annotations.apply(path, {entry_id(e): dict(charade) for e in real["entries"]},
                        by="human")
say("apply_keeps_solutions_detail",
    json.loads(path.read_text()).get("solutions", {}).get("url") == blog)

# A partial _ann file applies as it stands: absent keys become null.
pending = path.parent / "_ann_cyclops-99998.json"
pending.write_text(json.dumps({"1-across": charade}))
filled = AC.fill_missing(path, pending)
ann = json.loads(pending.read_text())
say("missing_keys_filled_null", len(filled) == 29 and len(ann) == 30
    and ann["2-across"] is None and ann["1-across"] == charade)

# A refused write still says what the validator thinks, in the same turn.
ann["1-across"] = {"def": "Some", "wp": "[words here]ABCD", "notes": {"words here": "this is ABCD"}}
pending.write_text(json.dumps(ann))
errs, _ = AC.preview(path, pending)
say("preview_names_validator_errors", any("names the answer" in e for e in errs)
    and not any(e.startswith("schema:") for e in errs))

# A clue the write refuses is named by the refusal, not also called unwritten:
# that echo was 56 of 80 check_every_clue_is_annotated failures (audit 10-14).
# A clue really left null still is.
full = {k: dict(charade) for k in ann}
full["3-across"] = {"def": "Some", "wp": "[words]ZZZZ"}
full["4-across"] = None
pending.write_text(json.dumps(full))
fresh = json.loads(path.read_text())     # a fresh run: 3-across has nothing filed yet
for e in fresh["entries"]:
    if entry_id(e) == "3-across":
        e.pop("annotation", None)
path.write_text(json.dumps(fresh))
bad = []
say("bad_wordplay_is_refused", apply_annotations.landed(
    full["3-across"], next(e for e in real["entries"] if entry_id(e) == "3-across"),
    real["entries"], "3-across", bad) is None and bad)
errs, _ = AC.preview(path, pending)
blank = [e for e in errs if "no annotation. Every clue" in e]
say("preview_refused_clue_not_called_blank",
    len(blank) == 1 and blank[0].startswith("4A: ") and "3A" not in blank[0])
say("drop_refused_blanks_keeps_the_rest",
    AC.drop_refused_blanks("3A,4A,5D: no annotation. Every clue x. With 3 blank, y", {"3A"})
    == "4A,5D: no annotation. Every clue x. With 2 blank, y"
    and AC.drop_refused_blanks("3A: no annotation. Every clue x", {"3A"}) == ""
    and AC.drop_refused_blanks("3A: other check", {"3A"}) == "3A: other check")

# --patch consumes its file, so the run has nothing to rm afterwards.
fix = path.parent / "_patch.json"
anagram = {"def": "Some", "wp": "ana([words]DCBA)"}
fix.write_text(json.dumps({"2-across": anagram}))
say("patch_deletes_its_file", AC.patch(pending, fix) is None and not fix.exists()
    and json.loads(pending.read_text())["2-across"] == anagram)

# A patch nulling every field takes the clue back: it is null, not {} that
# apply counts as landed (timesquick-1703 17A, 10-23: "24/24 annotations"
# above "17A: no annotation").
fix.write_text(json.dumps({"2-across": {"def": None, "wp": None}}))
say("patch_nulling_every_field_is_null", AC.patch(pending, fix) is None
    and json.loads(pending.read_text())["2-across"] is None)

# An answer typed with the enumeration's comma is respelt with a space.
pending.write_text(json.dumps({"1-across": {"answer": "TITUS, ANDRONICUS"}, "2-across": None}))
say("comma_answer_spaced", AC.respell_answers(pending) == ["1-across"]
    and json.loads(pending.read_text())["1-across"]["answer"] == "TITUS ANDRONICUS")

# A block note naming its answer is rewritten without it when no judgement goes
# into that; one naming it mid-thought is left for the validator.
named = path.parent / "cyclops-99995.json"
named.write_text(json.dumps({"id": "cyclops-99995", "number": 99995, "entries": [
    entry("1-across", "Drain cover rasping (7)", "GRATING"),
    entry("2-across", "Archbishop's church (6)", "TEMPLE"),
    entry("3-across", "Rag every day (5)", "DAILY")]}))
pending.write_text(json.dumps({
    "1-across": {"def": "rasping", "wp": "[Drain cover]GRATING",
                 "notes": {"Drain cover": "a grating is a grid of metal bars over a drain"}},
    "2-across": {"def": "church", "wp": "[Archbishop's]TEMPLE",
                 "notes": {"Archbishop's": "William Temple was Archbishop of Canterbury"}},
    "3-across": {"def": "every day", "wp": "[Rag]DAILY",
                 "notes": {"Rag": "a rag is a newspaper, and one out every day is a daily"}}}))
unnamed = AC.unname_block_notes(named, pending)
notes_now = {k: next(iter(v["notes"].values())) for k, v in json.loads(pending.read_text()).items()}
say("answer_opener_trimmed", unnamed == ["1-across", "2-across", "3-across"]
    and notes_now["1-across"] == "a grid of metal bars over a drain")
# What no rule clears is blanked, so the model is not sent back for it.
say("unclearable_note_blanked", notes_now["2-across"] == "William ... was Archbishop of Canterbury"
    and notes_now["3-across"].startswith("a rag") and "daily" not in notes_now["3-across"].lower())
from find_answer_leaks import unname
say("unname_gives_the_answer", unname("noaHS ARk; read backwards gives RASH", "RASH")
    == "noaHS ARk; read backwards gives the answer")
say("unname_partial_block_drops_clause",
    unname("AN, the article, removed from UNCLEAN, gives UNCLE", "UNCLE", gives="UNCLEAN")
    == "AN, the article, removed from UNCLEAN"
    and unname("E = European; SH+E inside AN: A(SHE)N", "ASHEN", gives="ASHEN")
    == "E = European; SH+E inside AN")
say("unname_hidden_display", unname("fin(AL PHA)se", "ALPHA", clue="Top dog in final phase (5)")
    == "letters 4-8 of 'final phase'")
say("unname_leaves_mid_thought", unname("a dormant animal may be sleeping through winter", "DORMANT")
    is None and unname("an archer aims for the bull, so is a bull's hitter", "ARCHER") is None)

# A definition word reused as fodder warns, and says a setter's reuse is left as is,
# so a run does not go hunting for a field to mark it.
w = []
V.check_definition_not_fodder([entry("1-across", annotation={"type": ["charade"],
    "definitions": [{"text": "rock"}], "blocks": [{"clueFragment": "rock", "gives": "ROC"}]})], [], w)
say("fodder_reuse_says_leave_it", len(w) == 1 and "leave it" in w[0])

# A given entry prints its answer as its clue, so quoting the clue leaks nothing;
# a definition the annotator wrote that spells the answer still fails.
errs = []
V.check_no_answer_in_early_rungs("24A", {"answer": "MEAE", "definitions": [{"text": "MEAE"}]}, "MEAE", errs, [])
say("given_entry_definition_passes", errs == [])
V.check_no_answer_in_early_rungs("3D", {"answer": "ABCD", "definitions": [{"text": "ABCD"}]}, "Letters (4)", errs, [])
say("written_answer_still_fails", len(errs) == 1)

# A linked answer's lights are answers too: a note naming one light leaks it,
# though the whole answer is never said, unless a block prints that light as
# its letters on the same rung. A function word light leaks nothing.
errs = []
V.check_block_notes_dont_name_the_answer("1A", {"answer": "PRIME MINISTER", "blocks": [
    {"note": "to prime a gun is to make it ready", "gives": "PRIM"}]}, errs, [],
    ["PRIME", "MINISTER"])
say("light_answer_named_fails", len(errs) == 1 and "'PRIME'" in errs[0])
errs = []
V.check_block_notes_dont_name_the_answer("1A", {"answer": "PRIME MINISTER", "blocks": [
    {"note": "to prime a gun is to make it ready", "gives": "PRIME"}]}, errs, [],
    ["PRIME", "MINISTER"])
say("light_the_block_prints_passes", errs == [])

# A run of words that only looks like the answer is no leak: an article before
# a one-word answer, a last word lending one letter or the note's copula, and
# pieces the rung already prints.
for answer, gives, note in [("AJAR", ["A", "JAR"], "a jar is a glass container"),
                            ("LUNGI", ["LUNG", "I"], "lung is one of the organs sold as offal"),
                            ("TUNIS", ["TUNS", "I"], "a tun is a large cask"),
                            ("JUT", ["JUTE"], "the Jutes were a Germanic people"),
                            ("YONIS", ["YON", "IS"], "yon is an old word for that"),
                            ("AS IS", ["A", "SIS"], "a sis is a sister"),
                            ("GLOUCESTER", ["DOUBLEGLOUCESTER"], "Double Gloucester is a hard cheese")]:
    errs = []
    V.check_block_notes_dont_name_the_answer("1A", {"answer": answer, "blocks": [
        {"note": note, "gives": g} for g in gives]}, errs, [])
    say(f"lookalike_run_passes_{answer.replace(' ', '_')}", errs == [])
# Mirror: the same shapes still fail when they are the answer.
for answer, note in [("AFLOAT", "an AFLOAT boat"), ("PLEASE", "to please is to delight"),
                     ("TRUMP CARDS", "trump cards win tricks"), ("CANT", "can't is a contraction"),
                     ("ALPHA", "fin(AL PHA)se")]:
    errs = []
    V.check_block_notes_dont_name_the_answer("1A", {"answer": answer, "blocks": [
        {"note": note, "gives": "XYZ"}]}, errs, [])
    say(f"answer_run_fails_{answer.replace(' ', '_')}", len(errs) == 1)

# A double definition's sense is blanked where no rule can drop the answer.
from find_answer_leaks import unname as _un
say("dd_sense_blanked", _un("first meaning: Lambert Simnel, who claimed the throne in 1487",
                            "SIMNEL", None, "", (), blank=True)
    == "first meaning: Lambert ..., who claimed the throne in 1487")
say("blank_only_without_letters", _un("first meaning: Lambert Simnel, who claimed the throne",
                                      "SIMNEL", "SIMNEL", "") is None)
errs = []
V.check_block_notes_dont_name_the_answer("1A", {"answer": "THE LADY", "blocks": [
    {"note": "the rack stretched a prisoner", "gives": "THE"}]}, errs, [], ["THE", "LADY"])
say("function_word_light_passes", errs == [])
V.check_block_notes_dont_name_the_answer("1A", {"answer": "PRIME MINISTER", "blocks": [
    {"note": "a priest is a cleric"}]}, errs, [])
say("unlinked_still_whole_answer_only", errs == [])
linked = path.parent / "cyclops-99997.json"
linked.write_text(json.dumps({"entries": [
    {"number": 1, "direction": "across", "solution": "PRIME", "group": ["1-across", "2-down"],
     "clue": {"text": "Prepare English cleric for high office (5,8)"}},
    {"number": 2, "direction": "down", "solution": "MINISTER", "clue": {"text": "See 1"}}]}))
pending.write_text(json.dumps({"1-across": {
    "def": "high office", "wp": "[Prepare]PRIM + [English]E + [cleric]MINISTER",
    "notes": {"Prepare": "to prime is to prepare"}}}))
say("light_name_unnamed", AC.unname_block_notes(linked, pending) == ["1-across"]
    and json.loads(pending.read_text())["1-across"]["notes"]["Prepare"] == "to prepare")
# Real refusals that outlived the mend (annotate audit 10-24/25). A rebus's block
# note leads with its reading ("XC; ..."), so the run's note is found inside it;
# and rewriting for one light (TELL) can leave another (WILL), so go round again.
rebus = path.parent / "cyclops-99994.json"
rebus.write_text(json.dumps({"id": "cyclops-99994", "number": 99994, "entries": [
    entry("1-across", "Number somewhat excessive (6)", "NINETY"),
    entry("2-across", "Schedule archer at the end (4,4,4)", "TIMEWILLTELL")]}))
pending.write_text(json.dumps({"1-across": {
    "def": "Number", "wp": 'rebus([Somewhat excessive], "XC")',
    "notes": {"Somewhat excessive": "part of the word excessive is XC, the Roman numeral for ninety"}}}))
say("rebus_note_found_inside_block_note", AC.unname_block_notes(rebus, pending) == ["1-across"]
    and json.loads(pending.read_text())["1-across"]["notes"]["Somewhat excessive"]
    == "part of the word excessive is XC")
# The derived abbreviation gloss names an answer that is itself a word of it.
import annotation as ANN
gl = [b["note"] for b in ANN.unname_derived_block_text(
    [{"clueFragment": "road", "gives": "RD", "note": "RD is a standard abbreviation for road"},
     {"clueFragment": "x", "gives": "X", "note": "X is a standard abbreviation for x"}],
    {"words": "road", "gives": "RD"}, "STANDARD")]
say("uncovered_clue_words_listed", V.clue_words_no_block_covers(
    {"definitions": [{"text": "hat"}], "indicators": [{"text": "over"}], "blocks": [{"clueFragment": "Tea"}]},
    "Tea over hat or bit") == ["or", "bit"])
say("abbreviation_gloss_unnamed",gl[0] == "RD stands for road" and gl[1] == "X is a standard abbreviation for x")

# Each validator line names its check, and --explain takes what a run guesses.
import contextlib, io
errs = []
V.check_block_notes_dont_name_the_answer("3D", {"answer": "ABCD", "blocks": [{"note": "gives ABCD"}]}, errs, [])
named = AC.name_checks(V.ERROR_PREFIX + errs[0])
say("line_names_its_check", named.endswith("[check_block_notes_dont_name_the_answer]"))
def explained(name):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = V.explain(name)
    return rc, buf.getvalue()
say("explain_takes_a_field", explained("definitionFit")[1].count("def check_definition_fit(") == 1)
say("explain_takes_dashed_words", "def check_cryptic_definition_cap(" in explained("cryptic-definition-cap")[1])
say("explain_unknown_refused", explained("zzqx")[0] == 1)
say("explain_takes_a_ratchet_field", "CDEF_REPEAT =" in explained("wordplay.cdefRepeat")[1])
say("explain_takes_a_message_phrase", explained("check_assembly_machine_checkable")[0] == 0
    and "machine-checkable assembly" in explained("check_assembly_machine_checkable")[1])'''

WORKED = r'''import build_annotate_prompt as B, validate_annotations as V
from fetch_puzzle import read_puzzle_file, resolve_puzzle
bad = 0
for pid, eid in B.EXAMPLES:
    p = read_puzzle_file(resolve_puzzle(pid))
    _, errs, warns = V.validate_puzzle(p)
    num, _, d = eid.partition("-")
    bad += sum(x.startswith(f"{num}{d[0].upper()}:") for x in errs + warns)
print(bad)'''

env = {**os.environ, "PYTHONPATH": "tools"}
out = subprocess.run([sys.executable, "-"], input=PROG, text=True, stdout=subprocess.PIPE,
                     env=env).stdout.rstrip("\n")
for ln in out.split("\n"):
    print("  " + ln)

KEYS = """linked_leader_quiet
annotated_continuation_flagged
bare_continuation_not_flagged
grouped_continuation_flagged
hint_names_clue_spelling
hint_without_lookalike_says_copy
features_absent_warns
surface_absent_warns
surface_counted_by_ratchet
surface_optional_quiet
features_counted_by_ratchet
features_present_quiet
blog_hidden_when_many_null
blog_hidden_when_all_done
blog_shown_for_last_few
blog_hidden_when_blind
blog_hidden_without_a_blog
times_names_its_own_blog
plain_puzzle_no_notes
cd_note
likely_note
view_has_no_url
view_says_jigsaw
view_keeps_solutions
apply_keeps_solutions_detail
fragment_not_in_clue_fails
hole_fails_the_run
hole_queued_in_corpus
wrong_tree_not_called_blank
blanks_one_line
one_blank_not_called_half_written
reworded_clue_fails
retyped_clue_passes
missing_keys_filled_null
ocr_rewording_filed_fails
ocr_misread_filed_passes
preview_names_validator_errors
bad_wordplay_is_refused
preview_refused_clue_not_called_blank
drop_refused_blanks_keeps_the_rest
patch_deletes_its_file
patch_nulling_every_field_is_null
light_answer_named_fails
function_word_light_passes
unlinked_still_whole_answer_only
light_name_unnamed
line_names_its_check
explain_takes_a_field
explain_takes_dashed_words
explain_takes_a_ratchet_field
explain_takes_a_message_phrase
explain_unknown_refused
comma_answer_spaced
answer_opener_trimmed
unname_gives_the_answer
unname_partial_block_drops_clause
unname_hidden_display
unname_leaves_mid_thought
fodder_reuse_says_leave_it""".split()
lines_out = out.split("\n")
for k in KEYS:
    same(k, str(lines_out.count(k + "=yes")), "1")

print("the prompt no longer names the blog, and the run's inputs no longer carry it")
same("the run reads the copy", str(sum(1 for ln in Path("tools/prereset_backfill.sh").read_text().split("\n") if ln.startswith("ANNOTATE_PROMPT=") and re.search(r"tools/_puzzle_@\.json", ln))), "1")
same("the nightly reads the copy",
     count(r"ann_file=\$\(python3 tools/annotate_check.py --view", "tools/daily_update.sh"), "1")
same("the worker hands the prompt over in the system prompt",
     count(r"--append-system-prompt-file tools/annotate_prompt.md", "tools/puzzle_worker.sh"), "1")
same("the prompt's worked annotations pass every check",
     subprocess.run([sys.executable, "-c", WORKED], text=True, stdout=subprocess.PIPE,
                    env=env).stdout.rstrip("\n"), "0")
same("no blog in the prompt",
     count(r"fifteensquared|timesforthetimes", "tools/annotate_prompt.md", re.I), "0")

if fails > 0:
    print(f"FAILED: {fails}")
    sys.exit(1)
print("all passed")
