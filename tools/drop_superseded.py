#!/usr/bin/env python3
"""Cancel a pages.yml push run whose build job was replaced by a newer run's.

    python3 tools/drop_superseded.py REPO RUN_ID ATTEMPT [--watch]

The build job is in the "pages" concurrency group, where a newer run's pending
build replaces an older pending one, which is cancelled without ever starting.
The older run then has no site, and its deploy ships only its own run's site
(tools/wait_for_build.py), so nothing it still has to do can be used: its
annotate shards would check a commit that will never go live, its requeue
would file drift the newer run's own full check files too, and both hold
runners tests.yml is waiting for. So the run is cancelled as soon as its build
is seen to be dropped.

Only a push run. A push run's full check is chosen by validate_scope.py from
the diff against the live commit, and the newer run diffs against the same
commit (or a later one that a full check deployed), so it chooses the full
check again and nothing is lost. The nightly tick and a manual run ask for the
full check outright, and no other run repeats it, so they run to the end
whatever happened to their build.

Without --watch: one look, and the cancel if the build was dropped. With
--watch: a look every WATCH_SECONDS until the build has started (a running
build is never replaced) or the run is cancelled. Either way it exits 0: a
failure to look or to cancel leaves the run as it was, which is correct, only
slower.
"""
import os
import subprocess
import sys
import time

from wait_for_build import run_jobs

#: How often --watch looks. Each look is one jobs API call per annotate shard
#: watching, against the repository's GITHUB_TOKEN rate limit.
WATCH_SECONDS = 30


def build_job(jobs):
    return next((j for j in jobs if j.get("name") == "build"), None)


def dropped(jobs):
    """True when the run's build job was cancelled before a runner took it:
    replaced in the "pages" group (or the run cancelled while it waited). A
    build cancelled after it started (its 90-minute cap) is a broken build,
    whose run's checks still say something, so it does not count."""
    build = build_job(jobs)
    return bool(build and build.get("status") == "completed" and build.get("conclusion") == "cancelled"
                and not build.get("steps"))


def settled(jobs):
    """True when the build can no longer be replaced: it has ended, or a
    runner has taken it (a concurrency group only replaces pending jobs). The
    jobs API lists a job's steps only once a runner has it; a job waiting in
    its group has none, and a started_at already set, so that is no sign."""
    build = build_job(jobs)
    return bool(build and (build.get("status") == "completed" or build.get("steps")))


def applies():
    """Only push runs are dropped (see the module doc). GITHUB_EVENT_NAME is
    the runner's own record of what started the run."""
    return os.environ.get("GITHUB_EVENT_NAME") == "push"


def cancel(repo, run_id):
    print(f"::notice title=Superseded::this run's build was replaced by a newer run's before it started, "
          f"so nothing this run still does can deploy; cancelling run {run_id}", flush=True)
    done = subprocess.run(["gh", "run", "cancel", str(run_id), "--repo", repo], capture_output=True, text=True)
    if done.returncode:
        print(f"gh run cancel failed: {done.stderr.strip() or done.stdout.strip()}; the run goes on", flush=True)


def look(repo, run_id, attempt):
    """Cancel the run if its build was dropped. True when there is nothing
    more to watch for."""
    try:
        jobs = run_jobs(repo, run_id, attempt)
    except (subprocess.CalledProcessError, ValueError) as err:  # a blip of the API
        print(f"jobs API: {err!r}; looking again later", flush=True)
        return False
    if dropped(jobs):
        cancel(repo, run_id)
        return True
    return settled(jobs)


def main(argv):
    watch = "--watch" in argv
    args = [a for a in argv if a != "--watch"]
    repo, run_id = args[0], args[1]
    attempt = args[2] if len(args) > 2 else "1"
    if not applies():
        return 0
    while not look(repo, run_id, attempt) and watch:
        time.sleep(WATCH_SECONDS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
