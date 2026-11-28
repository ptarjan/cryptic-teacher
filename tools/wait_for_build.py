#!/usr/bin/env python3
"""Wait for pages.yml's build job to have its site uploaded and checked, and
for the run's annotation check to have passed.

    python3 tools/wait_for_build.py REPO RUN_ID [ATTEMPT [MODE]]

Writes ready=true to $GITHUB_OUTPUT once the build job's READY_STEP has
succeeded (the site is uploaded and its checks passed) and, when MODE (the
validate job's `mode` output) is "full", every annotate shard has succeeded.
The requeue job (which pushes the allowance raises the shards flagged) is not
waited for: it needs the shards and runs after them, and the site's content
does not depend on it, so it stays off the path to the live site. Writes
ready=false when the build job ended without getting there or a shard
failed, and exits 0 either way: the failure is the run's red, and the
deploy job only decides whether to ship. The deploy job starts when validate
has passed, long before the shards and the build are done, so this is where
it waits for them. A push run whose build a newer run replaced is cancelled
from here (tools/drop_superseded.py), so its shards still queued for runners
never take one.
"""
import json
import os
import subprocess
import sys
import time

#: The last build step the deployed site depends on.
READY_STEP = "Keep the IndexNow list"
POLL_SECONDS = 2
#: The annotate matrix's size in pages.yml.
SHARDS = 12


def run_jobs(repo, run_id, attempt):
    out = subprocess.run(["gh", "api", "--paginate", "--jq", ".jobs[] | tojson",
                          f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"],
                         capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


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


def check_verdict(jobs, mode):
    """True (the annotation check passed), False (it failed), None (still going)
    for the run's jobs. Only a full check has shards. All of them exist once
    validate has passed, but a missing one counts as still going, not as
    passed."""
    if mode != "full":
        return True
    shards = [j for j in jobs if j.get("name", "").startswith("annotate")]
    if any(j.get("status") == "completed" and j.get("conclusion") != "success" for j in shards):
        return False
    done = [j for j in shards if j.get("status") == "completed"]
    return True if len(done) >= SHARDS else None


def verdict_of(jobs, mode):
    """True (ship), False (never will), None (still going)."""
    build = next((j for j in jobs if j.get("name") == "build"), None)
    got, checked = verdict(build), check_verdict(jobs, mode)
    if got is False or checked is False:
        return False
    if got and checked:
        return True
    return None


def main(argv):
    repo, run_id = argv[0], argv[1]
    attempt = argv[2] if len(argv) > 2 else "1"
    mode = argv[3] if len(argv) > 3 else "files"
    import drop_superseded  # it imports run_jobs from here
    while True:
        try:
            jobs = run_jobs(repo, run_id, attempt)
            got = verdict_of(jobs, mode)
        except (subprocess.CalledProcessError, ValueError) as err:  # a blip of the API
            print(f"jobs API: {err!r}; trying again")
            got = None
        if got is False and drop_superseded.applies() and drop_superseded.dropped(jobs):
            # A newer run replaced the build: its queued shards and requeue go too.
            drop_superseded.cancel(repo, run_id)
        if got is not None:
            break
        time.sleep(POLL_SECONDS)
    print(f"the build's site is {'ready' if got else 'not coming: the build job ended without it or the check failed'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"ready={'true' if got else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
