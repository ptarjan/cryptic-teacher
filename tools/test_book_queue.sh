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
mkdir -p "$tree/tools/data" "$tree/puzzles"
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

# One puzzle filed against book 1 (numbers are book_index * 1000 + position).
echo '{}' > "$tree/puzzles/book-1007.json"

got="$(cd "$tree" && python3 tools/book_queue.py | cut -f1 | tr '\n' ' ')"
# A book with a puzzle in the corpus is read; the rest are offered best first,
# and the one nothing measured goes last rather than being dropped.
check "order, best first, unranked last" "unread-best unread-worse unranked " "$got"
check "a book the corpus already holds is not offered" "" "$(echo "$got" | grep -o read-one)"
check "--next names the head of that queue" "unread-best" \
  "$(cd "$tree" && python3 tools/book_queue.py --next)"
check "--count counts the unread, not the registry" "3" \
  "$(cd "$tree" && python3 tools/book_queue.py --count)"

# Every book read: --next must FAIL rather than print nothing, or the caller
# cannot tell "finished" from "broken" and alerts on a finished queue.
for n in 2007 3007 4007; do echo '{}' > "$tree/puzzles/book-$n.json"; done
check "--count is 0 once every book is read" "0" \
  "$(cd "$tree" && python3 tools/book_queue.py --count)"
(cd "$tree" && python3 tools/book_queue.py --next >/dev/null 2>&1)
check "--next exits non-zero on an empty queue" "1" "$?"

# The real registries must still parse and agree with each other, since the
# fixtures above cannot catch a row that lost its identifier.
(cd "$REPO" && python3 tools/book_queue.py >/dev/null 2>&1)
check "the real registry still produces a queue" "0" "$?"

[ "$fails" = 0 ] && echo "PASSED" || { echo "$fails FAILED"; exit 1; }
