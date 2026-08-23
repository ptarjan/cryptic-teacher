#!/bin/bash
# Burn the tail of the weekly usage window on backfills, just before it resets.
#
# Why this exists, separately from daily_update.sh: unspent quota does not roll
# over. Whatever is left when the weekly window turns over is simply gone.
# daily_update.sh deliberately refuses to annotate above ANNOTATE_MAX_WEEKLY_PCT
# (50%) because a crossword backlog is never worth being rate-limited for real
# work — but that reasoning stops applying at the end of the window, when there
# is no real work left to protect. So this job runs with NO usage gate at all,
# on purpose, and ONLY then.
#
# "Only then" is load-bearing and was wrong for its first week: the job is fired
# hourly and almost always exits immediately, because whether this is the hour
# is decided by asking the usage API when the window resets, not by the time on
# the clock. See the check below.
#
# HOW MUCH IS LEFT DECIDES BOTH THE START AND THE WIDTH. Two hours of one
# annotation at a time spends a few percent, so a week that ends with tens of
# percent unspent ends that way however faithfully this job runs. Both numbers
# are arithmetic on the remainder and on a burn rate this job measures for
# itself — tools/prereset_plan.py, which is where they are explained and tested.
# A remainder that is nearly spent still gets the old behaviour: start two hours
# out, one run at a time.
#
# Paul, 2026-08-02: "right before my weekly inference resets you should spend
# whatever is left on backfills."
#
# What it backfills, in priority order:
#   1. Un-annotated puzzles, NEWEST FIRST BY DATE, across every series at once.
#      A solver arriving today is looking at this week's puzzles, so this week's
#      puzzles are the ones worth spending on, whoever printed them.
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
# How close to the reset counts as "the end of the week" — computed from what is
# left to spend, so a nearly-spent window still starts two hours out and a badly
# under-spent one starts early enough to have a chance. tools/prereset_plan.py
# clamps it at both ends; nothing here may start the ungated part days early.
WINDOW_HOURS="${WINDOW_HOURS:-$(python3 tools/prereset_plan.py --window-hours 2>/dev/null || echo 2)}"
FORCE_HOURS="${FORCE_HOURS:-1}"
# Above this the weekly window really is gone and a failing run means it. Below
# it, a failure is the FIVE-hour window instead, which clears by itself.
EXHAUSTED="${EXHAUSTED:-97}"
MAX_NAPS="${MAX_NAPS:-6}"
# DRY_RUN=1 walks the whole job — gate, queue order, wave widths, deadline —
# without calling claude, touching git or rebuilding anything. This job spends
# ungated inference in parallel and cannot be rehearsed any other way; the first
# version of it ran seven ungated nights a week and read as healthy in the log.
DRY_RUN="${DRY_RUN:-0}"

echo "=== cryptic-teacher pre-reset backfill $(date '+%Y-%m-%d %H:%M') ==="

# One at a time. launchd will not start a second copy of its own job, but this
# now runs for hours rather than one, so an hourly fire and a hand-run FORCE=1
# overlap easily — and two copies would double the width nobody asked for and
# race each other's commits in the one git index. mkdir is the atomic part.
LOCK="$REPO/.prereset.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "another pre-reset backfill is running (started $(date -r "$LOCK" '+%H:%M')) — leaving it alone"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

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

# Hours between two epoch seconds. A function because both callers used to build
# the awk program by string interpolation and both got it wrong the same way.
hours_between() {
  awk -v a="$1" -v b="$2" 'BEGIN{printf "%.3f", (b - a) / 3600}'
}

# Run one claude task against the repo. Returns non-zero if the run failed.
#
# Its output goes to a file named after the puzzle rather than to the log, because
# several of these run at once now and interleaved transcripts belong to nobody.
# The caller prints the tail of each one as it reaps it, in order.
run_claude() {
  local tag="$1" log
  log="/tmp/ct-prereset-$1.txt"
  if [ "$DRY_RUN" = 1 ]; then
    echo "would spend one $MODEL run on $tag" >"$log"
    sleep 1
    return 0
  fi
  claude -p "$2" \
    --model "$MODEL" \
    --allowedTools "Read,Write,Edit,Bash(python3 *),Bash(node *)" \
    --max-turns 80 >"$log" 2>&1
  local rc=$?
  # Running out of window is how this job is SUPPOSED to end, so a plain failure
  # stays quiet. A broken login is a different animal: it fails identically, at
  # the same point, every night, and it hid there for seven days (2026-07-31 to
  # 2026-08-06) precisely because it looked like the normal ending.
  if [ $rc -ne 0 ] && grep -qi "Failed to authenticate\|Not logged in" "$log"; then
    alert "pre-reset backfill cannot authenticate — the CLI needs a fresh /login. Nothing has been backfilled since this started."
  fi
  return $rc
}

# Run a wave of puzzles at once and commit the ones that survive validation.
#   $1   commit message prefix, e.g. "Annotate"
#   $2   the prompt, with every @ standing for the puzzle id
#   $3+  the ids
# Returns how many runs failed. The claude runs are the only thing that happens
# in parallel: every git command below runs in this shell, one at a time, because
# a second process staging its own file mid-commit swallows it into ours.
run_wave() {
  local what="$1" tmpl="$2"; shift 2
  local ids=("$@") pids=() i failed=0
  echo "--- wave of ${#ids[@]}: ${ids[*]} ---"
  for i in "${!ids[@]}"; do
    run_claude "${ids[$i]}" "${tmpl//@/${ids[$i]}}" &
    pids+=($!)
  done
  for i in "${!ids[@]}"; do
    if wait "${pids[$i]}"; then
      tail -3 "/tmp/ct-prereset-${ids[$i]}.txt" | sed "s/^/  [${ids[$i]}] /"
      commit_puzzle "${ids[$i]}" "$what"
    else
      echo "  [${ids[$i]}] run failed — discarding its changes"
      git checkout -- "puzzles/${ids[$i]}.js" 2>/dev/null
      failed=$((failed + 1))
    fi
  done
  return $failed
}

# What a finished wave teaches, and whether to keep going.
#   $1 percent used before the wave  $2 hours it took  $3 how wide it was
#   $4 how many of its runs failed
# Returns non-zero when the caller should stop.
after_wave() {
  local before="$1" hours="$2" wide="$3" failed="$4" now climb
  now=$(python3 tools/weekly_usage.py 2>/dev/null || echo "$before")
  # awk -v, never string interpolation: an unset or empty number splices into the
  # program text and awk dies of a syntax error, which reads as a broken script
  # rather than as the missing reading it is.
  climb=$(awk -v a="$before" -v b="$now" 'BEGIN{print b - a}')
  python3 tools/prereset_plan.py --observe "$climb" "$hours" "$wide" >/dev/null 2>&1
  echo "  weekly window ${before}% -> ${now}% in ${hours}h at width ${wide}"
  [ "${failed:-1}" -eq 0 ] && return 0
  # A failed wave with room still on the weekly clock is almost always the
  # FIVE-hour limit, which this job is now wide enough to hit on purpose and
  # which clears by itself. Treating that as "the week is over" is how a job
  # built to spend the remainder leaves most of it behind. Only the seven-day
  # number gets to end the run.
  if awk -v n="$now" -v e="$EXHAUSTED" 'BEGIN{exit !(n >= e)}'; then
    echo "  weekly window is spent (${now}%) — stopping"
    return 1
  fi
  naps=$((naps + 1))
  if [ "$naps" -gt "$MAX_NAPS" ]; then
    echo "  $naps waits already and runs still fail — stopping rather than looping"
    return 1
  fi
  local nap=$(( STOP_AT - $(date +%s) - 60 ))
  [ "$nap" -gt 1200 ] && nap=1200
  if [ "$nap" -le 0 ]; then return 1; fi
  echo "  runs failed at ${now}% weekly — five-hour limit; waiting ${nap}s (nap $naps)"
  sleep "$nap"
  return 0
}

# Commit whatever a task produced, but only if the tree still validates. A run
# that ran out of room mid-file leaves a half-written annotation behind, and
# committing that would publish a broken puzzle page at 06:15.
commit_puzzle() {
  local num="$1" what="$2"   # num is a puzzle ID, e.g. cryptic-30089
  if [ "$DRY_RUN" = 1 ]; then echo "  would commit $what $num"; return 0; fi
  # This puzzle only. A whole-tree run would fail for a sibling in the same wave
  # that is still mid-write, and discard a good annotation to punish it.
  if ! python3 tools/validate_annotations.py "$num" >/tmp/ct-prereset-validate.txt 2>&1; then
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
echo "un-annotated backlog, newest first:"
todo=$(python3 - <<'EOF'
import json, sys
from datetime import datetime, timezone
idx = json.load(open("puzzles/index.json"))
todo = [p for p in idx["puzzles"] if not p["annotated"] and p.get("hasSolutions")]
# Newest first, by DATE and by date alone — one queue across every series.
#
# Not by number: each paper numbers from its own 1, so a number sort is a series
# sort wearing a disguise. It ran every Guardian cryptic (30,0xx), then every
# Independent (12,4xx), then every Indy Sunday (1,9xx), in that order, purely
# because of how big each paper's counter happens to be.
#
# Not by series tier either. Whichever series goes first, its whole archive goes
# before the other series' puzzle from yesterday, and the archive is always
# deeper than one window of quota — so the tail never runs and today is last.
todo.sort(key=lambda p: -p["date"])
# The order this job spends a whole window in is worth one readable line in the
# log. It ran in the wrong order for weeks behind a single line listing 166 ids.
# stderr, because stdout is the queue itself.
for p in todo[:5]:
    print(f"  {datetime.fromtimestamp(p['date'] / 1000, timezone.utc):%Y-%m-%d}  "
          f"{p['id']}", file=sys.stderr)
if len(todo) > 5:
    print(f"  ... and {len(todo) - 5} older", file=sys.stderr)
# IDs, not numbers: the file is puzzles/<id>.js and every consumer below names
# it directly, so nothing downstream has to resolve a number that two papers
# could one day share.
print(" ".join(p["id"] for p in todo))
EOF
)

# Not "Guardian crossword": since 2026-08-05 some of these are the
# Independent's. The puzzle file records its own series and publisher.
ANNOTATE_PROMPT="Annotate the crossword in puzzles/@.js in this repo. Follow the instructions in tools/annotate_prompt.md exactly, including running the validator until it passes. Every clue needs a definitionFit, and every indicator needs an indicatorNotes entry saying why THAT word carries THAT instruction. Do not commit — the calling script commits."

naps=0
queue=($todo)
at=0
while [ "$at" -lt "${#queue[@]}" ]; do
  if past_deadline; then echo "deadline reached — stopping"; break; fi
  # Re-asked every wave, not decided once: the remainder shrinks as we spend it,
  # the hours shrink faster, and something else on this machine may be spending
  # too. A width fixed at the top would be wrong by the second wave.
  hours_left=$(hours_between "$(date +%s)" "$STOP_AT")
  wide=$(python3 tools/prereset_plan.py --width "$hours_left" 2>/dev/null || echo 1)
  before=$(python3 tools/weekly_usage.py 2>/dev/null || echo 0)
  started=$(date +%s)
  run_wave "Annotate" "$ANNOTATE_PROMPT" "${queue[@]:$at:$wide}"
  failed=$?
  at=$((at + wide))
  after_wave "$before" "$(hours_between "$started" "$(date +%s)")" \
    "$wide" "$failed" || break
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
  prompt="In this repo, add the missing \`$field\` to every annotated clue in puzzles/@.js that lacks one. $field is $what. Read tools/annotate_prompt.md and STYLE.md for the voice, and read an existing puzzle that already has the field so yours match. This is ADDITIVE: change nothing else, do not rewrite existing hints, types, indicators or pieces. Run python3 tools/validate_annotations.py @ until it passes. Do not commit — the calling script commits."
  queue=($nums)
  at=0
  while [ "$at" -lt "${#queue[@]}" ]; do
    if past_deadline; then echo "deadline reached — stopping"; break 2; fi
    hours_left=$(hours_between "$(date +%s)" "$STOP_AT")
    wide=$(python3 tools/prereset_plan.py --width "$hours_left" 2>/dev/null || echo 1)
    before=$(python3 tools/weekly_usage.py 2>/dev/null || echo 0)
    started=$(date +%s)
    run_wave "Backfill $field for" "$prompt" "${queue[@]:$at:$wide}"
    failed=$?
    at=$((at + wide))
    after_wave "$before" "$(hours_between "$started" "$(date +%s)")" \
      "$wide" "$failed" || break 2
  done
done

if [ "$DRY_RUN" = 1 ]; then
  echo "=== dry run — nothing spent, nothing built, nothing committed $(date '+%H:%M') ==="
  exit 0
fi

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
