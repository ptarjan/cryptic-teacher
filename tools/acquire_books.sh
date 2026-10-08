#!/bin/bash
# Read the archive.org crossword books nobody has read yet, as a queue of small
# units (tools/unit_queue.py, tools/book_units.py): one loan or one book each.
#
#     tools/acquire_books.sh                 # a tick: start every due unit, detached; returns in seconds
#     tools/acquire_books.sh unit <key>      # one unit, in a tree of its own (what a tick starts)
#     python3 tools/unit_queue.py status books
#
# The units: borrow:<id> takes one loan, fetches that book's text onto disk
# and returns the loan (minutes); read:<id> reads one book from its text on
# disk, its grid searches on the desktop when it answers; supersede turns a
# held book file that reprints a held newspaper puzzle into a reading of it.
# Each has its own lock, time limit and worktree, so one slow book holds up
# only itself, and a book borrowed now is read at the next tick rather than
# behind every other read.
#
# WHY THE LOANS ARE ASKED FOR ON A SCHEDULE AND NOT IN A LOOP. The only thing
# standing between the books and the corpus is archive.org's lending limit.
# That limit counts loans TAKEN over a period archive.org does not publish, it
# is not cleared by returning anything, and the account has been refused for
# hours while holding zero loans — so there is no interval a script can wait
# out and no counter it can read. The only way to learn whether the account may
# borrow again is to ask. Asking costs one request and takes no loan, so a
# borrow unit asks, and a refusal is not a failure: it is the answer "not yet",
# and tools/book_units.py asks again an hour later (REFUSAL_WAIT), taking at
# most BORROWS_PER_HOUR loans an hour.
#
# WHICH BOOK: tools/book_queue.py, best first — see its header for why "unread"
# means no puzzles at all rather than a fraction of an estimate.
#
# THE LOAN IS ALWAYS RETURNED. tools/fetch_ia_book.py's borrowed() returns it on
# normal exit, exception and Ctrl-C alike, so a borrow unit cannot strand one;
# the reconcile in its EXIT trap is for the case that context manager never gets
# to run — the process killed outright, the container stopped mid-fetch. It
# reads the loan ledger and returns anything left open, and it is the only
# reason this job can be killed at any moment without owing archive.org a book.
# Only a borrow unit runs it: loans are taken one at a time (book_units.py
# LIMITS), so whatever is open when one starts or ends is nobody's.
#
# Scheduled by household-plugins/cryptic-books/plugin.toml, symlinked from
# ~/.config/household/plugins/cryptic-books; after an edit run
# `tools/plugins.py --write` in the household repo. Never a second cron.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
# A tick runs in the tree acquire_books and reads only the ledgers, so it
# rebuilds no generated file; a unit in one of book_units.py's trees,
# acquire_book-1 .. -SLOTS, leased to it by tools/unit_queue.py (CT_JOB). What a
# dropped read filed is pushed by the next unit to take its tree
# (CT_SALVAGE_PATHS), and while a read runs it is committed every few minutes
# (tools/durable.sh).
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
[ $# -eq 0 ] && CT_GENERATED=none
# shellcheck disable=SC2034  # read by the sourced nightly_worktree.sh
CT_SALVAGE_PATHS="puzzles clues_only"
. "$(dirname "$0")/nightly_worktree.sh"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
. "$REPO/tools/alert.sh"
# shellcheck disable=SC2034  # read by the sourced durable.sh
DURABLE_PATHS=(puzzles clues_only)
. "$REPO/tools/durable.sh"

if [ $# -eq 0 ]; then
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') acquire_books tick"
  exec python3 tools/unit_queue.py tick books ${UNIT_QUEUE_DRY:+--dry-run}
fi
[ "$1" = unit ] && [ -n "${2:-}" ] || { echo "usage: acquire_books.sh [unit <key>]" >&2; exit 2; }
key="$2"

# Why this run is failing, said on stderr as its LAST line: the bridge
# (household tools/plugin-run.py) reports a non-zero exit with the last line the
# job wrote to stderr, and the tools this calls write their success lines there
# too. fail() sets it; a path out that did not still names its exit status.
FAIL_REASON=""
fail() {  # fail <message>: alert with it, and exit 1 with it on stderr
  alert "$1"
  FAIL_REASON="$1"
  exit 1
}
# A borrow unit returns anything left open, on every path out of it.
on_exit() {
  local rc=$?
  case "$key" in borrow:*) python3 "$REPO/tools/fetch_ia_book.py" --loans 2>&1 | sed "s/^/loans: /" ;; esac
  if [ "$rc" != 0 ] && [ "$rc" != 3 ]; then
    echo "acquire_books: ${FAIL_REASON:-exited $rc with no reason recorded; the lines above in .books.log say why}" >&2
  fi
}
trap on_exit EXIT

echo "=== $(date '+%Y-%m-%d %H:%M:%S') acquire_books $key"

# Commit what a read filed, plus the read ledger, and push. Prints the count.
# One retry: the daily units, the burn and the other book units push to the
# same branch, so losing a race is ordinary and being unable to push twice is not.
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
  local subject="$1"
  [ "$n" = 0 ] || subject="$1: $n puzzles"
  git commit -q -m "$subject" \
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

if [ "$key" = supersede ]; then
  # A book leaf filed here and the newspaper puzzle it reprints, filed by another
  # job before either push reached the other, met in no write: each becomes a
  # reading of the newspaper puzzle now that this tree holds both.
  python3 tools/fetch_puzzle.py --supersede-books ||
    fail "fetch_puzzle.py --supersede-books exited $?; its traceback is above"
  publish "Book reprints of held newspaper puzzles kept as readings" ||
    fail "could not push the superseded book files"
  exit 0
fi

# BORROW: one book's text onto disk, the loan returned as soon as its pages are
# read (minutes). Only the text needs a loan; a read unit takes it from disk.
# 4 is EXIT_NOT_LENDABLE: archive.org lends the book to no one, so
# acquire_book.py wrote it out of the queue (book_queue.record_not_lendable);
# that is published, and the next tick asks for the next book. No loan was
# taken. 3 is EXIT_LENDING_LIMIT, the account's refusal (below). Any other
# failure alerts with what acquire_book.py said it stopped on: its stage-1
# report's status and reason, or, when it died before writing one, the last
# line it printed on stderr; the unit is retried later.
borrow_failure() {  # borrow_failure <id> <started epoch> <stderr file>
  python3 - "$@" <<'PY'
import json, sys
sys.path.insert(0, "tools")
from acquire_book import DEFAULT_OUT
report = DEFAULT_OUT / sys.argv[1] / "report.json"
try:
    r = (json.loads(report.read_text(encoding="utf-8"))
         if report.stat().st_mtime >= int(sys.argv[2]) else {})
except (OSError, ValueError):
    r = {}
if r.get("status"):
    print(f"{r['status']}: {r.get('reason', '')}")
else:
    with open(sys.argv[3], errors="replace") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    print("no report written; it said: " + (lines[-1] if lines else "nothing on stderr"))
PY
}

# 3 is EXIT_LENDING_LIMIT: the account is over its allowance, which says
# nothing about this book. Silent for the first refusals, once at about ten
# days of them, then about monthly while it lasts, and once when it clears.
# The thresholds count refusals; tools/book_units.py asks once an hour after
# one (REFUSAL_WAIT), so RUN_HOURS turns them into days and must match it.
STREAK_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/cryptic-teacher/lending-refusals"
streak_write() {
  mkdir -p "$(dirname "$STREAK_FILE")" 2>/dev/null || true
  printf '%s\n' "$1" > "$STREAK_FILE" 2>/dev/null || true
}
RUN_HOURS=1            # book_units.py REFUSAL_WAIT
STREAK_ALERT_AT=240    # so: about ten days of refusals
STREAK_ALERT_EVERY=720 # and about a month between reminders after that

case "$key" in
  borrow:*)
    id="${key#borrow:}"
    streak="$(cat "$STREAK_FILE" 2>/dev/null || echo 0)"
    case "$streak" in ''|*[!0-9]*) streak=0 ;; esac
    # Whatever an earlier borrow left open (one killed outright) first.
    python3 tools/fetch_ia_book.py --loans 2>&1 | sed "s/^/loans: /"
    echo "borrowing $id ($(python3 tools/book_queue.py --count) queued)"
    borrow_err="$(mktemp "${TMPDIR:-/tmp}/acquire-books-err.XXXXXX")"
    started="$(date +%s)"
    nice -n 19 python3 tools/acquire_book.py "$id" --text-only 2>"$borrow_err"
    rc=$?
    cat "$borrow_err" >&2
    if [ "$rc" = 4 ]; then
      rm -f "$borrow_err"
      echo "$id: archive.org lends it to no one; out of the queue for good (tools/data/book_reads.json)"
      publish "Drop $id from the book queue: archive.org lends it to no one" ||
        alert "dropped $id from the book queue (archive.org lends it to no one) but could not push the ledger — it is in $PWD. See .books.log."
      exit 0
    fi
    if [ "$rc" = 3 ]; then
      rm -f "$borrow_err"
      streak=$((streak + 1))
      streak_write "$streak"
      echo "lending limit — no loan taken, nothing filed; asked again in an hour (refusal $streak in a row)"
      if [ "$streak" = "$STREAK_ALERT_AT" ] ||
         { [ "$streak" -gt "$STREAK_ALERT_AT" ] &&
           [ $((streak % STREAK_ALERT_EVERY)) = 0 ]; }
      then
        alert "archive.org has refused this account a loan $streak times in a row, so $(python3 tools/book_queue.py --count) registered books are still at zero puzzles and nothing here will change that. Every one of them reports a free copy — the block is on the account, not the books, and archive.org holds no loan of ours. Its own answer is \"Please try again later or contact info@archive.org\", and later has now been about $((streak * RUN_HOURS / 24)) day(s). Write to them, or accept that the book shelf stops here."
      fi
      exit 3
    fi
    if [ "$rc" != 0 ]; then
      why="$(borrow_failure "$id" "$started" "$borrow_err")"
      rm -f "$borrow_err"
      fail "borrowing $id off archive.org failed (exit $rc), and it is asked for again later: ${why:0:600}"
    fi
    rm -f "$borrow_err"
    if [ "$streak" -ge "$STREAK_ALERT_AT" ]; then
      ALERT_ICON="✅" alert "archive.org is lending to this account again after $streak refusals — the book job borrowed $id and will work through the remaining queue."
    fi
    streak_write 0
    echo "$id: its text is on disk; the next tick starts its read"
    exit 0 ;;
  read:*)
    book="${key#read:}"
    # A read is capped at 90 minutes. acquire_book.py skips every leaf already
    # filed, and puzzles are filed as each search lands, so a cut-short read
    # keeps what it derived; it is recorded as read all the same, or the same
    # book would come back every tick forever.
    echo "reading $book from its text on disk"
    durable_run "Read $book (so far)" \
      timeout 5400 nice -n 19 python3 tools/acquire_book.py "$book" --file --puzzle-dir puzzles --jobs 2 --no-borrow
    read_rc=$?
    # 5 is EXIT_NO_PUZZLES: the text holds no puzzle region the reader finds;
    # acquire_book.py recorded a no_puzzles row, so it is not due again. Not a
    # failure: publish the ledger.
    if [ "$read_rc" = 5 ]; then
      echo "$book: no puzzle region in its text; recorded in tools/data/book_reads.json"
      read_rc=0
    fi
    if [ "$read_rc" = 124 ]; then
      echo "read of $book cut short at 90 minutes; recorded as read"
      python3 -c 'import sys; sys.path.insert(0, "tools"); import book_queue as q; q.record_read(sys.argv[1], None, None)' "$book"
      read_rc=0
    fi
    publish "Read $book" ||
      fail "read $book but could not commit or push its puzzles — the next unit to take this tree salvages them. See .books.log."
    exit "$read_rc" ;;
esac
fail "acquire_books.sh: no unit $key"
