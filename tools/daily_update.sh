#!/bin/bash
# Daily updater for Cryptic Teacher — designed for a cron job on the Mac mini.
#
# What it does:
#   1. Fetches the newest Guardian cryptic if we don't have it yet.
#   2. Asks Claude Code (headless) to annotate the oldest un-annotated puzzle,
#      following tools/annotate_prompt.md — one puzzle per run, so a backlog
#      drains gradually without burning tokens in a single run.
#   3. Validates, reindexes, and commits (and pushes, if a remote is set up).
#
# Install (do this manually — nothing installs itself):
#   crontab -e
#   15 6 * * *  /Users/pt/github/cryptic-teacher/tools/daily_update.sh >> /Users/pt/github/cryptic-teacher/.update.log 2>&1
#
# Requirements: python3, git, and the `claude` CLI on PATH for the annotation step.

set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

echo "=== cryptic-teacher update $(date '+%Y-%m-%d %H:%M') ==="

# --- 1. fetch the latest puzzle (exit 3 = nothing new, which is fine) ---
python3 tools/fetch_puzzle.py --latest
fetch_rc=$?
if [ $fetch_rc -ne 0 ] && [ $fetch_rc -ne 3 ]; then
  echo "fetch failed (rc=$fetch_rc); continuing to annotation of any backlog"
fi

# --- 2. annotate the oldest un-annotated puzzle, if any and if claude exists ---
pending=$(python3 - <<'EOF'
import json
idx = json.load(open("puzzles/index.json"))
todo = sorted((p["number"] for p in idx["puzzles"]
               if not p["annotated"] and p.get("hasSolutions")), )
print(todo[0] if todo else "")
EOF
)

if [ -n "$pending" ]; then
  if command -v claude >/dev/null 2>&1; then
    echo "annotating puzzle $pending with Claude Code..."
    claude -p "Annotate Guardian cryptic No $pending in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Do not commit — the calling script commits." \
      --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
      --max-turns 80 || echo "claude annotation run failed; will retry next run"
  else
    echo "claude CLI not found; skipping annotation of $pending"
  fi
fi

# --- 3. validate, reindex, commit ---
python3 tools/fetch_puzzle.py --reindex
if ! python3 tools/validate_annotations.py; then
  echo "VALIDATION FAILED — reverting today's puzzle-file changes"
  git checkout -- puzzles/
  exit 1
fi

# Re-stamp index.html so phones don't serve yesterday's cached assets.
python3 tools/stamp_assets.py

if [ -n "$(git status --porcelain)" ]; then
  git add puzzles/ index.html
  git commit -m "$(printf 'Daily update: fetch latest cryptic / annotate backlog\n\nCo-Authored-By: Claude Fable 5 <noreply@anthropic.com>')"
  # Push only if a remote exists (GitHub Pages picks it up from master).
  git remote get-url origin >/dev/null 2>&1 && git push origin HEAD || true
else
  echo "nothing to commit"
fi
echo "=== done ==="
