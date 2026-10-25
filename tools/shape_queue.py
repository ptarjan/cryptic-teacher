#!/usr/bin/env python3
"""The clues whose wordplay tree tools/shape_suspects.py flags and
tools/fix_shape_suspects.py could not repair: tools/data/shape_reannotate.json,
{"id": "<puzzle>#<number><a|d>", "reason": ...} per clue (Paul 10-15: "Mechanical
fixes first, re-annotate the rest behind hinting", per clue, not per puzzle).

The burn queues their puzzles as the LAST tier (prereset_plan.backlog), and a run
on one writes just the listed clues (annotate_check.to_write), with the flag
reason in the view (`flagged`). The old annotation stays live until the new one
validates; a null never blanks it (apply_annotations holds it).

A clue leaves the list when apply_annotations files its new annotation (done(),
at the end of apply). The detectors are the gate, not the prompt: apply refuses
a tree for a listed clue that they still flag (findings()), so a run cannot
re-file the old tree with new prose and call it done. A clue the run nulls keeps
its old hint and its row, marked "tried", so it is not redone; pending() skips
tried rows. A later write in the same run still settles it (done() looks at
every listed row, tried or not).

The row changes ship in the puzzle's own commit (tools/own_rows.py), so a
pruned row reaches master with the tree that settled it, and a discarded run
puts its rows back."""
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PATH = Path(__file__).resolve().parent / "data" / "shape_reannotate.json"
_cache = {}


def rows():
    """The list's rows, re-read only when the file changes."""
    try:
        st = PATH.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size, str(PATH))
    if _cache.get("key") != key:
        try:
            _cache.update(key=key, rows=json.loads(PATH.read_text()))
        except ValueError:
            _cache.update(key=key, rows=[])
    return _cache["rows"]


_pending_cache = {}


def pending():
    """{puzzle id: {clue key ("22a"): reason}} for the rows not yet tried."""
    rs = rows()
    sha = code_sha()
    if _pending_cache.get("rows") is not rs or _pending_cache.get("sha") != sha:  # rows() returns one list per file version
        out = {}
        for r in rs:
            if r.get("tried") and not rearmed(r, sha):
                continue
            pid, _, clue = r["id"].partition("#")
            if exempt(pid) and shape_reason(r.get("reason", "")):
                continue
            out.setdefault(pid, {})[clue] = r.get("reason", "")
        _pending_cache.update(rows=rs, out=out, sha=sha)
    return _pending_cache["out"]


#: A clue the model nulled is tried again when the annotate code (or the flagging rule, which
#: annotate_ledger.CODE_PATHS covers) changed since, at most this many tries in all.
MAX_TRIES = 3
_sha_cache = {}


def code_sha():
    """Short sha of the last commit touching annotate code (annotate_ledger.code_commit), the same
    signal the cost ledger judges by; None when git or the module is not there. Looked up at most
    every 10 minutes: pending() asks on every call."""
    import time
    now = time.monotonic()
    if "at" not in _sha_cache or now - _sha_cache["at"] > 600:
        try:
            import annotate_ledger
            sha = annotate_ledger.code_commit()[0]
        except Exception:
            sha = None
        _sha_cache.update(at=now, sha=sha)
    return _sha_cache["sha"]


def tries(row):
    """How many times the model has tried this row (rows tried before the count was kept: once)."""
    return row.get("tries", 1 if row.get("tried") else 0)


def rearmed(row, sha=None):
    """True for a tried row the burn should take again: the annotate code changed since its last
    try (tried_code differs; rows tried before it was kept count as changed) and it is under
    MAX_TRIES. Past the cap it stays hidden; exhausted() lists it."""
    sha = sha or code_sha()
    return bool(sha) and tries(row) < MAX_TRIES and row.get("tried_code") != sha


def exhausted():
    """Row ids tried MAX_TRIES times and still flagged: the report of clues the model cannot fix."""
    return [r["id"] for r in rows() if r.get("tried") and tries(r) >= MAX_TRIES]


def puzzle_ids():
    return set(pending())


def clue_key(entry):
    return f"{entry.get('number')}{(entry.get('direction') or '?')[:1]}"


def _by_entry(puzzle, want):
    if not want:
        return {}
    return {f"{e['number']}-{e['direction']}": want[clue_key(e)]
            for e in puzzle.get("entries") or [] if clue_key(e) in want}


def flagged(puzzle):
    """{entry id ("22-across"): reason} for this puzzle's pending clues, less the
    stale ones (settled(): no detector the row names fires on the tree now), so
    the burn's bag and a run skip them without the file being rewritten under it;
    tools/prune_shape_queue.py drops the rows."""
    got = _by_entry(puzzle, pending().get(puzzle.get("id")))
    by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle.get("entries") or []}
    return {k: why for k, why in got.items() if not settled(by_id[k], why)}


def listed(puzzle):
    """{entry id: reason} for every listed clue of this puzzle, tried or not:
    the ones apply holds to the detectors."""
    return _by_entry(puzzle, _listed_by_puzzle().get(puzzle.get("id")))


def hidden(puzzle):
    """{entry id: reason} for the listed clues whose walkthrough the site hides: those still flagged.
    A stale row (settled(): no detector it names fires now) and a convention-series shape row (never
    redone, see exempt) hide nothing, so a fixed clue shows before its row is pruned."""
    got = listed(puzzle)
    if not got:
        return got
    by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle.get("entries") or []}
    skip = exempt(puzzle.get("id"))
    return {k: why for k, why in got.items()
            if not (skip and shape_reason(why)) and not settled(by_id[k], why)}


_listed_cache = {}


def _listed_by_puzzle():
    """{puzzle id: {clue key: reason}} for every row; one pass per file version
    (a full site build asks once per puzzle, 57k times)."""
    rs = rows()
    if _listed_cache.get("rows") is not rs:
        out = {}
        for r in rs:
            pid, _, clue = r["id"].partition("#")
            out.setdefault(pid, {})[clue] = r.get("reason", "")
        _listed_cache.update(rows=rs, out=out)
    return _listed_cache["out"]


def findings(entry, ann=None, pid=None):
    """The precise detectors' findings on `ann` (default: the entry's own
    annotation) as "detector: what" strings; [] when they pass it. Given the
    puzzle id `pid`, a convention series (azed, genius) keeps only unchecked ones."""
    got = _findings(entry, ann)
    return [f for f in got if not shape_finding(f.split(":")[0])] if exempt(pid) else got


def _findings(entry, ann=None):
    import clue_shapes as cs
    import shape_suspects as ss
    ann = entry.get("annotation") if ann is None else ann
    if not ann or ann.get("wordplay") is None:
        return []
    wp = ann["wordplay"]
    row = {"id": "", "series": "", "clue": (entry.get("clue") or {}).get("text", ""),
           "sol": entry.get("solution", ""), "sk": cs.analyse(wp)[0], "line": cs.compact(wp),
           "wp": wp, "defs": ann.get("definitions") or [], "andLit": bool(ann.get("andLit"))}
    found = [f"{k}: {v}" if isinstance(v, str) else k
             for _, hits in ss.run_detectors([row]) for k, v in hits.items() if k in ss.PRECISION]
    # The validator's verdict: every shape rule a redo must clear (a tree that evaluates to
    # the answer but nests a container wrongly, or hangs an indicator on the wrong op, passes
    # every other check: times-29420 24a ABUSE, 16d SWEETPEAS). The gate was three of the
    # rules only because those were the ones added in 767fd6cea22, not by choice: a redo
    # that keeps any other flagged shape would pass the ratchet (it counts per puzzle),
    # so the gate is every rule in _validator_rules() but unchecked_step (see gated()).
    rules = _validator_rules()
    clue = (entry.get("clue") or {}).get("text", "")
    ann = {**ann, "_answer": _answer(entry)}
    # One finding once: a validator rule whose detector (indInLeaf / ind_in_leaf) already fired is not repeated.
    seen = {f.split(":")[0] for f in found}
    snake = lambda k: re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower()
    return found + [f"{k}: {_why(k)}" for k in gated() if snake(k) not in seen and rules[k](wp, ann, clue)]


def _why(rule):
    """What a gated rule says: the hint written for it, else the validator's own label."""
    import validate_annotations as V
    labels = {"scrambledLeaf": V.SCRAMBLED_LEAF, "indFolded": V.IND_FOLDED, "fakeParts": V.FAKE_PARTS,
              "bareInCharade": V.BARE_IN_CHARADE, "inDefinition": V.IN_DEFINITION, "leafFold": V.LEAF_FOLD,
              "anagramOfContainer": V.ANAGRAM_OF_CONTAINER, "anaCharade": V.ANAGRAM_CHARADE}
    return WHY.get(rule) or labels.get(rule, rule)


def gated():
    """The validator rules the redo gate enforces: all of _validator_rules() except
    unchecked_step, which is a status tools/clear_unchecked.py settles (a tree with
    an unchecked op is not refused here, only the unchecked_leaf detector's leaves are).
    A rule added to the validator and to _validator_rules() is gated with no edit here."""
    return tuple(k for k in _validator_rules() if k != "unchecked_step" and k not in WARN_ONLY)


#: Rules the validator still computes as warnings but that queue no redo and count nowhere in
#: the ratchet (round 20: the judges passed most of their flags as fine).
WARN_ONLY = ("unindicatedBare", "bareInitial", "indFolded", "inDefinition", "charadeOrder", "cutInLeaf", "nonWordOperand",
             "selectPhraseInLeaf",  # r27: 26 of 40 judged hits fine
             # 10-20 redo audit: the model left 95-100% of these clues unchanged (107/32/30 sampled)
             "deletionInside", "deletionScope", "bareInCharade")

#: Series whose own conventions make the judges accept the tree: no shape rule queues for them.
CONVENTION_SERIES = ("azed", "genius")


def exempt(pid):
    """True for a puzzle id (azed-2482, genius-100) of a series whose conventions the shape rules do not fit."""
    return str(pid).partition("-")[0] in CONVENTION_SERIES


def reason_names(reason):
    """The class names a row's reason lists ("a: why; b: why" -> a, b)."""
    return re.findall(r"(?:^|; )([A-Za-z][\w-]*)(?=:|;|$)", str(reason))


def shape_reason(reason):
    """True when every class a reason names is a shape rule or detector (what the convention
    series skip), none a walkthrough/model-fixable/unchecked one."""
    names = reason_names(reason)
    return bool(names) and all(shape_finding(n) and n in _shape_names() for n in names)


def _shape_names():
    import shape_suspects as ss
    return set(_validator_rules()) | set(ss.PRECISION)


def shape_finding(name):
    """True for a finding the convention-series exemption drops: every shape rule or detector,
    not the unchecked leaf/step ones (a status clear_unchecked settles)."""
    return not name.startswith("unchecked")


WHY = {"anaSynonym": "a synonym is scrambled inside an anagram: only the clue's own words are "
                     "the fodder, the synonym joins the result in a charade",
       "nestedContainer": "a container holds another container as its holder: join the pieces "
                          "going into one holder as a charade, or nest the other way round",
       "misplacedIndicator": "an indicator is filed on the charade but signals another op: "
                             "put it on that op",
       "bareInitial": "a leaf gives the first letter of its word with no selection op: "
                      "use first<indicator>(word)",
       "deletionScope": "a deletion over a charade names an end but the removed letters are not at the "
                        "charade's end: the indicator acts on one piece, so delete inside the charade",
       "wrongRole": "an indicator is filed on an op of another type (a reversal word on the container, "
                    "a container word on the anagram, a selection word on the container): put each "
                    "indicator on the op it signals",
       "deletionInside": "a deletion over a charade takes letters from one piece (or takes a whole piece "
                         "the charade added): the indicator acts on that piece alone, so delete inside "
                         "the charade, del(piece, letters), and add no piece only to remove it",
       "containerInside": "a container over a charade puts its piece in inside one piece of it: the "
                          "indicator acts on that piece alone, so insert inside the charade, "
                          "ins(piece, letters), not over the whole",
       "unindicatedBare": "an op has no indicator word of its own, or one indicator is filed for several "
                          "ops: give each op the clue word that signals it (a pair of first/last picks "
                          "may share one); if the clue gives none, the tree is not the solver's route",
       "sharedIndicator": "the same indicator words are claimed twice (on two ops, or again as a leaf's "
                          "clue words): a clue word does one job",
       "halfLeaf": "a leaf gives half of its word with no op carrying the half: pick it with an op, "
                   "once per word, each with the clue word that says so",
       "deletionScattered": "one 'half' deletion over several words picks its letters from all of them: "
                            "'half' acts on one word, so delete inside each word",
       "reversePhrase": "a reverse reading over a whole phrase of the clue: say what the words do "
                        "(an anagram, a hidden word, a charade)",
       "indInLeaf": "an indicator's words also sit inside a longer leaf: the leaf holds only the words "
                    "that give its letters, the indicator word goes on the op",
       "deletionScopeAnswer": "a deletion over a charade names an end, but the letters that make the "
                              "answer are not at it: the indicator acts on one piece, so delete inside "
                              "the charade, del(piece, letters)",
       "doubleIndicator": "one op carries two indicators (or a hidden word stacks a selection on its one "
                          "indicator): one op per indicator, so write two reversals / two deletions",
       "movedLetter": "a letter is deleted and put back by a sibling leaf: that is a move, so redo it as "
                      "move<indicator>(fodder, MOVED), e.g. move<dropping>([England]ALBION, [ball]O)",
       "poolGap": "an anagram's fodder pieces have another op's words between them in the clue: the "
                  "piece belongs to the charade or insertion, not the anagram pool",
       "tradedIndicator": "two ops carry each other's indicator word (an 'about' on the reversal and a "
                          "'knocking back' on the container), or a hidden word carries a reversal's word: "
                          "put each indicator word on the op of its own kind",
       "charadeOrder": "a charade joins its pieces in another order than the clue gives them, with no 'after' or "
                       "'before' to say so: keep the clue's order or reverse the piece that moves",
       "reversalSplit": "a reversal's indicator stands between the pieces it reverses: it reverses the one piece "
                        "it sits by, so reverse that piece inside the charade or container",
       "cutInLeaf": "a leaf opens with a cut word (short, half, first) and gives fewer letters than its other "
                    "words: the cut is an op with its own indicator",
       "anaSelectEdge": "an anagram holds a first/last-letter pick at the edge of its fodder, and the answer shows "
                        "that letter outside the scramble: set the pick beside the anagram in a charade",
       "nonWordOperand": "a deletion, substitution or homophone acts on a leaf that is no word (two synonyms run "
                         "together): give the op one word and join the pieces in a charade",
       "delWide": "a deletion lists several pieces before its indicator, so the indicator cuts only the piece beside "
                  "it: the other pieces belong to the parent op",
       "indLeafOverlap": "a two-word indicator takes a word that a leaf also gives: the leaf holds that word, the "
                         "indicator is the other word",
       "anaDoubleInd": "an anagram carries two separate indicators: one op, one indicator",
       "delStraddle": "a deletion over a charade removes letters from across two of its pieces: the word cuts one "
                      "piece, so delete inside the charade",
       "swappedPair": "a parent op and its child carry each other's indicator words: file each indicator on the op "
                      "of its own kind",
       "linkInLeaf": "a leaf opens or closes with a link word (in, of, with, by ...) and gives what its other words "
                     "alone give: the link word is the clue's join, not the leaf's",
       "anaStandIn": "an anagram held by a container scrambles an abbreviation or synonym beside the clue's own "
                     "words: spell the stand-in as its own piece",
       "selectWordInLeaf": "a selection op's leaf opens with the op's own indicator words (bit of, end for, "
                           "outline of): the leaf holds only the words that give its letters",
       "selectPhraseInLeaf": "a leaf opens with a letter-selection phrase (borders of, heading off) and gives "
                             "fewer letters than its other words: the selection is an op with its own indicator",
       "halvedAsDeletion": "a deletion whose indicator says half (half of, 50 per cent, bottom half) keeps half the "
                           "word: write the halving selection, not a deletion of the other half",
       "truncInLeaf": "a leaf holds a truncation word (mostly, almost, nearly) and gives the word one letter short: "
                      "give the whole word and cut it with a deletion op carrying that indicator",
       "cutNoteLeaf": "a leaf gives a non-word that its note says is a real word with letters cut: give the real "
                      "word and show the cut as a deletion op with its indicator",
       "selectorAsCut": "a deletion removes a leaf made of a first/last-letter word (leader, City's first): write the "
                        "removed letter as a first/last pick with its own indicator",
       "anaLoneEdge": "an anagram scrambles a single letter that the answer shows at its start or end: a lone letter "
                      "that can sit outside the anagram must, so set it beside the anagram in a charade",
       "anaLiteralEdge": "an anagram holds a clue word as written at the edge of its fodder, and the answer shows it "
                         "unscrambled at its edge: set the word beside the anagram in a charade",
       "delWrapsCharade": "a deletion wraps a charade though its indicator stands between the charade's pieces: it cuts "
                          "the one piece next to it, so put the deletion on that piece inside the charade",
       "repeatInLeaf": "a leaf holds a doubling word (twice, double, again) and gives a doubled string: give the "
                       "block once and repeat it with an op carrying that indicator",
       "splitWordLeaves": "one word is split into two leaves over the same clue words with an insert between (EI + N + D "
                          "for EID round N): write the word as the container's outer piece, one leaf",
       "moveNoteLeaf": "a leaf gives a non-word whose note says a letter was moved: write move<indicator>(fodder, MOVED)",
       "firstSiblingLeaves": "a first-letters op picks one word while sibling leaves give the next words' initials: one "
                             "indicator over the list is one multi-part op",
       "hiddenIndAbove": "a hidden op has no indicator while the op above opens with a hidden-word marker (having, "
                         "holding): put the marker on the hidden op",
       "deletionNoCut": "a deletion has one leaf part and no cut piece, the leaf a word one letter short: give the whole "
                        "word and cut it with a deletion carrying the indicator",
       "initialsInLeaf": "a leaf holds a first-letters word (primarily, initially) and gives its other words' initials: "
                         "write first<indicator> over those words",
       "nestedSameOp": "an op sits directly in an op of its own kind and only one of the two has an indicator: one "
                       "indicator is one multi-part op",
       "middleSiblingLeaf": "a middle op picks one word while a sibling leaf gives the middle letters of its own word: one "
                            "middle indicator over the list is one multi-part op",
       "delOnePiece": "a deletion wraps a charade though the cut lies inside one piece: put the deletion on that piece "
                      "inside the charade",
       "anaIsMove": "an anagram of one word gives the word with a single letter moved: write move<indicator>(fodder, MOVED)",
       "delAsMove": "a deletion's indicator is a movement word and its cut letters are no clue word: write "
                    "move<indicator>(fodder, MOVED)",
       "halfInLeaf": "a leaf holds half (half-done taco) and gives half of another of its words: write the halving "
                     "as a selection op with its own indicator",
       "selectIndEndsLeaf": "a first/last/outer op's leaf ends with the op's own indicator words (cooked on top): "
                            "the leaf holds only the words that give its letters",
       "beheadInLeaf": "a leaf holds a losing-head/tail phrase (youngster losing head) and gives the letters left: "
                       "give the whole word and cut it with a deletion op carrying that indicator",
       "ownIndInLeaf": "an op's own indicator words also sit inside its leaf (French way back under rev<back>): "
                       "the leaf holds only the words that give its letters",
       "splitSharedIndicator": "two neighbouring same-kind ops share one indicator, only one carrying it: write "
                               "one multi-part op under the indicator",
       "midWordLeaf": "a leaf gives a stretch of several clue words that starts or ends inside a word: "
                      "the cut is an op (del, first, last) with its indicator, not part of the leaf"}


def _validator_rules():
    """{reason class: fn(tree, ann, clue) -> truthy when it fires}: the
    tools/validate_annotations.py rules a row's reason can name. The shape_suspects
    detectors (arity_ins, del_single, ...) are read from findings() instead."""
    import validate_annotations as V
    return {"anagramOfContainer": lambda t, a, c: V.anagram_of_container(t),
            "scrambledLeaf": lambda t, a, c: V.scrambled_leaves(t),
            "indFolded": lambda t, a, c: V.folded_indicators(t),
            "fakeParts": lambda t, a, c: V.fake_parts(t),
            "bareInCharade": lambda t, a, c: V.bare_in_charade(t, a),
            "inDefinition": lambda t, a, c: V.in_definition(a, c),
            "leafFold": lambda t, a, c: V.leaf_folds(t),
            "anaCharade": lambda t, a, c: V.anagram_charades(t, a.get("_answer") or None),
            "nestedContainer": lambda t, a, c: V.nested_containers(t, a.get("_answer") or None),
            "anaSynonym": lambda t, a, c: V.anagram_synonyms(t, a, c),
            "misplacedIndicator": lambda t, a, c: V.misplaced_indicators(t),
            "bareInitial": lambda t, a, c: V.bare_initials(t),
            "deletionScope": lambda t, a, c: V.deletion_scope(t),
            "wrongRole": lambda t, a, c: V.wrong_role_indicators(t),
            "deletionInside": lambda t, a, c: V.deletion_inside_component(t, c, a.get("_answer") or None),
            "containerInside": lambda t, a, c: V.container_inside_component(t, a.get("_answer") or None),
            "unindicatedBare": lambda t, a, c: V.unindicated_uncovered(t),
            "sharedIndicator": lambda t, a, c: V.shared_indicators(t, c),
            "halfLeaf": lambda t, a, c: V.half_leaves(t),
            "deletionScattered": lambda t, a, c: V.deletion_scattered(t),
            "reversePhrase": lambda t, a, c: V.reverse_phrase(t),
            "midWordLeaf": lambda t, a, c: V.midword_leaves(t, c),
            "deletionScopeAnswer": lambda t, a, c: V.deletion_scope_answer(t, a.get("_answer") or None),
            "doubleIndicator": lambda t, a, c: V.double_indicators(t),
            "poolGap": lambda t, a, c: V.pool_gaps(t, c),
            "tradedIndicator": lambda t, a, c: V.traded_indicators(t),
            "charadeOrder": lambda t, a, c: V.charade_out_of_order(t, c),
            "reversalSplit": lambda t, a, c: V.reversal_split(t, c),
            "cutInLeaf": lambda t, a, c: V.cut_in_leaf(t, c),
            "anaSelectEdge": lambda t, a, c: V.ana_select_edge(t, a.get("_answer") or None),
            "nonWordOperand": lambda t, a, c: V.non_word_operands(t),
            "delWide": lambda t, a, c: V.del_wide(t, c),
            "indLeafOverlap": lambda t, a, c: V.ind_leaf_overlap(t, c),
            "anaDoubleInd": lambda t, a, c: V.ana_double_indicator(t),
            "delStraddle": lambda t, a, c: V.del_straddle(t),
            "swappedPair": lambda t, a, c: V.swapped_pair(t),
            "linkInLeaf": lambda t, a, c: V.link_in_leaf(t),
            "anaStandIn": lambda t, a, c: V.ana_stand_in(t),
            "selectWordInLeaf": lambda t, a, c: V.select_word_in_leaf(t),
            "selectPhraseInLeaf": lambda t, a, c: V.select_phrase_in_leaf(t),
            "halvedAsDeletion": lambda t, a, c: V.halved_as_deletion(t),
            "splitSharedIndicator": lambda t, a, c: V.split_shared_indicators(t),
            "truncInLeaf": lambda t, a, c: V.trunc_in_leaf(t),
            "cutNoteLeaf": lambda t, a, c: V.cut_note_leaf(t),
            "ownIndInLeaf": lambda t, a, c: V.own_ind_in_leaf(t),
            "repeatInLeaf": lambda t, a, c: V.repeat_in_leaf(t),
            "splitWordLeaves": lambda t, a, c: V.split_word_leaves(t),
            "moveNoteLeaf": lambda t, a, c: V.move_note_leaf(t),
            "firstSiblingLeaves": lambda t, a, c: V.first_sibling_leaves(t),
            "hiddenIndAbove": lambda t, a, c: V.hidden_ind_above(t),
            "deletionNoCut": lambda t, a, c: V.deletion_no_cut(t),
            "initialsInLeaf": lambda t, a, c: V.initials_in_leaf(t),
            "nestedSameOp": lambda t, a, c: V.nested_same_op(t),
            "middleSiblingLeaf": lambda t, a, c: V.middle_sibling_leaf(t),
            "delOnePiece": lambda t, a, c: V.del_one_piece(t),
            "anaIsMove": lambda t, a, c: V.ana_is_move(t, a),
            "delAsMove": lambda t, a, c: V.del_as_move(t),
            "halfInLeaf": lambda t, a, c: V.half_in_leaf(t),
            "selectIndEndsLeaf": lambda t, a, c: V.select_ind_ends_leaf(t),
            "beheadInLeaf": lambda t, a, c: V.behead_in_leaf(t),
            "selectorAsCut": lambda t, a, c: V.selector_as_cut(t),
            "anaLoneEdge": lambda t, a, c: V.ana_lone_edge(t, a.get("_answer") or None),
            "anaLiteralEdge": lambda t, a, c: V.ana_literal_edge(t, a.get("_answer") or None),
            "delWrapsCharade": lambda t, a, c: V.del_wraps_charade(t, c),
            "movedLetter": lambda t, a, c: V.moved_letters(t),
            "indInLeaf": lambda t, a, c: V.ind_in_leaf(t, c),
            # A step taken as filed that tools/clear_unchecked.py could not verify:
            # fires while any node of the tree still carries the flag.
            # (steps V.step_verified computes from their leaf do not count: fix round 4)
            "unchecked_step": lambda t, a, c: bool(V.unverified_unchecked(t, a.get("_answer") or None))}


def _answer(entry):
    alt = entry.get("alteration")
    return alt["from"] if isinstance(alt, dict) and alt.get("from") else entry.get("solution", "")


def _bad_tree(entry, ann):
    """True when the wordplay tree does not give the answer (or cannot be evaluated)."""
    import wordplay
    try:
        wordplay.evaluate(ann["wordplay"], _answer(entry))
    except (wordplay.WordplayError, KeyError, TypeError, ValueError, IndexError):
        return True
    return False


def _walkthrough_gap(entry, ann):
    """True when the walkthrough leaves an indicator or intermediate result unnamed."""
    import validate_annotations as V
    import wordplay
    walk = (ann.get("explanation") or {}).get("walkthrough")
    if not walk or not ann.get("fromBlog"):  # the rung lists the tree's steps itself (follow_warnings)
        return False
    try:
        return bool(V.walkthrough_gaps(ann["wordplay"], _answer(entry), walk))
    except (wordplay.WordplayError, KeyError, TypeError, ValueError):
        return False  # a tree that does not give its answer is another reason's job


#: Reasons a stored reason class names, re-checked on the tree as it stands: the
#: tree gives the answer now (the reason is only "model-fixable: bad tree"), or the
#: walkthrough now follows it.
_ENTRY_RULES = {"model-fixable": lambda e, a: _bad_tree(e, a),
                "walkthrough": _walkthrough_gap,
                # "the repaired tree gives the answer but the validator holds it back": stale once the
                # tree gives the answer, no walkthrough step is unnamed and no detector fires (round 12:
                # times-15476 7d ICARIAN was a correct tree still queued)
                "walkthrough-gate": lambda e, a: _bad_tree(e, a) or _walkthrough_gap(e, a)}


def settled(entry, reason):
    """True when every detector the row's reason names is known and none fires on
    the entry's annotation as it stands: the row is stale (the clue was fixed
    by another sweep, or the detector changed after the row was queued) and a
    run on it would redo a clue nothing flags (~4k tokens). A reason that names
    anything else (walkthrough-gate, ddMissesWordplay, ...) or a clue with no tree
    is never settled: only the model can say those are done. "model-fixable" and
    "walkthrough" are re-checked (the tree gives the answer now; no walkthrough gap)."""
    ann = entry.get("annotation")
    if not ann or ann.get("wordplay") is None:
        return False
    # A hint may hold "; " itself (unindicatedBare's): a class starts only at "<word>:" after one.
    import re
    names = re.findall(r"(?:^|; )([A-Za-z][\w-]*)(?=:|;|$)", str(reason)) or [str(reason).split(":")[0].strip()]
    names = [n for n in names if n != "re-narrate"]    # the tail of a walkthrough-gate hint
    rules = _validator_rules()
    import shape_suspects as ss
    if names and all(n in WARN_ONLY for n in names):
        return True     # warning-only now: nothing queues a redo for it
    names = [n for n in names if n not in WARN_ONLY]
    if not names or any(n not in rules and n not in ss.PRECISION and n not in _ENTRY_RULES
                        for n in names):
        return False
    if any(n in _ENTRY_RULES and _ENTRY_RULES[n](entry, ann) for n in names):
        return False
    fired = {f.split(":")[0] for f in findings(entry)}
    clue = (entry.get("clue") or {}).get("text", "")
    for n in names:
        if n in fired:
            return False
        if n in rules and rules[n](ann["wordplay"], {**ann, "_answer": _answer(entry)}, clue):
            return False
    return True


def regressions(entry, new):
    """Ways a listed clue's new annotation `new` gives up what the old one on
    file (the entry's own) had, as strings; [] when it gives up nothing. The
    comparison lives in the one validator, validate_annotations.redo_regressions."""
    import validate_annotations as V
    return V.redo_regressions(entry.get("annotation"), new, (entry.get("clue") or {}).get("text", ""))


def still_flagged(entry):
    """The detectors' verdict on this entry's annotation as it stands now."""
    return bool(findings(entry))


def done(puzzle, written, held=()):
    """Account for the clues a run just filed: `written` is the entry ids it
    gave an annotation, `held` the ones whose null kept the old hint. A written
    clue the detectors pass is pruned; a held one (or a written one they still
    flag, which apply refuses before it gets here) is marked tried. Every
    listed row counts, tried or not, so a fix later in the run still prunes.
    Returns how many listed clues it settled."""
    by_id = {f"{e['number']}-{e['direction']}": e for e in puzzle["entries"]}
    mine = {k for k in listed(puzzle) if (k in written or k in held) and k in by_id}
    if not mine:
        return 0
    verdict = {clue_key(by_id[k]): k in held or still_flagged(by_id[k]) for k in mine}
    sha = code_sha()
    with locked():
        out = []
        for r in json.loads(PATH.read_text()):
            p, _, c = r["id"].partition("#")
            if p == puzzle["id"] and c in verdict:
                if verdict[c]:
                    out.append({**r, "tried": True, "tries": tries(r) + 1, "tried_code": sha})
                continue
            out.append(r)
        write(dump(out))
    return len(mine)


@contextlib.contextmanager
def locked():
    """Exclusive lock for a read-modify-write of the list. The lock is a file of
    its own, not PATH, because write() replaces PATH's inode."""
    lock = Path(tempfile.gettempdir()) / f"ct-shape-queue-{hashlib.sha1(str(PATH).encode()).hexdigest()[:12]}.lock"
    import fcntl  # POSIX-only, imported where used: the desktop OCR code imports this module and runs on Windows
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def write(text, path=None):
    """Replace the list with `text` in one step (a temp file beside it, then
    os.replace), so a reader, and the burn's `git add`, which takes no lock,
    sees the old file or the new one and never a truncated half: 16 "Annotate"
    commits (10-17) captured it empty while done() rewrote it in place."""
    path = Path(path or PATH)
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    with open(part, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, path)


def dump(out):
    """The list's layout: one row per line, as tools/fix_shape_suspects.py
    writes it, so rows of different puzzles are different lines."""
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n]\n"


def splice(base, donor, pid):
    """`base` (the list's text) with pid's rows as `donor` has them, each after
    the row it follows in donor that base also holds, so splicing back the
    text a splice started from gives it byte for byte (tools/own_rows.py)."""
    def ours(r):
        return r["id"].partition("#")[0] == pid
    b, d = json.loads(base or "[]"), json.loads(donor or "[]")
    others = {r["id"] for r in b if not ours(r)}
    after, anchor = {}, None
    for r in d:
        if not ours(r):
            anchor = r["id"] if r["id"] in others else anchor
        else:
            after.setdefault(anchor, []).append(r)
    out = list(after.get(None, []))
    for r in b:
        if not ours(r):
            out += [r] + after.get(r["id"], [])
    return dump(out)
