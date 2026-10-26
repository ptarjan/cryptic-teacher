#!/usr/bin/env python3
"""Tests tools/security_alert_watch.py with a fake gh and a fake wake.sh."""
import json
import os
import pathlib
import stat
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(HERE))


def script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def main():
    tmp = pathlib.Path(tempfile.mkdtemp())
    calls = tmp / "wakes.txt"
    alerts = tmp / "alerts.json"
    script(tmp / "wake.sh", f'echo "$4" >> {calls}\n')
    script(tmp / "gh", f"""case "$*" in
  *code-scanning*) cat {alerts} ;;
  *dependabot*) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
  *) echo "gh: Forbidden (HTTP 403)" >&2; exit 1 ;;
esac
""")
    os.environ.update(WAKE_SH=str(tmp / "wake.sh"), GH_BIN=str(tmp / "gh"),
                      SECURITY_WATCH_STATE=str(tmp / "state.json"))
    import security_alert_watch as w
    w.WAKE_SH, w.GH, w.STATE = str(tmp / "wake.sh"), str(tmp / "gh"), tmp / "state.json"

    def wakes():
        return calls.read_text().count("New GitHub security") if calls.exists() else 0

    alerts.write_text("[]")
    assert w.main(["--force"]) == 0 and wakes() == 0   # seeds, 404/403 sources skipped
    one = [{"number": 7, "html_url": "https://x/7", "rule": {"id": "py/sql"},
            "most_recent_instance": {"location": {"path": "a.py", "start_line": 3}}}]
    alerts.write_text(json.dumps(one))
    assert w.main([]) == 0 and wakes() == 0            # inside the hour: no check
    assert w.main(["--force"]) == 0 and wakes() == 1   # new alert wakes once
    text = calls.read_text()
    assert "py/sql" in text and "a.py:3" in text and "https://x/7" in text
    assert text.strip().endswith("report to Paul.")
    assert w.main(["--force"]) == 0 and wakes() == 1   # same alert: no wake
    print("ok")


if __name__ == "__main__":
    main()
