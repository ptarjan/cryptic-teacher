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
    e = {"id": eid, "number": int(num), "direction": d, "clue": clue,
         "solution": sol, **kw}
    if group:
        e["group"] = group
    return e


def say(name, ok):
    print(f"{name}={'yes' if ok else 'no'}")


# Linked groups: the lead covers the group, every other leg only points at it.
lead_ann = {"type": "charade", "answer": "ABCDEFGH", "definition": "Some",
            "walkthrough": "w", "blocks": [{"clueFragment": "words", "gives": "X"}],
            "coversGroup": True}
g = ["1-across", "2-down"]
good = {"id": "t-1", "entries": [
    entry("1-across", group=g, annotation=lead_ann),
    entry("2-down", sol="EFGH", group=g, annotation={"linkedTo": "1-across"})]}
errs = []
V.check_linked_entries(good, errs)
say("linked_good_quiet", not errs)

bad_lead = copy.deepcopy(good)
del bad_lead["entries"][0]["annotation"]["coversGroup"]
errs = []
V.check_linked_entries(bad_lead, errs)
say("linked_lead_flagged", any("coversGroup" in e for e in errs))

bad_leg = copy.deepcopy(good)
bad_leg["entries"][1]["annotation"] = dict(lead_ann)
errs = []
V.check_linked_entries(bad_leg, errs)
say("linked_leg_flagged", any('{"linkedTo": "1-across"}' in e for e in errs))

null_leg = copy.deepcopy(good)
del null_leg["entries"][1]["annotation"]
errs, warns = [], []
V.check_every_clue_is_annotated(null_leg["entries"], errs, warns)
say("null_leg_names_linkedTo", any('{"linkedTo": "1-across"}' in e for e in errs))

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
hole = [entry("1-across", annotation={"type": "charade"}), entry("2-across")]
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns)
say("hole_fails_the_run", bool(errs))
errs, warns = [], []
V.check_every_clue_is_annotated(hole, errs, warns, corpus=True)
say("hole_queued_in_corpus", not errs and any("queued" in w for w in warns))

# The clue is the source's: an annotated clue whose words differ from the
# committed file's fails; one retyped with other punctuation does not.
from pathlib import Path
import fetch_puzzle
committed = Path("puzzles/sundaytimes-5067.json")
held = fetch_puzzle.read_puzzle_file(committed)
lead = next(e for e in held["entries"] if e.get("annotation"))
reworded, retyped = copy.deepcopy(held), copy.deepcopy(held)
next(e for e in reworded["entries"] if e["id"] == lead["id"])["clue"] = "Invented " + lead["clue"]
next(e for e in retyped["entries"] if e["id"] == lead["id"])["clue"] = lead["clue"].replace(" ", "  ") + "!"
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


# The blog lookup, from annotate_check's notes.
def puzzle(series="cryptic", nulls=0, total=30, solutions=True):
    es = []
    for i in range(total):
        e = entry(f"{i + 1}-across", sol="ABCD" if solutions else "")
        if i >= nulls:
            e["annotation"] = {"type": "charade"}
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
p["entries"][0]["annotation"] = {"type": "cryptic definition"}
p["entries"][1]["solutionConfidence"] = "LIKELY"
ns = AC.notes(p)
say("cd_note", any("1-across typed `cryptic definition`" in n for n in ns))
say("likely_note", any(n.startswith("2-across have LIKELY") for n in ns))

# The run reads a copy without the blog URL; the apply still writes the real
# file, whose solutionSource survives it.
import json, tempfile
from pathlib import Path
import apply_annotations
blog = "https://fifteensquared.net/2025/08/02/cyclops-99998-x/"
real = puzzle(series="cyclops", nulls=30)
real.update(id="cyclops-99998", name="Private Eye Cyclops crossword No 99998",
            sourceUrl="https://www.private-eye.co.uk/crossword",
            provenance={"retrievedUrl": blog},
            solutionSource={"kind": "fifteensquared", "url": blog})
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
apply_annotations.apply(path, {e["id"]: {"type": "charade"} for e in real["entries"]},
                        by="human")
say("apply_keeps_solutionSource",
    json.loads(path.read_text()).get("solutionSource", {}).get("url") == blog)
PY
)
echo "$out" | sed 's/^/  /'

for k in linked_good_quiet linked_lead_flagged linked_leg_flagged \
         null_leg_names_linkedTo hint_names_clue_spelling \
         hint_without_lookalike_says_copy features_absent_warns \
         features_counted_by_ratchet features_present_quiet \
         blog_hidden_when_many_null blog_hidden_when_all_done \
         blog_shown_for_last_few blog_hidden_when_blind \
         blog_hidden_without_a_blog times_names_its_own_blog \
         plain_puzzle_no_notes cd_note likely_note view_has_no_url \
         view_keeps_solutions apply_keeps_solutionSource \
         fragment_not_in_clue_fails hole_fails_the_run hole_queued_in_corpus \
         reworded_clue_fails retyped_clue_passes; do
  same "$k" "$(grep -c "^$k=yes$" <<<"$out")" "1"
done

echo "the prompt no longer names the blog, and the run's inputs no longer carry it"
same "the run reads the copy" "$(grep -c 'tools/_puzzle_@\.json' tools/prereset_backfill.sh)" "1"
same "the nightly reads the copy" "$(grep -c 'ann_file=\$(python3 tools/annotate_check.py --view' tools/daily_update.sh)" "1"
same "no blog in the prompt" "$(grep -ci 'fifteensquared\|timesforthetimes' tools/annotate_prompt.md)" "0"

if [ "$fails" -gt 0 ]; then echo "FAILED: $fails"; exit 1; fi
echo "all passed"
