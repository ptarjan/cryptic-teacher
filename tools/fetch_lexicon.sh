#!/usr/bin/env bash
# Fetch the Lufz lexicon (MIT, https://github.com/viresh-ratnakar/lufz) and the
# Exet lexicon API (MIT, https://github.com/viresh-ratnakar/exet) into
# tools/data/, then extract the filler's word list from them.
#
# ~26 MB of JavaScript, so the blobs are gitignored and fetched on demand;
# tools/data/lexicon.tsv is derived from them by tools/build_lexicon.js.
# Licence notice lives in tools/data/README.md.
set -euo pipefail

DATA="$(cd "$(dirname "$0")" && pwd)/data"
mkdir -p "$DATA"

LUFZ=https://raw.githubusercontent.com/viresh-ratnakar/lufz/master
EXET=https://raw.githubusercontent.com/viresh-ratnakar/exet/master

# A sibling agent or an earlier run may already have a copy; copying beats
# re-downloading 24 MB.
LOCAL="${LUFZ_LOCAL:-$HOME/cryptic-setter-data}"

fetch() { # fetch <url> <basename> <local-subdir>
  local url="$1" name="$2" sub="$3"
  if [ -s "$DATA/$name" ]; then
    echo "have $name"
  elif [ -s "$LOCAL/$sub/$name" ]; then
    echo "copying $name from $LOCAL/$sub"
    cp "$LOCAL/$sub/$name" "$DATA/$name"
  else
    echo "downloading $name"
    curl -sSfL -o "$DATA/$name" "$url/$name"
  fi
}

fetch "$LUFZ" lufz-en-lexicon.js lufz
fetch "$LUFZ" lufz-en-lexicon-stems.js lufz
fetch "$EXET" exet-lexicon.js exet

node "$(dirname "$0")/build_lexicon.js" "$DATA"
