#!/bin/bash
# Does the annotate audit name the right check, and wake only on news?
#
#     bash tools/test_annotate_audit.sh
#
# The wake is the part that costs: a finding the room was already told about
# must not wake it again unless it has clearly grown, and a line must be
# named by the check that wrote it rather than by its wording.
set -uo pipefail
cd "$(dirname "$0")/.."
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

item = {"key": "rule:x", "share": 0.40, "title": "", "detail": ""}
check([w for _, w in a.decide([item], [], {})], ["new"], "an untold finding is news")
check(a.decide([dict(item, share=0.05)], [], {}), [], "a small one is not")
told = {"items": {"rule:x": {"value": 0.40, "woken": "2026-09-01T00:00:00", "seen": "x"}}}
check(a.decide([dict(item, share=0.45)], [], told), [], "an unchanged finding does not wake twice")
check(len(a.decide([dict(item, share=0.55)], [], told)), 1, "a clearly worse one does")
cur = dict(n=40, cost=1.30, turns=10); prev = dict(n=40, cost=1.00, turns=10)
check([i["key"] for i in a.trend_items(cur, prev)], ["trend:cost"], "a cost regression is a finding")
check(a.trend_items(dict(cur, n=5), prev), [], "not on too few sessions")
sys.exit(1 if fails else 0)
EOF
