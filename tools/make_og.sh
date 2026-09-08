#!/bin/bash
# Render the 1200x630 social cards with headless Chrome, rather than drawing
# pixels by hand, because the cards need real type.
#
#   tools/make_og.sh            og.png — the site card, from tools/og_card.html
#   tools/make_og.sh --all      og.png plus og/<number>.png for every puzzle
#                               whose annotation can carry a card
#   tools/make_og.sh 30066      just that puzzle's card
#
# Every puzzle page unfurls as a clue from THAT puzzle (2026-08-08). One shared
# card meant a hundred different pages all previewing the same crossword; which
# clue each puzzle shows is decided by make_og_card.py's score(), not here.
#
# --all only redraws a card older than its puzzle file, so the nightly job costs
# one Chrome launch rather than a hundred. Touch the puzzle, or delete the png,
# to force one.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
# Any headless Chrome will do, and which one is installed is a property of the
# machine, not of this script. The macOS app bundle is only the first guess.
CHROME="${CHROME:-}"
if [ -z "$CHROME" ]; then
  for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    google-chrome chromium chromium-browser
  do
    if [ -x "$candidate" ] || command -v "$candidate" >/dev/null 2>&1; then
      CHROME="$candidate"
      break
    fi
  done
fi
if [ -z "$CHROME" ]; then
  echo "make_og.sh: no headless Chrome found, so no social card was drawn." \
       "Install one or set CHROME to its path." >&2
  exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --no-sandbox because the only machine that runs this on a schedule is a
# container without the kernel namespaces Chrome's sandbox is built out of,
# and the page being opened is a file this script generated one line earlier
# — never a URL, never anything a stranger wrote. --disable-dev-shm-usage for
# the same container: Docker's default /dev/shm is 64MB and Chrome renders a
# 1200x630 page into it and dies.
#
# Chrome's own diagnosis is kept and printed only when the shot fails. Sent
# to /dev/null unconditionally it took the reason with it, and a card that
# did not get drawn is exactly when you want to know why.
shot() {  # shot <html> <png>
  local err
  if ! err=$("$CHROME" --headless --no-sandbox --disable-gpu \
      --disable-dev-shm-usage --hide-scrollbars \
      --screenshot="$2" --window-size=1200,630 "file://$1" 2>&1); then
    echo "make_og.sh: $CHROME could not draw $2: $err" >&2
    return 1
  fi
}

# The site card. Rebuilt from a published puzzle before screenshotting, which
# also checks that the answer really is hidden where the card underlines it, so
# the card can't go back to being a picture that quietly asserts something false.
python3 "$REPO/tools/make_og_card.py" >/dev/null
shot "$REPO/tools/og_card.html" "$REPO/og.png"
echo "wrote og.png"

one() {  # one <puzzle number>
  local n="$1" out="$REPO/og/$1.png"
  python3 "$REPO/tools/make_og_card.py" --out "$TMP/$n.html" "$n" >/dev/null
  shot "$TMP/$n.html" "$out"
  echo "wrote og/$n.png"
}

case "${1:-}" in
  "") ;;
  --all)
    mkdir -p "$REPO/og"
    # Listed into a variable of its own, because `for n in $(...)` throws the
    # command's exit status away: a lister that dies partway through is then
    # indistinguishable from a shorter corpus, and every puzzle after the one it
    # died on silently keeps a stale card while the run reports success.
    list="$(python3 "$REPO/tools/make_og_card.py" --list)"
    for n in $list; do
      if [ ! -f "$REPO/og/$n.png" ] || [ "$REPO/puzzles/$n.js" -nt "$REPO/og/$n.png" ]; then
        one "$n"
      fi
    done ;;
  *) mkdir -p "$REPO/og"; one "$1" ;;
esac
