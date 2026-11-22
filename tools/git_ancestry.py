#!/usr/bin/env python3
"""`git merge-base --is-ancestor` without the full-history walk when the answer is
visibly "no". A commit committed more than a day after another cannot be its ancestor,
yet git walks every reachable commit to prove it. Callers whose question can be
"newer commit vs older commit" go through is_ancestor() here; the shortcut needs one
cheap `git show` and falls back to the real check whenever the dates are close or unknown."""
import subprocess

SKEW = 86400  # seconds: committer clocks drift, so only a clear gap decides


def _times(cwd, a, b):
    r = subprocess.run(["git", "-C", str(cwd), "show", "-s", "--format=%ct", a, b],
                       capture_output=True, text=True, check=False)
    if r.returncode:
        return None
    try:
        ta, tb = (int(x) for x in r.stdout.split())
    except ValueError:
        return None
    return ta, tb


def newer_than_by_a_day(cwd, a, b):
    """True when commit `a` was committed over a day after commit `b`, so `a` is no ancestor of `b`."""
    t = _times(cwd, a, b)
    return bool(t) and t[0] - t[1] > SKEW


def is_ancestor(cwd, a, b):
    """Whether commit `a` is an ancestor of (or equal to) commit `b`."""
    if newer_than_by_a_day(cwd, a, b):
        return False
    return subprocess.run(["git", "-C", str(cwd), "merge-base", "--is-ancestor", a, b],
                          capture_output=True, check=False).returncode == 0
