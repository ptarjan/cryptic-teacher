#!/usr/bin/env bash
# tools/bg_job.sh: a command started in the background runs beside the caller,
# its output and status are collected whole by wait, a failure is the waiter's
# failure, and a job that never reports is given up on.
set -euo pipefail
cd "$(dirname "$0")/.."
tool=$PWD/tools/bg_job.sh
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
export BG_JOB_DIR=$tmp
fail() { echo "test_bg_job: $*" >&2; exit 1; }

start=$(date +%s)
bash "$tool" start slow bash -c 'sleep 3; echo done-slow'
now=$(date +%s)
[ $(( now - start )) -le 1 ] || fail "start did not return at once"
out=$(bash "$tool" wait slow) || fail "wait failed for a job that passed"
[ "$out" = done-slow ] || fail "wait printed '$out'"

bash "$tool" start bad bash -c 'echo before; echo oops >&2; exit 3'
rc=0; out=$(bash "$tool" wait bad 2>&1) || rc=$?
[ "$rc" = 3 ] || fail "a failed job's status was $rc, not 3"
case "$out" in *before*oops*"failed with status 3"*) ;; *) fail "the log was not shown: $out" ;; esac

# A status left by an earlier job of the same name is not mistaken for this one.
echo 0 > "$tmp/again.rc"
bash "$tool" start again bash -c 'sleep 1; exit 4'
rc=0; bash "$tool" wait again >/dev/null 2>&1 || rc=$?
[ "$rc" = 4 ] || fail "a stale status was read: $rc"

# A job whose status never arrives (killed outright) is given up on.
echo partial > "$tmp/lost.log"
rc=0; out=$(BG_JOB_TIMEOUT=1 bash "$tool" wait lost 2>&1) || rc=$?
[ "$rc" = 1 ] || fail "a lost job did not fail the wait"
case "$out" in *partial*) ;; *) fail "the lost job's log was not shown" ;; esac
# Several names: every log shown, the first failure's own status returned.
bash "$tool" start one bash -c 'echo log-one'
bash "$tool" start two bash -c 'echo log-two; exit 5'
bash "$tool" start three bash -c 'sleep 1; echo log-three; exit 6'
rc=0; out=$(bash "$tool" wait one two three 2>&1) || rc=$?
[ "$rc" = 5 ] || fail "wait on several names returned $rc, not the first failure's 5"
case "$out" in *log-one*log-two*log-three*) ;; *) fail "a log was missing: $out" ;; esac
bash "$tool" start quiet bash -c 'echo hidden'
out=$(bash "$tool" wait -q quiet 2>&1) || fail "wait -q failed for a job that passed"
[ -z "$out" ] || fail "wait -q printed '$out'"
echo "test_bg_job: all passed"
