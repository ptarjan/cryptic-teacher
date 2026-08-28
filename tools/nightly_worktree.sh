#!/bin/bash
# Move a scheduled job into a checkout of its own, then hand control back.
#
# Sourced as the FIRST thing a scheduled script does. It re-execs that script
# from a private git worktree pinned to origin/master, so a job that runs for
# two hours never shares a working tree with a person editing the repo.
#
# WHY. /Users/pt/github/cryptic-teacher is somebody's editor window. The daily
# job used to run there, which made every one of these true at once:
#
#   * A half-written feature sitting unstaged looked, to the job, exactly like
#     something the job had changed. It was swallowed into "Daily update: fetch
#     latest cryptic" on 2026-08-10 — the work survived, in the wrong commit,
#     and could as easily have been committed broken. The defence was a
#     DIRTY_BEFORE snapshot subtracted from the final status, which then had to
#     be right about renames, spaces in names and staged-vs-unstaged.
#   * The reverse also held: while the job was mid-run, its half-fetched puzzle
#     files were in the tree, so a person could not commit their own work
#     either. The asset stamps span both sets of files, so a partial commit
#     ships an index.html pointing at a puzzles/index.js that isn't there.
#   * `git pull --rebase --autostash` before a push stashed whatever the other
#     writer had in flight, out from under them.
#
# None of that is a bug in the checks. It is one working tree with two writers,
# and the fix is two working trees. A worktree shares the object store, so this
# costs no extra clone and no extra fetch — and because every run starts at
# `reset --hard origin/master`, a run that died halfway leaves nothing for the
# next one to trip over.
#
# What the job gets: a tree containing exactly what it changes. That is why
# these scripts can now `git add -A` and assert a clean tree afterwards instead
# of maintaining a pathspec that has twice been missing the one file that
# mattered.
#
# Untracked state is deliberately NOT copied. It is symlinked back to the main
# checkout, so the usage cache, the alert dedupe and the CLI's settings stay one
# thing across all three trees — otherwise the same alert fires from each job
# and the quota reading is measured three times.
#
# Logs are unaffected: launchd owns the redirect, and it names the main
# checkout's .update.log / .prereset.log. Where the script ran from does not
# change where its output lands.
#
# Set CT_NO_WORKTREE=1 to run in place — for testing a change to one of these
# scripts before it is pushed, since the worktree only ever runs committed code.

if [ "${CT_IN_WORKTREE:-0}" != 1 ] && [ "${CT_NO_WORKTREE:-0}" != 1 ]; then
  _ct_main="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  _ct_job="$(basename "$0" .sh)"
  _ct_tree="${CT_WORKTREE_ROOT:-$HOME/.cryptic-teacher}/$_ct_job"

  if [ ! -d "$_ct_tree/.git" ] && [ ! -f "$_ct_tree/.git" ]; then
    # Quiet: the first run checks out 600 files and the progress meter writes a
    # line per percent into a log somebody has to read a failure out of.
    git -C "$_ct_main" worktree add -q --detach "$_ct_tree" origin/master || {
      echo "WORKTREE: cannot create $_ct_tree — running in place instead" >&2
      _ct_tree=""
    }
  fi

  if [ -n "$_ct_tree" ]; then
    # Objects come through the main checkout because that is where the remote
    # is configured; the worktree shares the store, so the fetch is one fetch.
    git -C "$_ct_main" fetch -q origin master || {
      echo "WORKTREE: fetch failed — working from whatever origin/master was last known" >&2
    }
    # Tracked files back to the branch, untracked state left alone. A leftover
    # from a crashed run is discarded here rather than committed tonight.
    git -C "$_ct_tree" reset -q --hard origin/master || {
      echo "WORKTREE: cannot reset $_ct_tree — running in place instead" >&2
      _ct_tree=""
    }
  fi

  if [ -n "$_ct_tree" ]; then
    # One copy of each, in the main checkout, reached from everywhere.
    for _ct_share in .claude .alert-state .usage_cache.json; do
      [ -e "$_ct_tree/$_ct_share" ] && continue
      [ -e "$_ct_main/$_ct_share" ] || continue
      ln -s "$_ct_main/$_ct_share" "$_ct_tree/$_ct_share"
    done
    export CT_IN_WORKTREE=1
    export CT_MAIN_CHECKOUT="$_ct_main"
    echo "=== running in $_ct_tree @ $(git -C "$_ct_tree" rev-parse --short HEAD) ==="
    exec /bin/bash "$_ct_tree/tools/$(basename "$0")" "$@"
  fi
fi
