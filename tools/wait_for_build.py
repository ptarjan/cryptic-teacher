#!/usr/bin/env python3
"""Wait for pages.yml's build job to have its site uploaded and checked.

    python3 tools/wait_for_build.py REPO RUN_ID [ATTEMPT]

Writes ready=true to $GITHUB_OUTPUT once the build job's READY_STEP has
succeeded (the site is uploaded and its checks passed), ready=false when the
build job ended without getting there, and exits 0 either way: the build's own
failure is the run's red, and the deploy job only decides whether to ship.
"""
import json
import os
import subprocess
import sys
import time

#: The last build step the deployed site depends on.
READY_STEP = "Keep the IndexNow list"
POLL_SECONDS = 5


def build_job(repo, run_id, attempt):
    out = subprocess.run(["gh", "api", "--paginate", "--jq", ".jobs[] | tojson",
                          f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"],
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        job = json.loads(line) if line.strip() else {}
        if job.get("name") == "build":
            return job
    return None


def verdict(job):
    """True (ship), False (never will), None (still going) for a build job as
    the jobs API shows it."""
    if job is None:
        return None
    for step in job.get("steps") or ():
        if step.get("name") == READY_STEP and step.get("conclusion") == "success":
            return True
    if job.get("status") == "completed":
        return False
    return None


def main(argv):
    repo, run_id = argv[0], argv[1]
    attempt = argv[2] if len(argv) > 2 else "1"
    while True:
        try:
            got = verdict(build_job(repo, run_id, attempt))
        except (subprocess.CalledProcessError, ValueError) as err:  # a blip of the API
            print(f"jobs API: {err!r}; trying again")
            got = None
        if got is not None:
            break
        time.sleep(POLL_SECONDS)
    print(f"the build's site is {'ready' if got else 'not coming: the build job ended without it'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"ready={'true' if got else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
