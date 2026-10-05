#!/bin/bash
# Run one job of tools/data/corpus_queue.json: read its chunk files, one at a time.
#
#     (started by: python3 tools/corpus_queue.py tick; never by hand)
#     tools/corpus_job.sh <name> <chunks dir>
#
# Each chunk file c_<NNN>_<paper>_<series> lists up to 20 archive.org
# editions. The filer reads them (--wait queues behind another filer's ledger
# hold, `timeout` bounds the whole read), the puzzles it filed under
# puzzles/<series> are committed by pathspec and pushed, and the editions the
# ledger shows read since the chunk began are struck from it; an empty chunk
# is deleted. A chunk still holding editions after three tries moves to
# failed/ so one bad edition cannot hold the job. Last, it hands back to
# corpus_queue.py, which starts the next job.
#
# The job is a session leader (corpus_queue.py launch); everything it starts
# shares its session, and `corpus_queue.py stop` or the next tick after the
# leader dies kills the whole session, not just this shell.
. "$(dirname "$0")/nightly_worktree.sh"
cd "$(dirname "$0")/.." || exit 1
set -u
export PYTHONUNBUFFERED=1
NAME="$1" CH="$2"
OUT="$HOME/.cache/archive_org_crops/unfiled"
TRIES=3
READ_SECONDS="${CORPUS_JOB_SECONDS:-3000}"
mkdir -p "$OUT" "$CH/failed"

publish() {  # publish <series> <what> (all puzzles/)
  git add -- puzzles || return 1
  git diff --cached --quiet -- puzzles && return 0
  git commit -q -m "$(printf 'Corpus queue %s: %s\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>' "$NAME" "$2")" -- puzzles || return 1
  for i in 1 2 3 4 5; do
    git checkout -q -- index.html 2>/dev/null
    git pull -q --rebase origin master && git push -q origin HEAD:master && return 0
    git rebase --abort 2>/dev/null
    sleep $((i * 5))
  done
  echo "push failed 5 times; the commit stays here and goes with the next chunk"
}

next_chunk() {  # the first chunk file left
  python3 tools/corpus_queue.py chunks "$CH" | head -n 1 | grep .
}

while c=$(next_chunk); do
  base=$(basename "$c")
  # A list split by hand (split -l: c_aa) is the Times'.
  if [[ $base =~ ^c_[0-9]+_([a-z]+)_([a-z]+)$ ]]; then
    paper=${BASH_REMATCH[1]} series=${BASH_REMATCH[2]}
  else
    paper=times series=times
  fi
  try=$(( $(cat "$c.tries" 2>/dev/null || echo 0) + 1 ))
  echo "$try" > "$c.tries"
  since=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
  args=(); while read -r e; do [ -n "$e" ] && args+=(--edition "$e"); done < "$c"
  echo "=== $(date '+%F %T') $base: ${#args[@]} editions of $paper, try $try of $TRIES"
  git checkout -q -- index.html 2>/dev/null
  git pull -q --rebase origin master || echo "pull failed; reading on the tree as it is"
  timeout $((READ_SECONDS + 1200)) nice -n 19 python3 tools/file_archive_org_puzzles.py --paper "$paper" \
    --out "$OUT" --workers 6 --seconds "$READ_SECONDS" --wait "${args[@]}"
  rc=$?
  [ "$rc" -eq 0 ] || echo "filer exit $rc on $base"
  publish "$series" "$((${#args[@]})) $paper editions re-read ($base)" || echo "commit failed for $base"
  python3 tools/corpus_queue.py unread "$c" "$since" > "$c.left" && mv "$c.left" "$c"
  if [ ! -s "$c" ]; then
    rm -f "$c" "$c.tries"
  elif [ "$try" -ge "$TRIES" ]; then
    echo "$base: $(wc -l < "$c") editions still unread after $TRIES tries; moved to failed/"
    mv "$c" "$c.tries" "$CH/failed/"
  else
    echo "$base: $(wc -l < "$c") editions left for the next try"
  fi
done
failed=$(python3 tools/corpus_queue.py chunks "$CH/failed" | wc -l | tr -d ' ')
echo "=== $(date '+%F %T') $NAME: no chunks left ($failed failed)"
# Let go of this tree's lease first: the next job is started from here and needs it.
exec 9>&-
exec python3 tools/corpus_queue.py finished "$NAME"
