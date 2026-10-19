#!/usr/bin/env python3
"""The commit the live site was last deployed from, read off GitHub.

    python3 tools/last_deploy.py OWNER/REPO            # prints the sha, exit 1 when there is none
    python3 tools/last_deploy.py OWNER/REPO --moved    # prints "yes" when master is ahead of it

pages.yml builds and deploys only when something other than puzzle files
changed, plus every 15 minutes (pages-schedule.yml) when master has moved since
the last deploy, so "what is live" is no longer "the last push's run". The
github-pages deployments say it directly: one call, and the newest one with a
success status is the live site (deploy-pages records the built commit as the
deployment's sha). A deployment still in flight, or a failed one, is skipped.

Needs a token with `deployments: read` (the workflows grant it) and, for
--moved, `contents: read`.
"""
import json
import subprocess
import sys


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(f"gh api {path}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def last_deployed(repo, look=8):
    """The sha of the newest github-pages deployment with a success status, or ''."""
    for dep in gh(f"repos/{repo}/deployments?environment=github-pages&per_page={look}"):
        statuses = gh(f"repos/{repo}/deployments/{dep['id']}/statuses?per_page=10")
        if any(s.get("state") == "success" for s in statuses):
            return dep["sha"]
    return ""


def master_head(repo):
    return gh(f"repos/{repo}/commits/master")["sha"]


def main(argv):
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--moved"):
        print(__doc__)
        return 2
    try:
        deployed = last_deployed(argv[0])
        if len(argv) == 2:
            print("yes" if deployed != master_head(argv[0]) else "no")
            return 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        print(f"last_deploy: {exc}", file=sys.stderr)
        return 1
    print(deployed)
    return 0 if deployed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
