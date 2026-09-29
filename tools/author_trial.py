#!/usr/bin/env python3
"""Write-several-then-pick: an isolated author writes five candidate clues per
answer, a separate model picks one per answer, and the picks go to
tools/grade_clues.py like any other clue set.

  python3 tools/author_trial.py --out scratch/authoring-opus55-r3 \
      --base scratch/authoring-opus55-r2/control_clues.json

The author prompt is tools/author_trial_author.md, the selector prompt
tools/author_trial_select.md followed by tools/data/grading_rubric.md. Each
author run is a fresh `claude -p` with no tools, started in an empty directory,
so it sees one answer and the prompt and nothing else: no earlier clue for that
answer, published or ours. The selector sees the candidates with their parses.

A candidate is validated by swapping it into --base (a clue set for the same
fill that already passes) and running the build-time validator, so every error
belongs to the candidate. Failures go back to the author with the errors, up
to --repairs times; a candidate still failing is dropped, and the count is
printed. Every stage writes its output under --out and is skipped if that
output already parses, so a killed run resumes.

Writes <out>/author/<entry>.json, <out>/select.json and <out>/picks.json (the
chosen clues, in tools/grade_clues.py's --clues shape).
"""

import argparse
import concurrent.futures
import copy
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_authored_puzzle

ROOT = Path(__file__).resolve().parent.parent
AUTHOR_MD = ROOT / "tools/author_trial_author.md"
SELECT_MD = ROOT / "tools/author_trial_select.md"
RUBRIC = ROOT / "tools/data/grading_rubric.md"
FILL = ROOT / "tools/data/sample_fill_11.json"


def claude(prompt, model, effort, timeout=1800):
    """One fresh, tool-less `claude -p` in an empty directory; its stdout."""
    env = dict(os.environ)
    path = subprocess.run(["bash", "-c", ". tools/claude_path.sh; echo $PATH"], cwd=ROOT,
                          capture_output=True, text=True, check=False).stdout.strip()
    env["PATH"] = path or env.get("PATH", "")
    with tempfile.TemporaryDirectory() as cwd:
        r = subprocess.run(["claude", "-p", "--model", model, "--effort", effort,
                            "--tools", "", "--no-session-persistence"],
                           input=prompt, capture_output=True, text=True, cwd=cwd,
                           env=env, timeout=timeout, check=False)
    if r.returncode:
        raise RuntimeError(f"claude exited {r.returncode}: {r.stderr[-500:]}")
    return r.stdout


def parse_object(raw):
    """The JSON object in a model reply, fenced or not."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in reply: " + raw[:300].replace("\n", " "))
    return json.loads(m.group(0))


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def validate_set(clues):
    """Build-time validator ERRORs for a whole clue set on the sample fill."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(clues, f)
    try:
        puzzle = build_authored_puzzle.build(FILL, f.name, 999, "trial", "trial",
                                             datetime.date(2026, 1, 1))
        _, errors = build_authored_puzzle.finish(puzzle, "claude-opus-5-5")
    except SystemExit as err:            # build() exits on a mismatched answer
        errors = [str(err)]
    finally:
        os.unlink(f.name)
    return errors


def candidate_errors(base, entry, cand):
    trial = copy.deepcopy(base)
    trial[entry] = {"clue": cand.get("clue"), "annotation": cand.get("annotation")}
    try:
        return validate_set(trial)
    except (KeyError, TypeError, AttributeError, ValueError) as err:  # malformed: report it
        return [f"{type(err).__name__}: {err}"]


def author_one(entry, answer, enum, base, out, model, effort, repairs):
    path = out / "author" / f"{entry}.json"
    got = load_json(path)
    if got and got.get("final"):
        return entry, got
    head = AUTHOR_MD.read_text() + f"\n\nYour answer: entry {entry}, {answer} ({enum}).\n"
    reply = parse_object(claude(head, model, effort))
    history = []
    for attempt in range(repairs + 1):
        cands = reply.get("candidates") or []
        errs = {i: candidate_errors(base, entry, c) for i, c in enumerate(cands)}
        bad = {i: e for i, e in errs.items() if e}
        history.append({"reply": reply, "errors": {str(i): e for i, e in bad.items()}})
        if not bad or attempt == repairs:
            break
        fix = (head + "\nYou already wrote this:\n" + json.dumps(reply, indent=1)
               + "\n\nThe validator rejected these candidates (numbered from 0):\n"
               + "\n".join(f"{i}: " + "; ".join(e) for i, e in bad.items())
               + "\n\nReturn the whole object again. Fix each rejected candidate, or "
                 "replace it with a different decomposition. Keep the five distinct.\n")
        reply = parse_object(claude(fix, model, effort))
    good = [c for i, c in enumerate(cands) if not bad.get(i)]
    result = {"entry": entry, "answer": answer, "obviousSplit": reply.get("obviousSplit"),
              "final": good, "dropped": len(cands) - len(good), "history": history}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1) + "\n")
    return entry, result


def describe(n, cand, enum):
    a = cand["annotation"]
    defs = ", ".join(repr(d.get("text")) for d in a.get("definitions") or [])
    blocks = "; ".join(f"{b.get('clueFragment')!r} -> {b.get('gives')}"
                       for b in a.get("blocks") or [])
    walk = (a.get("explanation") or {}).get("walkthrough", "")
    return (f"  {n}. {cand['clue']['text']} ({enum})\n"
            f"     parse: {'+'.join(a.get('type') or [])}; definition {defs}; {blocks}. {walk}")


def select(authored, enums, out, model, effort):
    path = out / "select.json"
    got = load_json(path)
    if got:
        return got
    parts = [SELECT_MD.read_text(), RUBRIC.read_text(), "\nThe candidates:\n"]
    for entry, res in authored.items():
        parts.append(f"\nEntry {entry}, {res['answer']} ({enums[entry]}):")
        parts += [describe(i + 1, c, enums[entry]) for i, c in enumerate(res["final"])]
    prompt = "\n".join(parts) + "\n"
    (out / "select_prompt.txt").write_text(prompt)
    picks = parse_object(claude(prompt, model, effort))
    path.write_text(json.dumps(picks, indent=1) + "\n")
    return picks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", required=True,
                    help="a passing clue set for the same fill; candidates are swapped into it")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--author-effort", default="high")
    ap.add_argument("--select-effort", default="high")
    ap.add_argument("--repairs", type=int, default=2)
    ap.add_argument("--parallel", type=int, default=5)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = {k: v for k, v in json.loads(Path(args.base).read_text()).items()
            if not k.startswith("_")}
    if validate_set(base):
        sys.exit("--base does not pass the validator:\n  " + "\n  ".join(validate_set(base)))
    enums = {k: v["clue"]["enumeration"] for k, v in base.items()}
    answers = {k: v["annotation"]["answer"] for k, v in base.items()}
    (out / "run.txt").write_text(
        f"model={args.model} author_effort={args.author_effort} "
        f"select_effort={args.select_effort} repairs={args.repairs}\n")

    authored, failed = {}, []
    with concurrent.futures.ThreadPoolExecutor(args.parallel) as pool:
        futs = {pool.submit(author_one, e, answers[e], enums[e], base, out, args.model,
                            args.author_effort, args.repairs): e for e in base}
        for fut in concurrent.futures.as_completed(futs):
            e = futs[fut]
            try:
                _, res = fut.result()
                authored[e] = res
                print(f"{e} {res['answer']}: {len(res['final'])} valid, "
                      f"{res['dropped']} dropped", flush=True)
            except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as err:
                failed.append(e)
                print(f"{e}: author failed: {err}", flush=True)
    if failed or any(not r["final"] for r in authored.values()):
        sys.exit("no valid candidates for: " + ", ".join(
            sorted(failed + [e for e, r in authored.items() if not r["final"]])))

    authored = dict(sorted(authored.items()))
    picks = select(authored, enums, out, args.model, args.select_effort)
    chosen = {}
    for entry, res in authored.items():
        n = int(picks[entry]["pick"])
        chosen[entry] = res["final"][n - 1]
        print(f"{entry}: pick {n}/{len(res['final'])}  {chosen[entry]['clue']['text']}")
    errors = validate_set(chosen)
    (out / "picks.json").write_text(json.dumps(chosen, indent=1) + "\n")
    if errors:
        sys.exit("the picked set fails the validator:\n  " + "\n  ".join(errors))
    print(f"wrote {out / 'picks.json'}: {len(chosen)} clues, validator clean")


if __name__ == "__main__":
    main()
