#!/usr/bin/env bash
# annotate_check prints every missing block note as one --patch file, so the
# commonest first-check failure is one Write and one command.
#
#     bash tools/test_annotate_note_skeleton.sh
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import json
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
PY
echo ok
