#!/bin/bash
# Do the annotation rules arrive where they are broken?
#
#     bash tools/test_annotate_disclosure.sh
#
# tools/annotate_prompt.md keeps only what no check can see. Every other rule
# lives in the message of the check that catches it, and a few pieces of advice
# are printed by tools/annotate_check.py only in the state that makes them
# matter. That trade only holds if the checks fire on the broken shape and stay
# quiet on the right one, so each is tested from both sides here. The blog
# lookup most of all: it must appear once only the last few clues are null, and
# never earlier, never on a blind run and never for a series nobody blogs.
set -uo pipefail
cd "$(dirname "$0")/.."
fails=0
same() { if [ "$2" = "$3" ]; then echo "  ok: $1"; else
  echo "  FAIL: $1"$'\n'"    want $3"$'\n'"    got  $2"; fails=$((fails + 1)); fi; }

out=$(PYTHONPATH=tools python3 - <<'PY'
import copy
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
lead_ann = {"type": ["charade"], "answer": "ABCDEFGH", "definitions": [{"text": "Some", "at": 0}],
            "explanation": {"walkthrough": "w"}, "blocks": [{"clueFragment": "words", "gives": "X"}]}
g = ["1-across", "2-down"]
good = {"id": "t-1", "entries": [
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
    any(e.startswith("2-down:") and "does not start with this entry" in e for e in errs))

# A fragment retyped with straight quotes where the clue has curly ones.
clue = "Setter’s back (4)"
say("hint_names_clue_spelling",
    "'Setter’s'" in V.verbatim_hint("Setter's", clue))
say("hint_without_lookalike_says_copy",
    "character for character" in V.verbatim_hint("Nowhere", clue))

# A block quotes the clue it explains: a fragment the clue lacks fails.
frag = copy.deepcopy(good)
frag["entries"][0]["annotation"] = dict(lead_ann, blocks=[{"clueFragment": "sis trumpeted"}])
say("fragment_not_in_clue_fails",
    any("block fragment 'sis trumpeted' not found" in e for e in V.validate_puzzle(frag)[1]))

# A hole is the annotating run's failure; in the committed corpus it is a
# clue queued to be annotated again, not a broken build.
hole = [entry("1-across", annotation={"type": ["charade"]}), entry("2-across")]
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns)
say("hole_fails_the_run", bool(errs))
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns, corpus=True)
say("hole_queued_in_corpus", not errs and any("queued" in w for w in warns))

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
say("reworded_clue_fails", len(errs) == 1 and "drop this entry's annotation" in errs[0])
errs = []
V.check_clue_unchanged(retyped, committed, errs)
say("retyped_clue_passes", not errs)

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
            e["annotation"] = {"type": ["charade"]}
        es.append(e)
    return {"id": f"{series}-99999", "series": series, "number": 99999,
            "entries": es}


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
p["entries"][0]["annotation"] = {"type": ["cryptic_definition"]}
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
# Thirty unplaced lights are not a whole puzzle; the write gate has its own test, tools/test_puzzle_invariants.sh.
puzzle_integrity.refuse_bad_write = lambda puzzle, old=None: None
blog = "https://fifteensquared.net/2025/08/02/cyclops-99998-x/"
real = puzzle(series="cyclops", nulls=30)
real.update(id="cyclops-99998", name="Private Eye Cyclops crossword No 99998",
            source={"url": "https://www.private-eye.co.uk/crossword"},
            solutions={"origin": "writeup", "blog": "fifteensquared", "url": blog})
path = Path(tempfile.mkdtemp()) / "cyclops-99998.json"
path.write_text(json.dumps(real))
view = AC.write_view(path)
try:
    text = view.read_text()
    say("view_has_no_url", "http" not in text and "fifteensquared" not in text)
    say("view_keeps_solutions",
        [e["solution"] for e in json.loads(text)["entries"]] == ["ABCD"] * 30)
finally:
    view.unlink()
apply_annotations.apply(path, {entry_id(e): {"type": ["charade"]} for e in real["entries"]},
                        by="human")
say("apply_keeps_solutions_detail",
    json.loads(path.read_text()).get("solutions", {}).get("url") == blog)

# A partial _ann file applies as it stands: absent keys become null.
pending = path.parent / "_ann_cyclops-99998.json"
pending.write_text(json.dumps({"1-across": {"type": ["charade"]}}))
filled = AC.fill_missing(path, pending)
ann = json.loads(pending.read_text())
say("missing_keys_filled_null", len(filled) == 29 and len(ann) == 30
    and ann["2-across"] is None and ann["1-across"] == {"type": ["charade"]})

# A refused write still says what the validator thinks, in the same turn.
ann["1-across"] = {"type": ["charade"], "answer": "ABCD",
                   "blocks": [{"clueFragment": "Some", "gives": "ABCD", "note": "this is ABCD"}]}
pending.write_text(json.dumps(ann))
errs, _ = AC.preview(path, pending)
say("preview_names_validator_errors", any("names the answer" in e for e in errs)
    and not any(e.startswith("schema:") for e in errs))

# --patch consumes its file, so the run has nothing to rm afterwards.
fix = path.parent / "_patch.json"
fix.write_text(json.dumps({"2-across": {"type": ["anagram"]}}))
say("patch_deletes_its_file", AC.patch(pending, fix) is None and not fix.exists()
    and json.loads(pending.read_text())["2-across"] == {"type": ["anagram"]})

# An answer typed with the enumeration's comma is respelt with a space.
pending.write_text(json.dumps({"1-across": {"answer": "TITUS, ANDRONICUS"}, "2-across": None}))
say("comma_answer_spaced", AC.respell_answers(pending) == ["1-across"]
    and json.loads(pending.read_text())["1-across"]["answer"] == "TITUS ANDRONICUS")

# A block note naming its answer is rewritten without it when no judgement goes
# into that; one naming it mid-thought is left for the validator.
pending.write_text(json.dumps({
    "1-across": {"answer": "GRATING", "blocks": [{"note": "a grating is a grid of metal bars over a drain"}]},
    "2-across": {"answer": "TEMPLE", "blocks": [{"note": "William Temple was Archbishop of Canterbury"}]},
    "3-across": {"answer": "DAILY", "blocks": [{"note": "a rag is a newspaper, and one out every day is a daily"}]}}))
unnamed = AC.unname_block_notes(path, pending)
notes_now = {k: v["blocks"][0]["note"] for k, v in json.loads(pending.read_text()).items()}
say("answer_opener_trimmed", unnamed == ["1-across"]
    and notes_now["1-across"] == "a grid of metal bars over a drain"
    and notes_now["2-across"].startswith("William") and notes_now["3-across"].startswith("a rag"))
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
PY
)
echo "$out" | sed 's/^/  /'

for k in linked_leader_quiet annotated_continuation_flagged \
         bare_continuation_not_flagged grouped_continuation_flagged \
         hint_names_clue_spelling \
         hint_without_lookalike_says_copy features_absent_warns \
         surface_absent_warns surface_counted_by_ratchet surface_optional_quiet \
         features_counted_by_ratchet features_present_quiet \
         blog_hidden_when_many_null blog_hidden_when_all_done \
         blog_shown_for_last_few blog_hidden_when_blind \
         blog_hidden_without_a_blog times_names_its_own_blog \
         plain_puzzle_no_notes cd_note likely_note view_has_no_url \
         view_keeps_solutions apply_keeps_solutions_detail \
         fragment_not_in_clue_fails hole_fails_the_run hole_queued_in_corpus \
         reworded_clue_fails retyped_clue_passes missing_keys_filled_null \
         preview_names_validator_errors patch_deletes_its_file \
         line_names_its_check explain_takes_a_field explain_takes_dashed_words \
         explain_unknown_refused comma_answer_spaced answer_opener_trimmed \
         unname_gives_the_answer unname_partial_block_drops_clause \
         unname_hidden_display unname_leaves_mid_thought \
         fodder_reuse_says_leave_it; do
  same "$k" "$(grep -c "^$k=yes$" <<<"$out")" "1"
done

echo "the prompt no longer names the blog, and the run's inputs no longer carry it"
same "the run reads the copy" "$(grep -c 'tools/_puzzle_@\.json' tools/prereset_backfill.sh)" "1"
same "the nightly reads the copy" "$(grep -c 'ann_file=\$(python3 tools/annotate_check.py --view' tools/daily_update.sh)" "1"
same "the burn hands the prompt over in the system prompt" "$(grep -c -- '--append-system-prompt-file tools/annotate_prompt.md' tools/prereset_backfill.sh)" "1"
same "the prompt's worked annotations pass every check" "$(PYTHONPATH=tools python3 -c '
import build_annotate_prompt as B, validate_annotations as V
from fetch_puzzle import read_puzzle_file, resolve_puzzle
bad = 0
for pid, eid in B.EXAMPLES:
    p = read_puzzle_file(resolve_puzzle(pid))
    _, errs, warns = V.validate_puzzle(p)
    num, _, d = eid.partition("-")
    bad += sum(x.startswith(f"{num}{d[0].upper()}:") for x in errs + warns)
print(bad)')" "0"
same "no blog in the prompt" "$(grep -ci 'fifteensquared\|timesforthetimes' tools/annotate_prompt.md)" "0"

if [ "$fails" -gt 0 ]; then echo "FAILED: $fails"; exit 1; fi
echo "all passed"
