#!/usr/bin/env python3
"""Probe every number of a Guardian series between two bounds, file what is served.

    python3 tools/sweep_series.py everyman 2 2964

The Guardian serves everyman No 1 (1946) and everything from No 2965, and 404s
the numbers between; this finds any other that is served rather than assuming.
One request a second, one log line per number on stdout. Resumable: a number on
disk or in the ledger (puzzles it already saw 404) is skipped. A non-404 error
gets three tries, is logged "failed" and left out of the ledger so the next run
retries it. Served pages go through tools/fetch_puzzle.py, and every 20 filed
the new files are committed and pushed.
"""

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import puzzle_paths


def served(series, n):
    """True/False for 200/404; raises after three tries on anything else."""
    url = f"https://www.theguardian.com/crosswords/{series}/{n}"
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=30).status == 200
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            err = f"HTTP {e.code}"
        except OSError as e:  # timeouts, resets
            err = repr(e)
        time.sleep(5 * attempt)
    raise RuntimeError(err)


def publish(message):
    subprocess.run(["git", "add", "-A", "puzzles"], cwd=ROOT, check=True)
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", "puzzles"], cwd=ROOT, check=False
    ).returncode:
        subprocess.run(
            [
                "git",
                "commit",
                "-q",
                "-m",
                message + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                "--",
                "puzzles",
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(["tools/push_puzzle_commit.sh"], cwd=ROOT, check=True)


def main():
    series, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    ledger = Path(
        sys.argv[4]
        if len(sys.argv) > 4
        else f"/Users/pt/.cryptic-teacher/{series}_404.txt"
    )
    seen = set(ledger.read_text().split()) if ledger.exists() else set()
    filed = 0
    for n in range(lo, hi + 1):
        pid = f"{series}-{n}"
        if puzzle_paths.find(pid):
            print(f"{pid} on-disk", flush=True)
            continue
        if str(n) in seen:
            print(f"{pid} known-404", flush=True)
            continue
        try:
            ok = served(series, n)
        except RuntimeError as e:
            print(f"{pid} failed {e}", flush=True)
            continue
        if not ok:
            with ledger.open("a") as f:
                f.write(f"{n}\n")
            print(f"{pid} 404", flush=True)
        else:
            r = subprocess.run(
                [sys.executable, "tools/fetch_puzzle.py", pid],
                cwd=ROOT,
                capture_output=True,
                check=False,
                text=True,
            )
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
            print(f"{pid} served exit={r.returncode} {tail[0][:120]}", flush=True)
            filed += r.returncode == 0
            if filed and filed % 20 == 0:
                publish(f"archive: {series} sweep {lo}-{hi}")
        time.sleep(1)
    publish(f"archive: {series} sweep {lo}-{hi}")
    print(f"== DONE {series} {lo}-{hi} filed={filed}", flush=True)


if __name__ == "__main__":
    main()
