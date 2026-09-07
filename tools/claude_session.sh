# Session ids for the `claude` runs these jobs make, so a run that dies can be
# RESUMED instead of bought a second time. A run that was cut off had already
# read the puzzle, worked out the wordplay and written half of it down; a fresh
# -p pays for all of that again.
#
# Sourced by both daily_update.sh and prereset_backfill.sh rather than written
# twice, because the way this fails is silent. The CLI accepts an empty
# --session-id by ignoring it, so a generator that is missing does not stop
# anything: every run simply gets its own fresh conversation, every --resume
# finds no transcript, and the mechanism is off with nothing in the log to say
# so. One copy, and it reports its own failure.

# A fresh conversation id. python3 and not uuidgen: both callers already
# require python3 and neither can require uuidgen, which macOS has and the
# bridge's container does not.
session_id() {
  local id
  id=$(python3 -c 'import uuid; print(uuid.uuid4())') || id=""
  if [ -z "$id" ]; then
    echo "WARNING: no session id, so a failed run cannot be resumed and will" \
         "start over" >&2
    return 1
  fi
  printf '%s\n' "$id"
}

# Does the CLI still hold that conversation? A --resume naming a transcript
# that was never written fails on the spot, which would spend the run's one
# retry on nothing. An empty id is never a conversation.
session_exists() {
  [ -n "${1:-}" ] || return 1
  [ -n "$(find "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" -maxdepth 2 \
            -name "$1.jsonl" 2>/dev/null | head -1)" ]
}
