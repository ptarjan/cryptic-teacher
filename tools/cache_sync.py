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

  * A cache whose readers look posts up in the SSD manifest (media_manifest.py) gets
    a row there for each post it lands (MANIFESTED): the manifest is how a scheduled
    reader sees a file without listing the spinning disk.

A cache joins by a row in CACHES and a workflow that uploads cache-<name>-<run id>
(timesforthetimes and bigdave44: blog-fetch.yml). SUPERSEDABLE files, the one exception to
'only adds', are merged with the later copy, keeping every old row.
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
import media_manifest

REPO = "ptarjan/cryptic-teacher"
#: cache name -> the folder of the media disk it mirrors.
CACHES = {"telegraph-source": downloads.TELEGRAPH, "fifteensquared": downloads.FIFTEENSQUARED,
          "timesforthetimes": downloads.TIMESFORTHETIMES, "bigdave44": downloads.ROOT / "bigdave44"}
#: cache name -> the workflow file that writes it and uploads cache-<name>-<run id>.
WORKFLOWS = {"telegraph-source": "telegraph-bucket.yml", "fifteensquared": "fifteensquared-fetch.yml",
             "timesforthetimes": "blog-fetch.yml", "bigdave44": "blog-fetch.yml"}
#: cache name -> the blog whose posts/<id>.json files it carries (manifest posts-<blog>).
MANIFESTED = {"fifteensquared": "posts", "timesforthetimes": "posts", "bigdave44": "posts"}
#: cache name -> the folder of month files (YYYY-MM.json) whose manifest (comments-<blog>) a
#: landed file gets a row in. A month the blog's fetch refetched is replaced, never plain added:
#: see SUPERSEDABLE.
COMMENTED = {"timesforthetimes": "comments", "bigdave44": "comments"}
#: The few files a fetch rewrites in place: a comments month still filling, and the blog's
#: category list. A differing copy is merged into the disk's one (merged()), so no row is lost.
SUPERSEDABLE = {"comments", "categories.json"}


def record_landed(name, dest, rel, data):
    """Append the manifest row of a post just landed as dest/<rel> (a no-op for any file
    that is no post of a MANIFESTED cache)."""
    p = Path(rel)
    if name in MANIFESTED and len(p.parts) == 2 and p.parts[0] == MANIFESTED[name] and p.stem.isdigit():
        media_manifest.record_post(dest / p.parts[0], json.loads(data))
    elif (name in COMMENTED and len(p.parts) == 2 and p.parts[0] == COMMENTED[name] and p.suffix == ".json"
          and p.stem not in media_manifest.comment_keys(dest / p.parts[0])):
        media_manifest.record_comments(dest / p.parts[0], p.stem)


def merged(rel, old, new):
    """The bytes a rewritable file `rel` becomes when the later copy `new` meets the disk's
    `old`: the later copy's rows, plus any row only the old one has (a comment since deleted
    upstream is kept; an edited one takes the later text). None for a file that is not
    rewritable or does not parse."""
    p = Path(rel)
    if not (p.name in SUPERSEDABLE or (p.parts and p.parts[0] in SUPERSEDABLE)):
        return None
    try:
        a, b = json.loads(old), json.loads(new)
    except ValueError:
        return None
    if isinstance(a, list) and isinstance(b, list):
        have = {r["id"] for r in b}
        rows = sorted(b + [r for r in a if r["id"] not in have], key=lambda r: (r.get("date", ""), r["id"]))
        return json.dumps(rows).encode()
    if isinstance(a, dict) and isinstance(b, dict):
        return json.dumps({**a, **b}, ensure_ascii=False).encode()
    return None


def gh(*args, out=None):
    """`gh api` output as text (or streamed to the file object `out`)."""
    r = subprocess.run(["gh", "api", *args], stdout=out or subprocess.PIPE, stderr=subprocess.PIPE,
                       text=out is None, timeout=900, check=False)
    if r.returncode:
        raise RuntimeError(f"gh api {' '.join(args)}: {(r.stderr or b'')[-300:]}")
    return r.stdout


def artifacts(name):
    """The unexpired artifacts called cache-<name>-*, oldest first. Found through the
    workflow's own runs: the repo holds tens of thousands of artifacts (the site's), too
    many to page through."""
    found = []
    runs = json.loads(gh(f"repos/{REPO}/actions/workflows/{WORKFLOWS[name]}/runs?per_page=100"))
    for run in runs.get("workflow_runs") or []:
        if run["status"] != "completed":
            continue
        doc = json.loads(gh(f"repos/{REPO}/actions/runs/{run['id']}/artifacts"))
        found += [a for a in doc.get("artifacts") or []
                  if a["name"].startswith(f"cache-{name}-") and not a["expired"]]
    return sorted(found, key=lambda a: a["created_at"])


def safe(rel):
    p = Path(rel)
    return not p.is_absolute() and ".." not in p.parts


def land(zf, dest, dry=False, name=None):
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
            old = target.read_bytes()
            if old == data:
                same += 1
            else:
                new = merged(info.filename, old, data)
                if new is None:
                    differ.append(info.filename)
                elif new == old:
                    same += 1
                else:
                    if not dry:
                        tmp = target.with_name(f".{target.name}.sync{os.getpid()}")
                        tmp.write_bytes(new)
                        os.replace(tmp, target)
                        record_landed(name, dest, info.filename, new)
                    added += 1
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
            record_landed(name, dest, info.filename, data)
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
                added, same, differ = land(zf, dest, dry, name)
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
