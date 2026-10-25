#!/bin/bash
# Run one command at the lowest CPU share: tools/low_cpu.sh CMD [ARG...]
#
# In the container `nice -n 19` alone does nothing (autogroups: the CPU is
# split between sessions by each session's nice), and deprioritizing the
# caller's own pid would lower its whole session, the unit around it too. So
# the command gets a session of its own (setsid), which
# /app/tools/deprioritize.sh lowers to nice 19, group and process, before the
# exec. Where either is missing (macOS) it is a plain renice. The exit status
# is the command's; open descriptors (a held flock) pass through.
if [ -z "${LOW_CPU_SESSION:-}" ] && command -v setsid >/dev/null 2>&1; then
  LOW_CPU_SESSION=1 exec setsid -w "$0" "$@"
fi
unset LOW_CPU_SESSION
/app/tools/deprioritize.sh -q 19 $$ 2>/dev/null || renice -n 19 $$ >/dev/null 2>&1
exec "$@"
