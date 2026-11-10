#!/usr/bin/env python3
# Does a code edit re-buy a failed run only after a cooldown that doubles?
#
#     python3 tests/test_failed_backoff.py
#
# 10-16 audit: tls-1133 and nation-3490 were solved 3-4 times in three days
# because every edit to puzzle_integrity.py made their rows due again. A puzzle
# change still releases at once; a code-only change waits 1, 2, 4... days.
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import _path  # puts tools/ on sys.path
tmp = tempfile.mkdtemp()
os.environ["FAILED_INPUTS_FILE"] = str(Path(tmp) / "ledger.json")
import failed_inputs as fi

utc_today = datetime.now(UTC).date()
today = utc_today.isoformat()
old = (utc_today - timedelta(days=3)).isoformat()
rec = {"puzzle": fi.input_hash.__name__, "code": "stale", "date": today, "reason": "x"}
fi.input_hash = lambda pid, held=None: "same"
fi.code_version = lambda kind, pid, reason: "new"
rec["puzzle"] = "same"

assert not fi.due("solve", "a-1", rec), "same-day code change must wait"
rec["date"] = (utc_today - timedelta(days=1)).isoformat()
assert fi.due("solve", "a-1", rec), "first retry waits one day"
rec["retries"] = 2
assert not fi.due("solve", "a-1", rec), "third buy waits 4 days"
rec["date"] = old
assert not fi.due("solve", "a-1", rec), "3 days is short of 4"
rec["date"] = (utc_today - timedelta(days=4)).isoformat()
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

# The cooldown counts from the record's time, not its day: a row written at
# 23:59 UTC is not a day old a minute later.
late = datetime(2026, 11, 4, 23, 59, tzinfo=UTC)
row = {"date": late.isoformat(timespec="seconds")}
assert fi.code_age_days(row, now=late + timedelta(minutes=1)) < 1
assert fi.code_age_days(row, now=late + timedelta(days=1)) >= 1
assert fi.code_age_days({"date": "2026-11-04"}, now=late) < 1, "a bare date is its midnight"
assert "T" in fi.load()["solve"]["a-1"]["date"], "record keeps the time"

# summary drops a row only when its puzzle changed. 11-04..11-10 it dropped
# rows a code edit had released too, so each was recorded again with
# retries=0, its cooldown never grew past a day, and the burn bought
# everyman-3984 three times for the same "no change".
ns = argparse.Namespace(kind="annotate", id="e-1", reason="the run exited cleanly but wrote no annotation",
                        judged=True)
fi.input_hash = lambda pid, held=None: "p"
fi.code_version = lambda kind, pid, reason: "v1"
fi.cmd_record(ns)
data = fi.load()
data["annotate"]["e-1"]["date"] = "2026-01-01"   # long past any cooldown
fi.save(data)
fi.code_version = lambda kind, pid, reason: "v2"   # a checker was edited
assert "e-1" not in fi.skipped(fi.load(), "annotate"), "a code edit releases it"
fi.cmd_summary(argparse.Namespace())
assert "e-1" in fi.load()["annotate"], "summary keeps a code-released row"
fi.cmd_record(ns)   # bought again, failed again on the same puzzle
rec = fi.load()["annotate"]["e-1"]
assert rec["retries"] == 1, rec
assert fi.code_cooldown_days(rec) == 2
assert "e-1" in fi.skipped(fi.load(), "annotate"), "held again after the new failure"
fi.input_hash = lambda pid, held=None: "p-changed"
fi.cmd_summary(argparse.Namespace())
assert "e-1" not in fi.load()["annotate"], "summary drops a row whose puzzle changed"
print("failed backoff: all checks passed")
