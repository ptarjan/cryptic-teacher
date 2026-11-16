#!/bin/bash
# Wait for the GitHub Actions runs of one commit and report them.
#
#     tools/ci_wait.sh [sha]        # sha defaults to HEAD
#     CI_WAIT_TIMEOUT=600 tools/ci_wait.sh
#
# Polls with backoff (15 s doubling to 120 s) until every run for the sha has completed.
# CI_WAIT_TIMEOUT seconds (default 2700) bounds the whole wait; a sha with no run after
# 180 s counts as a timeout. Prints one line per run:
#     <short sha> <workflow> <conclusion> <failed jobs, comma-separated> <url>
# and, for each failed run, the last 40 lines of its failed-job log.
# Exit 0 all runs passed, 1 something failed, 2 timeout.
set -uo pipefail

git fetch -q origin master || exit 1
sha="$(git rev-parse "${1:-HEAD}")" || exit 1
timeout="${CI_WAIT_TIMEOUT:-2700}"
no_run_limit=180
start=$SECONDS
delay=15

runs=""
while :; do
  runs="$(gh run list --commit "$sha" --json databaseId,name,status,conclusion,url,headSha)" || runs="[]"
  total="$(jq 'length' <<<"$runs")"
  pending="$(jq '[.[] | select(.status != "completed")] | length' <<<"$runs")"
  elapsed=$((SECONDS - start))
  if [ "$total" -gt 0 ] && [ "$pending" -eq 0 ]; then
    break
  fi
  if [ "$total" -eq 0 ] && [ "$elapsed" -ge "$no_run_limit" ]; then
    echo "${sha:0:10} no workflow run appeared within ${no_run_limit}s" >&2
    exit 2
  fi
  if [ "$elapsed" -ge "$timeout" ]; then
    echo "${sha:0:10} timed out after ${elapsed}s with $pending of $total runs unfinished" >&2
    exit 2
  fi
  sleep "$delay"
  delay=$((delay * 2))
  [ "$delay" -gt 120 ] && delay=120
done

status=0
failed_ids=""
while IFS=$'\t' read -r id name conclusion url; do
  failed_jobs=""
  case "$conclusion" in
    success|skipped|neutral) ;;
    *)
      status=1
      failed_ids="$failed_ids $id"
      failed_jobs="$(gh run view "$id" --json jobs --jq '[.jobs[] | select(.conclusion == "failure" or .conclusion == "timed_out" or .conclusion == "cancelled") | .name] | join(",")')"
      ;;
  esac
  echo "${sha:0:10} $name $conclusion ${failed_jobs:--} $url"
done < <(jq -r '.[] | [.databaseId, .name, .conclusion, .url] | @tsv' <<<"$runs")

for id in $failed_ids; do
  echo "--- last 40 lines of failed log, run $id ---"
  gh run view "$id" --log-failed 2>&1 | tail -n 40
done
exit "$status"
