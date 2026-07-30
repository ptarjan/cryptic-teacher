#!/usr/bin/env python3
"""Warn about the clue shapes that lose to human setters in blind grading.

tools/validate_annotations.py proves a clue is *sound*. Blind grading against
published clues showed soundness is not the problem — we scored +0.72 on fairness
and still lost overall, because we scored -1.21 on misdirection and -0.98 on
penny-drop. The clues were correct and lifeless.

This tool cannot see wit; nothing can. What it can see is the *shape* that
lifeless clues share, which turned out to be strikingly consistent across our six
worst-scoring clues: the parts of the mechanism listed in order, joined by a
comma or a copula, with no sentence wrapped around them.

  Later rewritten, to change          (2.47/5 — fodder, indicator, definition)
  Cold heap is inexpensive            (2.33/5 — part + part IS definition)
  Identity tucked into southeast      (2.80/5 — pure assembly instructions)

Rewriting those six clues produced a second complaint, and it is the sharper one:
*they still do not read as real sentences or carry a joke.* `That Conservative
lot, and mean with it` is a grammatical fragment with no finite verb — nothing a
person would ever say out loud. Three further checks look for that: a clue with
no finite verb (`not-a-sentence`), a clue that opens by telling the solver what
to do (`imperative-opening`), and a clue built out of word pairs that no
published setter has ever written (`unattested-phrasing`).

Every warning here is a smell, not an error. Exit status is 0 either way — this
informs the setter, it does not block the build.

How well each check actually predicts a judge's score, measured on the 20 clues
of A001 (mean judge score when the check fires, minus when it does not):

    copula-definition        -0.46   (fired on 2)
    indicator-abuts-fodder   -0.45   (fired on 4)
    terse                    -0.27   (fired on 10)
    fenced-definition        +0.16   (fired on 3)
    stock-indicator          +1.22   (fired on 1)

Only the first three point the way they were designed to, and n=20 clues judged
by 3 judges is far too small to call any of them established. The last two are
currently evidence *against* themselves — `stock-indicator` fired once, on our
single best clue. They are kept because the reasoning behind them is sound and
one clue cannot refute it, but do not treat them as authority. Re-run this table
after the next graded puzzle; a check that keeps pointing the wrong way should be
deleted, not defended.

How often each check fires on clues nobody thinks are broken — 1000 clues drawn
at random from times_xwd_times, fifteensquared and bigdave44, held out of the
corpus tables so `unattested-phrasing` cannot find its own input attested
(`python3 tools/clue_quality.py --calibrate`). Beside it, the same checks on our
20, both as they were graded and as they stand after rewriting:

    check                    published   A001 graded   A001 rewritten
    copula-definition             1.1%          10%            5%
    fenced-definition             5.9%          15%           10%
    indicator-abuts-fodder         n/a          20%           20%
    stock-indicator                n/a           5%            5%
    terse                        20.0%          50%           30%
    not-a-sentence               48.3%          60%           45%
    imperative-opening            1.5%           0%            0%
    unattested-phrasing           5.7%           0%            0%

    n/a: reads an annotation the corpus does not carry, so it cannot be run on
    published clues at all. Those two rates are not evidence of anything.

A second draw (`--calibrate --sample 800 --seed 5`) gives 48.0%, 2.2% and 3.5%
for the three new checks, so the published column is not an artefact of one
sample.

Read that table before trusting any of these, because two of the three new checks
fire on MORE published clues than on ours, and a check that flags Araucaria is a
broken check:

  * `not-a-sentence` flags nearly half the Times. Published setters write
    verbless clues constantly — `Bird — large one in sort of American pie`,
    `Old man in sham woolly shawl` — and they are fine, because a noun phrase can
    still be a thing a person would say. The check does point the right way at
    the margin (60% on the 20 as graded, 45% on the same 20 after rewriting,
    against 48% published), but a 12-point gap on n=20 is a nudge in aggregate
    and nothing at all on a single clue. Do not rewrite a clue because this
    fired — reread it aloud, and decide for yourself.
  * `unattested-phrasing` fires on 5.7% of published clues and on none of ours,
    at any threshold that keeps the published rate under 10%. The reason is
    measurable: our clues' unattested content-bigram fraction averages 0.39 and
    the published median is 0.38. Our phrasing is as attested as the Times'. So
    whatever is wrong with `That Conservative lot, and mean with it`, it is not
    that the word pairs are strange — it is that the pairs are ordinary and the
    sentence they make is not one anybody needed to say. The check earns nothing
    today; it is kept as a guard against letter-driven word salad, which is a
    failure we have not made yet.
  * `imperative-opening` also fires more on published (1.5%) than on ours (0%),
    but all 15 published firings are real solver-instructions (`Cut complaints
    associated with take-out`, `Get rid of endless booty…`), so the check is
    doing what it says; the shape is simply rare everywhere. It is a guard, not a
    diagnosis.

The concealment complaint, and why no check came out of it
---------------------------------------------------------
Blind grading produced a second, quite separate criticism, which three judges
wrote down independently and unprompted: not that the clues lacked wit but that
they gave the mechanism away — "the anagrind is the second word", "the hiding
place announced by the first two words", "entirely fair and entirely
telegraphed". That is a claim about where indicators sit, so it can be measured.

It was measured against the 559,848 clues of times_xwd_times, fifteensquared and
bigdave44. 444,664 of them contain one of the 13,920 indicator phrases in the
corpus's `indicators` table. In 38,830 the answer is a letter-for-letter anagram
of a run of clue words, so the fodder is verified by sorting rather than guessed
and the anagrind is whichever anagram indicator sits outside it; 12,166 more
hide the answer across a word boundary, giving the same structural certainty
about hidden-word clues. Our side is the 13 clues of A001 that carry an
annotated indicator. "Wordplay region" below means the clue minus its
definition, which is where an indicator is actually free to move.

    measure                                        published        A001
    indicator abuts its fodder (verified anagram)      88.9%      4 of 5
      ...counting any candidate anagrind               94.5%
    indicator abuts its hiding place (hidden)          92.2%      2 of 2
    indicator starts in the clue's first two words     36.7%     10 of 13
    indicator in first two words of the wordplay       53.0%     11 of 13
    indicator IS the first word of the wordplay        26.6%      4 of 13
    indicator in the first quarter of the wordplay     41.6%      6 of 13
    mean normalised position in the wordplay            0.40        0.35
    definition sits at a clue boundary                 99.4%     20 of 20
    punctuation between indicator and fodder            8.3%      0 of 5
    every content word used by the mechanism           62.3%      3 of 5

The criticism does not reproduce as a measurable property, and two parts of it
are simply false:

  * Adjacency is the published norm, overwhelmingly. Nine anagram clues in ten
    put the anagrind directly against its fodder, and hidden-word clues are
    tighter still. Our four-in-five is unremarkable. `indicator-abuts-fodder`
    therefore does not mean "unlike published practice" — it flags the commonest
    shape in the corpus. It is kept only because it is the check with the second
    strongest correlation to judge score above (-0.45), and that correlation, not
    the shape, is the whole of its claim to exist. Read it as "this clue had no
    other disguise", never as "setters do not do this". Since 2026-07-30 the
    opposite is a hard rule: `check_indicator_adjacency` in
    validate_annotations.py ERRORs when an anagram indicator is NOT next to its
    fodder, because an indicator only operates on what it touches. So the only
    legal response to this smell is a different indicator, never a moved one.
  * Rarity does not separate once indicators are compared like with like. The
    existing `stock-indicator` premise — that published setters use each
    indicator about once — is an artefact of counting rows in the `indicators`
    table, which holds one row per (wordplay, indicator) pair and so tops out at
    5; the real usage counts live in its `clue_rowids` column. Counted properly,
    the anagrind of a published anagram clue has a median of 31 recorded uses
    (p25 6, p75 137) — published anagrinds are stock words half the time. Ours
    have a median of 136, which is the 60th percentile of published practice on
    n=5; our two hidden-word indicators land at the 44th. Against a pooled
    all-types distribution ours look commoner (mean percentile 0.69), but that
    pool mixes anagram indicators with container and deletion ones drawn from far
    larger vocabularies, and the comparison is worthless. A rarity percentile
    does not discriminate better than the current top-2% cutoff; it discriminates
    no better than chance, so nothing was changed.

Position is the one place a gap appears, and it did not survive being poked. Our
indicator starts in the clue's first two words on 10 of 13 against a published
36.7%, which looks damning; but published clues are longer than ours, and the
rate depends strongly on clue length and on whether the definition is leading or
trailing. Conditioned on both, the expected count is 6.0 of 13 against our 10
(Poisson-binomial p=0.015). Conditioned instead on the length of the wordplay
region — the fairer control, and one our clues do not fail: our median region is
5 words and so is the corpus's — the expectation is 7.5 of 13 against our 11
(p=0.032).

Then the same property was binarised five other ways, and every one of them
comes out flat: indicator as the wordplay's first word, 26.6% published against
4 of 13; indicator in the first quarter of the region, 41.6% against 6 of 13;
mean normalised position, 0.40 published against our 0.35 (permutation p=0.30 on
region-length-matched draws). The whole effect lives at exactly one cut — the
indicator being the *second* word of the wordplay, 26.4% published against 7 of
13 — which is the very phrase the judges used, and which is what one expects to
find after trying six cuts on thirteen clues. A p of 0.03 chosen from six
attempts is not a finding.

So: no check was added. Any threshold loose enough to catch our shape fires on
roughly half the Times, which is the `not-a-sentence` failure over again, and
the stricter thresholds show no gap at all. Three other candidate tells were
tried and are dead on arrival: the definition sits at a clue boundary in 99.4% of
published clues (it is a convention of the genre, not a tell), punctuation
between indicator and fodder is rare everywhere, and the fraction of clues whose
every content word does mechanism duty is 62.3% published against 3 of our 5.

The honest summary is that the judges were describing something real about how
the clues read and reaching for the nearest structural explanation, which turned
out to be wrong. Our indicators are not placed unusually and are not unusually
stock. Whatever is being seen when a clue feels telegraphed, it is not the
position or the frequency of the indicator, and the search for it should look
somewhere other than the mechanism's coordinates. Re-run this against the next
graded puzzle before believing any of it; n=13 refutes nothing on its own, it
only fails to establish.

  python3 tools/clue_quality.py tools/data/authored_A001_clues.json
  python3 tools/clue_quality.py --calibrate --sample 1000
"""

import argparse
import json
import random
import re
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path.home() / "cryptic-setter-data" / "georgeho" / "data.db"

# Verbs that bolt a definition onto assembled wordplay. Real setters use these
# too, but as part of a sentence that means something; when one sits exactly at
# the seam between wordplay and definition it is doing no surface work at all.
COPULAS = r"(?:is|are|was|were|gives|makes|means|provides|produces|becomes|yields)"

# How rare an indicator has to be before it stops shouting. Published setters use
# 92% of their indicators exactly once; ours clustered in the top few percent by
# frequency, which is why judges could see the mechanism coming.
STOCK_PERCENTILE = 0.02

# Every second row of the corpus: 330k of the 660k clues, spread across all ten
# sources because the rowids interleave. The bigram table it builds has ~870k
# entries and costs a few seconds and a few hundred MB; set this to 1 for the
# whole corpus if you are willing to pay double for a slightly denser table.
CORPUS_SAMPLE_MODULUS = 2

# --- the finite-verb inventory ----------------------------------------------
# There is no POS tagger here and there will not be one; the whole tool is
# stdlib. So "does this clue contain a finite verb" is answered by a closed-class
# inventory plus two corpus-derived open-class sets (see load_corpus_norms).
#
# Its limits, stated up front:
#   * A finite verb outside the inventory and outside the corpus sets is missed,
#     so a real sentence can be flagged. Rare present-tense verbs ("Minister
#     resigns") are the usual victims.
#   * -ed forms are hopelessly ambiguous in cryptic English: `Dream disturbed,
#     carrying a gun` is a noun phrase but `Morgan dropped a million` is a
#     sentence, and they are the same shape. The tie is broken by asking whether
#     the corpus ever uses that word as a wordplay indicator; if it does, it is
#     assumed to be doing mechanism duty rather than being the sentence's verb.
#     That is a guess, and it is wrong on some clues in both directions.
#   * "'s" is counted as a verb, though it is a genitive at least as often as it
#     is `is`/`has`. That direction is chosen deliberately: everywhere this
#     inventory guesses, it guesses towards "there is a verb", because a missed
#     warning costs nothing and a wrong one scolds a good clue.
#   * No agreement, no clause structure, no scope. A finite verb anywhere in the
#     clue counts, even inside a subordinate clause, and a bare plural present
#     ("Compilers keep secrets") is missed entirely for want of a subject number.
COPULA_FORMS = {
    "is", "are", "was", "were", "am", "isn't", "aren't", "wasn't", "weren't",
    "has", "have", "had", "hasn't", "haven't", "hadn't",
    "does", "do", "did", "doesn't", "don't", "didn't",
    "will", "won't", "would", "wouldn't", "can", "can't", "cannot", "could",
    "couldn't", "may", "might", "must", "mustn't", "shall", "should",
    "shouldn't", "ought", "need", "dare", "'s", "'re", "'ll", "'ve", "'d",
}
# Irregular finite pasts. Deliberately excludes forms that are commoner as nouns
# or adjectives in clue English (left, lost, won, put, hit, set, cast, read,
# rose, bore, wound, drew, shot, spent, ground), because a false negative here
# only costs a missed warning while a false positive scolds a good clue.
IRREGULAR_PAST = {
    "went", "saw", "took", "gave", "came", "said", "told", "knew", "thought",
    "wrote", "broke", "kept", "sent", "met", "brought", "caught", "fell",
    "felt", "heard", "meant", "paid", "sold", "stood", "understood", "became",
    "began", "drove", "ate", "flew", "grew", "bought", "built", "chose",
    "fought", "forgot", "hid", "rode", "rang", "sang", "sank", "slept",
    "spoke", "stole", "swam", "taught", "tore", "woke", "blew", "dug", "fed",
    "fled", "froze", "hung", "leapt", "lit", "shook", "shone", "sprang",
    "stuck", "swore", "swept", "threw", "wore", "struck", "led", "ran",
}
# Words that end in -ed and are not past tenses. The -eed family (speed, need,
# breed, indeed) is excluded wholesale, which costs "agreed" and "freed"; the
# rest are the -ed nouns and adjectives frequent enough in clue English to
# matter. Without this, `Space losing its head at speed` reads "speed" as a verb.
ED_NOT_A_VERB = {
    "sacred", "hundred", "hatred", "kindred", "wicked", "naked", "aged",
    "united", "limited", "moped", "shred", "biped", "quadruped", "tweed",
    "shed", "sled", "embed", "inbred", "crossbred", "learned", "beloved",
    "rugged", "ragged", "jagged", "wretched", "crooked", "blessed", "cursed",
}
# Verbs that tell the SOLVER what to do with the letters. An imperative is
# grammatically a sentence, which is why these words are exempt from
# `not-a-sentence` — but an imperative addressed to the solver is not a surface,
# which is why they get their own warning instead. The two checks never fire on
# the same clue: this list is folded into the imperative openers that satisfy
# check 1, and then flagged by check 2.
ASSEMBLY_VERBS = {
    "take", "put", "add", "note", "place", "insert", "get", "set", "bring",
    "give", "append", "attach", "combine", "include", "join", "move",
    "position", "remove", "replace", "return", "swap", "use", "keep", "hold",
    "follow", "precede", "surround", "contain", "drop", "cut", "trim",
}
# Words too common to carry any information about whether a phrase is real
# English. A bigram of two of these is not evidence of anything.
FUNCTION_WORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "by",
    "from", "as", "and", "or", "but", "not", "no", "nor", "so", "if", "then",
    "than", "there", "here", "it", "its", "this", "that", "these", "those",
    "he", "she", "they", "we", "i", "you", "his", "her", "their", "my", "our",
    "your", "him", "them", "us", "me", "who", "whom", "whose", "which",
    "what", "when", "where", "how", "why", "up", "down", "out", "off", "over",
    "under", "into", "about", "after", "before", "between", "through",
    "during", "against", "one", "some", "any", "all", "is", "are", "was",
    "were", "be", "been", "being", "am", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "must", "should",
    "'s", "'re", "'ll", "'ve", "'d", "'t",
}

# `unattested-phrasing` fires when this fraction or more of a clue's content
# bigrams are absent from the corpus. Chosen from the published-clue
# distribution, not from taste: 1000 held-out broadsheet clues have a median
# unattested fraction of 0.38, p90 of 0.75 and p95 of 0.83, so 0.8 sits in the
# tail and fires on 5.7% of them. 0.75 would fire on 10.5%, which is too loud.
UNATTESTED_FRACTION = 0.8
# Below this many content bigrams the fraction is too coarse to mean anything —
# one unlucky pair out of two is 50% and says nothing.
UNATTESTED_MIN_BIGRAMS = 4


def words(clue):
    return re.findall(r"[A-Za-z']+", clue)


def strip_enum(clue):
    # The corpus is scraped from blogs and uses curly apostrophes; normalise, or
    # every contraction in it ("doesn't", "he's") tokenises as a nonsense word.
    clue = clue.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s*\([\d,\-\s/]+\)\s*$", "", clue).strip()


def tokens(clue):
    """Lowercased words, with contractions split off as their own token."""
    out = []
    for w in re.findall(r"[a-z']+", strip_enum(clue).lower()):
        m = re.match(r"^(.*?)('s|'re|'ll|'ve|'d|n't)$", w)
        if m and m.group(1):
            out.extend([m.group(1), m.group(2).replace("n't", "'t")])
        else:
            out.append(w)
    return [w for w in out if w]


def bigrams(toks):
    return list(zip(toks, toks[1:]))


def stems(word):
    """Candidate base forms of a third-person -s word. No real morphology."""
    if not word.endswith("s") or len(word) < 4:
        return ()
    out = [word[:-1]]
    if word.endswith("es"):
        out.append(word[:-2])
    if word.endswith("ies"):
        out.append(word[:-3] + "y")
    return tuple(out)


def load_corpus_norms(path, exclude=None):
    """Corpus norms: clue length, indicator frequency, verb sets, bigrams.

    `exclude` is a set of clue strings to leave out of the bigram table, so that
    calibration can score published clues against a corpus that does not already
    contain them.
    """
    if not Path(path).exists():
        return None
    exclude = exclude or set()
    db = sqlite3.connect(path)

    lengths = {}
    seen_bigrams = set()
    after_to = {}       # word -> times it followed "to" (infinitive evidence)
    after_det = {}      # word -> times it followed a determiner (noun evidence)
    after_subj = {}     # word -> times it followed a subject pronoun (verb evidence)
    determiners = {"the", "a", "an", "his", "her", "its", "their", "this",
                   "that", "these", "those", "my", "our", "your", "every"}
    subjects = {"he", "she", "they", "we", "who", "which", "you", "i"}

    rows = db.execute(
        "select answer, clue from clues where clue is not null "
        f"and rowid % {CORPUS_SAMPLE_MODULUS} = 0"
    )
    n_rows = 0
    for ans, clue in rows:
        n_rows += 1
        toks = tokens(clue)
        if ans:
            n = len("".join(c for c in ans if c.isalpha()))
            if 3 <= n <= 12:
                lengths.setdefault(n, []).append(len(words(strip_enum(clue))))
        if clue.strip() not in exclude:
            for bg in bigrams(toks):
                seen_bigrams.add(bg)
        for i, w in enumerate(toks):
            if not i:
                continue
            prev = toks[i - 1]
            if prev == "to":
                after_to[w] = after_to.get(w, 0) + 1
            elif prev in determiners:
                after_det[w] = after_det.get(w, 0) + 1
            elif prev in subjects:
                after_subj[w] = after_subj.get(w, 0) + 1

    median_words = {n: statistics.median(v) for n, v in lengths.items() if len(v) > 50}

    freq = {}
    for (ind,) in db.execute("select indicator from indicators"):
        if ind:
            freq[ind.strip().lower()] = freq.get(ind.strip().lower(), 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: -kv[1])
    cutoff = max(1, int(len(ranked) * STOCK_PERCENTILE))
    stock = {w for w, _ in ranked[:cutoff]}

    # Base forms, from infinitives: "to bury", "to alter". A noun that sometimes
    # follows "to" (a destination) is filtered out by the determiner count.
    base_verbs = {w for w, c in after_to.items()
                  if c >= 6 and after_det.get(w, 0) < 0.5 * c}
    # Present-tense -s forms: the word follows a subject pronoun at least as
    # often as it follows a determiner ("gets" does, "stars" and "papers" do
    # not). The second signal — stem is a known infinitive — is applied at check
    # time by finite_verbs(), so a word never seen in either context still gets
    # a hearing. Both are measured on clues of the exact register we write in.
    verby_s = {w for w, c in after_subj.items()
               if w.endswith("s") and c >= 2 and c >= after_det.get(w, 0)}

    return {"median_words": median_words, "stock": stock,
            "verby_s": verby_s, "base_verbs": base_verbs | ASSEMBLY_VERBS,
            "bigrams": seen_bigrams, "indicator_vocab": set(freq),
            "n_rows": n_rows}


def finite_verbs(toks, norms):
    """Words in `toks` that can be read as the finite verb of a clause."""
    found = []
    for w in toks:
        if w in COPULA_FORMS or w in IRREGULAR_PAST:
            found.append(w)
        elif norms and (w in norms["verby_s"]
                        or any(s in norms["base_verbs"] for s in stems(w))):
            found.append(w)
        elif w.endswith("ed") and len(w) > 4 and not w.endswith("eed") \
                and w not in ED_NOT_A_VERB:
            # Past tense or participle-as-indicator? Ask the corpus whether the
            # word has a life as a wordplay indicator; if it does, assume it is
            # the mechanism talking, not the sentence.
            if not norms or w not in norms["indicator_vocab"]:
                found.append(w)
    return found


def opens_imperative(toks, norms):
    if not toks:
        return None
    first = toks[0]
    if first in COPULA_FORMS:
        return None
    if first in ASSEMBLY_VERBS or (norms and first in norms["base_verbs"]):
        return first
    return None


def check(eid, spec, norms):
    """Return a list of (code, message) smells for one clue."""
    clue = strip_enum(spec["clue"])
    ann = spec.get("annotation", {})
    out = []
    ws = words(clue)
    lower = clue.lower()
    definition = (ann.get("definition") or "").strip()

    # 1. Definition welded on with a copula, at the seam of the wordplay.
    if definition:
        d = re.escape(definition.lower())
        if re.search(rf"\b{COPULAS}\s+(?:an?\s+|the\s+)?{d}\b", lower):
            out.append(("copula-definition",
                        f"'{definition}' is bolted on with a copula; the clue "
                        f"states its own answer rather than describing a scene"))

    # 2. Definition fenced off by punctuation — the giveaway of a parts list.
    for chunk in re.split(r"\s*[,:;]\s*", lower):
        c = re.sub(r"^(?:to|a|the|an)\s+", "", chunk).strip()
        if definition and c == definition.lower():
            out.append(("fenced-definition",
                        f"'{definition}' sits alone behind punctuation, so the "
                        f"surface never has to accommodate it"))
            break

    # 3. Anagram indicator jammed against its own fodder.
    fodder = ((ann.get("anagram") or {}).get("fodder") or "").strip()
    if fodder:
        for ind in ann.get("indicators") or []:
            pat = rf"\b{re.escape(fodder.lower())}\s+{re.escape(ind.lower())}\b|" \
                  rf"\b{re.escape(ind.lower())}\s+{re.escape(fodder.lower())}\b"
            if re.search(pat, lower):
                # NOT a suggestion to move the indicator: adjacency is REQUIRED
                # (check_indicator_adjacency in validate_annotations.py makes a
                # separated indicator a hard ERROR — an indicator only operates
                # on what it touches). This smell survives only on its -0.45
                # correlation with judge score, and the fix is always to change
                # the indicator, never to slide it away from the fodder.
                out.append(("indicator-abuts-fodder",
                            f"'{ind}' sits directly against '{fodder}' with no "
                            f"disguise — pick an indicator that reads as ordinary "
                            f"description; do NOT move it, adjacency is required"))
                break

    # 6. No finite verb: a noun phrase, not an utterance.
    toks = tokens(clue)
    imperative = opens_imperative(toks, norms)
    verbs = finite_verbs(toks, norms)
    if not verbs and not imperative:
        out.append(("not-a-sentence",
                    "no finite verb found, so this is a noun phrase rather than "
                    "an utterance; published setters do this on half their clues "
                    "and get away with it, so the question is only whether the "
                    "phrase is one a person would actually say aloud"))

    # 7. Opens by telling the solver what to do. Grammatically a sentence
    #    (which is why check 6 lets it through), but the addressee is the solver,
    #    not anyone inside the surface — instructions wearing a sentence's
    #    clothes.
    if imperative and imperative in ASSEMBLY_VERBS:
        out.append(("imperative-opening",
                    f"'{imperative}' opens the clue by instructing the solver; "
                    f"the sentence's addressee is the person holding the pencil, "
                    f"so there is no scene for anyone else to picture"))

    if norms:
        # 8. Phrasing nobody has ever published. Not a rule against novelty —
        #    a rule against word pairs that only exist because the letters
        #    needed them.
        content = [(a, b) for a, b in bigrams(toks)
                   if a not in FUNCTION_WORDS or b not in FUNCTION_WORDS]
        if len(content) >= UNATTESTED_MIN_BIGRAMS:
            missing = [bg for bg in content if bg not in norms["bigrams"]]
            frac = len(missing) / len(content)
            if frac >= UNATTESTED_FRACTION:
                shown = ", ".join(f"'{a} {b}'" for a, b in missing[:3])
                out.append(("unattested-phrasing",
                            f"{len(missing)} of {len(content)} content word "
                            f"pairs never appear in {norms['n_rows']:,} published "
                            f"clues ({shown}); the phrasing was built to fit the "
                            f"letters, not spoken"))

        # 4. Stock indicators. Rarity is the cheapest misdirection there is.
        for ind in ann.get("indicators") or []:
            k = ind.strip().lower()
            if k in norms["stock"]:
                out.append(("stock-indicator",
                            f"'{ind}' is one of the most-used indicators in the "
                            f"corpus; solvers read it as a signpost"))

        # 5. Too short to carry a picture. Not a rule against brevity — a rule
        #    against having no room for a surface idea.
        n = len("".join(c for c in ann.get("answer", "") if c.isalpha()))
        med = norms["median_words"].get(n)
        if med and len(ws) < med - 1:
            out.append(("terse",
                        f"{len(ws)} words against a published median of "
                        f"{med:.0f} for {n}-letter answers; there may be no room "
                        f"for a surface"))

    return out


CODES = ["copula-definition", "fenced-definition", "indicator-abuts-fodder",
         "stock-indicator", "terse", "not-a-sentence", "imperative-opening",
         "unattested-phrasing"]

CALIBRATION_SOURCES = ("times_xwd_times", "fifteensquared", "bigdave44")


def calibrate(corpus, n, seed):
    """Firing rate of every check on published broadsheet clues.

    A check that fires often on the Times is not measuring our problem, it is
    measuring English. The published clues are held out of the bigram table so
    `unattested-phrasing` cannot trivially find its own input attested.
    """
    db = sqlite3.connect(corpus)
    marks = ",".join("?" * len(CALIBRATION_SOURCES))
    rows = [(c, a, d) for c, a, d in db.execute(
        f"select clue, answer, definition from clues where source in ({marks}) "
        f"and clue is not null and answer is not null", CALIBRATION_SOURCES)]
    random.Random(seed).shuffle(rows)
    sample = rows[:n]
    print(f"sampling {len(sample)} clues from "
          f"{', '.join(CALIBRATION_SOURCES)} (seed {seed})")

    held_out = {c.strip() for c, _, _ in sample}
    print("building corpus norms with those clues held out...")
    norms = load_corpus_norms(corpus, exclude=held_out)
    print(f"{norms['n_rows']:,} corpus clues, {len(norms['bigrams']):,} bigrams, "
          f"{len(norms['verby_s']):,} present-tense verb forms, "
          f"{len(norms['base_verbs']):,} base forms")

    # The published clues carry no annotation, so the three checks that read one
    # (copula-definition, fenced-definition, indicator-abuts-fodder) get the
    # corpus `definition` column and nothing else; stock-indicator and
    # indicator-abuts-fodder cannot run at all and are reported as n/a.
    counts = {c: 0 for c in CODES}
    fracs = []
    for clue, answer, definition in sample:
        spec = {"clue": clue, "annotation": {
            "answer": answer, "definition": definition or "", "indicators": []}}
        for code, _ in check("pub", spec, norms):
            counts[code] += 1
        toks = tokens(strip_enum(clue))
        content = [(a, b) for a, b in bigrams(toks)
                   if a not in FUNCTION_WORDS or b not in FUNCTION_WORDS]
        if len(content) >= UNATTESTED_MIN_BIGRAMS:
            fracs.append(sum(bg not in norms["bigrams"] for bg in content)
                         / len(content))

    print("\nfiring rate on published clues:")
    for code in CODES:
        note = ""
        if code in ("stock-indicator", "indicator-abuts-fodder"):
            note = "  (needs an annotation; not comparable)"
        print(f"  {code:24} {counts[code] / len(sample):6.1%}{note}")

    fracs.sort()
    print(f"\nunattested content-bigram fraction, published clues "
          f"(n={len(fracs)} of {len(sample)} have >= {UNATTESTED_MIN_BIGRAMS} "
          f"content pairs; the rest can never fire):")
    for pct in (50, 75, 90, 95, 98, 99):
        print(f"  p{pct:<3} {fracs[int(len(fracs) * pct / 100)]:.2f}")
    for thresh in (0.4, 0.5, 0.6, 0.667, 0.75, 0.8, 1.0):
        rate = sum(f >= thresh for f in fracs) / len(sample)
        print(f"  threshold {thresh:.3f} would fire on {rate:6.2%} of the "
              f"{len(sample)} sampled clues")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clues", nargs="?",
                    default="tools/data/authored_A001_clues.json")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--calibrate", action="store_true",
                    help="report each check's firing rate on published clues")
    ap.add_argument("--sample", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    if args.calibrate:
        calibrate(args.corpus, args.sample, args.seed)
        return

    path = Path(args.clues)
    if not path.is_absolute():
        path = ROOT / path
    data = json.loads(path.read_text())
    norms = load_corpus_norms(args.corpus)
    if norms is None:
        print(f"note: no corpus at {args.corpus} — skipping frequency and "
              f"length checks", file=sys.stderr)

    flagged = 0
    total = 0
    for eid, spec in sorted(data.items()):
        if eid.startswith("_"):
            continue
        total += 1
        smells = check(eid, spec, norms)
        if not smells:
            continue
        flagged += 1
        print(f"\n{eid}: {spec['clue']}")
        for code, msg in smells:
            print(f"  [{code}] {msg}")

    print(f"\n{flagged}/{total} clues carry at least one smell.")
    print("These are smells, not errors. Three on one clue means it is a list "
          "of parts wearing a sentence's clothes.")


if __name__ == "__main__":
    main()
