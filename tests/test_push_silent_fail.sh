#!/bin/bash
# Does tools/push_puzzle_commit.sh say why it failed when git says nothing,
# and try again when git was killed by a signal?
#
# 10-31: the burn's "could not push Annotate <id>" lines came seven times in a
# night after an EMPTY line, where git's error should be: fetch_base printed an
# empty $out. A git killed by a signal (10-17: SIGBUS, a pack repacked under its
# mmap by a gc in a sibling worktree) exits 128+n and writes nothing. A git shim
# on PATH plays that part: it dies of SIGBUS, or exits 1 wordless, on the calls
# named in $tmp/plan, and runs the real git otherwise.
#
#     bash tests/test_push_silent_fail.sh
set -uo pipefail
export PUSH_BATCH_SECS=0 PUSH_BATCH_FLUSHER=0
push="$(cd "$(dirname "$0")/../tools" && pwd)/push_puzzle_commit.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
ulimit -c 0
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else
  echo "FAIL $1"; echo "       want $3"; echo "       got  $2"; fails=$((fails + 1)); fi; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
real_git="$(command -v git)"
mkdir "$tmp/bin"
# plan: one line per git fetch/push call, in order: "bus", "quiet" or "ok";
# calls past the end run for real.
cat >"$tmp/bin/git" <<EOF
#!/bin/bash
case "\$1" in fetch|push)
  n=\$(( \$(cat "$tmp/calls.\$1" 2>/dev/null || echo 0) + 1 )); echo "\$n" >"$tmp/calls.\$1"
  case "\$(sed -n "\${n}p" "$tmp/plan.\$1" 2>/dev/null)" in
    bus) kill -BUS \$\$ ;;
    quiet) exit 1 ;;
  esac ;;
esac
exec "$real_git" "\$@"
EOF
# The retries' backoff is not under test.
printf '#!/bin/sh\nexit 0\n' >"$tmp/bin/sleep"
chmod +x "$tmp/bin/git" "$tmp/bin/sleep"

"$real_git" init -q --bare -b master "$tmp/origin.git"
"$real_git" clone -q "$tmp/origin.git" "$tmp/burn" 2>/dev/null
cd "$tmp/burn" || exit 1
mkdir -p puzzles/s/2026 && echo 0 >puzzles/s/2026/seed.json
"$real_git" add -A && "$real_git" commit -qm seed && "$real_git" push -q origin HEAD:master
"$real_git" checkout -q --detach

# run <name> <fetch plan> <push plan>: commit a puzzle and push it through the
# shim. Sets rc, err (stderr) and sub (the commit's subject).
run() {
  rm -f "$tmp"/calls.* "$tmp"/plan.*
  [ -n "$2" ] && printf '%s\n' $2 >"$tmp/plan.fetch"
  [ -n "$3" ] && printf '%s\n' $3 >"$tmp/plan.push"
  sub="Annotate $1"
  echo "{}" >"puzzles/s/2026/$1.json"
  "$real_git" add -- "puzzles/s/2026/$1.json" && "$real_git" commit -qm "$sub"
  err=$(PATH="$tmp/bin:$PATH" "$push" 2>&1); rc=$?
}
published() { "$real_git" --git-dir="$tmp/origin.git" log --format=%s master | grep -cx "$1"; }
blank_lines() { printf '%s\n' "$err" | grep -c '^$'; }

echo "a fetch killed by SIGBUS is tried again, says so, and the commit lands:"
run bus1 "bus" ""
check "exit 0" "$rc" "0"
check "published" "$(published "$sub")" "1"
check "names the signal" "$(printf '%s' "$err" | grep -c 'git fetch origin master was killed by SIGBUS (exit 135)')" "1"
check "no empty line" "$(blank_lines)" "0"

echo "a fetch that exits 1 without a word fails with a line saying so:"
run quiet1 "quiet" ""
check "exit 1" "$rc" "1"
check "not published" "$(published "$sub")" "0"
check "says how git ended" "$(printf '%s' "$err" | grep -c 'git fetch origin master exited 1 and said nothing')" "1"
check "no empty line" "$(blank_lines)" "0"

echo "a fetch that keeps dying of SIGBUS gives up after 10 tries, and says so:"
run busall "bus bus bus bus bus bus bus bus bus bus" ""
check "exit 1" "$rc" "1"
check "ten fetches" "$(cat "$tmp/calls.fetch")" "10"
check "says it gave up" "$(printf '%s' "$err" | grep -c "gave up on $sub after 10 attempts")" "1"
check "no empty line" "$(blank_lines)" "0"

echo "a push killed by SIGBUS is rebuilt on a fresh fetch and lands:"
run pushbus "" "bus"
check "exit 0" "$rc" "0"
check "published once" "$(published "$sub")" "1"
check "names the signal" "$(printf '%s' "$err" | grep -c 'git push to origin/master was killed by SIGBUS (exit 135)')" "1"
check "no empty line" "$(blank_lines)" "0"

echo "a push that exits 1 without a word fails with a line saying so:"
run pushquiet "" "quiet"
check "exit 1" "$rc" "1"
check "says how git ended" "$(printf '%s' "$err" | grep -c 'git push to origin/master exited 1 and said nothing')" "1"
check "no empty line" "$(blank_lines)" "0"

[ "$fails" = 0 ] && echo "all ok" || { echo "$fails failed"; exit 1; }
