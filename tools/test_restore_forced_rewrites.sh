#!/bin/bash
# Does restore_forced_rewrites recover the text a run wrote before a check flagged it?
#
#     bash tools/test_restore_forced_rewrites.sh
#
# A transcript that writes a definitionFit, fails annotate_check on it (exit 1,
# so the tool result is an error), patches it and passes must replay to the
# first text and the patched one; the field functions restore only a field the
# puzzle still holds as the session left it; and every RESTORE row names a
# check the validator has.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
python3 - "$tmp" <<'EOF'
import json, sys
sys.path.insert(0, "tools")
import restore_forced_rewrites as r
import validate_annotations as va

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

good, padded = "Oslo is the capital city of Norway.", "Oslo is the seat of government of Norway, so it is an example of a capital."
ann = {"7-down": {"answer": "OSLO", "explanation": {"definitionFit": good}}}
patch = {"7-down": {"explanation": {"definitionFit": padded}}}
def use(i, name, inp): return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}
def res(i, text, err=False): return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": text, "is_error": err}]}}
rows = [
    {"type": "user", "message": {"content": f"{r.ANNOTATE_PREFIX} cryptic-1 in this repo"}},
    use("a", "Write", {"file_path": "/w/tools/_ann_cryptic-1.json", "content": json.dumps(ann)}), res("a", "ok"),
    use("b", "Bash", {"command": "python3 tools/annotate_check.py cryptic-1"}),
    res("b", "Exit code 1\n  ERROR: 7D: definitionFit is thin [check_definition_fit]\n  ERROR: 1A: other [check_type]", err=True),
    use("c", "Write", {"file_path": "/w/tools/_p.json", "content": json.dumps(patch)}), res("c", "ok"),
    use("d", "Edit", {"file_path": "/w/tools/_ann_cryptic-1.json", "old_string": "not there", "new_string": "x"}),
    res("d", "String to replace not found", err=True),
    use("e", "Bash", {"command": "python3 tools/annotate_check.py cryptic-1 --patch tools/_p.json"}),
    res("e", "merged _p.json into _ann_cryptic-1.json and deleted it\n... OK"),
]
path = f"{sys.argv[1]}/s.jsonl"
open(path, "w").write("\n".join(json.dumps(x) for x in rows))
got = r.replay(path, "check_definition_fit")
check([(p, e, b["explanation"]["definitionFit"], f["explanation"]["definitionFit"]) for p, e, b, f, _ in got],
      [("cryptic-1", "7-down", good, padded)], "a failing check's flag is read and the patch replayed")
check(r.replay(path, "check_indicators"), [], "a check that flagged nothing finds nothing")

before, final = ann["7-down"], {"answer": "OSLO", "explanation": patch["7-down"]["explanation"]}
check(r.definition_fit(before, final, final, [])["explanation"]["definitionFit"], good,
      "the earlier definitionFit goes back over the forced one")
later = {"answer": "OSLO", "explanation": {"definitionFit": "edited since"}}
check(r.definition_fit(before, final, later, []), None, "a field changed since the session is left alone")

blk = lambda note: {"answer": "AMAZE", "blocks": [{"clueFragment": "puzzle", "gives": "MAZE", "note": note}]}
flag = ["block note 'a maze is a puzzle of paths' names the answer"]
out = r.block_notes(blk("a maze is a puzzle of paths"), blk("a labyrinth"), blk("a labyrinth"), flag)
check(out["blocks"][0]["note"], "a maze is a puzzle of paths", "the quoted block note goes back")
check(r.block_notes(blk("a maze is a puzzle of paths"), blk("a labyrinth"), blk("a labyrinth"), []), None,
      "a block note no flag quoted is left alone")

check(sorted(c for c in r.RESTORE if not callable(getattr(va, c, None))), [],
      "every RESTORE row names a check in validate_annotations")
sys.exit(1 if fails else 0)
EOF
