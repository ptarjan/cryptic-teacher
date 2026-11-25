#!/usr/bin/env bash
# Run part of a workflow job in the background beside the steps that follow it.
#
#   bash tools/bg_job.sh start NAME CMD [ARG...]   # returns at once
#   bash tools/bg_job.sh wait [-q] NAME...         # prints each log (-q: none), exits with the
#                                                  # first failing CMD's own status
#
# A step runs one after another, and most of the deploy's time is steps that
# wait on the network (an actions/cache restore) or on a disk, which leave the
# four cores idle. A command that does not need what those steps fetch is
# started here and collected by a later step, so the two run together. Output
# goes to $BG_JOB_DIR/NAME.log (default $RUNNER_TEMP) and the exit status to
# NAME.rc; wait prints each log whole, so a failure shows up where the step that
# waits for it is, with the output of the command that failed.
#
# Detached from the step's output, or the runner holds the step open on the
# inherited pipe (5s in run 38389462732). A job that dies without writing its
# status is caught by wait's timeout (BG_JOB_TIMEOUT seconds for all the names
# together, default 1200), which names the job and shows what it logged.
set -uo pipefail
dir="${BG_JOB_DIR:-${RUNNER_TEMP:-/tmp}}"
case "${1:-}" in
  start)
    [ $# -ge 3 ] || { echo "usage: $0 start NAME CMD [ARG...]" >&2; exit 2; }
    name=$2; shift 2
    rm -f "$dir/$name.rc" "$dir/$name.log"
    ( "$@" > "$dir/$name.log" 2>&1; echo $? > "$dir/$name.rc.tmp"; mv "$dir/$name.rc.tmp" "$dir/$name.rc" ) \
      < /dev/null > /dev/null 2>&1 &
    ;;
  wait)
    shift
    quiet=0
    [ "${1:-}" != -q ] || { quiet=1; shift; }
    [ $# -ge 1 ] || { echo "usage: $0 wait [-q] NAME..." >&2; exit 2; }
    # One shared deadline for all the names, then each one's own status: the
    # waiter exits with the first failing job's real status.
    ticks=0
    limit=$(( ${BG_JOB_TIMEOUT:-1200} * 5 ))
    status=0
    for name in "$@"; do
      while [ ! -f "$dir/$name.rc" ]; do
        if [ "$ticks" -ge "$limit" ]; then
          echo "bg_job: $name wrote no status in ${BG_JOB_TIMEOUT:-1200}s" >&2
          cat "$dir/$name.log" 2>/dev/null
          exit 1
        fi
        sleep 0.2
        ticks=$(( ticks + 1 ))
      done
      [ "$quiet" = 1 ] || cat "$dir/$name.log"
      rc=$(cat "$dir/$name.rc")
      if [ "$rc" != 0 ]; then
        echo "bg_job: $name failed with status $rc" >&2
        [ "$status" != 0 ] || status=$rc
      fi
    done
    exit "$status"
    ;;
  *) echo "usage: $0 start NAME CMD... | wait [-q] NAME..." >&2; exit 2 ;;
esac
