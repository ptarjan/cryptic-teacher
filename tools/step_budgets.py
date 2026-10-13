#!/usr/bin/env python3
"""Hold every step of the deploy to a time budget, from one table.

  python3 tools/step_budgets.py check-run REPO RUN_ID [ATTEMPT]   # the last step of pages.yml's build job
  python3 tools/step_budgets.py lint [WORKFLOW TABLE]              # tools/test_step_budgets.sh

The deploy went from about five minutes to fourteen in under two weeks without
anyone choosing it: a serial corpus check that gained rules while the corpus
grew, and a per-file cache whose store lived in .git/ and so started empty on
every CI checkout. Each step was only a little slower than the day before, so
nobody saw it. tools/data/deploy_budgets.json gives each step a number, and:

  check-run  reads the run's step times off the jobs API and fails on a step
             over its budget or with no row, with a ::error annotation naming
             it. pages.yml runs it after the deploy, so the site still ships
             and the run goes red.
  lint       checks .github/workflows/pages.yml against the table: every step
             named and budgeted, no row for a step that is gone, and every step
             that runs a tool reading the whole corpus (CORPUS_MARKS in its
             source) marked "corpus" and saying how it avoids redoing
             unchanged work: "cache" (actions/cache steps earlier in the same
             job), "incremental" (how), or "uncached" (why it cannot).
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "tools" / "data" / "deploy_budgets.json"
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
#: What a tool that reads every puzzle file says in its source.
CORPUS_MARKS = ("puzzle_files(", "parallel.pmap(", "cached_map(", "--reindex", "og_list.py")
#: Steps the runner adds to every job, not the workflow's own.
RUNNER_STEPS = re.compile(r"^(Set up job|Complete job|Post .*)$")


def budgets(table=TABLE):
    return {k: v for k, v in json.loads(Path(table).read_text(encoding="utf-8")).items() if not k.startswith("_")}


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def check_run(repo, run_id, attempt="1"):
    table = budgets()
    out = subprocess.run(["gh", "api", "--paginate", "--jq", ".jobs[] | tojson",
                          f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"],
                         capture_output=True, text=True, check=True).stdout
    jobs = [json.loads(line) for line in out.splitlines() if line.strip()]
    rows, bad = [], []
    for job in jobs:
        if job["name"] == "budgets":
            continue        # the old budgets job (runs before it was folded into build)
        for step in job.get("steps") or ():
            if RUNNER_STEPS.match(step["name"]) or step.get("conclusion") in (None, "skipped"):
                continue
            if not (step.get("started_at") and step.get("completed_at")):
                continue
            key = f"{job['name']}/{step['name']}"
            took = round((_t(step["completed_at"]) - _t(step["started_at"])).total_seconds())
            row = table.get(key)
            if row is None:
                bad.append(f"{key} took {took}s and has no budget: add its row to tools/data/deploy_budgets.json")
                rows.append((key, took, None))
                continue
            rows.append((key, took, row["seconds"]))
            if took > row["seconds"]:
                bad.append(f"{key} took {took}s, over its {row['seconds']}s budget "
                           "(tools/data/deploy_budgets.json): find what made it slower")
    summary = ["| step | seconds | budget |", "|---|---:|---:|"]
    summary += [f"| {k} | {t} | {b if b is not None else 'none'}{' **over**' if b is None or t > b else ''} |"
                for k, t, b in rows]
    print("\n".join(summary))
    try:
        import os
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## Step budgets\n\n" + "\n".join(summary) + "\n")
    except (KeyError, OSError):
        pass
    for b in bad:
        print(f"::error title=Step over budget::{b}")
    return 1 if bad else 0


def workflow_steps(text):
    """[(job, step name or None, the step's own lines)] from pages.yml, read
    by indentation: jobs at two spaces, steps as `      - ` items."""
    steps, job, in_jobs, cur = [], None, False, None
    for line in text.splitlines():
        if line.startswith("jobs:"):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            job, cur = m.group(1), None
            continue
        if line.startswith("      - "):
            cur = [job, None, []]
            steps.append(cur)
        elif cur is not None and line.strip() and not line.startswith("        "):
            if not line.startswith("      #"):
                cur = None
        if cur is not None and not line.lstrip().startswith("#"):
            cur[2].append(line)
            n = re.match(r"^      (?:- |  )name:\s*(.+?)\s*$", line)
            if n:
                cur[1] = n.group(1).strip("\"'")
    return [(j, n, "\n".join(ls)) for j, n, ls in steps]


def reads_corpus(step_text):
    """Whether the step runs a tool of this repo whose source carries a CORPUS_MARK."""
    seen, todo = set(), re.findall(r"tools/[\w/]+\.(?:py|sh)", step_text)
    while todo:
        rel = todo.pop()
        if rel in seen or rel == "tools/step_budgets.py" or not (ROOT / rel).is_file():
            continue
        seen.add(rel)
        src = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        src = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        if any(m in src for m in CORPUS_MARKS):
            return True
        if rel.endswith(".sh"):
            todo += re.findall(r"tools/[\w/]+\.(?:py|sh)", src)
    return False


def lint(workflow=WORKFLOW, table=TABLE):
    table, errors = budgets(table), []
    steps = workflow_steps(Path(workflow).read_text(encoding="utf-8"))
    names = {}
    for at, (job, name, text) in enumerate(steps):
        if name is None:
            errors.append(f"a step of job {job} has no name: name it, and give it a budget row\n{text}")
            continue
        key = f"{job}/{name}"
        if key in names:
            errors.append(f"{key}: two steps share the name, so they share one budget")
        names[key] = text
        row = table.get(key)
        if row is None:
            errors.append(f"{key}: no row in tools/data/deploy_budgets.json")
            continue
        if not isinstance(row.get("seconds"), int) or row["seconds"] <= 0:
            errors.append(f"{key}: its budget needs whole seconds above 0")
        if reads_corpus(text) and not row.get("corpus"):
            errors.append(f"{key} runs a tool that reads the whole corpus: mark its row \"corpus\": true "
                          "and say how it skips unchanged puzzles")
        if row.get("corpus"):
            how = [k for k in ("cache", "incremental", "uncached") if row.get(k)]
            if not how:
                errors.append(f"{key} reads the whole corpus: its row needs \"cache\" (the actions/cache "
                              "steps it restores), \"incremental\" (how), or \"uncached\" (why it cannot be)")
        earlier = [n for j, n, t in steps[:at] if j == job and "actions/cache" in t]
        for c in row.get("cache") or ():
            if c not in earlier:
                errors.append(f"{key} names cache step {c!r}, which is not an actions/cache step "
                              f"earlier in job {job}")
    for key in table:
        if key not in names:
            errors.append(f"{key}: a budget row for a step pages.yml does not have")
    for e in errors:
        print(f"FAIL {e}")
    return 1 if errors else 0


def main(argv):
    if argv[:1] == ["check-run"] and len(argv) in (3, 4):
        return check_run(*argv[1:])
    if argv[:1] == ["lint"] and len(argv) in (1, 3):
        return lint(*argv[1:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
