#!/bin/bash
# Read the next archive.org crossword books nobody has read yet — up to three
# loans a run, then every book due.
#
# WHY THIS IS A SCHEDULE AND NOT A LOOP. The only thing standing between them and the corpus is archive.org's
# lending limit. That limit counts loans TAKEN over a period archive.org does
# not publish, it is not cleared by returning anything, and the account has been
# refused for hours while holding zero loans — so there is no interval a script
# can wait out and no counter it can read. The only way to learn whether the
# account may borrow again is to ask. Asking costs one request and takes no
# loan, so this asks on a schedule and a refusal is not a failure: it is the
# answer "not yet", and the run exits 0 having spent nothing. It asks hourly
# (household-plugins/cryptic-books/plugin.toml).
#
# SEVERAL BOOKS PER RUN. A loan is held only while its pages are fetched
# (minutes) and the text then sits on disk, so the borrow and the read are
# separate: up to BORROWS_PER_RUN loans, stopping at the first refusal rather
# than collecting one per book, then every due book with text on disk is read,
# its grid searches on the desktop when it answers. Before 2026-10-06 this took
# one book per run, and a run's two books took 1-2 hours of this box's CPU, so
# the hourly schedule mostly found the previous run still holding the lock.
#
# WHICH BOOK: tools/book_queue.py, best first — see its header for why "unread"
# means no puzzles at all rather than a fraction of an estimate.
#
# THE LOAN IS ALWAYS RETURNED. tools/fetch_ia_book.py's borrowed() returns it on
# normal exit, exception and Ctrl-C alike, so the run below cannot strand one;
# the reconcile in the EXIT trap is for the case that context manager never gets
# to run — the process killed outright, the container stopped mid-fetch. It
# reads the loan ledger and returns anything left open, and it is the only
# reason this job can be killed at any moment without owing archive.org a book.
#
# Scheduled by household-plugins/cryptic-books/plugin.toml, symlinked from
# ~/.config/household/plugins/cryptic-books; after an edit run
# `tools/plugins.py --write` in the household repo. Never a second cron.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# A checkout of nobody else's — see tools/nightly_worktree.sh. What a dropped
# read filed is pushed by the next start (CT_SALVAGE_PATHS), and while a read
# runs it is committed every few minutes (tools/durable.sh).
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS="puzzles clues_only"
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
. "$REPO/tools/alert.sh"
# shellcheck disable=SC2034  # read by the sourced durable.sh
DURABLE_PATHS=(puzzles clues_only)
. "$REPO/tools/durable.sh"

# Return anything the run left open, on every path out of this script.
trap 'python3 "$REPO/tools/fetch_ia_book.py" --loans 2>&1 | sed "s/^/loans: /"' EXIT

echo "=== $(date '+%Y-%m-%d %H:%M:%S') acquire_books"

# Commit what a read filed, plus the read ledger, and push. Prints the count.
# One retry: the daily job and the pre-reset burn push to the same branch, so
# losing a race is ordinary and being unable to push twice is not.
publish() {  # publish <subject>
  local n
  n="$(git status --porcelain -uall -- puzzles/ clues_only/ | wc -l | tr -d ' ')"
  echo "filed $n puzzles"
  git add -A -- puzzles/ tools/data/book_reads.json
  # Puzzles held as their clues alone (tools/clues_only.py). git add refuses a
  # pathspec that matches nothing, and the folder exists only once one is held.
  if [ -e clues_only ] || [ -n "$(git ls-files clues_only)" ]; then
    git add -A -- clues_only/
  fi
  git diff --cached --quiet && return 0
  git commit -q -m "$1: $n puzzles" \
    -m "Filed unsolved by tools/acquire_book.py, with a grid or as clues only; the nightly solve queue takes them from here." ||
    return 1
  git fetch -q origin master && git rebase -q --autostash origin/master &&
    git push -q origin HEAD:master || {
    git fetch -q origin master && git rebase -q --autostash origin/master &&
      git push -q origin HEAD:master; } || return 1
  echo "pushed"
}

# The grid searches run on Paul's desktop when it answers (tools/ocr_remote.py,
# which yields it the moment he games); OCR_REMOTE= keeps them here.
export OCR_REMOTE="${OCR_REMOTE-micro@100.68.145.15,micro@192.168.1.198}"

# BORROW: up to BORROWS_PER_RUN books' text onto disk, each loan returned as
# soon as its pages are read (minutes). Only the text needs a loan; the read
# below takes it from disk. The first refusal ends the borrowing.
BORROWS_PER_RUN=3
rc=0
for _ in $(seq "$BORROWS_PER_RUN"); do
  id="$(python3 tools/book_queue.py --next)" || break
  echo "borrowing $id ($(python3 tools/book_queue.py --count) queued)"
  nice -n 19 python3 tools/acquire_book.py "$id" --text-only
  rc=$?
  [ "$rc" = 0 ] || break
done

# READ every due book whose text is on disk: the ones just borrowed and the
# ones a reader change made due (RE-READS in tools/book_queue.py). A book is
# started only inside READ_START_SECONDS and capped at 90 minutes, so a run
# ends inside the plugin's 3-hour timeout. acquire_book.py skips every leaf
# already filed, and puzzles are filed as each search lands, so a cut-short
# read keeps what it derived; it is recorded as read all the same, or the
# same book would hold every run's slot forever.
READ_START_SECONDS=3600
read_started=$SECONDS
for book in $(python3 tools/book_queue.py --reread); do
  [ $((SECONDS - read_started)) -lt "$READ_START_SECONDS" ] || break
  echo "reading $book from its text on disk"
  durable_run "Read $book (so far)" \
    timeout 5400 nice -n 19 python3 tools/acquire_book.py "$book" --file --puzzle-dir puzzles --jobs 2 --no-borrow
  if [ $? = 124 ]; then
    echo "read of $book cut short at 90 minutes; recorded as read"
    python3 -c 'import sys; sys.path.insert(0, "tools"); import book_queue as q; q.record_read(sys.argv[1], None, None)' "$book"
  fi
  publish "Read $book" ||
    alert "read $book but could not commit or push its puzzles — they are in $PWD. See .books.log."
done

# 3 is EXIT_LENDING_LIMIT: the account is over its allowance, which says
# nothing about this book. Silent for the first refusals, once at about ten
# days of them, then about monthly while it lasts, and once when it clears.
# The thresholds count runs; RUN_HOURS turns runs into days and must match the
# plugin manifest's schedule.
STREAK_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/cryptic-teacher/lending-refusals"
streak="$(cat "$STREAK_FILE" 2>/dev/null || echo 0)"
case "$streak" in ''|*[!0-9]*) streak=0 ;; esac
streak_write() {
  mkdir -p "$(dirname "$STREAK_FILE")" 2>/dev/null || true
  printf '%s\n' "$1" > "$STREAK_FILE" 2>/dev/null || true
}
RUN_HOURS=1            # the plugin manifest asks hourly
STREAK_ALERT_AT=240    # so: about ten days of refusals
STREAK_ALERT_EVERY=720 # and about a month between reminders after that

if [ "$rc" = 3 ]; then
  streak=$((streak + 1))
  streak_write "$streak"
  echo "lending limit — no loan taken, nothing filed; next run asks again (refusal $streak in a row)"
  if [ "$streak" = "$STREAK_ALERT_AT" ] ||
     { [ "$streak" -gt "$STREAK_ALERT_AT" ] &&
       [ $((streak % STREAK_ALERT_EVERY)) = 0 ]; }
  then
    alert "archive.org has refused this account a loan $streak times in a row, so $(python3 tools/book_queue.py --count) registered books are still at zero puzzles and nothing here will change that. Every one of them reports a free copy — the block is on the account, not the books, and archive.org holds no loan of ours. Its own answer is \"Please try again later or contact info@archive.org\", and later has now been about $((streak * RUN_HOURS / 24)) day(s). Write to them, or accept that the book shelf stops here."
  fi
  exit 0
fi
if [ "$rc" != 0 ]; then
  alert "borrowing $id off archive.org failed (exit $rc) and it was NOT a lending refusal, so every retry will hit the same wall on the same book until someone looks. See .books.log."
  exit 1
fi

if [ "$streak" -ge "$STREAK_ALERT_AT" ]; then
  ALERT_ICON="✅" alert "archive.org is lending to this account again after $streak refused runs — the book job is reading $id now and will work through the remaining queue."
fi
streak_write 0

