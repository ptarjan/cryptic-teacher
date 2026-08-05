#!/bin/bash
# Burn the tail of the weekly usage window on backfills, just before it resets.
#
# Why this exists, separately from daily_update.sh: unspent quota does not roll
# over. The weekly window resets around 05:00 and whatever is left at 04:59 is
# simply gone. daily_update.sh deliberately refuses to annotate above
# ANNOTATE_MAX_WEEKLY_PCT (50%) because a crossword backlog is never worth being
# rate-limited for real work — but that reasoning stops applying in the last
# hour of the window, when there is no real work left to protect. So this job
# runs with NO usage gate at all, on purpose, and only in that hour.
#
# Paul, 2026-08-02: "right before my weekly inference resets you should spend
# whatever is left on backfills."
#
# What it backfills, in priority order:
#   1. Un-annotated puzzles, QUIPTICS FIRST. The quiptic is the Guardian's
#      beginner crossword and the reason we started fetching it at all; an
#      un-annotated one teaches nothing and shows no difficulty band, so it is
#      the least useful thing on the site and the most valuable to fix.
#   2. definitionFit — the one-sentence "why does the answer mean the
#      definition" that every annotation is supposed to carry. Until the
#      backlog is zero, tools/validate_annotations.py can only warn about it
#      instead of requiring it.
#
# It stops on the FIRST failed claude run rather than retrying. Out here that
# almost always means the window is finally exhausted, which is exactly the
# state this job is trying to reach; hammering it after that just produces a
# log full of identical errors.
#
# Install: LaunchAgent ~/Library/LaunchAgents/com.pt.cryptic-teacher-prereset.plist,
# NOT crontab — same reason as daily_update.sh. The `claude` CLI keeps its OAuth
# credentials in the *login* keychain, which cron cannot unlock.
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.pt.cryptic-teacher-prereset.plist
#   launchctl kickstart -k gui/$(id -u)/com.pt.cryptic-teacher-prereset   # run it now

set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="$HOME/.local/bin:$HOME/.claude/local:/usr/local/bin:/opt/homebrew/bin:$PATH"

# Hard stop before the window turns over. Past this point we would be spending
# the NEW week's quota on a backlog, which is the opposite of the point — the
# 06:15 daily job will pick the backlog up again under its normal 50% gate.
DEADLINE="${DEADLINE:-04:55}"
MODEL="${ANNOTATE_MODEL:-fable}"

echo "=== cryptic-teacher pre-reset backfill $(date '+%Y-%m-%d %H:%M') (deadline $DEADLINE) ==="

# String comparison is fine for HH:MM, but only while the clock is still on the
# same side of midnight as the deadline. Started after it (someone kickstarting
# the job by hand at 11am to see what it does) every check would fire instantly
# and the run would silently do nothing — so in that case there is no deadline
# at all, and a manual run just works.
STARTED_LATE=0
[ "$(date '+%H:%M')" \> "$DEADLINE" ] && STARTED_LATE=1
past_deadline() {
  [ "$STARTED_LATE" = 0 ] && [ "$(date '+%H:%M')" \> "$DEADLINE" ]
}

# Run one claude task against the repo. Returns non-zero if the run failed,
# which the callers treat as "the window is gone, stop".
run_claude() {
  claude -p "$1" \
    --model "$MODEL" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
    --max-turns 80
}

# Commit whatever a task produced, but only if the tree still validates. A run
# that ran out of room mid-file leaves a half-written annotation behind, and
# committing that would publish a broken puzzle page at 06:15.
commit_puzzle() {
  local num="$1" what="$2"
  if ! python3 tools/validate_annotations.py >/tmp/ct-prereset-validate.txt 2>&1; then
    echo "VALIDATION FAILED after $what $num — discarding that puzzle's changes"
    tail -5 /tmp/ct-prereset-validate.txt
    git checkout -- "puzzles/$num.js" 2>/dev/null
    return 1
  fi
  if [ -n "$(git status --porcelain -- "puzzles/$num.js")" ]; then
    # By pathspec, never `git add .`: the nightly job and any interactive
    # session share this checkout, and a bare commit swallows their staged work.
    git add "puzzles/$num.js"
    git commit -q -m "$what $num" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
    git pull --rebase -q && git push -q origin HEAD || {
      git pull --rebase -q && git push -q origin HEAD || echo "push failed for $num; left committed locally"
    }
    echo "committed $what $num"
  else
    echo "$what $num produced no change"
  fi
  return 0
}

if ! command -v claude >/dev/null 2>&1; then
  echo "ERROR: claude CLI not on PATH ($PATH) — nothing to do."
  exit 1
fi

python3 tools/fetch_puzzle.py --reindex >/dev/null

# --- 1. un-annotated puzzles, quiptics first ---------------------------------
todo=$(python3 - <<'EOF'
import json
idx = json.load(open("puzzles/index.json"))
todo = [p for p in idx["puzzles"] if not p["annotated"] and p.get("hasSolutions")]
# Gentler series first — quiptic and everyman ahead of the daily cryptic, since
# the beginner puzzles are the ones worth having hints on — then newest-first
# within each series so today's puzzle is never last in the queue.
todo.sort(key=lambda p: (p.get("series", "cryptic") == "cryptic", -p["number"]))
print(" ".join(str(p["number"]) for p in todo))
EOF
)
echo "un-annotated backlog: ${todo:-none}"

for num in $todo; do
  if past_deadline; then echo "past $DEADLINE — stopping"; break; fi
  echo "--- annotating $num ---"
  run_claude "Annotate Guardian crossword No $num in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Every clue needs a definitionFit. Do not commit — the calling script commits." || {
    echo "annotation run for $num failed (window exhausted?) — stopping here"
    git checkout -- "puzzles/$num.js" 2>/dev/null
    break
  }
  commit_puzzle "$num" "Annotate" || break
done

# --- 2. definitionFit backfill ------------------------------------------------
# Additive only: these puzzles are already annotated and their hints are fine,
# they just predate the field. Anything that rewrites an existing hint here is a
# bug, not an improvement.
fits=$(python3 - <<'EOF'
import json, glob
J1, J2 = "/*JSON-START*/", "/*JSON-END*/"
out = []
for path in sorted(glob.glob("puzzles/[0-9]*.js")):
    t = open(path, encoding="utf-8").read()
    puz = json.loads(t.split(J1, 1)[1].rsplit(J2, 1)[0])
    missing = sum(1 for e in puz["entries"]
                  if (e.get("annotation") or {}).get("type")
                  and not (e.get("annotation") or {}).get("definitionFit"))
    if missing:
        out.append((missing, puz["number"]))
# Smallest backlog first: with an unknown amount of quota left, finishing four
# puzzles beats getting most of the way through one.
out.sort()
print(" ".join(str(n) for _, n in out))
EOF
)
echo "definitionFit backlog: ${fits:-none}"

for num in $fits; do
  if past_deadline; then echo "past $DEADLINE — stopping"; break; fi
  echo "--- definitionFit $num ---"
  run_claude "In this repo, add the missing \`definitionFit\` field to every annotated clue in puzzles/$num.js that lacks one. definitionFit is ONE sentence saying why the answer means the definition; it renders last in the walkthrough. Read tools/annotate_prompt.md and STYLE.md for the voice, and read the existing definitionFit sentences in puzzles/30039.js first so yours match. This is ADDITIVE: change nothing else, do not rewrite existing hints, types, indicators or pieces. Run python3 tools/validate_annotations.py until it passes. Do not commit — the calling script commits." || {
    echo "definitionFit run for $num failed (window exhausted?) — stopping here"
    git checkout -- "puzzles/$num.js" 2>/dev/null
    break
  }
  commit_puzzle "$num" "Backfill definitionFit for" || break
done

# --- 3. republish -------------------------------------------------------------
# Unconditionally, even if nothing was annotated: this is cheap, deterministic
# and idempotent, and running it always means a run that landed one puzzle and a
# run that landed none leave the tree in the same shape. The index, the static
# pages and the ?v= stamps have to move together, and the smoke test is the last
# word on whether the app still boots against what we just wrote.
python3 tools/fetch_puzzle.py --reindex
python3 tools/build_seo_pages.py
python3 tools/stamp_assets.py
if command -v node >/dev/null 2>&1; then
  node tools/smoke_test.js
  smoke_rc=$?
  [ $smoke_rc -ne 0 ] && [ $smoke_rc -ne 2 ] && echo "WARNING: smoke test failed (rc=$smoke_rc)"
fi
if [ -n "$(git status --porcelain)" ]; then
  git add puzzles/ index.html learn/ sitemap.xml
  git commit -q -m "$(printf 'Republish after pre-reset backfill\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>')"
  git pull --rebase -q && git push -q origin HEAD || echo "republish push failed; committed locally"
fi

# The definitionFit rollout finishes itself: the moment the backlog is empty the
# field stops being advisory. Left as a printed instruction rather than a sed,
# because flipping a validator flag unattended at 4am is how a job starts
# failing every night with nobody watching.
python3 tools/validate_annotations.py 2>&1 | grep -i "definitionFit backlog" || true

echo "=== done $(date '+%H:%M') ==="
