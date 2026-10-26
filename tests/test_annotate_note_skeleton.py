#!/usr/bin/env python3
# annotate_check prints every missing block note as one --patch file, so the
# commonest first-check failure is one Write and one command.
#
#     python3 tests/test_annotate_note_skeleton.py
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import annotate_check as AC
import validate_annotations as V

line = lambda tag, frag, gives: (f"warn: {tag}: block {frag!r} > {gives!r} {V.BLOCK_NO_NOTE}. Say why.")
report = "\n".join([line("6D", "engraver and artist", "VERANDA"),
                    line("14A", "Giza bus, I'm Belgian", "ABUSIMBEL"),
                    "warn: 3D: something else [check_surface]"])
got = json.loads(AC.note_skeleton(report))
assert set(got) == {"6-down", "14-across"}, got
assert "Giza bus, I'm Belgian" in got["14-across"]["notes"], got
assert AC.note_skeleton("warn: 3D: something else") == ""
print("ok")
