#!/bin/bash
# Does tools/book_queue.py still offer the right book to tools/acquire_books.sh?
#
#     bash tools/test_book_queue.sh
#
# This queue drives an UNATTENDED scheduled job that spends a one-hour archive.org
# loan on whatever it names. Two ways to get that wrong, and both are silent:
# offering a book the corpus already holds burns the account's allowance
# re-reading it, and dropping a book nobody has read leaves it unread forever
# with the log saying the queue is empty. Neither shows up anywhere a person
# looks, so they are asserted here.
#
# The fixtures are synthetic registries in a temp tree — no loan, no network,
# and no dependence on how many books happen to be read today.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

tree="$(mktemp -d)"
trap 'rm -rf "$tree"' EXIT
# Cached book text lives under $XDG_STATE_HOME; keep the real one out of it.
export XDG_STATE_HOME="$tree/state"
mkdir -p "$tree/tools/data" "$tree/puzzles/book/2000"
cp "$REPO/tools/book_queue.py" "$tree/tools/"

cat > "$tree/tools/data/books.json" <<'JSON'
{"books": [
 {"book_index": 1, "identifier": "read-one", "title": "Read One"},
 {"book_index": 2, "identifier": "unread-best", "title": "Unread Best"},
 {"book_index": 3, "identifier": "unread-worse", "title": "Unread Worse"},
 {"book_index": 4, "identifier": "unranked", "title": "Registered But Unranked"}]}
JSON
cat > "$tree/tools/data/book_candidates.json" <<'JSON'
{"ranking": [
 {"identifier": "read-one", "estimated_puzzle_count": 70},
 {"identifier": "unread-best", "estimated_puzzle_count": 80},
 {"identifier": "unread-worse", "estimated_puzzle_count": 90}]}
JSON

# One puzzle filed against book 1 (numbers are book_index * 1000 + position),
# read by the reader in force (see RE-READS below).
echo '{}' > "$tree/puzzles/book/2000/book-1007.json"
reads_all() { echo '{"read-one": {"on": "9999-01-01"}, "unread-best": {"on": "9999-01-01"},
 "unread-worse": {"on": "9999-01-01"}, "unranked": {"on": "9999-01-01"}}' \
  > "$tree/tools/data/book_reads.json"; }
echo '{"read-one": {"on": "9999-01-01"}}' > "$tree/tools/data/book_reads.json"

got="$(cd "$tree" && python3 tools/book_queue.py | cut -f1 | tr '\n' ' ')"
# A book with a puzzle in the corpus is read; the rest are offered best first,
# and the one nothing measured goes last rather than being dropped.
check "order, best first, unranked last" "unread-best unread-worse unranked " "$got"
check "a book the corpus already holds is not offered" "" "$(echo "$got" | grep -o read-one)"
check "--next names the head of that queue" "unread-best" \
  "$(cd "$tree" && python3 tools/book_queue.py --next)"
check "--count counts the unread, not the registry" "3" \
  "$(cd "$tree" && python3 tools/book_queue.py --count)"

# A pin jumps the ranking, an already-read or unknown pin is skipped.
echo '{"pinned": ["read-one", "no-such-book", "unranked"]}' > "$tree/tools/data/book_pins.json"
check "pinned book comes first; read and unknown pins are skipped" \
  "unranked unread-best unread-worse " \
  "$(cd "$tree" && python3 tools/book_queue.py | cut -f1 | tr '\n' ' ')"
rm "$tree/tools/data/book_pins.json"

# Every book read: --next must FAIL rather than print nothing, or the caller
# cannot tell "finished" from "broken" and alerts on a finished queue.
for n in 2007 3007 4007; do echo '{}' > "$tree/puzzles/book/2000/book-$n.json"; done
reads_all
check "--count is 0 once every book is read" "0" \
  "$(cd "$tree" && python3 tools/book_queue.py --count)"
(cd "$tree" && python3 tools/book_queue.py --next >/dev/null 2>&1)
check "--next exits non-zero on an empty queue" "1" "$?"

# RE-READS. Every book above is filed and none has a read on record, so all
# are due. The ones whose text is on disk are re-read with no loan; the rest
# go back to the borrow queue, behind any unread book.
rm "$tree/tools/data/book_reads.json"
mkdir -p "$tree/state/cryptic-teacher/ia-books"
echo text > "$tree/state/cryptic-teacher/ia-books/read-one.txt"
echo text > "$tree/state/cryptic-teacher/ia-books/unread-best.sample-6p.txt"
check "a due book with cached text is re-read, a sample is not a book" "read-one" \
  "$(cd "$tree" && python3 tools/book_queue.py --reread | tr '\n' ' ' | sed 's/ $//')"
check "a due book whose text is gone is borrowed again" \
  "unread-best unread-worse unranked " \
  "$(cd "$tree" && python3 tools/book_queue.py | cut -f1 | tr '\n' ' ')"
# A read on or after REREAD_BEFORE takes a book off both lists.
(cd "$tree/tools" && python3 -c '
import book_queue as q
for i in ("read-one", "unread-best", "unread-worse", "unranked"):
    q.record_read(i, 60, 50)')
check "a book read by the reader in force is not re-read" "" \
  "$(cd "$tree" && python3 tools/book_queue.py --reread)"
check "nor borrowed again" "0" "$(cd "$tree" && python3 tools/book_queue.py --count)"
# A book never read whose text is on disk is re-read, never borrowed.
rm "$tree/tools/data/book_reads.json" "$tree/puzzles/book/2000/book-2007.json"
echo text > "$tree/state/cryptic-teacher/ia-books/unread-best.txt"
check "an unread book with text on disk is not borrowed" "" \
  "$(cd "$tree" && python3 tools/book_queue.py | cut -f1 | grep -x unread-best)"

# The real registries must still parse and agree with each other, since the
# fixtures above cannot catch a row that lost its identifier.
(cd "$REPO" && python3 tools/book_queue.py >/dev/null 2>&1)
check "the real registry still produces a queue" "0" "$?"

[ "$fails" = 0 ] && echo "PASSED" || { echo "$fails FAILED"; exit 1; }
