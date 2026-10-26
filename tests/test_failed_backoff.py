#!/usr/bin/env python3
# Does a code edit re-buy a failed run only after a cooldown that doubles?
#
#     python3 tests/test_failed_backoff.py
#
# 10-16 audit: tls-1133 and nation-3490 were solved 3-4 times in three days
# because every edit to puzzle_integrity.py made their rows due again. A puzzle
# change still releases at once; a code-only change waits 1, 2, 4... days.
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
tmp = tempfile.mkdtemp()
os.environ["FAILED_INPUTS_FILE"] = str(Path(tmp) / "ledger.json")
import failed_inputs as fi

today = date.today().isoformat()
old = (date.today() - timedelta(days=3)).isoformat()
rec = {"puzzle": fi.input_hash.__name__, "code": "stale", "date": today, "reason": "x"}
fi.input_hash = lambda pid, held=None: "same"
fi.code_version = lambda kind, pid, reason: "new"
rec["puzzle"] = "same"

assert not fi.due("solve", "a-1", rec), "same-day code change must wait"
rec["date"] = (date.today() - timedelta(days=1)).isoformat()
assert fi.due("solve", "a-1", rec), "first retry waits one day"
rec["retries"] = 2
assert not fi.due("solve", "a-1", rec), "third buy waits 4 days"
rec["date"] = old
assert not fi.due("solve", "a-1", rec), "3 days is short of 4"
rec["date"] = (date.today() - timedelta(days=4)).isoformat()
assert fi.due("solve", "a-1", rec)
rec["retries"] = 40
assert fi.code_cooldown_days(rec) == 16
rec.pop("date")
assert fi.due("solve", "a-1", rec), "an undated row has nothing to wait out"
rec["date"] = today
rec["puzzle"] = "changed"
assert fi.due("solve", "a-1", rec), "a changed puzzle is due at once"
rec["puzzle"] = "same"
rec["code"] = "new"
assert not fi.due("solve", "a-1", rec), "unchanged code and puzzle stays held"

# record: a second failure on the same puzzle backs off, a changed one resets
fi.puzzle_inputs = lambda pid, held=None: {"x": 1}
fi.committed = lambda pid: None
fi.input_hash = lambda pid, held=None: "h1"
fi.code_version = lambda kind, pid, reason: "c"
import argparse
ns = argparse.Namespace(kind="solve", id="a-1", reason="r", judged=True)
fi.cmd_record(ns)
assert fi.load()["solve"]["a-1"]["retries"] == 0
fi.cmd_record(ns)
assert fi.load()["solve"]["a-1"]["retries"] == 1
fi.cmd_record(ns)
assert fi.load()["solve"]["a-1"]["retries"] == 2
fi.input_hash = lambda pid, held=None: "h2"
fi.cmd_record(ns)
assert fi.load()["solve"]["a-1"]["retries"] == 0
print("failed backoff: all checks passed")
