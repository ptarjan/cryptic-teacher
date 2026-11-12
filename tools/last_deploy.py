#!/usr/bin/env python3
"""The commit the live site was last deployed from, read off GitHub.

    python3 tools/last_deploy.py OWNER/REPO            # prints the sha, exit 1 when there is none
    python3 tools/last_deploy.py OWNER/REPO --moved    # prints "yes" when master is ahead of it

pages.yml builds and deploys only when something other than puzzle files
changed, plus every 15 minutes (its own schedule) when master has moved since
the last deploy, so "what is live" is no longer "the last push's run". The
github-pages deployments say it directly: one call, and the newest one with a
success status is the live site (deploy-pages records the built commit as the
deployment's sha). A deployment still in flight, or a failed one, is skipped. A failure after the
deploy step flips the deployment too, so deployed_by_run (the Deploy to Pages
step's own conclusion) is asked first and the deployments are the fallback.

Needs a token with `deployments: read` (the workflows grant it) and, for
--moved, `contents: read`.
"""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(f"gh api {path}: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def last_deployed(repo, look=60):
    """The sha of the newest github-pages deployment with a success status, or ''.

    Deploy-pages makes a deployment for every build that reaches its step,
    including the ones a busier build then cancels, so a burst of pushes puts
    a dozen without a success ahead of the live one (8 were not enough, run
    39271238600): one status call each until the first success."""
    deps = gh(f"repos/{repo}/deployments?environment=github-pages&per_page={look}")

    def succeeded(dep):
        return any(s.get("state") == "success"
                   for s in gh(f"repos/{repo}/deployments/{dep['id']}/statuses?per_page=10"))

    # All the status calls at once (a serial walk of 40 was ~50s), newest first.
    with ThreadPoolExecutor(max_workers=16) as pool:
        for dep, ok in zip(deps, pool.map(succeeded, deps)):
            if ok:
                return dep["sha"]
    return ""


def deployed_by_run(repo, look=30):
    """The head_sha of the newest pages.yml run whose Deploy to Pages step
    succeeded, or ''. A job failing after that step (a blown step budget, run
    43235745415) leaves the deployment marked failed though the site is live,
    so the deployment list alone names an older commit; the step's own
    conclusion is the truth."""
    runs = gh(f"repos/{repo}/actions/workflows/pages.yml/runs?per_page={look}&exclude_pull_requests=true")
    runs = runs.get("workflow_runs", [])

    def live(run):
        jobs = gh(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100").get("jobs", [])
        return any(st["name"] in ("Deploy to Pages", "Deploy to Pages (retry)")
                   and st.get("conclusion") == "success"
                   for job in jobs for st in job.get("steps") or ())

    with ThreadPoolExecutor(max_workers=16) as pool:
        for run, ok in zip(runs, pool.map(live, runs)):
            if ok:
                return run["head_sha"]
    return ""


def master_head(repo):
    return gh(f"repos/{repo}/commits/master")["sha"]


def main(argv):
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--moved"):
        print(__doc__)
        return 2
    try:
        deployed = deployed_by_run(argv[0]) or last_deployed(argv[0])
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
