#!/usr/bin/env python3
# The mend for a pure cryptic definition's blocks: `gives` dropped, bare "= ANSWER" notes stripped,
# everything subtler left for check_cryptic_definition_blocks.
#
#     python3 tests/test_mend_cryptic_definition.py
import _path  # puts tools/ on sys.path
import mend_cryptic_definition as M

fails = 0


def check(name, ok):
    global fails
    print(("  ok: " if ok else "  FAIL: ") + name)
    fails += not ok


def ann(blocks, typ=("cryptic_definition",), answer="WATCHSTRAP"):
    return {"type": list(typ), "answer": answer, "blocks": blocks}


a = ann([{"clueFragment": "Might this keep you to time?", "gives": "WATCHSTRAP", "note": "a strap keeps a watch on"}])
check("gives dropped, note kept", M.mend(a, "WATCHSTRAP") and a["blocks"] == [
    {"clueFragment": "Might this keep you to time?", "note": "a strap keeps a watch on"}])

a = ann([{"clueFragment": "x y", "gives": "WATCHSTRAP"}])
check("gives that was the answer leaves no note", M.mend(a, "WATCHSTRAP") and "note" not in a["blocks"][0])

a = ann([{"clueFragment": "x y", "gives": "a timepiece band", "note": "reads two ways"}])
M.mend(a, "WATCHSTRAP")
check("other text moves into the note", a["blocks"][0]["note"] == "reads two ways (a timepiece band)")

a = ann([{"clueFragment": "x y", "gives": "the watch strap", "note": "n"}])
M.mend(a, "WATCHSTRAP")
check("a move that would spell the answer is not made", a["blocks"][0] == {"clueFragment": "x y", "note": "n"})

for note, want in [("= WATCHSTRAP", None), ("the answer is Watchstrap.", None),
                   ("a strap holds a watch; = WATCHSTRAP", "a strap holds a watch"),
                   ("It is a watchstrap, worn daily", "It is a watchstrap, worn daily")]:
    a = ann([{"clueFragment": "x y", "note": note}])
    M.mend(a, "WATCHSTRAP")
    check(f"note {note!r}", a["blocks"][0].get("note") == want)

a = ann([{"clueFragment": "x", "gives": "A"}], typ=("charade",))
check("other types untouched", not M.mend(a, "WATCHSTRAP") and a["blocks"][0].get("gives") == "A")

for note, ans, want in [
        ("Sir Lancelot of the Round Table, split as a weapon plus 'a lot', is a weapon",
         "LANCE", "Sir ... of the Round Table, split as a weapon plus 'a lot', is a weapon"),
        ("not unlocking a door but pressing the keys of a typewriter at work", "TYPE",
         "not unlocking a door but pressing the keys of a ... at work"),
        ("a plain note that says nothing of it", "TYPE", None),
        ("Hale is a town in Cheshire, so people there are in it", "INHALE", None),
        ("a kneading of dough", "KNEE", None)]:
    check(f"blank_note_words {ans}: {note[:30]!r}", M.blank_note_words(note, ans) == want)

raise SystemExit(1 if fails else 0)
