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

# The CLI resumes a conversation only from the project directory of the cwd it
# runs in (the path with every character but a letter or digit made a dash), so
# one begun in another tree, a daily unit retried in a sibling tree, is copied
# into this tree's first. 0 when it is here.
session_here() {
  local root="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects" here src
  [ -n "${1:-}" ] || return 1
  here="$root/$(pwd -P | sed 's/[^A-Za-z0-9]/-/g')"
  [ -f "$here/$1.jsonl" ] && return 0
  src=$(find "$root" -maxdepth 2 -name "$1.jsonl" 2>/dev/null | head -1)
  [ -n "$src" ] && mkdir -p "$here" && cp "$src" "$here/"
}

# A one-shot run's conversation, named in sid file $1 so that a run stopped from
# outside (a restart, its unit's time limit) is resumed by the next attempt at
# the same task rather than bought again. Fills the array named $2 with the
# flags for it; when it resumes, the variable named $3 (the task) becomes the
# note saying it was stopped and what that may have cost, with the task after it.
# The caller removes $1 when the run ends: one still there was stopped. A day
# old, or with no transcript, it is not resumed.
session_args() {   # sidfile array-name task-var
  local -n _args="$2" _task="$3"
  local sid=""
  _args=()
  [ -s "$1" ] && read -r sid _ <"$1"
  if [ -n "$sid" ] && [ -z "$(find "$1" -mmin +1440 2>/dev/null)" ] && session_here "$sid"; then
    _args=(--resume "$sid")
    _task="You were stopped from outside (the job restarted or hit its time limit) and are now resumed. Edits you made to files may have been reset since: check them, redo from your reasoning above whatever is missing, and finish the task. As it stands now:

$_task"
    touch "$1"
    return 0
  fi
  sid=$(session_id) || { rm -f "$1"; return 0; }
  echo "$sid" >"$1"
  _args=(--session-id "$sid")
}

# Headless runs read the repo's settings alone: no user plugins, MCP servers or
# auto-memory, which put ~8k tokens in every turn and drew a third of sessions
# into the memory directory. The 5-minute cache, because nine turn gaps in ten
# are under 90s and a 1-hour cache write is billed at the higher rate.
export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 CLAUDE_CODE_PROMPT_CACHE_TTL=5m
# A -p run exits when the model ends its turn, so a command it backgrounds (or
# that the 2-minute Bash timeout backgrounds for it) never reports back and the
# work after it never happens. Every command runs in the foreground, with room
# for a whole-corpus check to finish.
export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 BASH_DEFAULT_TIMEOUT_MS=900000
# shellcheck disable=SC2034  # used by the scripts that source this
CLAUDE_HEADLESS=(--strict-mcp-config --setting-sources project)
