#!/usr/bin/env python3
# Is a withdrawn annotate record held against code edits, and listed for triage?
#
#     python3 tests/test_failed_withdrawn.py
import contextlib
import io
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import _path  # puts tools/ on sys.path
tmp = tempfile.mkdtemp()
os.environ["FAILED_INPUTS_FILE"] = str(Path(tmp) / "ledger.json")
import failed_inputs as fi

fi.input_hash = lambda pid, held=None: "same"
fi.code_version = lambda kind, pid, reason: "new"
W = fi.WITHDRAWN + " 1-down has no clean parse"
rec = {"puzzle": "same", "code": "old", "date": "2020-01-01", "retries": 0, "reason": W}
assert not fi.due("annotate", "a-1", rec), "a code-only change must not release a withdrawal"
assert not fi.due("annotate", "a-1", {k: v for k, v in rec.items() if k != "code"}), "nor a legacy row"
assert fi.due("annotate", "a-1", {**rec, "puzzle": "other"}), "a changed puzzle releases it"
assert fi.due("annotate", "a-1", {**rec, "reason": "x"}), "other failures keep the code release"
assert fi.due("solve", "a-1", {**rec}), "solve keeps the code release"

data = {"annotate": {
    "b-2": {**rec, "date": "2026-11-03", "retries": 2},
    "a-1": {**rec, "date": "2026-10-30"},
    "c-3": {**rec, "reason": "plain failure"}}, "solve": {}}
fi.save(data)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    fi.cmd_triage(SimpleNamespace(kind="annotate"))
lines = out.getvalue().splitlines()
assert [l.split("\t")[0] for l in lines] == ["a-1", "b-2"], lines
assert lines[1].split("\t")[1:3] == ["2026-11-03", "retries=2"] and "no clean parse" in lines[1], lines

fi.cmd_clear(SimpleNamespace(kind="annotate", ids=["a-1"], reason=None, all=False))
assert "a-1" not in fi.load()["annotate"], "clear releases it"
print("ok")
