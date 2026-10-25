#!/usr/bin/env python3
# Does every fetcher keep its downloads under tools/downloads.py's ROOT?
#
#     python3 tools/test_downloads.py
#
# tools/downloads.py names every folder a fetcher fills. A path spelled
# anywhere else is how downloads scatter, so this fails on any code in tools/
# that names a home-relative directory other than the caches and config it is
# allowed (~/.cache's DERIVED folders, ~/.config, ~/.local, ~/.claude, ~/.ssh, the job worktrees
# in ~/.cryptic-teacher), a folder downloads.py has moved, or an absolute
# container path. Gale's tools keep their pages on the Mac's media disk and are
# skipped.
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)

files = [f for f in subprocess.run(["git", "ls-files", "tools/*.py", "tools/*.sh", "tools/*.js"],
                                   capture_output=True, text=True, check=True).stdout.split()
         if not re.match(r"tools/(gale_|test_|downloads\.py$)", f)]
# What ~/.cache may hold: what a tool rebuilds from the downloads, or a job's
# own state. Anything fetched from the web is a download.
DERIVED = ["annotate_cost_ledger\\.jsonl", "archive_coverage", "cryptic-progress-rows\\.json", "clues_only_grids", "cryptic-abbreviations-table\\.json", "vlm_health", "fetch_nation", "held_dates","archive_org_crops", "archive_org_tess", "corpus_queue", "coverage_ledger", "detsolve",
           "cryptic-blog-facts(?:\\.(?:lock|deferred)|-index\\.sqlite)", "cryptic-teacher", "gale_inbox", "ocr_remote", "ocr_words", "postproc_learn", "rapidocr", "scan_reread_requests\\.jsonl",
           "vlm_reader", "cryptic-letter-pass-day", "security_alert_watch\\.json"]
ALLOWED = r"(\.cache|\.config|\.local|\.claude|\.ssh|\.cryptic-teacher)\b"
rules = [
    ("a home path outside the allowed dot-directories",
     re.compile(r'(Path\.home\(\)\s*/\s*"|expanduser\("~/|\$HOME/|(?<![\w.])HOME\s*/\s*")(?!' + ALLOWED + ")")),
    ("the downloads root spelled out", re.compile(r"cryptic-setter-data")),
    ("a ~/.cache folder that is not a derived cache or job state (a download goes in downloads.py)",
     re.compile(r'\.cache(?:/|"\s*/\s*")(?!(?:' + "|".join(DERIVED) + r')\b)[\w.-]')),
    ("a book-text folder downloads.py moved", re.compile(r"cryptic-teacher/ia-books|/tmp/cryptic-teacher-ia")),
    ("an absolute container path", re.compile(r'"/data/home/')),
]
bad = []
for f in files:
    for n, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
        for why, rx in rules:
            if rx.search(line):
                bad.append(f"{f}:{n}: {why}: {line.strip()[:120]}")
if bad:
    print("Downloads go under a folder named in tools/downloads.py:\n" + "\n".join(bad))
    sys.exit(1)
print(f"ok: {len(files)} files keep their downloads under tools/downloads.py's ROOT")

# Importing downloads without CT_DOWNLOADS must not exit where the media disk's
# path is absent (CI, the site build): 124 tools import it.
r = subprocess.run([sys.executable, "-c", 'import sys; sys.path.insert(0, "tools"); import downloads'],
                   env={k: v for k, v in os.environ.items() if k != "CT_DOWNLOADS"})
if r.returncode:
    sys.exit(r.returncode)
print("ok: downloads imports without CT_DOWNLOADS")

# migrate() unlinks an old path left as a symlink, moves in a real one, and
# refuses to choose between two copies.
tmp = tempfile.mkdtemp()
try:
    os.environ["HOME"] = f"{tmp}/home"
    os.environ["CT_DOWNLOADS"] = f"{tmp}/dl"
    sys.path.insert(0, "tools")
    import downloads

    old = list(downloads.OLD_PATHS)
    old[0].parent.mkdir(parents=True)
    downloads.ARCHIVE_ORG.mkdir(parents=True)
    old[0].symlink_to(downloads.ARCHIVE_ORG)
    (old[1] / "1").mkdir(parents=True)
    downloads.migrate()
    assert not os.path.lexists(old[0]) and downloads.ARCHIVE_ORG.is_dir(), "a symlink is unlinked, its folder kept"
    assert (downloads.TROVE / "1").is_dir() and not old[1].exists(), "a real folder is moved in"
    old[1].mkdir()
    try:
        downloads.migrate()
        raise AssertionError("two copies must not be merged silently")
    except SystemExit:
        pass
    print("ok: migrate")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
