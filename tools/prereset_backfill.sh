#!/bin/bash
# Burn the tail of the weekly usage window on backfills, just before it resets.
#
# Why this exists, separately from daily_update.sh: unspent quota does not roll
# over. Whatever is left when the weekly window turns over is simply gone.
# daily_update.sh deliberately refuses to annotate above ANNOTATE_MAX_WEEKLY_PCT
# (50%) because a crossword backlog is never worth being rate-limited for real
# work — but that reasoning stops applying in the last hour of the window, when
# there is no real work left to protect. So this job runs with NO usage gate at
# all, on purpose, and ONLY in that hour.
#
# "Only in that hour" is load-bearing and was wrong for its first week: the job
# is fired hourly and almost always exits immediately, because whether this is
# the hour is decided by asking the usage API when the window resets, not by the
# time on the clock. See the check below.
#
# Paul, 2026-08-02: "right before my weekly inference resets you should spend
# whatever is left on backfills."
#
# What it backfills, in priority order:
#   1. Un-annotated puzzles, QUIPTICS FIRST. The quiptic is the Guardian's
#      beginner crossword and the reason we started fetching it at all; an
#      un-annotated one teaches nothing and shows no difficulty band, so it is
#      the least useful thing on the site and the most valuable to fix.
#   2. Every field in tools/annotation_backlog.json — definitionFit, the
#      one-sentence "why does the answer mean the definition", and
#      indicatorNotes, "why is THAT word the indicator". New puzzles are
#      required to carry these; the file is the list of puzzles annotated
#      before each rule existed, and draining one tightens the rule on it
#      forever. The fields are read from the file, so this job needs no edit
#      when the next rule lands.
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
# Without this the CLI reads the legacy un-suffixed keychain entry, which a
# file-based /login emptied on 2026-07-31, and every run dies on "Failed to
# authenticate: OAuth session expired and could not be refreshed". See the longer
# note in daily_update.sh.
export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
. "$REPO/tools/alert.sh"

# Kept in step with daily_update.sh — Opus since 2026-08-09, benchmarked against
# Fable on 30078 (STYLE.md). Matching quality at a third the cost matters more
# here than anywhere: this script exists to burn the tail of the weekly window,
# so a cheaper annotator is straightforwardly more puzzles per reset.
ANNOTATE_MODEL="${ANNOTATE_MODEL:-opus}"
. "$REPO/tools/annotate_model.sh"
MODEL="$ANNOTATE_MODEL"
# How close to the reset counts as "the last hour of the week", and how long a
# forced manual run is allowed to spend.
WINDOW_HOURS="${WINDOW_HOURS:-2}"
FORCE_HOURS="${FORCE_HOURS:-1}"

echo "=== cryptic-teacher pre-reset backfill $(date '+%Y-%m-%d %H:%M') ==="

# THE WHOLE JOB HANGS ON THIS CHECK. Everything below runs with no usage gate
# whatsoever, which is only defensible in the hour before quota that cannot roll
# over evaporates. The first version decided it was that hour by looking at the
# clock — 04:00 to 04:55, hard-coded — and was scheduled daily, so an ungated
# hour of inference ran SEVEN nights a week instead of one. That is what carried
# the week to 68% by Friday and left the 06:15 job crashing into rate limits it
# had itself created, while the log cheerfully said "past 04:55 — stopping" as
# though the design were working.
#
# The reset is not a time of day to be guessed at. It is a timestamp the usage
# API hands over on request, it moves with daylight saving and with whatever
# Anthropic does to the account, and a fitted constant standing in for a
# queryable fact is always the wrong model. So: ask, and if the answer is "not
# yet", exit having spent nothing. This job is now a poll, not an appointment —
# see the plist, which fires it hourly precisely because the answer moves.
#
# Exit 3 means the answer is derived rather than read: the API had turned the
# window over without re-stamping it, so the number is one window length past
# the reset we last saw. That is trustworthy in exactly one direction. It can
# say "not the pre-reset hour" — the window just started, so of course it isn't
# — and it must never say "spend", because spending an ungated hour on an
# inferred reset time is the hard-coded 04:00 all over again, aimed at a guess.
resets_in=$(python3 tools/weekly_usage.py --resets-in)
resets_rc=$?
if [ -z "$resets_in" ]; then
  alert "pre-reset backfill can't read when the weekly window resets, so it can't tell whether this is the hour to spend the remainder. Skipped — see .prereset.log. Nothing is being backfilled until this reads again."
  exit 1
fi
if [ "$resets_rc" = 3 ] && awk "BEGIN{exit !($resets_in <= $WINDOW_HOURS)}"; then
  alert "pre-reset backfill thinks the weekly window resets in ${resets_in}h, but that is inferred from a reset the API stopped reporting rather than read from it — and it will not spend an ungated hour of inference on a guess. Skipped; see .prereset.log."
  exit 1
fi

if [ "${FORCE:-0}" = 1 ]; then
  echo "FORCE=1 — ignoring the ${resets_in}h until reset, capped at ${FORCE_HOURS}h"
  budget_hours="$FORCE_HOURS"
elif awk "BEGIN{exit !($resets_in > $WINDOW_HOURS)}"; then
  echo "weekly window resets in ${resets_in}h (more than ${WINDOW_HOURS}h away)"
  echo "not the pre-reset hour — nothing spent. Set FORCE=1 to override."
  exit 0
else
  echo "weekly window resets in ${resets_in}h — spending the remainder"
  budget_hours="$resets_in"
fi

# Stop five minutes short of the turnover: past it we would be spending the NEW
# week's quota on a backlog, which is the opposite of the point. Computed as an
# epoch second rather than compared as an "HH:MM" string, which used to need a
# special case for runs that started after midnight-ish and got it subtly wrong.
STOP_AT=$(python3 -c "import sys,time; print(int(time.time() + float(sys.argv[1])*3600 - 300))" "$budget_hours")
echo "deadline $(date -r "$STOP_AT" '+%H:%M')"
past_deadline() {
  [ "$(date +%s)" -ge "$STOP_AT" ]
}

# Run one claude task against the repo. Returns non-zero if the run failed,
# which the callers treat as "the window is gone, stop".
run_claude() {
  claude -p "$1" \
    --model "$MODEL" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
    --max-turns 80 2>&1 | tee /tmp/ct-prereset-claude.txt
  local rc=${PIPESTATUS[0]}
  # Running out of window is how this job is SUPPOSED to end, so a plain failure
  # stays quiet. A broken login is a different animal: it fails identically, at
  # the same point, every night, and it hid there for seven days (2026-07-31 to
  # 2026-08-06) precisely because it looked like the normal ending.
  if [ $rc -ne 0 ] && grep -qi "Failed to authenticate\|Not logged in" /tmp/ct-prereset-claude.txt; then
    alert "pre-reset backfill cannot authenticate — the CLI needs a fresh /login. Nothing has been backfilled since this started."
  fi
  return $rc
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
    git commit -q -m "$what $num" -m "$ANNOTATE_TRAILER"
    # --autostash, because the tree is never clean here: the reindex above and
    # the rebuilt pages are sitting unstaged while we commit one puzzle file,
    # and a plain `pull --rebase` refuses outright ("cannot pull with rebase:
    # You have unstaged changes"). Every push in this job failed that way on the
    # nights of 2026-08-05 and 08-06, so the work stayed on the mini and the
    # site went on serving un-annotated puzzles that were annotated locally.
    git pull --rebase --autostash -q && git push -q origin HEAD || {
      git pull --rebase --autostash -q && git push -q origin HEAD ||
        alert "pre-reset backfill committed $what $num but could not push it — the site will not show it until someone pushes. See .prereset.log."
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
import json, sys
sys.path.insert(0, "tools")
import series
idx = json.load(open("puzzles/index.json"))
todo = [p for p in idx["puzzles"] if not p["annotated"] and p.get("hasSolutions")]
# Gentler series first — the beginner puzzles are the ones worth having hints on,
# because the people they are for are exactly the people who can't get through
# them unaided — then newest-first within a tier so today's puzzle is never last
# in the queue. The ranking is tools/series.py's, not a test for "cryptic": with
# four series and two publishers, "is it the Guardian daily" stopped being the
# same question as "is it hard".
todo.sort(key=lambda p: (series.gentleness(p.get("series")), -p["number"]))
print(" ".join(str(p["number"]) for p in todo))
EOF
)
echo "un-annotated backlog: ${todo:-none}"

for num in $todo; do
  if past_deadline; then echo "deadline reached — stopping"; break; fi
  echo "--- annotating $num ---"
  # Not "Guardian crossword": since 2026-08-05 some of these are the
  # Independent's. The puzzle file records its own series and publisher.
  run_claude "Annotate crossword No $num in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Every clue needs a definitionFit, and every indicator needs an indicatorNotes entry saying why THAT word carries THAT instruction. Do not commit — the calling script commits." || {
    echo "annotation run for $num failed (window exhausted?) — stopping here"
    git checkout -- "puzzles/$num.js" 2>/dev/null
    break
  }
  commit_puzzle "$num" "Annotate" || break
done

# --- 2. grandfathered-field backfill ------------------------------------------
# Additive only: these puzzles are already annotated and their hints are fine,
# they just predate a field. Anything that rewrites an existing hint here is a
# bug, not an improvement.
#
# The list of fields is read from tools/annotation_backlog.json, so a rule added
# next month is drained by this job without anyone editing it. Newest field
# first: it is the one the app has just started rendering, so it is the one a
# solver is most likely to hit an empty rung on.
backlog_fields=$(python3 -c 'import json;print(" ".join(k for k in json.load(open("tools/annotation_backlog.json")) if not k.startswith("_")))')

for field in $backlog_fields; do
  # Smallest backlog first: with an unknown amount of quota left, finishing four
  # puzzles beats getting most of the way through one.
  nums=$(python3 -c 'import json,sys
d=json.load(open("tools/annotation_backlog.json")).get(sys.argv[1],{})
print(" ".join(n for n,_ in sorted(d.items(), key=lambda kv: kv[1])))' "$field")
  echo "$field backlog: ${nums:-none}"
  case "$field" in
    definitionFit) what="ONE sentence saying why the answer means the definition; it renders last in the walkthrough" ;;
    indicatorNotes) what="an object keyed by the exact indicator string, ONE sentence each saying why THAT word carries THAT instruction — never the generic sentence about what the device does, and never a word of the answer" ;;
    *) what="the field as tools/annotate_prompt.md describes it" ;;
  esac
  for num in $nums; do
    if past_deadline; then echo "deadline reached — stopping"; break 2; fi
    echo "--- $field $num ---"
    run_claude "In this repo, add the missing \`$field\` to every annotated clue in puzzles/$num.js that lacks one. $field is $what. Read tools/annotate_prompt.md and STYLE.md for the voice, and read an existing puzzle that already has the field so yours match. This is ADDITIVE: change nothing else, do not rewrite existing hints, types, indicators or pieces. Run python3 tools/validate_annotations.py $num until it passes. Do not commit — the calling script commits." || {
      echo "$field run for $num failed (window exhausted?) — stopping here"
      git checkout -- "puzzles/$num.js" 2>/dev/null
      break 2
    }
    commit_puzzle "$num" "Backfill $field for" || break 2
  done
done

# Record what got drained. The allowance may only shrink, so every puzzle
# finished here is a puzzle that can never quietly lose the field again.
python3 tools/validate_annotations.py --tighten >/dev/null 2>&1 || true

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
  # Same list as daily_update.sh, and for the same reason: a backfill that needs
  # a new wordplay type edits app.js and STYLE.md as well as the puzzle, and
  # leaving those behind ships a clue the app cannot describe.
  git add puzzles/ index.html learn/ sitemap.xml app.js STYLE.md \
          tools/validate_annotations.py tools/annotation_backlog.json
  git commit -q -m "$(printf 'Republish after pre-reset backfill\n\n%s' "$ANNOTATE_TRAILER")"
  git pull --rebase --autostash -q && git push -q origin HEAD ||
    alert "pre-reset backfill could not push its republish commit — the built pages are committed locally only. See .prereset.log."
fi

# Where the rollout got to. Nothing to flip by hand any more: the ratchet in
# tools/validate_annotations.py already requires these fields of every puzzle
# annotated since they were added, and the numbers below are only the historical
# remainder.
python3 tools/validate_annotations.py 2>&1 | grep -i "backlog" || true

echo "=== done $(date '+%H:%M') ==="
