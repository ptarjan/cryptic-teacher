#!/usr/bin/env python3
"""What fills the site artifact, by kind of file.

  python3 tools/site_size.py LIST          # bytes by path shape and by type
  python3 tools/site_size.py LIST --dupes  # also the bytes in identical files

LIST is the tar file list tools/stage_site.py --list writes. A path's shape
is the path with each name that has many siblings (a puzzle id, a card) read
as *, so puzzles/times-29674/index.html counts under puzzles/*/index.html.
The deploy's time scales with what this reports: the artifact is these bytes
plus tar's 512-byte header and padding per entry.
"""
import hashlib
import os
import sys
from collections import Counter, defaultdict

import parallel  # the hashing across the cores

#: A directory with more entries than this has its entries read as *.
MANY = 50


def shapes(files):
    """{rel: shape} for the files, relative paths with /."""
    kids = defaultdict(set)
    for rel in files:
        parts = rel.split("/")
        for i in range(len(parts)):
            kids["/".join(parts[:i])].add(parts[i])
    out = {}
    for rel in files:
        parts = rel.split("/")
        shaped = []
        for i, name in enumerate(parts):
            parent = "/".join(parts[:i])
            if len(kids[parent]) > MANY:
                name = "*" + os.path.splitext(name)[1] if i == len(parts) - 1 else "*"
            shaped.append(name)
        out[rel] = "/".join(shaped)
    return out


def md5(rel):
    with open(rel, "rb") as f:
        return rel, hashlib.md5(f.read()).hexdigest()


def table(title, sizes, counts, total):
    print(f"{title}:")
    for key, size in sorted(sizes.items(), key=lambda kv: -kv[1])[:25]:
        print(f"  {size / 1e6:9.1f} MB {100 * size / total:5.1f}%  {counts[key]:7d} files"
              f"  {size / counts[key] / 1e3:7.1f} KB each  {key}")


def main(argv):
    if not argv or argv[1:] not in ([], ["--dupes"]):
        print(__doc__, file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as f:
        entries = [line.rstrip("\n")[2:] for line in f if line.strip() != "./"]
    dirs = {os.path.dirname(e) for e in entries}
    files = [e for e in entries if e not in dirs]
    size = {rel: os.stat(rel).st_size for rel in files}
    total = sum(size.values())
    shape = shapes(files)
    by_shape, n_shape, by_ext, n_ext = Counter(), Counter(), Counter(), Counter()
    for rel, n in size.items():
        ext = os.path.splitext(rel)[1] or rel
        by_shape[shape[rel]] += n
        n_shape[shape[rel]] += 1
        by_ext[ext] += n
        n_ext[ext] += 1
    headers = 512 * len(entries) + sum(-n % 512 for n in size.values())
    print(f"site: {len(files)} files, {len(dirs)} directories, {total / 1e6:.1f} MB of content,"
          f" {headers / 1e6:.1f} MB of tar headers and padding")
    table("by path shape", by_shape, n_shape, total)
    table("by type", by_ext, n_ext, total)
    if argv[1:] == ["--dupes"]:
        same_size = defaultdict(list)
        for rel, n in size.items():
            same_size[n].append(rel)
        suspects = [rel for group in same_size.values() if len(group) > 1 for rel in group]
        groups = defaultdict(list)
        for rel, digest in parallel.pmap(md5, suspects, chunksize=256):
            groups[digest].append(rel)
        spare, n_spare = Counter(), Counter()
        for group in groups.values():
            for rel in sorted(group)[1:]:
                spare[shape[rel]] += size[rel]
                n_spare[shape[rel]] += 1
        wasted = sum(spare.values())
        print(f"identical copies beyond the first: {sum(n_spare.values())} files, {wasted / 1e6:.1f} MB")
        if wasted:
            table("copies by path shape", spare, n_spare, wasted)
            for group in sorted(groups.values(), key=lambda g: -len(g) * size[g[0]])[:5]:
                if len(group) > 1:
                    print(f"  e.g. {len(group)} x {size[group[0]]} B: {', '.join(sorted(group)[:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
