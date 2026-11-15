#!/usr/bin/env python3
"""Land the raw fetch caches that GitHub Actions writes on the media disk.

    python3 tools/cache_sync.py            # every cache in CACHES
    python3 tools/cache_sync.py telegraph-source --dry-run

A fetcher that moved to CI (a workflow under .github/workflows/) keeps its
raw fetch cache in actions/cache and uploads each run's NEW files as the
artifact cache-<name>-<run id> (the workflow's "Upload the new cache files"
step, kept 90 days). This is the local half: the media disk stays a complete
mirror, which the local readers (cross_validate, blog-facts, ratings comments)
keep reading unchanged.

  * It only adds. A file already on the disk is never replaced or removed, even
    one that differs (reported, and its artifact kept until it expires): the
    raw fetch caches are never deleted or overwritten.
  * An artifact is deleted only once every file in it is on the disk with the
    same bytes. One that cannot be fully landed is kept and tried again.
  * Idempotent: a rerun finds nothing to add.

A later cache (the fifteensquared trio, timesforthetimes, bigdave44) joins by a
row in CACHES and a workflow that uploads cache-<name>-<run id>.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import downloads

REPO = "ptarjan/cryptic-teacher"
#: cache name -> the folder of the media disk it mirrors.
CACHES = {"telegraph-source": downloads.TELEGRAPH}


def gh(*args, out=None):
    """`gh api` output as text (or streamed to the file object `out`)."""
    r = subprocess.run(["gh", "api", *args], stdout=out or subprocess.PIPE, stderr=subprocess.PIPE,
                       text=out is None, timeout=900, check=False)
    if r.returncode:
        raise RuntimeError(f"gh api {' '.join(args)}: {(r.stderr or b'')[-300:]}")
    return r.stdout


def artifacts(name):
    """The unexpired artifacts called cache-<name>-*, oldest first."""
    found = []
    page = 1
    while True:
        doc = json.loads(gh(f"repos/{REPO}/actions/artifacts?per_page=100&page={page}"))
        rows = doc.get("artifacts") or []
        found += [a for a in rows if a["name"].startswith(f"cache-{name}-") and not a["expired"]]
        if len(rows) < 100:
            break
        page += 1
    return sorted(found, key=lambda a: a["created_at"])


def safe(rel):
    p = Path(rel)
    return not p.is_absolute() and ".." not in p.parts


def land(zf, dest, dry=False):
    """Add each file of the open zip under `dest`. -> (added, same, differing)."""
    added = same = 0
    differ = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        if not safe(info.filename):
            differ.append(f"{info.filename} (unsafe path)")
            continue
        target = dest / info.filename
        data = zf.read(info)
        if target.exists():
            if target.read_bytes() == data:
                same += 1
            else:
                differ.append(info.filename)
            continue
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.sync{os.getpid()}")
            tmp.write_bytes(data)
            try:
                os.link(tmp, target)  # fails if a file appeared meanwhile: never replaces
            except FileExistsError:
                differ.append(info.filename)
                continue
            finally:
                tmp.unlink()
            if target.read_bytes() != data:
                differ.append(f"{info.filename} (did not land intact)")
                continue
        added += 1
    return added, same, differ


def sync(name, dry=False):
    dest = CACHES[name]
    if not (dest.parent / ".on-media-disk").exists() and not os.environ.get("CT_DOWNLOADS"):
        print(f"{name}: {dest.parent} is not the media disk (unmounted?); nothing synced")
        return 1
    rc = 0
    for art in artifacts(name):
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            gh(f"repos/{REPO}/actions/artifacts/{art['id']}/zip", out=tmp)
            tmp.flush()
            with zipfile.ZipFile(tmp.name) as zf:
                added, same, differ = land(zf, dest, dry)
        print(f"{name}: {art['name']}: {added} added, {same} already there, {len(differ)} differ")
        for d in differ:
            print(f"  kept the disk's copy of {d}")
        if dry:
            continue
        if differ:
            print(f"  {art['name']} kept: not every file landed as is")
            continue
        try:
            gh("-X", "DELETE", f"repos/{REPO}/actions/artifacts/{art['id']}")
            print(f"  {art['name']} landed in full; artifact deleted")
        except RuntimeError as err:
            print(f"  landed in full; artifact not deleted ({err}); it expires on its own")
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help="caches to sync (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="report what would land; add and delete nothing")
    args = ap.parse_args(argv)
    rc = 0
    for name in args.names or CACHES:
        rc |= sync(name, args.dry_run)
    return rc


if __name__ == "__main__":
    sys.exit(main())
