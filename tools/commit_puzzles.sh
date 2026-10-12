#!/bin/bash
# One commit per puzzle: commit each staged puzzle or clues-only file on its own.
#
#     . tools/commit_puzzles.sh; ct_commit_puzzles "<job>"    # from a shell job
#     tools/commit_puzzles.sh "<job>"                         # from anything else
#
# Paul 10-12: "The archive makes one commit instead of one per puzzle." Every
# writer that files puzzles in bulk calls this before its own catch-all commit,
# so a run's history reads "File times-17317", "File book-123", ... and not one
# commit holding a night's worth. Each commit is subject "File <id>" (or
# Update, Drop, Renumber; tools/commit_subject.py), a rename's two paths
# together. What is staged outside puzzles/ and clues_only/ (ledgers, series
# files, generated pages) is left staged for the caller's own commit, except the
# table rows a drop or rename carries, which go in that puzzle's commit.
#
# Prints nothing; returns 1 if a commit fails.
_cp_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_cp_staged() {  # staged puzzle and clues-only files, each folder alone so a promotion is an add and a drop, not a rename
  git diff --cached --name-status -M -- puzzles
  git diff --cached --name-status -M -- clues_only
}

ct_commit_puzzles() {  # ct_commit_puzzles <job>
  local what="$1" trailer line subj p t gone now
  git diff --cached --quiet && return 0
  trailer="$(python3 "$_cp_dir/provenance.py" trailer 2>/dev/null)"
  while IFS= read -r line; do
    [[ "$line" == *.json ]] || continue
    IFS=$'\t' read -r -a p <<<"$line"
    subj="$(printf '%s\n' "$line" | python3 "$_cp_dir/commit_subject.py" "$what")"
    # A rename carries its row of tools/data/renamed_ids.json, the old id's redirect.
    if [[ "$line" == R* ]]; then
      python3 "$_cp_dir/renamed_ids.py" --stage || return 1
      p+=(tools/data/renamed_ids.json)
    fi
    # A deletion or rename takes its per-puzzle table rows (tools/puzzle_rows.py:
    # carried to the new id, else discarded) in this commit; otherwise
    # the rows name no puzzle and CI fails (book-12076, 10-11). These lines
    # come last, so the whole tables they carry follow every puzzle file
    # their other rows describe. A clues-only file dropped is usually promoted
    # to a puzzle of the same id, which keeps its rows.
    if [[ "$line" == [DR]* ]] && [[ "$line" != D*$'\t'clues_only/* ]] && [ -f "$_cp_dir/puzzle_rows.py" ]; then
      gone="${p[1]##*/}"
      now=""
      [[ "$line" == R* ]] && now="${p[2]##*/}" && now="${now%.json}"
      python3 "$_cp_dir/puzzle_rows.py" retire "${gone%.json}" $now >/dev/null || return 1
      for t in source_clue_wrong source_answer_wrong setter_error blog_disagree ninas blind_misses diagnosed_misses renamed_ids; do
        [ -f "tools/data/$t.json" ] && p+=("tools/data/$t.json")
      done
    fi
    git commit -q -m "$(printf '%s\n\n%s' "$subj" "$trailer")" -- "${p[@]:1}" || return 1
  done < <(_cp_staged | grep -v '^[DR]'
           _cp_staged | grep '^[DR]')
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then ct_commit_puzzles "$@"; fi
