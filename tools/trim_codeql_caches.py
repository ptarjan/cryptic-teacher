#!/usr/bin/env python3
"""Delete all but the newest CodeQL overlay database per language from the
repo's Actions cache.

  python3 tools/trim_codeql_caches.py OWNER/REPO            # delete
  python3 tools/trim_codeql_caches.py OWNER/REPO --dry-run  # list only
  python3 tools/trim_codeql_caches.py --pick < caches.tsv   # "id<TAB>key" lines in, ids to delete out

GitHub's CodeQL default setup saves one ~50MB entry per language per push,
keyed codeql-overlay-base-database-<n>-<hash>-<language>-<version>-<sha>-<run>-<attempt>,
and deletes none. They filled 9.6GB of the 10GB the repo gets, so GitHub
evicted the deploy's own caches to make room (.github/workflows/pages.yml,
Trim the CodeQL caches). CodeQL restores the newest entry for its
<n>-<hash>-<language>, so that one stays, and only that one.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

PREFIX = "codeql-overlay-base-database-"


def group(key):
    """The part of a CodeQL key that one analysis restores by: up to its language."""
    return "-".join(key.split("-")[:7])


def pick(caches):
    """The ids to delete from [(id, key, created_at)]: every CodeQL entry but
    the newest of its group. Anything not CodeQL's is never picked."""
    newest, doomed = {}, []
    for cid, key, created in sorted(caches, key=lambda c: c[2], reverse=True):
        if not key.startswith(PREFIX):
            continue
        if group(key) in newest:
            doomed.append(cid)
        else:
            newest[group(key)] = cid
    return doomed


def listed(repo):
    out = subprocess.run(
        ["gh", "api", "--paginate", "--jq", ".actions_caches[] | [.id, .key, .created_at] | @json",
         f"repos/{repo}/actions/caches?key={PREFIX}&per_page=100"],
        capture_output=True, text=True, check=True).stdout
    return [tuple(json.loads(line)) for line in out.splitlines() if line.strip()]


def delete(repo, cid):
    r = subprocess.run(["gh", "api", "-X", "DELETE", "--silent", f"repos/{repo}/actions/caches/{cid}"],
                       capture_output=True, text=True)
    return r.returncode == 0


def main(argv):
    if argv == ["--pick"]:
        rows = [line.rstrip("\n").split("\t") for line in sys.stdin if line.strip()]
        print("\n".join(str(i) for i in pick([(r[0], r[1], r[2]) for r in rows])))
        return 0
    if not argv or argv[0].startswith("-"):
        print(__doc__, file=sys.stderr)
        return 2
    repo, dry = argv[0], "--dry-run" in argv[1:]
    caches = listed(repo)
    doomed = pick(caches)
    print(f"{len(caches)} CodeQL cache(s), deleting {len(doomed)}")
    if dry or not doomed:
        return 0
    with ThreadPoolExecutor(8) as pool:
        ok = sum(pool.map(lambda c: delete(repo, c), doomed))
    print(f"deleted {ok} of {len(doomed)}")
    return 0 if ok == len(doomed) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
