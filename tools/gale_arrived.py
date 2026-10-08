#!/usr/bin/env python3
"""Mark a Gale download arrived on the checklists within seconds of it landing.

A launchd job on the Mac (LABEL, WatchPaths on the download folders) runs
this on every change in them. It reads the Gale document id off each page
file's name and writes ARRIVED beside the checklists: a script,
galeArrived({doc: when}), that an open checklist loads with its status file.
A row whose Download names that document shows "downloaded, checking" until
the sync's own status says the file is in the inbox. Nothing here opens,
moves or deletes a file or asks Gale anything: matching, sorting and reading
stay with tools/gale_inbox.py sync, which installs this job (install_watcher).
Stdlib only: it runs on the Mac's own python.

    python3 tools/gale_arrived.py [--out FILE] DIR...
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PAGES = (".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp")
DOC_ID = re.compile(r"GALE[\W_]{0,3}([A-Z]{2}\d{8,12})", re.IGNORECASE)
#: Gale's own download name, the bare number ("IF0500468517.pdf", a second
#: copy "IF0500254930 (1).pdf").
BARE_DOC = re.compile(r"([A-Z]{2}\d{8,12})(?:\s*\(\d+\))?", re.IGNORECASE)
#: The file the checklists load, in their folder.
NAME = "Arrived.js"
#: How long a document stays marked: by then a sync has swept it in (and
#: the row is "in the inbox") or set it aside, and the mark would only lie.
KEEP = 3600
LABEL = "com.pt.gale-arrived"
CALL = "galeArrived("


def name_doc(name):
    """The Gale document a file's name gives, upper-cased, or None."""
    m = DOC_ID.search(name) or BARE_DOC.fullmatch(Path(name).stem)
    return m.group(1).upper() if m else None


def read(out):
    """{doc: when} last written to `out`; {} when there is none."""
    try:
        text = Path(out).read_text()
        return json.loads(text[text.index(CALL) + len(CALL):text.rindex(")")])
    except (OSError, ValueError):
        return {}


def scan(dirs, out, now=None, keep=KEEP):
    """Add every page file in `dirs` that names a Gale document and landed
    in the last `keep` seconds to `out`, dropping marks older than that;
    `out` is written (whole or not at all) when missing, else only when
    that changes it.
    [(doc, file, seconds since it landed)] of the documents new to it."""
    now = time.time() if now is None else now
    was = read(out)
    marks = {d: t for d, t in was.items() if now - t < keep}
    new = []
    for folder in dirs:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            doc = Path(e.name).suffix.lower() in PAGES and name_doc(e.name)
            if not doc or doc in marks:
                continue
            try:
                landed = e.stat().st_mtime
            except OSError:  # moved by the sync between listing and stat
                continue
            if now - landed < keep:
                marks[doc] = int(landed)
                new.append((doc, e.name, round(now - landed, 1)))
    if marks != was or not Path(out).exists():  # an open page loads it from the first
        # In place, never renamed over: see gale_inbox.publish (polled).
        Path(out).write_text(f"{CALL}{json.dumps(marks, sort_keys=True)});\n")
    return new


def plist(python, script, dirs, out, log):
    """The launchd job that runs `script` on every change in `dirs`."""
    from xml.sax.saxutils import escape
    args = "".join(f"<string>{escape(a)}</string>" for a in [python, script, "--out", out, *dirs])
    watch = "".join(f"<string>{escape(d)}</string>" for d in dirs)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array>{args}</array>
<key>WatchPaths</key><array>{watch}</array>
<key>RunAtLoad</key><true/>
<key>ThrottleInterval</key><integer>1</integer>
<key>StandardOutPath</key><string>{escape(log)}</string>
<key>StandardErrorPath</key><string>{escape(log)}</string>
</dict></plist>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("dirs", nargs="+")
    a = ap.parse_args(argv)
    for doc, name, ago in scan(a.dirs, a.out):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {doc} marked arrived ({name}, landed {ago}s before)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
