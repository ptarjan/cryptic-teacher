#!/bin/bash
# Does tools/build_readme.py still read the header of every file it is asked about?
#
#     bash tools/test_build_readme.sh
#
# --add-missing writes a LAYOUT row from a file's own header comment, and the
# row it cannot derive is one a person has to write by hand. That failure is
# silent in the direction that matters: a reader that knows only `//` reports a
# `/* */` file as having no description at all, which reads as "this file
# explains nothing" rather than "the tool cannot see it". Both spellings are in
# use in this repo, so both are asserted here, along with the shebang skip and
# the None that keeps the tool from inventing a description for a data file.
#
# The fixtures are written into a temp tree, so the assertions do not move when
# somebody rewords the header of a real file.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
fails=0
check() {  # check <what> <expected> <got>
  if [ "$2" = "$3" ]; then echo "ok   $1"; else
    echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi
}

tree="$(mktemp -d)"
trap 'rm -rf "$tree"' EXIT

printf '/* boxed header sentence.\n *\n * A second paragraph nobody asked for.\n */\nconsole.log(1);\n' > "$tree/boxed.js"
printf '/* one-line header sentence. */\nconsole.log(1);\n' > "$tree/oneline.js"
printf '// slashes header sentence.\n//\n// A second paragraph.\nconsole.log(1);\n' > "$tree/slashes.js"
printf '#!/bin/bash\n# shell header sentence.\nexit 0\n' > "$tree/hashes.sh"
printf '{"not": "prose"}\n' > "$tree/data.json"

got="$(cd "$REPO" && python3 - "$tree" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("br", "tools/build_readme.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)
br.REPO = pathlib.Path(sys.argv[1])
for name in ("boxed.js", "oneline.js", "slashes.js", "hashes.sh", "data.json"):
    print(f"{name}\t{br.derive_description(name)}")
PY
)"

field() { printf '%s\n' "$got" | awk -F'\t' -v n="$1" '$1 == n {print $2}'; }

check "a boxed /* */ header is read"      "boxed header sentence"    "$(field boxed.js)"
check "a one-line /* */ header is read"   "one-line header sentence" "$(field oneline.js)"
check "a // header still works"           "slashes header sentence"  "$(field slashes.js)"
check "a # header survives its shebang"   "shell header sentence"    "$(field hashes.sh)"
check "a file with no header gets None"   "None"                     "$(field data.json)"

# Every tracked .js and .sh in tools/ should yield something, or --add-missing
# hands the next new file straight back to a person for no reason.
blind="$(cd "$REPO" && python3 - <<'PY'
import importlib.util, subprocess
spec = importlib.util.spec_from_file_location("br", "tools/build_readme.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)
tracked = subprocess.run(["git", "ls-files", "tools/*.js", "tools/*.sh"],
                         capture_output=True, text=True).stdout.split()
print(" ".join(f for f in tracked if not br.derive_description(f)))
PY
)"
check "every tools/*.{js,sh} header is readable" "" "$blind"

if [ "$fails" -gt 0 ]; then echo "build_readme: $fails check(s) failed"; exit 1; fi
echo "build_readme: all checks passed"
