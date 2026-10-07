#!/bin/bash
# Does the annotate audit name the right check, and pick one fix target a day?
#
#     bash tools/test_annotate_audit.sh
#
# Every run with enough sessions must name exactly one finding to fix, rotating
# down the ranking past ones woken within the cooldown unless they have grown,
# and a line must be named by the check that wrote it rather than by its wording.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
python3 - <<'EOF'
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
check(len(a.load_templates(a.VALIDATOR.read_text())) > 50, True,
      "the real validator yields its message templates")
check(a.stopped_names("SCHEMA $.entries[2].annotation: missing required key 'blocks'; "
                      "SCHEMA $.entries[9].annotation: missing required key 'blocks'"),
      {"apply refused: schema annotation: missing required key 'blocks'"},
      "schema refusals collapse across entries")
check(a.stopped_names("apply_annotations: x.json: refused to write, fix these in the _ann file:\n"
                      "  7-down explanation: missing required key 'walkthrough'\n"
                      "  11-across explanation: missing required key 'walkthrough'\n"
                      "  3-down: missing required key 'blocks' — write `blocks` as shown\n\n"
                      "annotate_check x: STOPPED — the annotations were not applied"),
      {"apply refused: schema explanation: missing required key 'walkthrough'",
       "apply refused: schema missing required key 'blocks'"},
      "apply_annotations refusals are named by finding, entry id dropped")
check(a.tool_error_kind("Bash", "python3 tools/annotate_check.py x", "Exit code 1\nFAIL"), None,
      "annotate_check reporting errors is not a wasted call")
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
cur = dict(n=40, cost=1.30, turns=10); prev = dict(n=40, cost=1.00, turns=10)
check([i["key"] for i in a.trend_items(cur, prev)], ["trend:cost"], "a cost regression is a finding")
check(a.trend_items(dict(cur, n=5), prev), [], "not on too few sessions")
sys.exit(1 if fails else 0)
EOF
