#!/bin/bash
# Read the next archive.org crossword book nobody has read yet — one book, one
# loan, one run.
#
# WHY THIS IS A SCHEDULE AND NOT A LOOP. 24 registered books hold no puzzle at
# all, and the only thing standing between them and the corpus is archive.org's
# lending limit. That limit counts loans TAKEN over a period archive.org does
# not publish, it is not cleared by returning anything, and the account has been
# refused for hours while holding zero loans — so there is no interval a script
# can wait out and no counter it can read. The only way to learn whether the
# account may borrow again is to ask. Asking costs one request and takes no
# loan, so this runs hourly and a refusal is not a failure: it is the answer
# "not yet", and the run exits 0 having spent nothing.
#
# ONE BOOK PER RUN, deliberately. A loan is one hour and one copy; taking at
# most one an hour is the slowest rate that still finishes, and it means a
# refusal stops this run rather than failing 24 times in a row and burning the
# allowance the refusal was protecting.
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
# Install: a plugin manifest at ~/.config/household/plugins/cryptic-books/,
# then `tools/plugins.py --write` in the household repo. Never a second cron.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# A checkout of nobody else's — see tools/nightly_worktree.sh.
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
. "$REPO/tools/alert.sh"

# Return anything the run left open, on every path out of this script.
trap 'python3 "$REPO/tools/fetch_ia_book.py" --loans 2>&1 | sed "s/^/loans: /"' EXIT

echo "=== $(date '+%Y-%m-%d %H:%M:%S') acquire_books"

id="$(python3 tools/book_queue.py --next)"
if [ -z "$id" ]; then
  echo "every registered book has been read — nothing queued"
  exit 0
fi
echo "next unread book: $id ($(python3 tools/book_queue.py --count) still unread)"

python3 tools/acquire_book.py "$id" --file --puzzle-dir puzzles
rc=$?

# 3 is EXIT_LENDING_LIMIT: the account is over its allowance, which says
# nothing about this book and nothing this run can act on. One refusal is not
# worth an alert — an hourly poll that shouts on every refusal is a channel
# nobody reads by Tuesday. A refusal that never stops is a different thing: on
# 2026-09-21 this job had been refused 39 hours running, the 24 books were
# still at zero puzzles, and the only reason anyone found out was a ranked
# audit of a question being asked for the 16th time. A streak past a day is no
# longer "not yet", it is an account archive.org will not unblock on its own,
# and the message it returns names the address to write to. So: silent for the
# first day, once at a day, then once a week while it lasts, and once more when
# it clears.
STREAK_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/cryptic-teacher/lending-refusals"
streak="$(cat "$STREAK_FILE" 2>/dev/null || echo 0)"
case "$streak" in ''|*[!0-9]*) streak=0 ;; esac
streak_write() {
  mkdir -p "$(dirname "$STREAK_FILE")" 2>/dev/null || true
  printf '%s\n' "$1" > "$STREAK_FILE" 2>/dev/null || true
}
STREAK_ALERT_AT=24      # a full day of hourly asks
STREAK_ALERT_EVERY=168  # and weekly after that

if [ "$rc" = 3 ]; then
  streak=$((streak + 1))
  streak_write "$streak"
  echo "lending limit — no loan taken, nothing filed; next run asks again (refusal $streak in a row)"
  if [ "$streak" = "$STREAK_ALERT_AT" ] ||
     { [ "$streak" -gt "$STREAK_ALERT_AT" ] &&
       [ $((streak % STREAK_ALERT_EVERY)) = 0 ]; }
  then
    alert "archive.org has refused this account a loan $streak hours in a row, so $(python3 tools/book_queue.py --count) registered books are still at zero puzzles and nothing here will change that. Every one of them reports a free copy — the block is on the account, not the books, and archive.org holds no loan of ours. Its own answer is \"Please try again later or contact info@archive.org\", and later has now been $((streak / 24)) day(s). Write to them, or accept that the book shelf stops here."
  fi
  exit 0
fi
if [ "$rc" != 0 ]; then
  alert "reading $id off archive.org failed (exit $rc) and it was NOT a lending refusal, so the hourly retry will hit the same wall on the same book every hour until someone looks. See .books.log."
  exit 1
fi

if [ "$streak" -ge "$STREAK_ALERT_AT" ]; then
  ALERT_ICON="✅" alert "archive.org is lending to this account again after $streak hours of refusals — the hourly book job is reading $id now and will work through the remaining queue an hour at a time."
fi
streak_write 0

filed="$(git status --porcelain -- puzzles/ | wc -l | tr -d ' ')"
if [ "$filed" = 0 ]; then
  alert "reading $id off archive.org succeeded but filed no puzzle, so the queue will offer the same book every hour forever. Its report says why it rejected every leaf. See .books.log."
  exit 1
fi
echo "filed $filed puzzles from $id"

git add -A -- puzzles/
git commit -q -m "Read $id off archive.org: $filed puzzles" \
  -m "Filed unsolved by tools/acquire_book.py; the nightly solve queue takes them from here." || {
  alert "could not commit the $filed puzzles read from $id — they are in $PWD and nothing else will pick them up. See .books.log."
  exit 1
}
# One retry, then say so: the daily job and the pre-reset burn push to the same
# branch, so losing a race is ordinary and being unable to push twice is not.
git fetch -q origin master && git rebase -q --autostash origin/master &&
  git push -q origin HEAD:master || {
  git fetch -q origin master && git rebase -q --autostash origin/master &&
    git push -q origin HEAD:master ||
    alert "read $filed puzzles from $id and committed them, but could not push — they will not reach the site until someone pushes $PWD. See .books.log."
}
echo "pushed"
