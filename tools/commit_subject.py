#!/usr/bin/env python3
"""A commit subject naming the puzzles staged, for jobs that commit as they go.

    git diff --cached --name-status -M -- puzzles | python3 tools/commit_subject.py "<job>"

prints e.g. "File times-17317, renumber times-18318 as times-17318 (Full OCR
pass)": what changed comes first, the job that changed it after. With no
puzzle staged it prints the job alone.
"""
import sys
from pathlib import PurePosixPath

#: Shown per verb before the rest are counted.
SHOWN = 3

VERBS = {"A": "file", "M": "update", "D": "drop", "R": "renumber"}


def subject(lines, job):
    by = {v: [] for v in VERBS.values()}
    for line in lines:
        f = line.rstrip("\n").split("\t")
        if len(f) < 2 or not f[-1].endswith(".json"):
            continue
        kind, ids = f[0][0], [PurePosixPath(p).stem for p in f[1:]]
        if kind == "R":
            by["renumber"].append(f"{ids[0]} as {ids[1]}")
        elif kind in VERBS:
            by[VERBS[kind]].append(ids[0])
    parts = []
    for verb, ids in by.items():
        if ids:
            more = f" and {len(ids) - SHOWN} more" if len(ids) > SHOWN else ""
            parts.append(f"{verb} {', '.join(ids[:SHOWN])}{more}")
    if not parts:
        return job
    head = "; ".join(parts)
    return f"{head[0].upper()}{head[1:]} ({job})"


if __name__ == "__main__":
    print(subject(sys.stdin, sys.argv[1]))
