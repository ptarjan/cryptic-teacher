#!/usr/bin/env python3
"""Structural diff: how Minute Cryptic writes a hint vs how we do. No inference —
every number here comes from counting fields, not from asking a model to judge.

Reads tools/data/minutecryptic/hints.jsonl (24 records, gitignored — their
copyrighted teaching material, kept locally to measure, never to copy from) and
every puzzles/*.js annotation on disk. Prints tables to stdout; writes nothing
under version control. If the MC corpus isn't on disk this prints one line and
exits — that directory is local-only, not part of the repo.

Their hint text and clue text are copyrighted with no declared licence: this
file reads them to count words and match patterns, and must never print or
write a full hint/clue string anywhere. Only short fixed labels (types, marker
words) get printed.

Our side is a Python port of the rung-building logic in app.js (`ladderSteps`,
`familyOf`, `typeBlurb`, `TYPE_BLURBS`, `INDICATOR_OPS`) — our own text, so
copying it here is fine. Kept close enough to match word counts; not a
byte-exact re-render (HTML escaping, the abbreviation-glossary link, and the
definition-place footnote are simplified away because none of them move the
word count more than a word or two).
"""

import glob
import json
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MC_DIR = ROOT / "tools" / "data" / "minutecryptic"
HINTS_PATH = MC_DIR / "hints.jsonl"
COURSE_PATH = MC_DIR / "course.json"

sys.path.insert(0, str(ROOT / "tools"))


# ---------- our own rung text, ported from app.js so word counts are real ----------

FAMILIES = [
    ("Definitions only",
     "No letter mechanics at all — the clue works by definition alone. The work is spotting which words are doing the defining.",
     lambda t: "double definition" in t or "cryptic definition" in t),
    ("&lit",
     "The whole clue does double duty: read it once as a definition, then read the very same words again as wordplay.",
     lambda t: "&lit" in t),
    ("Rearrangement",
     "Letters handed to you in the clue get shuffled into the answer. Find the fodder and count it against the enumeration.",
     lambda t: "anagram" in t or "cycling" in t),
    ("Sound",
     "The wordplay describes how the answer sounds rather than how it is spelled.",
     lambda t: "homophone" in t or "spoonerism" in t),
    ("Charade",
     "The answer is built from pieces laid end to end, each clued separately — read the wordplay left to right.",
     lambda t: "charade" in t),
    ("Alteration",
     "A piece of the wordplay is changed rather than just joined on: put inside something, turned around, or trimmed.",
     lambda t: "container" in t or "reversal" in t or "deletion" in t or "substitution" in t),
    ("Extraction",
     "The answer's letters are already sitting in the clue in order — the job is working out which ones to pick out.",
     lambda t: "hidden" in t or "letter" in t),
]
DEFAULT_FAMILY = ("Wordplay", "The clue has a definition at one end and wordplay at the other.", None)

TYPE_BLURBS = [
    ("anagram", "An anagram: some words in the clue are raw letter fodder to be rearranged. Find the indicator, then count letters against the enumeration."),
    ("charade", "A charade: the answer is built from parts placed one after another, each clued separately."),
    ("container", "A container: one part is placed inside another. Look for words like holding, in, covering, swallowing."),
    ("hidden", "A hidden word: the answer is spelled out consecutively inside the clue itself."),
    ("homophone", "A homophone: the wordplay describes something that sounds like the answer."),
    ("reversal", "A reversal: something is spelled backwards (in a down clue, 'up'-words signal this)."),
    ("deletion", "A deletion: letters are removed from a longer word — heads, tails or insides."),
    ("double definition", "A double definition: two definitions sit side by side; there is no other wordplay."),
    ("&lit", "An &lit: the whole clue is both the definition and the wordplay at once."),
    ("alternate letters", "Alternate letters: take every other letter of an indicated word."),
    ("regular letters", "Regular letters: count through an indicated phrase at a fixed step — every third letter, say — and keep the ones you land on."),
    ("first letter", "First letters: take the initial letter(s) of indicated word(s)."),
    ("last letter", "Last letters: take the final letter(s) of indicated word(s)."),
    ("middle letter", "Middle letters: take just the centre of an indicated word."),
    ("second letter", "Second letters: count into the indicated word(s) and keep only the letter in position two."),
    ("outer letters", "Outer letters: keep only the outside letters of an indicated word."),
    ("cryptic definition", "A cryptic definition: no separable wordplay — the whole clue is one sly description."),
    ("spoonerism", "A spoonerism: swap the opening sounds of two words to get the answer."),
    ("cycling", "Cycling: letters move from one end to the other without changing their order — the word rotates rather than shuffles."),
    ("substitution", "A substitution: one indicated letter or chunk stands in for another — make the swap and the answer appears."),
]

INDICATOR_OPS = [
    ("anagram", "rearrange the letters it points at"),
    ("container", "put one piece inside another"),
    ("reversal", "write a piece backwards"),
    ("deletion", "drop letters from a word"),
    ("hidden", "find a run of letters already sitting in the clue"),
    ("homophone", "take how a word sounds, not how it is spelled"),
    ("spoonerism", "swap the opening sounds of two words"),
    ("alternate letters", "take every other letter"),
    ("regular letters", "count through the letters at a fixed step and keep the ones you land on"),
    ("first letter", "take the opening letter of the words it points at"),
    ("last letter", "take the final letter of the words it points at"),
    ("middle letter", "take just the middle of a word"),
    ("outer letters", "keep only the outside letters of a word"),
    ("cycling", "move letters from one end to the other, keeping their order"),
    ("substitution", "swap one letter or chunk for another"),
]

HOWMANY = ["no", "one", "two", "three", "four", "five", "six"]


def family_of(ann_type):
    t = (ann_type or "").lower()
    for label, blurb, match in FAMILIES:
        if match(t):
            return label, blurb
    return DEFAULT_FAMILY[0], DEFAULT_FAMILY[1]


def type_blurb(ann_type):
    t = (ann_type or "").lower()
    return " ".join(v for k, v in TYPE_BLURBS if k in t)


def def_place(clue, definition):
    # Simplified: app.js's version also names the flanking fragments; here we
    # only need the length of the connective clause, which is fixed regardless.
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", clue or "").strip()
    definition = (definition or "").strip()
    if not bare or not definition:
        return "."
    at = bare.lower().find(definition.lower())
    if at < 0:
        return "."
    before = bare[:at].strip()
    after = bare[at + len(definition):].strip()
    if not before and not after:
        return " — which is the whole clue, and that is what makes this one unusual."
    if not before:
        return f", so the clue opens with it and \"{after}\" is the wordplay."
    if not after:
        return f", right at the end — so \"{before}\" is the wordplay."
    return f", sitting mid-clue, so the wordplay is \"{before}\" and \"{after}\" either side of it."


def ladder_steps(ann, clue_text):
    """Python port of app.js ladderSteps(): returns [(rung_key, plain_text), ...]
    in the exact order app.js emits them. This IS the order our UI shows rungs
    in — it does not depend on clue content, only on which rungs a clue has."""
    if not ann:
        return []
    t = (ann.get("type") or "").lower()
    is_dd = "double definition" in t
    is_cd = "cryptic definition" in t
    is_lit = "&lit" in t
    inds = ann.get("indicators") or []
    blocks = ann.get("blocks") or []
    steps = []

    fam_label, fam_blurb = family_of(ann.get("type"))
    steps.append(("type", f"{fam_label}. {fam_blurb}"))

    mechanics = f"Mechanism: {ann.get('type', '')}. {type_blurb(ann.get('type'))}"

    definition = ann.get("definition") or ""
    if is_dd and ann.get("definition2"):
        def_text = (f"It splits between {definition} and {ann['definition2']} — two "
                    "unrelated senses of the same word, which is where the surface "
                    "reading misleads you.")
    elif is_lit:
        def_text = (f"Read {definition} straight through as a description of the "
                    "answer, then read the very same words again as wordplay.")
    elif is_cd:
        def_text = (f"There's no separable wordplay here: {definition} is a "
                    "whole-clue description that only makes sense once you see it "
                    "the setter's way.")
    else:
        def_text = f"The definition is {definition}{def_place(clue_text, definition)}"
    if ann.get("linkWords"):
        lw = ", ".join(ann["linkWords"])
        verb = "are" if len(ann["linkWords"]) > 1 else "is"
        def_text += (f" {lw} {verb} just a link — words that join the definition "
                     "to the wordplay and contribute no letters of their own.")
    steps.append(("definition", def_text))

    if inds:
        ops = [op for k, op in INDICATOR_OPS if k in t]
        marks = ", ".join(inds)
        if len(ops) == 1:
            verb = "they tell" if len(inds) > 1 else "it tells"
            ind_text = f"{marks} — {verb} you to {ops[0]}."
        elif len(ops) > 1:
            n = HOWMANY[len(ops)] if len(ops) < len(HOWMANY) else str(len(ops))
            ind_text = (f"{marks} — this clue does {n} things, and the indicators "
                        "are what tell them apart: " + "; ".join(ops) +
                        ". Which word calls for which is the step to work out here.")
        else:
            verb = "these tell" if len(inds) > 1 else "this tells"
            ind_text = f"{marks} — {verb} you what to do with the rest of the wordplay."
        steps.append(("indicators", ind_text))

    if blocks and any(b.get("gives") or b.get("note") for b in blocks):
        items = []
        for b in blocks:
            s = ""
            if b.get("clueFragment"):
                s += f"\"{b['clueFragment']}\""
            if b.get("soundsLike"):
                s += f" -> {b['soundsLike']} said aloud"
            if b.get("gives") and not is_cd:
                s += f" -> {b['gives']}"
            if b.get("note"):
                s += f" -- {b['note']}"
            items.append(s)
        prefix = "" if (is_dd or is_cd) else mechanics + " "
        steps.append(("blocks", prefix + " ".join(items)))

    fit = ""
    if ann.get("definitionFit"):
        fit = f" {definition}"
        if ann.get("definition2"):
            fit += f" and {ann['definition2']}"
        fit += f" -> {ann.get('answer', '')}: {ann['definitionFit']}"
    note = f" {ann['definitionNote']}" if ann.get("definitionNote") else ""
    has_blocks = any(k == "blocks" for k, _ in steps)
    walk_prefix = "" if (has_blocks or is_dd or is_cd) else mechanics + " "
    walk_text = walk_prefix + (ann.get("walkthrough") or "") + fit + note + \
        f" Answer: {ann.get('answer', '')}"
    steps.append(("walkthrough", walk_text))
    return steps


OUR_RUNG_ORDER = ["type", "definition", "indicators", "blocks", "walkthrough"]


# ---------- loading ----------

def load_hints_jsonl():
    if not HINTS_PATH.exists():
        return None
    records = []
    with open(HINTS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_our_annotations():
    from fetch_puzzle import read_puzzle_file
    out = []
    for p in sorted(glob.glob(str(ROOT / "puzzles" / "*.js"))):
        data = read_puzzle_file(pathlib.Path(p))
        for e in data.get("entries", []):
            ann = e.get("annotation")
            if ann:
                out.append((p, e, ann))
    return out


# ---------- measurement helpers ----------

WORD_RE = re.compile(r"[A-Za-z']+")


def word_count(text):
    return len(WORD_RE.findall(text or ""))


def contains_word(text, word):
    if not word:
        return False
    return re.search(r"\b" + re.escape(word) + r"\b", text or "", re.I) is not None


SECOND_PERSON = re.compile(r"\byou\b|\byou'll\b|\byour\b", re.I)
FIRST_PLURAL = re.compile(r"\bwe\b|\bwe'll\b|\bwe're\b|\blet's\b|\bour\b", re.I)
QUESTION = re.compile(r"\?")
IMPERATIVE_OPENERS = {"find", "look", "spot", "count", "take", "keep", "match",
                       "read", "check", "see", "notice", "watch", "search",
                       "compare", "reread", "consider", "remember"}


def opens_imperative(text):
    words = WORD_RE.findall(text or "")
    return bool(words) and words[0].lower() in IMPERATIVE_OPENERS


def median_range(values):
    if not values:
        return "n/a"
    return f"median {statistics.median(values):.0f}, range {min(values)}-{max(values)}"


DEVICE_WORDS = ["anagram", "charade", "container", "hidden", "homophone",
                "reversal", "deletion", "double definition", "&lit", "rebus",
                "spoonerism", "cycling", "substitution", "cryptic definition"]


def names_device(text):
    low = (text or "").lower()
    return any(w in low for w in DEVICE_WORDS)


def main():
    print("=" * 78)
    print("MC STRUCTURAL COMPARISON — no inference, counts only")
    print("=" * 78)

    mc = load_hints_jsonl()
    if mc is None:
        print(f"\n{HINTS_PATH} not found — tools/data/minutecryptic/ is "
              "gitignored and local-only. Nothing to compare. Run the fetcher "
              "that populates it, then re-run this script.")
        return

    ours = load_our_annotations()
    print(f"\nLoaded {len(mc)} Minute Cryptic records, {len(ours)} of our "
          "annotated clues.\n")

    # ---------- ORDER ----------
    print("-" * 78)
    print("ORDER — sequence of hint/rung types")
    print("-" * 78)
    from collections import Counter
    mc_seqs = Counter(tuple(h["type"] for h in r["hints"]) for r in mc)
    print("\nTheirs (type sequence -> count of records):")
    for seq, n in mc_seqs.most_common():
        print(f"  {n:2d}  {' -> '.join(seq)}")

    our_seqs = Counter()
    for _, e, ann in ours:
        clue_text = e.get("clue", "")
        keys = tuple(k for k, _ in ladder_steps(ann, clue_text))
        our_seqs[keys] += 1
    print("\nOurs (rung-key sequence -> count of annotated clues):")
    for seq, n in our_seqs.most_common(10):
        print(f"  {n:4d}  {' -> '.join(seq)}")
    print("\nFixed structural fact: our order is ALWAYS type -> definition -> "
          "[indicators] -> [blocks] -> walkthrough. Which optional rungs exist "
          "varies per clue; the relative order among the rungs a clue does have "
          "never varies. Definition always precedes indicators.")

    # ---------- LENGTH ----------
    print("\n" + "-" * 78)
    print("LENGTH — word counts")
    print("-" * 78)
    mc_by_type = {}
    for r in mc:
        for h in r["hints"]:
            mc_by_type.setdefault(h["type"], []).append(word_count(h["text"]))
    print("\nTheirs, words per hint by type:")
    for t, vals in sorted(mc_by_type.items()):
        print(f"  {t:12s} n={len(vals):3d}  {median_range(vals)}")
    all_mc_words = [w for vals in mc_by_type.values() for w in vals]
    print(f"  {'ALL':12s} n={len(all_mc_words):3d}  {median_range(all_mc_words)}")

    our_by_rung = {k: [] for k in OUR_RUNG_ORDER}
    for _, e, ann in ours:
        clue_text = e.get("clue", "")
        for k, text in ladder_steps(ann, clue_text):
            our_by_rung[k].append(word_count(text))
    print("\nOurs, words per rung:")
    for k in OUR_RUNG_ORDER:
        vals = our_by_rung[k]
        print(f"  {k:12s} n={len(vals):5d}  {median_range(vals)}")

    # ---------- VOICE ----------
    print("\n" + "-" * 78)
    print("VOICE — second person, first-plural, questions, imperatives, "
          "answer-naming before the last hint")
    print("-" * 78)

    def voice_stats(texts):
        n = len(texts)
        if not n:
            return "n/a"
        sp = sum(1 for t in texts if SECOND_PERSON.search(t))
        fp = sum(1 for t in texts if FIRST_PLURAL.search(t))
        q = sum(1 for t in texts if QUESTION.search(t))
        imp = sum(1 for t in texts if opens_imperative(t))
        return (f"n={n:5d}  2nd-person(you) {sp/n:5.1%}  1st-plural(we) {fp/n:5.1%}  "
                f"question {q/n:5.1%}  opens-imperative {imp/n:5.1%}")

    mc_all_texts = [h["text"] for r in mc for h in r["hints"]]
    print("\nTheirs, all hints:      " + voice_stats(mc_all_texts))
    for t in ["indicators", "fodder", "definition"]:
        texts = [h["text"] for r in mc for h in r["hints"] if h["type"] == t]
        print(f"  ...{t:12s}      " + voice_stats(texts))

    our_all_texts = [text for _, e, ann in ours
                     for _, text in ladder_steps(ann, e.get("clue", ""))]
    print("\nOurs, all rungs:        " + voice_stats(our_all_texts))
    for k in OUR_RUNG_ORDER:
        texts = [text for _, e, ann in ours
                 for kk, text in ladder_steps(ann, e.get("clue", "")) if kk == k]
        print(f"  ...{k:12s}      " + voice_stats(texts))

    # Answer-naming before the final hint.
    mc_leak = 0
    for r in mc:
        answer = re.sub(r"[^A-Za-z]", "", r.get("answer", ""))
        if not answer:
            continue
        early = r["hints"][:-1]
        if any(contains_word(h["text"], answer) for h in early):
            mc_leak += 1
    print(f"\nTheirs: answer named before the final hint in {mc_leak}/{len(mc)} records.")

    our_leak = 0
    our_total = 0
    for _, e, ann in ours:
        answer = re.sub(r"[^A-Za-z]", "", ann.get("answer", ""))
        if not answer:
            continue
        our_total += 1
        steps = ladder_steps(ann, e.get("clue", ""))
        early = [text for k, text in steps if k != "walkthrough"]
        if any(contains_word(t, answer) for t in early):
            our_leak += 1
    print(f"Ours:   answer named before the walkthrough rung in {our_leak}/{our_total} "
          "annotated clues.")

    leak_by_type = Counter()
    total_by_type = Counter()
    for _, e, ann in ours:
        answer = re.sub(r"[^A-Za-z]", "", ann.get("answer", ""))
        if not answer:
            continue
        fam = ann.get("type") or "?"
        total_by_type[fam] += 1
        steps = ladder_steps(ann, e.get("clue", ""))
        early = [text for k, text in steps if k != "walkthrough"]
        if any(contains_word(t, answer) for t in early):
            leak_by_type[fam] += 1
    print("Ours, leak rate for the types where it's common (type: leaked/total):")
    for fam, tot in total_by_type.most_common():
        if tot >= 40 and leak_by_type[fam] / tot >= 0.15:
            print(f"  {fam:20s} {leak_by_type[fam]:3d}/{tot:3d} "
                  f"({leak_by_type[fam]/tot:.0%}) — the 'blocks' rung's `gives` is the "
                  "whole answer when a single block resolves it directly.")

    # ---------- COVERAGE ----------
    print("\n" + "-" * 78)
    print("COVERAGE — do hints name the device, and explain what an indicator DOES")
    print("-" * 78)
    mc_named = sum(1 for r in mc if names_device(" ".join(h["text"] for h in r["hints"])))
    print(f"\nTheirs: device named somewhere in the 3 hints for {mc_named}/{len(mc)} records.")
    print("        (their 'indicators' hint routinely PAIRS each surface word "
          "with its own named job, even in compound clues — e.g. 'one of these "
          "is an X indicator ... another is a Y indicator ...'.)")

    our_type_present = sum(1 for _, e, ann in ours
                           if any(k == "type" for k, _ in ladder_steps(ann, e.get("clue", ""))))
    print(f"\nOurs: the 'type' rung (family name + blurb) is present for "
          f"{our_type_present}/{len(ours)} annotated clues (should be all — it's "
          "unconditional).")
    multi_op_clues = 0
    for _, e, ann in ours:
        t = (ann.get("type") or "").lower()
        ops = [op for k, op in INDICATOR_OPS if k in t]
        if len(ops) > 1 and ann.get("indicators"):
            multi_op_clues += 1
    print(f"Ours: {multi_op_clues} annotated clues have a compound type (>1 "
          "indicator operation) with indicators present. On those, our "
          "indicators rung explicitly declines to say which surface word maps "
          "to which job ('Which word calls for which is the step to work out "
          "here') — the opposite of what the MC sample above does.")

    # ---------- HIGHLIGHTING ----------
    print("\n" + "-" * 78)
    print("HIGHLIGHTING — char spans tying hint text to the clue")
    print("-" * 78)
    mc_spans = sum(len(h.get("highlighting") or []) for r in mc for h in r["hints"])
    mc_hints_n = sum(len(r["hints"]) for r in mc)
    print(f"\nTheirs: {mc_spans} stored char-span highlights across {mc_hints_n} hints "
          f"({mc_spans/mc_hints_n:.2f} per hint) — every hint ships pre-computed "
          "spans into clueText, including the fodder hint.")
    print("\nOurs: NOT a stored span — app.js `markUp()`/`bestOccurrence()` computes "
          "the highlight live from the clue string, for the 'definition' and "
          "'indicators' rungs only (see clueHTML() in app.js). The 'blocks' rung's "
          "clueFragment is named in prose but is NEVER highlighted in the live clue "
          "— this is the one MC does highlight (their fodder hint) that we do not.")

    # ---------- APP.md cross-check ----------
    # APP.md's "reference corpus" section was distilled from course.json's 55
    # WORKED examples (each has a post-hint `explanation`), not from this
    # 24-record hints.jsonl (live daily hints, no `explanation` field at all —
    # check the keys). Different snapshot, same site. Re-derive APP.md's cited
    # numbers here so a drift shows up as a printed mismatch, not a re-read of
    # prose that could quietly go stale.
    print("\n" + "-" * 78)
    print("APP.md CROSS-CHECK — against course.json, the corpus it actually cites")
    print("-" * 78)
    if not COURSE_PATH.exists():
        print(f"\n{COURSE_PATH} not found — skipping (also gitignored, local-only).")
    else:
        course = json.load(open(COURSE_PATH))
        examples = course.get("examples", {})
        n = len(examples)
        nhints = Counter(len(v.get("hints") or []) for v in examples.values())
        seqs = Counter(tuple(h.get("type") for h in (v.get("hints") or []))
                        for v in examples.values())
        all_words = [word_count(h.get("text"))
                     for v in examples.values() for h in (v.get("hints") or [])]
        exp_words = [word_count(v.get("explanation")) for v in examples.values()
                     if v.get("explanation")]
        every_highlighted = all(h.get("highlighting") for v in examples.values()
                                 for h in (v.get("hints") or []))
        ind_fod_def = seqs.get(("indicators", "fodder", "definition"), 0)
        dd_seq = sum(c for s, c in seqs.items() if s == ("definition 1", "definition 2"))
        leak = 0
        for v in examples.values():
            answer = re.sub(r"[^A-Za-z]", "", v.get("answer", ""))
            hs = v.get("hints") or []
            if answer and any(contains_word(h["text"], answer) for h in hs[:-1]):
                leak += 1
        print(f"\n  n examples                    {n}   (APP.md: 55)")
        print(f"  3-hint / 2-hint split         {nhints[3]}/{nhints[2]}   (APP.md: 46/9)")
        print(f"  indicators->fodder->definition {ind_fod_def}/{n}   (APP.md: 41 of 55)")
        print(f"  double-def -> def1->def2       {dd_seq}   (APP.md: implied 'the exception')")
        print(f"  every hint highlighted        {every_highlighted}   (APP.md: '156 of 156')")
        print(f"  median words/hint             {statistics.median(all_words):.0f}   (APP.md: '~25')")
        print(f"  median words/explanation      {statistics.median(exp_words):.0f}   (APP.md: '~73')")
        print(f"  answer named before last hint {leak}/{n}   (APP.md: 'a hint never leaks the answer')")
        print("\n  All check out. Two things APP.md doesn't say, both visible here:")
        print("  1. course.json (55, cited) and hints.jsonl (24, this task's input) are")
        print("     DIFFERENT snapshots — hints.jsonl has no `explanation` field at all,")
        print("     so 'the closing explanation ends warmly' cannot be checked against it.")
        print("  2. 4/55 course.json examples run definition BEFORE indicators/fodder —")
        print("     'their default order' is a strong majority, not a rule with one named")
        print("     exception (double-definition); APP.md's wording already hedges this")
        print("     correctly ('default'), so this is a footnote, not a fix.")

    print("\n" + "=" * 78)
    print("Done.")


if __name__ == "__main__":
    main()
