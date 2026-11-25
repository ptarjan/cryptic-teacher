#!/usr/bin/env python3
"""Delete the Actions caches a newer one supersedes, so the repository's 10 GB cap holds.

    prune_caches.py newest KEY_PREFIX   # keep the newest cache whose key starts with KEY_PREFIX
    prune_caches.py families            # keep the newest of each family (the key up to its 40-hex sha)

Every restore takes the newest entry of its family, so the older ones only fill the cap.
A family is the key up to the commit sha it ends in (`seo-pages-<fingerprint>-<sha>`);
the `ci-results` families are never touched. A failed delete is reported and skipped:
pruning never fails the job. Needs GH_TOKEN and GITHUB_REPOSITORY, as `gh` does.
"""
import json
import os
import re
import subprocess
import sys

KEEP_FAMILIES = ("ci-results",)


def listing(*args):
    out = subprocess.run(["gh", "cache", "list", "-R", os.environ["GITHUB_REPOSITORY"], "--sort", "created_at",
                          "--order", "desc", "--json", "id,key", *args],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out or "[]")


def family(key):
    return re.sub(r"[0-9a-f]{40}.*", "", key)


def stale_of_prefix(prefix):
    """Every cache under PREFIX but the newest (the listing is newest first)."""
    return [c["key"] for c in listing("--key", prefix, "--limit", "100")[1:]]


def stale_families(caches):
    """Every cache but the newest of its family, in `caches` order (newest first)."""
    seen = set()
    stale = []
    for c in caches:
        fam = family(c["key"])
        if fam.startswith(KEEP_FAMILIES):
            continue
        if fam in seen:
            stale.append(c["key"])
        seen.add(fam)
    return stale


def delete(key):
    r = subprocess.run(["gh", "cache", "delete", key, "-R", os.environ["GITHUB_REPOSITORY"]],
                       capture_output=True, text=True)
    if r.returncode:
        print(f"prune_caches: could not delete {key}: {r.stderr.strip()}", file=sys.stderr)


def main(argv):
    try:
        if len(argv) == 3 and argv[1] == "newest":
            keys = stale_of_prefix(argv[2])
        elif len(argv) == 2 and argv[1] == "families":
            keys = stale_families(listing("--limit", "200"))
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except subprocess.CalledProcessError as e:
        print(f"prune_caches: listing the caches failed: {e.stderr.strip()}", file=sys.stderr)
        return 0
    for key in keys:
        delete(key)
    print(f"prune_caches: deleted {len(keys)} superseded cache(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
