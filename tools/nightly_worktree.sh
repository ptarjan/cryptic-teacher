#!/bin/bash
# Move a scheduled job into a checkout of its own, then hand control back.
#
# Sourced as the FIRST thing a scheduled script does. It re-execs that script
# from a private git worktree pinned to origin/master, so a job that runs for
# two hours never shares a working tree with a person editing the repo.
#
# WHY. The main checkout has other writers: people, agents and the other
# jobs. A job running there would make every one of these true at once:
#
#   * A half-written feature sitting unstaged looks, to the job, exactly like
#     something the job changed, and gets swallowed into the job's commit.
#   * The reverse: while the job is mid-run, its half-fetched puzzle
#     files are in the tree, so a person cannot commit their own work
#     either. The asset stamps span both sets of files, so a partial commit
#     ships an index.html pointing at a puzzles/index.js that isn't there.
#   * `git pull --rebase --autostash` before a push stashes whatever the other
#     writer has in flight, out from under them.
#
# None of that is a bug in the checks. It is one working tree with two writers,
# and the fix is two working trees. A worktree shares the object store, so this
# costs no extra clone and no extra fetch — and because every run starts at
# `reset --hard origin/master`, a run that died halfway leaves nothing for the
# next one to trip over.
#
# What the job gets: a tree containing exactly what it changes, so it can stage
# with `git add -A` rather than keep a list of the files it touched.
#
# Untracked state is deliberately NOT copied. It is symlinked back to the main
# checkout, so the usage cache, the alert dedupe and the CLI's settings stay one
# thing across every tree — otherwise the same alert fires from each job and
# the quota reading is measured once per tree.
#
# Logs do not move: the scheduler owns the redirect (each plugin manifest's
# `log`, under household-plugins/), and it names a file in the main checkout.
# Where the script ran from does not change where its output lands — which is
# why they are also trimmed from here.
#
# There is no fallback. If the worktree cannot be had the job stops and says so,
# because the only other tree is the one all of this exists to stay out of.
#
# Set CT_NO_WORKTREE=1 to run in place — for testing a change to one of these
# scripts before it is pushed, since the worktree only ever runs committed code.

# The tree is leased to one run of a job at a time, however the run was
# started: the reset below discards whatever a live run has not committed yet,
# and a run started inside the worktree (CT_IN_WORKTREE=1) or in place
# (CT_NO_WORKTREE=1) writes there just the same. The lock file lives in the main
# checkout, found through the shared .git from any tree. fd 9 survives the exec,
# so a run that inherits it already holds the lease and keeps it until the run
# and every child it started have exited.
_ct_lease="$(cd "$(dirname "${BASH_SOURCE[0]}")" &&
  dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.$(basename "$0" .sh).tree.lock"
if [ "$(readlink "/proc/$$/fd/9" 2>/dev/null)" != "$_ct_lease" ]; then
  exec 9>"$_ct_lease"
fi
if ! flock -n 9; then
  echo "another $(basename "$0" .sh) run holds its tree — leaving it alone"
  exit 0
fi

# The merge driver and clean filter .gitattributes names for the keyed JSON
# data files. Repo config is shared by every worktree of the checkout, so
# registering them on each run covers the jobs, the people and the agents
# rebasing and committing alongside them.
# Written only when the value differs: git takes .git/config.lock for every
# write, and two jobs starting together collide on it ("could not lock config
# file") although the value is already right.
_ct_cfg() {  # _ct_cfg <key> <value>
  local d; d="$(dirname "${BASH_SOURCE[0]}")"
  [ "$(git -C "$d" config --get "$1")" = "$2" ] || git -C "$d" config "$1" "$2"
}
_ct_cfg merge.json-keys.name "per-key JSON merge (tools/json_merge.py)"
_ct_cfg merge.json-keys.driver "python3 tools/json_merge.py %O %A %B"
_ct_cfg filter.json-keys.clean "python3 tools/json_merge.py --clean"
_ct_cfg merge.puzzle-json.name "per-entry puzzle merge (tools/json_merge.py --puzzle)"
_ct_cfg merge.puzzle-json.driver "python3 tools/json_merge.py --puzzle %O %A %B"

# The main checkout is nobody's editor window: the plugin manifests and the
# entry points the scheduler names are read from it, so it follows origin/master
# at every job start, whichever tree the job was started from. Its tracked files
# change only by this fast-forward. Two kinds of local edit are provably nothing
# and are put back so they cannot block it: a file already holding
# origin/master's content (a manifest edited live, then committed), and an
# index.html that differs from HEAD only by asset stamps (stamping is the deploy
# workflow's build step). Anything else — another edit, a branch, a local commit
# — leaves it behind, and that wakes the room: every job reading it runs old
# code until it moves. The alert text names no count, so it repeats only on
# alert.sh's schedule while the cause is unchanged.
_ct_follow_origin() {
  local common home path cur edits why clobber
  common="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --path-format=absolute --git-common-dir)"
  home="$(dirname "$common")"
  # One job at a time; a job that finds another mid-update leaves it to that one.
  exec 7>"$common/ct-follow-origin.lock"
  flock -w 60 7 || { exec 7>&-; return 0; }
  if [ "$(git -C "$home" symbolic-ref -q --short HEAD)" = master ]; then
    while IFS= read -r path; do
      [ -n "$path" ] && [ -f "$home/$path" ] || continue
      cur="$(git -C "$home" hash-object -- "$path")"
      if [ "$cur" = "$(git -C "$home" rev-parse -q --verify "origin/master:$path")" ] ||
         { [ "$path" = index.html ] &&
           [ "$(cd "$home" && python3 -c 'import sys; sys.path.insert(0, "tools"); import stamp_assets as s
sys.stdout.buffer.write(s.unstamp(s.INDEX_HTML.read_text(encoding="utf-8")).encode("utf-8"))' 2>/dev/null |
                git -C "$home" hash-object --path index.html --stdin)" = \
             "$(git -C "$home" rev-parse -q --verify HEAD:index.html)" ]; }; then
        git -C "$home" checkout -q -- "$path" &&
          echo "WORKTREE: put back $path in $home — its edit was already on origin/master or only asset stamps" >&2
      fi
    done < <(git -C "$home" diff --name-only HEAD --)
    git -C "$home" merge-base --is-ancestor origin/master HEAD ||
      git -C "$home" merge -q --ff-only origin/master 2>/dev/null
  fi
  if ! git -C "$home" merge-base --is-ancestor origin/master HEAD; then
    edits="$(git -C "$home" diff --name-only HEAD -- | head -8 | tr '\n' ' ')"
    clobber="$(comm -12 <(git -C "$home" ls-files --others --exclude-standard | sort) \
                        <(git -C "$home" diff --name-only --diff-filter=A HEAD origin/master | sort) | head -8 | tr '\n' ' ')"
    if [ "$(git -C "$home" symbolic-ref -q --short HEAD)" != master ]; then
      why="HEAD is $(git -C "$home" symbolic-ref -q --short HEAD || echo detached), not master"
    elif ! git -C "$home" merge-base --is-ancestor HEAD origin/master; then
      why="master has local commits origin/master does not"
    elif [ -n "$edits" ]; then
      why="uncommitted edits to tracked files: $edits"
    elif [ -n "$clobber" ]; then
      why="untracked files origin/master would overwrite: $clobber"
    else
      why="git merge --ff-only failed (a git lock held by another process?)"
    fi
    echo "WORKTREE: $home cannot fast-forward to origin/master: $why" >&2
    . "$home/tools/alert.sh" 2>/dev/null &&
      alert "the main checkout $home is behind origin/master and a job start could not fast-forward it — $why. Every scheduled job reads its manifest and entry script from there, so they run old code until it moves. Commit those changes from a worktree and put the checkout back (\`git -C $home checkout -- <file>\`); the next job start fast-forwards it."
  fi
  exec 7>&-
}

# ct_unstage_unparsable <tree>: take out of the index each staged .json that
# does not parse (a write cut off by a kill), so no commit carries one.
ct_unstage_unparsable() {
  local bad
  bad=$(git -C "$1" diff --cached --name-only --diff-filter=AM -- '*.json' |
    (cd "$1" && python3 -c 'import json, sys
for p in sys.stdin.read().split("\n"):
    if p:
        try:
            json.load(open(p))
        except (OSError, ValueError):
            print(p)'))
  [ -n "$bad" ] || return 0
  printf '%s\n' "$bad" | (cd "$1" && xargs -d '\n' git reset -q --)
  echo "left out of the commit, not parsable: $(printf '%s\n' "$bad" | tr '\n' ' ')" >&2
}

# _ct_salvage <tree> <job>: commit what a dropped run left under
# CT_SALVAGE_PATHS (a .json that does not parse, a write cut off, is left
# out), then push every commit the tree has that origin/master lacks with
# tools/push_puzzle_commit.sh. A commit that will not push is kept on the
# branch salvage/<job>-<time> and the room is told; the reset then goes ahead.
_ct_salvage() {
  local tree="$1" job="$2" c failed=0 msg lock
  # A run killed mid-git leaves its lock, and mid-rebase its rebase: the
  # lease says no run of this job is live, so one older than a minute is dead.
  lock="$(git -C "$tree" rev-parse --git-dir)/index.lock"
  [ -f "$lock" ] && [ -z "$(find "$lock" -mmin -1)" ] && rm -f "$lock"
  git -C "$tree" rebase --abort >/dev/null 2>&1
  for c in $CT_SALVAGE_PATHS; do
    [ -e "$tree/$c" ] || continue
    git -C "$tree" add -- "$c" || return 1
  done
  ct_unstage_unparsable "$tree"
  if ! git -C "$tree" diff --cached --quiet; then
    git -C "$tree" commit -q -m "$job: salvaged from a run that was dropped" || return 1
  fi
  # Oldest first; one origin/master already holds as the same patch (pushed
  # by tools/push_puzzle_commit.sh, which leaves the local commit) is skipped.
  for c in $(git -C "$tree" cherry origin/master HEAD | sed -n 's/^+ //p'); do
    msg=$(git -C "$tree" log -1 --format=%s "$c")
    if (cd "$tree" && bash tools/push_puzzle_commit.sh "$c" >/dev/null 2>&1); then
      echo "WORKTREE: salvaged and pushed: $msg" >&2
    else
      failed=1
    fi
  done
  if [ "$failed" = 1 ]; then
    c="salvage/$job-$(date +%Y%m%d-%H%M%S)"
    git -C "$tree" branch -q "$c" HEAD || return 1
    echo "WORKTREE: a dropped run's commit would not push; kept on branch $c" >&2
    . "$(dirname "${BASH_SOURCE[0]}")/alert.sh" 2>/dev/null &&
      alert "$job: a dropped run left commits that would not push onto origin/master (a conflict?). They are kept on local branch $c; cherry-pick them from a worktree."
  fi
  return 0
}

if [ "${CT_IN_WORKTREE:-0}" != 1 ] && [ "${CT_NO_WORKTREE:-0}" != 1 ]; then
  _ct_main="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  _ct_job="$(basename "$0" .sh)"
  _ct_tree="${CT_WORKTREE_ROOT:-$HOME/.cryptic-teacher}/$_ct_job"

  # Trim the jobs' logs before the run writes to them. They all live in the
  # main checkout whichever tree the job runs from, so they are trimmed together
  # here, at the one point every scheduled job passes through.
  #
  # Truncating in place is the rotation that works: the scheduler holds the log open
  # in append mode for the whole run, so renaming it sends tonight's output to
  # the renamed file, while an append write after a truncate lands at the new
  # end. A log is read when something failed, and what failed is recent.
  for _ct_log in "$_ct_main"/.*.log; do
    [ -f "$_ct_log" ] || continue
    [ "$(wc -c <"$_ct_log")" -gt "${CT_LOG_MAX_BYTES:-2000000}" ] || continue
    if tail -c "${CT_LOG_KEEP_BYTES:-1000000}" "$_ct_log" >"$_ct_log.trim"; then
      cat "$_ct_log.trim" >"$_ct_log"
      echo "=== trimmed $(basename "$_ct_log") to its last $(wc -c <"$_ct_log" | tr -d ' ') bytes ==="
    fi
    rm -f "$_ct_log.trim"
  done

  if [ ! -d "$_ct_tree/.git" ] && [ ! -f "$_ct_tree/.git" ]; then
    # Quiet: the first run checks out 45k files and the progress meter writes a
    # line per percent into a log somebody has to read a failure out of.
    git -C "$_ct_main" worktree add -q --detach "$_ct_tree" origin/master || {
      echo "WORKTREE: cannot create $_ct_tree" >&2
      _ct_tree=""
    }
  fi

  if [ -n "$_ct_tree" ]; then
    # Objects come through the main checkout because that is where the remote
    # is configured; the worktree shares the store, so the fetch is one fetch.
    git -C "$_ct_main" fetch -q origin master || {
      echo "WORKTREE: fetch failed — working from whatever origin/master was last known" >&2
    }
    _ct_follow_origin
    # A job that files into git as it goes (tools/durable.sh) sets
    # CT_SALVAGE_PATHS: any local commit a dropped run (SIGKILL, OOM, reboot,
    # a failed push) left, and what it filed under those paths uncommitted
    # (none when set empty), is pushed here before the reset below discards it.
    if [ -n "${CT_SALVAGE_PATHS+set}" ]; then
      _ct_salvage "$_ct_tree" "$_ct_job" || {
        echo "WORKTREE: cannot salvage $_ct_tree — the dropped run's work is parked, not reset" >&2
        _ct_tree=""
      }
    fi
    # Tracked files back to the branch, untracked state left alone. A leftover
    # from a crashed run is discarded here rather than committed tonight.
    if ! git -C "$_ct_tree" reset -q --hard origin/master; then
      # git holds an index.lock for the length of one command, so one still
      # there minutes later belongs to a process that is gone. Nothing will
      # ever clear it on its own, and while it sits there every run of this job
      # fails the same way, so it is taken over rather than waited on.
      _ct_lock="$(git -C "$_ct_tree" rev-parse --git-dir)/index.lock"
      if [ -f "$_ct_lock" ] && [ -z "$(find "$_ct_lock" -mmin -10)" ]; then
        echo "WORKTREE: clearing an index.lock from $(date -r "$_ct_lock" '+%H:%M') with no live git behind it" >&2
        rm -f "$_ct_lock"
      fi
      git -C "$_ct_tree" reset -q --hard origin/master || {
        echo "WORKTREE: cannot reset $_ct_tree" >&2
        _ct_tree=""
      }
    fi
  fi

  if [ -n "$_ct_tree" ]; then
    # The generated files are not tracked, so a tree just reset to origin/master
    # has either none of them (a tree made tonight) or the ones the last run
    # left, describing files the reset has since changed. Every job reads them —
    # and every page in the tree names them by content hash — long before the
    # job reaches its own build step, so they are rebuilt once, here, where the
    # tree changed.
    # A rebuild reads every puzzle (40k files): minutes of CPU. Untracked files
    # survive the reset, so when HEAD is where the last fully successful
    # rebuild stamped it they are current and the rebuild is skipped. A script
    # that reads none of them sets CT_GENERATED=none (unexported) before
    # sourcing this and gets no rebuild at all.
    _ct_head="$(git -C "$_ct_tree" rev-parse HEAD)"
    _ct_stamp="$(git -C "$_ct_tree" rev-parse --absolute-git-dir)/generated.stamp"
    if [ "${CT_GENERATED:-}" = none ]; then
      :
    elif [ "$(cat "$_ct_stamp" 2>/dev/null)" != "$_ct_head" ] || [ ! -e "$_ct_tree/puzzles/index.json" ]; then
      rm -f "$_ct_stamp"
      _ct_ok=1
      (cd "$_ct_tree" && python3 tools/fetch_puzzle.py --reindex >/dev/null) ||
        { _ct_ok=0; echo "WORKTREE: could not rebuild puzzles/index.* in $_ct_tree — the job will read a stale or missing manifest" >&2; }
      (cd "$_ct_tree" && python3 tools/build_abbreviations.py >/dev/null) ||
        { _ct_ok=0; echo "WORKTREE: could not rebuild abbreviations.js in $_ct_tree — every tool that stamps a page referencing it will stop" >&2; }
      [ "$_ct_ok" = 1 ] && printf '%s\n' "$_ct_head" >"$_ct_stamp"
    fi
    # One copy of each, in the main checkout, reached from everywhere.
    for _ct_share in .claude .alert-state .usage_cache.json; do
      [ -e "$_ct_tree/$_ct_share" ] && continue
      [ -e "$_ct_main/$_ct_share" ] || continue
      ln -s "$_ct_main/$_ct_share" "$_ct_tree/$_ct_share"
    done
    export CT_IN_WORKTREE=1
    export CT_MAIN_CHECKOUT="$_ct_main"
    echo "=== running in $_ct_tree @ $(git -C "$_ct_tree" rev-parse --short HEAD) ==="
    # Sourced, not run: bash reads a script FILE as it goes, and the job's own
    # publish rebases this tree, so a rebase that rewrites the script would
    # resume the new file at the old byte offset. `.` reads the whole file
    # before running any of it. $0 stays the tree's path for dirname "$0".
    exec /bin/bash -c '. "$0"' "$_ct_tree/tools/$(basename "$0")" "$@"
  fi

  # No worktree, no run. The main checkout is not a fallback: it has other
  # writers, and "clean and at origin/master" is a snapshot, not a lease —
  # it says nothing about the edit that lands a minute later. A job that rebases
  # over one wedges that tree with a conflict it cannot resolve and throws away
  # the annotation it just paid for. Stopping costs one window; the next run
  # clears whatever was stuck and gets its worktree back.
  echo "WORKTREE: no worktree for $_ct_job under ${CT_WORKTREE_ROOT:-$HOME/.cryptic-teacher} — stopping without running." >&2
  . "$_ct_main/tools/alert.sh" 2>/dev/null &&
    alert "$_ct_job could not get its own worktree and will not run in the main checkout. Nothing ran and nothing was spent. Fix the worktree under ${CT_WORKTREE_ROOT:-$HOME/.cryptic-teacher}."
  exit 1
fi

# Retry one fetch+rebase+push attempt through the ref-lock race two worktrees
# of the SAME repo can hit on refs/remotes/origin/master: this job and its
# sibling (daily_update.sh's nightly run and prereset_backfill.sh's burn, or
# two runs of the same job) each keep their own worktree but share one
# .git, and so one refs/remotes/origin/master. A fetch or push that lands
# while the other is mid-fetch/push fails with "cannot lock ref
# 'refs/remotes/origin/master': is at X but expected Y" — the ref moved
# under us, not a real disagreement, so redoing the whole attempt against
# wherever it landed clears it.
#
# $1 names a function that performs one whole attempt (fetch, rebase, any
# conflict handling, push) and returns its exit status; everything it writes
# to stdout/stderr is preserved either way. The attempt returns
# PUSH_RACED (75) when its push was refused because origin moved after its
# fetch (push_or_raced below): another worktree published in between, so the
# attempt is redone against the new tip too. Any other failure returns
# immediately — retrying a real conflict would only spin.
PUSH_RACED=75
# git push origin HEAD:master, returning PUSH_RACED when the only refusal is
# that origin is no longer an ancestor of HEAD (another push landed since this
# attempt's fetch). Read from --porcelain, git's machine-readable push report.
push_or_raced() {
  local out rc
  out=$(git push --porcelain -q origin HEAD:master 2>&1)
  rc=$?
  [ "$rc" -eq 0 ] && return 0
  printf '%s\n' "$out" >&2
  printf '%s\n' "$out" | grep -qE '^!	[^	]*	\[rejected\] \((fetch first|non-fast-forward)\)$' && return "$PUSH_RACED"
  return "$rc"
}

push_race_retry() {
  local fn="$1" attempt out rc
  for attempt in 1 2 3 4 5; do
    out=$("$fn" 2>&1)
    rc=$?
    [ -n "$out" ] && printf '%s\n' "$out" >&2
    [ "$rc" -eq 0 ] && return 0
    [ "$rc" -eq "$PUSH_RACED" ] || printf '%s' "$out" | grep -q "cannot lock ref" || return "$rc"
    echo "push race: origin/master moved under us (attempt $attempt) — retrying" >&2
    sleep "$attempt"
  done
  return "$rc"
}
