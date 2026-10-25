#!/usr/bin/env python3
# Does the annotate audit name the right check, and pick one fix target a day?
#
#     python3 tools/test_annotate_audit.py
#
# Every run with enough sessions must name exactly one finding to fix, rotating
# down the ranking past ones woken within the cooldown unless they have grown,
# and a line must be named by the check that wrote it rather than by its wording.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
sys.path.insert(0, "tools")
import annotate_audit as a

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

src = '''
def check_thin(tag, ann, errors):
    errors.append(f"{tag}: definitionFit {ann!r} is too thin. {HOW}")
def validate_puzzle(p):
    errors.append(f"{tag}: missing annotation field '{key}'")
'''
t = a.load_templates(src)
check(a.rule_name("  ERROR: 3D: definitionFit 'x' is too thin. Say why", t), "check_thin",
      "an ERROR line is named by the check function that wrote it")
check(a.rule_name("  ERROR: 1A: missing annotation field 'blocks'", t),
      "validate_puzzle: missing annotation field '", "a message outside a check_ is named by its words")
old = a.load_templates('''
def check_indicator_notes_name_no_block(tag, ann, errors):
    errors.append(f"{tag}: note on indicator {t!r} names the blocks by {w} — {n!r}. The rung")
''')
new = a.load_templates('''
def check_indicator_notes_name_no_block(tag, ann, errors):
    errors.append(f"{tag}: note on indicator {t!r} gives away the letters {w} — {n!r}. The rung")
''')
line = "  ERROR: 10A: note on indicator 'fans' names the blocks by new — 'spread'. The rung"
old = a.retire(old, new)
check(a.rule_name(line, new, old), a.SUPERSEDED + "check_indicator_notes_name_no_block",
      "a line only a retired message matches is named superseded")
row = {"first_rules": a.collections.Counter({a.rule_name(line, new, old): 1}),
       "first_fail": True, "tool_errors": a.collections.Counter(), "memory": False,
       "validator_reads": 0, "max_tokens": 0, "cache_1h": False}
check([f["key"] for f in a.findings([row])], [], "and is kept out of the ranking")
check(a.rule_name("  ERROR: 4D: note on indicator 'x' gives away the letters T — 'y'. The rung",
                  new, old), "check_indicator_notes_name_no_block",
      "the current message wins over a retired one")
t = a.load_templates(src + '''
def validate_more(p):
    errors.extend(f"{tag}: {p}" for p in problems)
def check_blocks_add_up(entries, errors):
    errors.append(f"puzzle: {len(hits)} clue(s) ({', '.join(hits)}) have blocks whose letters "
                  f"are not the answer's")
''')
check(a.rule_name("  ERROR: 3D: hiddenLetter 'E' is not in the blocks", t), "hiddenLetter '…' is not in the blocks",
      "a pass-through message is no template")
check(a.rule_name("  ERROR: puzzle: 1 clue(s) (1D) have blocks whose letters are not the answer's", t),
      "check_blocks_add_up", "a puzzle-level message is named by its check, whichever clues it lists")
check(len(a.load_templates(a.VALIDATOR.read_text())) > 50, True,
      "the real validator yields its message templates")
check(a.stopped_names("SCHEMA $.entries[2].annotation: missing required key 'blocks'; "
                      "SCHEMA $.entries[9].annotation: missing required key 'blocks'"),
      {"apply refused: schema annotation: missing required key 'blocks'"},
      "schema refusals collapse across entries")
check(any(n.startswith("STOPPED") for n in a.stopped_names(
    "apply_annotations: x.json: refused to write, fix these in the _ann file:\n"
    "  QUOTE 9-across: indicator 'put ... in' is not in the clue 'Monarch put ten in pot'\n\n"
    "annotate_check x: STOPPED — the annotations were not applied")), False,
      "a tagged refusal line is classed, not left as the generic STOPPED")
check(a.stopped_names("apply_annotations: x.json: refused to write, fix these in the _ann file:\n"
                      "  7-down explanation: missing required key 'walkthrough'\n"
                      "  11-across explanation: missing required key 'walkthrough'\n"
                      "  3-down: missing required key 'blocks' — write `blocks` as shown\n\n"
                      "annotate_check x: STOPPED — the annotations were not applied"),
      {"apply refused: schema explanation: missing required key 'walkthrough'",
       "apply refused: schema missing required key 'blocks'"},
      "apply_annotations refusals are named by finding, entry id dropped")
check({n for s in ("genius/2026/genius-1.json", "azed/2025/azed-9.json") for n in a.stopped_names(
    f"annotate_check x: STOPPED — the annotations were not applied, so puzzles/{s} is unchanged.")},
      {"STOPPED: the annotations were not applied, so <puzzle> is unchanged."},
      "a STOPPED line is one class whatever series path it names")
check(a.tool_error_kind("Bash", "python3 tools/annotate_check.py x", "Exit code 1\nFAIL"), None,
      "annotate_check reporting errors is not a wasted call")
check(a.tool_error_kind("Bash", "python3 tools/annotate_bag.py check tools/_ann_bag_x.json", "Exit code 1\nFAIL"),
      None, "nor is the bag check reporting errors")
check(a.tool_error_kind("Bash", "cat <<X", "Contains brace with quote character"),
      a.REFUSED["brace with quote"], "a refused heredoc is classified")

probe = ('{\n "id": "toughie-3670"\n}\n'
         "ls: cannot access 'tools/_ann_toughie-3670.json': No such file or directory")
check(a.tool_error_kind("Bash", "cat tools/_puzzle_toughie-3670.json; ls tools/_ann_toughie-3670.json",
                        "Exit code 2\n" + probe), None,
      "the opening read with an ls of the not-yet-written _ann file wastes nothing")
check(a.tool_error_kind("Bash", "cat a.json; ls b.json", "Exit code 2\nls: b.json: Permission denied"),
      "Bash `ls` exited non-zero", "an ls that fails for another reason is still a failure, named ls")
check(a.tool_error_kind("Bash", "cat STYLE.md | head -80; python3 -c \"import json; x=1\"",
                        "Exit code 1\nTraceback"),
      "Bash `python3 -c` exited non-zero", "a chain is named by its last command, not split inside quotes")
check(a.failed_command("python3 - <<'EOF'\nimport a; b\nEOF"), "python3 -",
      "a heredoc body splits nothing")
check(a.tool_error_kind("Bash", "cat nope.json", "Exit code 1\ncat: nope.json: No such file"),
      "Bash `cat` exited non-zero", "a cat that really failed still counts")
check(a.tool_error_kind("Bash", "python3 tools/apply_solution.py x-1 --fill f --check-only",
                        "Exit code 1\nREJECTED"), None, "a rejecting --check-only is the check working")
check(a.tool_error_kind("Bash", "python3 tools/apply_solution.py x-1 --fill f --no-reindex",
                        "Exit code 1\nTraceback"),
      "Bash `python3` exited non-zero", "a crashing real apply still counts")

now = a.datetime.datetime(2026, 10, 7, tzinfo=a.datetime.timezone.utc)
def f(key, sh):
    return {"key": key, "share": sh, "title": key, "detail": ""}
def told(days_ago, **vals):
    stamp = (now - a.datetime.timedelta(days=days_ago)).isoformat()
    return {"items": {k: {"value": v, "woken": stamp, "seen": stamp} for k, v in vals.items()}}
def target(ranked, state, trends=()):
    got = a.pick(ranked, list(trends), state, now)
    return got and got[0]["key"]
ranked = [f("rule:x", 0.07), f("rule:y", 0.06), f("rule:z", 0.05)]
check(target(ranked, {}), "rule:x", "an untold top finding is the target")
check(target(ranked, told(30, **{"rule:x": 0.07, "rule:y": 0.06})), "rule:x",
      "a stable ranking still wakes: past the cooldown the top finding is retried")
check(target(ranked, told(1, **{"rule:x": 0.07})), "rule:y",
      "inside the cooldown the target rotates to #2")
check(target(ranked, told(1, **{"rule:x": 0.07, "rule:y": 0.06})), "rule:z", "and on to #3")
check(target(ranked, told(1, **{"rule:x": 0.40, "rule:z": 0.05})), "rule:y",
      "a finding below its woken level does not jump the cooldown")
check(target([f("rule:x", 0.55)] + ranked[1:], told(1, **{"rule:x": 0.40})), "rule:x",
      "a clearly worse one jumps the cooldown")
check(target([f("rule:x", 0.02)], {}), None, "nothing above the floor stays quiet")
check(target(ranked, told(1, **{"rule:x": 0.1, "rule:y": 0.1, "rule:z": 0.1})), None,
      "every qualifying finding in its cooldown stays quiet")
trend = {"key": "trend:cost", "share": 1.0, "value": 1.3, "title": "t", "detail": ""}
check(target(ranked, {}, [trend]), "trend:cost", "a new regression comes first")
state = {}
a.mark_woken(ranked[0], "never targeted", state, now)
check((state["items"]["rule:x"]["value"], [x["key"] for x in state["attempts"]]),
      (0.07, ["rule:x"]), "a wake stamps its item and logs the attempt")
check("land a fix" in a.wake_text(ranked[0], "never targeted", dict(n=40, turns=5, cost=0.5,
                                                                      first_fail=0.5)),
      True, "the wake tells the room to land a fix")
cur = dict(n=40, cost_per_clue=0.13, turns_per_clue=1.0, puzzles=40, clues=100)
prev = dict(n=40, cost_per_clue=0.10, turns_per_clue=1.0, puzzles=40, clues=100)
check([i["key"] for i in a.trend_items(cur, prev)], ["trend:cost_per_clue"],
      "a cost-per-clue regression is a finding")
check(a.trend_items(dict(cur, cost_per_clue=0.10), prev), [],
      "a dearer session median alone is not (a bag's redo puzzles have few clues)")
check(a.trend_items(dict(cur, n=5), prev), [], "not on too few sessions")
import turn_cost
check([turn_cost.is_annotate_session(x) for x in (
    "Annotate the crossword nation-1 in this repo",
    "Solve the cryptic crossword nation-1 cold first. It ends by handing you this task: Annotate the crossword nation-1",
    "Solve the cryptic crossword nation-1 cold first.")], [True, True, False],
      "a cold-solve run that hands over the annotate task is an annotate session")
# A bag session is many puzzles; cost is compared per puzzle and per clue, pooled.
bag = ("Annotate these crosswords in this one session: azed-1 times-2 ft-3. Read tools/_bag_azed-1.txt once. "
       "Do not commit.")
check(a.is_audited(bag), True, "a bag session is an audited annotate run")
check(a.is_audited("Fix the validator"), False, "other runs are not")
check(a.bag_ids(bag), ["azed-1", "times-2", "ft-3"], "a bag's ids are read from its first message")
check(a.bag_ids("Annotate the crossword azed-1 in this repo."), [], "a solo run lists no bag ids")
older = "Annotate these crosswords in this one session, one after another: a-1 b-2. Each puzzle holds"
check(a.bag_ids(older), ["a-1", "b-2"], "the older bag wording reads the same")
bagfile = ('{"azed-1": {\n"1-across": {"def": "x", "notes": {"1-across": "n"}},\n"2-down": {"def": "y"}},\n'
           '"times-2": {\n"1-across": {"def": "z"}}}')
check(a.clues_written({"tools/_ann_bag_azed-1.json": bagfile}), 3, "clues written count entries across a bag file")
out = ("azed-1: clean, index refreshed — done\n--- times-2\nERROR: 3D: x\nannotate_check times-2: 1 ERROR\n\n"
       "--- ft-3\nannotate_check ft-3: STOPPED — the annotations were not applied\n\n1 to fix")
check(sorted(pid for pid, _ in a.bag_reports(out)), ["azed-1", "ft-3", "times-2"],
      "a bag check output is split into one report per puzzle")
check(dict(a.bag_reports(out))["azed-1"], "", "a clean puzzle has an empty report")
check(a.single_check_id("python3 tools/annotate_check.py --by x azed-1"), "azed-1", "the puzzle a check command names")
check(a.stopped_names("apply_annotations: x.json: refused to write — fix these in the _ann file:\n"
                      "  27-across: is on the shape re-annotation list (del_single: x) and this tree is still "
                      "flagged: dropped_words: for were in the old wordplay\n"
                      "  3-down: wordplay 'a(b': expected ')' at column 5 (…'b')\n\nannotate_check x: STOPPED"),
      {"apply refused: redo gate: dropped_words", "apply refused: schema wordplay '…': expected '…' at column N (…'…')"},
      "the new-wording refusal (an em dash) is read, and redo-gate refusals are classed by their finding")
check(a.stopped_names("--- cryptic-29412\n"
                      "20-across: notes ['LOW'] name no span of the wordplay; key each note by its words "
                      "(spans with no note yet: ['KEY'])\n"
                      "  21-across: 'Four aliens' is not in the clue 'Four contrary aliens welcoming a "
                      "conversation': each word is in the clue but not side by side\n"
                      "  5-down GAMBIT names BIT, GAM, GAME\n\n"
                      "annotate_check x: STOPPED — the annotations were not applied"),
      {"apply refused: notes name no span", "apply refused: quote not in clue"},
      "a bag refusal without its stripped header is itemised, walkthrough lines are not")
solo = lambda cost, turns, clues, puzzles=1: {"cost": cost, "turns": turns, "clues": clues, "puzzles": puzzles}
rows = [solo(1.0, 10, 20), solo(2.0, 30, 10, puzzles=10)]
check(round(a.pooled(rows, "cost", "puzzles"), 4), round(3.0 / 11, 4), "cost per puzzle is pooled over puzzles")
check(round(a.pooled(rows, "cost", "clues"), 4), 0.1, "cost per clue is pooled over clues")
check(a.pooled([solo(1.0, 10, 0)], "cost", "clues"), None, "a session with no clues counted is left out")

sys.exit(1 if fails else 0)
