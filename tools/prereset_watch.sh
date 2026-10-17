#!/bin/bash
# What the */5 fire of the pre-reset burn checks before it tries to start one.
#
#     bash tools/prereset_watch.sh
#
# tools/prereset_backfill.sh runs this ahead of the tree lease, so every fire
# does it whether or not the burn is alive. It looks for two ways a burn is lost
# that "is the lease free?" cannot see, and logs a line for each (the fire's
# output is the main checkout's .prereset.log):
#
# 1. ALIVE BUT STUCK. 10-17 the burn's shell sat 30 minutes in one pool_bag with
#    runs finished and unreaped (their /tmp/ct-prereset-*.rc written, nothing
#    committed), and every fire said "holds its tree" and left it. A burn whose
#    log has had no line for WATCH_STUCK_MIN minutes while a finished run has
#    sat unreaped as long is alerted on. It is not touched: it may only be
#    slow, and stopping it costs the runs in flight.
#
# 2. DEAD, BUT THE LEASE STILL HELD. The lease is flock'd on fd 9, which every
#    child of the burn inherits, so a model run (or the subshell around it)
#    that outlives a dead burn keeps the lease and the fire never restarts the
#    burn. When the lock's pid names no live burn and the holders are orphans
#    (parent pid 1), they are killed, so this same fire takes the lease and
#    starts the burn. The restart treats runs still recorded as stopped, so
#    leaving them alive would run each of them twice. A holder whose parent is a
#    live process is a start in progress, which takes the lease before the
#    lock, and is left alone.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LEASE="${WATCH_LEASE:-$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")/.prereset_backfill.tree.lock}"
LOCK="${WATCH_LOCK:-${CT_WORKTREE_ROOT:-$HOME/.cryptic-teacher}/prereset_backfill/.prereset.lock}"
STUCK_MIN="${WATCH_STUCK_MIN:-15}"
RC_DIR="${WATCH_RC_DIR:-/tmp}"
LOG_DIR="${WATCH_LOG_DIR:-${TMPDIR:-/tmp}}"
KILL_WAIT="${WATCH_KILL_WAIT:-10}"
. "$HERE/alert.sh"

# Pids holding the lease on fd 9, bar this one.
lease_holders() {
  local d p
  for d in /proc/[0-9]*; do
    p=${d#/proc/}
    [ "$p" = "$$" ] && continue
    [ "$(readlink "$d/fd/9" 2>/dev/null)" = "$LEASE" ] && echo "$p"
  done
}

# The lock's pid when it names a live burn: what lock_is_dead (prereset_backfill.sh)
# asks, from the command line, since pids are reused.
live_burn() {
  local pid
  pid=$(cat "$LOCK/pid" 2>/dev/null) && [ -n "$pid" ] || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep prereset_backfill >/dev/null || return 1
  echo "$pid"
}

# Alive: is it stuck?
check_stuck() {
  local pid="$1" n oldest
  # The burn's own log (its tee, /tmp/cryptic-prereset.*), not .prereset.log:
  # the fires append to that one themselves.
  find "$LOG_DIR" -maxdepth 1 -name 'cryptic-prereset.*' -mmin "-$STUCK_MIN" 2>/dev/null | grep . >/dev/null && return 0
  find "$RC_DIR" -maxdepth 1 -name 'ct-prereset-*.rc' -mmin "+$STUCK_MIN" 2>/dev/null | grep . >/dev/null || return 0
  n=$(find "$RC_DIR" -maxdepth 1 -name 'ct-prereset-*.rc' -mmin "+$STUCK_MIN" 2>/dev/null | grep -c .)
  oldest=$(ls -tr "$RC_DIR"/ct-prereset-*.rc 2>/dev/null | head -1)
  echo "watchdog: the burn (pid $pid) is alive but stuck: no log line for ${STUCK_MIN}+ min, $n finished run(s) unreaped, oldest $(basename "$oldest" .rc | sed 's/^ct-prereset-//') from $(date -r "$oldest" '+%H:%M')"
  # No minutes in the text: an identical alert is sent once per ALERT_REPEAT_HOURS.
  alert "the pre-reset burn (pid $pid) is alive but stuck: its log has been quiet for over ${STUCK_MIN} minutes while finished runs wait to be reaped and committed (oldest: $(basename "$oldest" .rc | sed 's/^ct-prereset-//')). Left running; look at what its shell is doing (ps, strace, .prereset.log)."
}

# Dead: does something still hold its lease?
check_orphans() {
  local holders h pp
  holders=$(lease_holders)
  [ -n "$holders" ] || return 0
  for h in $holders; do
    pp=$(ps -o ppid= -p "$h" 2>/dev/null | tr -d ' ')
    case " $(echo $holders) " in *" $pp "*) continue ;; esac   # a child of another holder
    if [ "$pp" != 1 ]; then
      echo "watchdog: pid $h holds the tree lease under a live parent ($pp), no burn lock behind it: a start in progress, leaving it"
      return 0
    fi
  done
  echo "watchdog: no live burn, but orphans hold its tree lease:$(for h in $holders; do printf ' %s=%s' "$h" "$(tr '\0' ' ' <"/proc/$h/cmdline" 2>/dev/null | cut -c1-60)"; done). Killing them so this fire restarts it."
  for h in $holders; do kill "$h" 2>/dev/null; done
  for _ in $(seq 1 "$KILL_WAIT"); do [ -z "$(lease_holders)" ] && break; sleep 1; done
  for h in $(lease_holders); do kill -9 "$h" 2>/dev/null; done
  sleep 1
  if [ -n "$(lease_holders)" ]; then
    alert "orphans of a dead pre-reset burn still hold its tree lease after a kill (pids $(lease_holders | tr '\n' ' ')): the burn cannot restart until they are gone."
  else
    echo "watchdog: lease free"
    alert "the pre-reset burn was dead with orphaned runs ($(echo $holders)) holding its tree lease; killed them and restarting. The runs they had in flight start over."
  fi
}

if pid=$(live_burn); then check_stuck "$pid"; else check_orphans; fi
exit 0
