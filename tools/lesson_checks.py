"""Annotation findings that tools/validate_annotations.py counts, each under its
own ratchet field:

  * a clue filed as a double definition (two definitions, no wordplay) whose own
    words hide the answer, or hold the exact letters of the answer in a run of
    whole clue words: the wordplay is there and was not parsed (DD_MISSES_WORDPLAY);
  * an answer that takes an apostrophe or an accent and has no `spelling`, so the
    page shows FLANEUR and GET SOMEONES GOAT: the annotation's own prose writes
    it so, or another annotation gave the same answer that spelling
    (tools/data/lexicons/spellings.json, written by tools/build_spellings.py)
    (SPELLING_UNSAID).
"""
import functools
import json
import re
import unicodedata
from pathlib import Path

DD_MISSES_WORDPLAY = "double definition whose clue hides or anagrams the answer"
SPELLING_UNSAID = "answer takes an apostrophe or accent, but no spelling"

#: Fewest answer letters for which a hidden word, or an anagram of whole clue
#: words, is more than chance (measured on the corpus: every sampled hit was a
#: real hidden word or anagram).
MIN_HIDDEN = 4
MIN_ANAGRAM = 5
#: A run of this many clue words or fewer is searched for the answer's letters.
MAX_RUN = 8


def _fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def letters(text):
    return re.sub(r"[^A-Z]", "", _fold(text).upper())


def double_definition(ann):
    """True for two or more definitions and no wordplay: the filing of a double definition."""
    return not ann.get("wordplay") and len(ann.get("definitions") or []) >= 2


def _def_spans(ann, clue):
    """[(start, end)] of each definition in the clue, by its `at` or else where its text first sits."""
    low = clue.lower()
    out = []
    for d in ann.get("definitions") or []:
        text = str(d.get("text") or "") if isinstance(d, dict) else str(d)
        at = d.get("at") if isinstance(d, dict) and isinstance(d.get("at"), int) else low.find(text.lower())
        if text and at is not None and at >= 0:
            out.append((at, at + len(text)))
    return out


def dd_misses_wordplay(ann, clue, answer):
    """'hidden' or 'anagram' when a double definition's clue holds the answer
    as a hidden word (read either way, not the whole of a word) or as the
    letters of a run of whole clue words in another order; else None. A run that
    lies wholly inside one definition is that definition's own words, not hidden
    wordplay: "for trees" scrambles to FORESTER by chance in the genuine double
    definition "A novelist, perhaps, for trees?" (round 12)."""
    if not double_definition(ann) or not clue or not answer:
        return None
    ans = letters(answer)
    found = [(m.start(), m.end(), letters(m.group())) for m in re.finditer(r"[^\W\d_]+", clue)]
    found = [f for f in found if f[2]]
    words = [f[2] for f in found]
    spans = _def_spans(ann, clue)

    def inside(i, j):  # words i..j (inclusive) lie within one definition
        return any(a <= found[i][0] and found[j][1] <= b for a, b in spans)

    if len(ans) >= MIN_HIDDEN:
        flat, pos = "".join(words), 0
        cuts, owner = set(), []
        for k, w in enumerate(words):
            owner += [k] * len(w)
            pos += len(w)
            cuts.add(pos)
        for rev, (text, own) in enumerate(((flat, owner), (flat[::-1], owner[::-1]))):
            i = text.find(ans)
            while i >= 0:
                ws = own[i:i + len(ans)]
                if any(i < c < i + len(ans) for c in ({len(flat) - c for c in cuts} if rev else cuts)) \
                        and not inside(min(ws), max(ws)):
                    return "hidden"
                i = text.find(ans, i + 1)
    if len(ans) >= MIN_ANAGRAM:
        for i in range(len(words)):
            run = ""
            for j, w in enumerate(words[i:i + MAX_RUN], i):
                run += w
                if len(run) >= len(ans):
                    break
            if len(run) == len(ans) and run != ans and sorted(run) == sorted(ans) and not inside(i, j):
                return "anagram"
    return None


def _hides(words, ans):
    """Whether `ans` sits in the run of `words` across at least one word break."""
    flat = "".join(words)
    cuts, pos = set(), 0
    for w in words:
        pos += len(w)
        cuts.add(pos)
    i = flat.find(ans)
    while i >= 0:
        if any(i < c < i + len(ans) for c in cuts):
            return True
        i = flat.find(ans, i + 1)
    return False


def _prose(node):
    """Every string in an annotation that is the annotator's own writing, not
    clue words (`words`, a definition's or indicator's `text`) or the spelling."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for x in node:
            yield from _prose(x)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k not in ("words", "text", "spelling", "at", "gives", "clueFragment"):
                yield from _prose(v)


@functools.lru_cache(maxsize=None)
def known_spellings():
    """{answer letters: spelling} for every answer an annotation has given an
    apostrophe or an accent (tools/build_spellings.py writes it)."""
    path = Path(__file__).resolve().parent / "data" / "lexicons" / "spellings.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _fits(said, enumeration):
    """Whether an apostrophe spelling of several words has the words the printed
    enumeration counts ("3,8,4"); a single word needs the known list, because
    prose writing she'd or messenger's is usually describing a pun or a clue word."""
    words = len(said.split())
    if words < 2:
        return False
    groups = re.fullmatch(r"[\d,\-\s]+", enumeration or "")
    return not groups or len(re.findall(r"\d+", enumeration)) == words


def prose_spellings(ann, answer, enumeration=None):
    """Every distinct way the annotation's own prose writes `answer` with an
    apostrophe or an accent (upper case, straight apostrophes), in order found."""
    ans = letters(answer)
    out = []
    for text in _prose(ann):
        if not re.search(r"[’'À-ɏ]", text):
            continue
        words = re.findall(r"[A-Za-zÀ-ɏ]+(?:[’'][A-Za-zÀ-ɏ]+)*", text)
        for i in range(len(words)):
            run = ""
            for j in range(i, min(i + MAX_RUN, len(words))):
                run += letters(words[j])
                if run == ans:
                    said = " ".join(words[i:j + 1])
                    if re.search(r"[À-ɏ]", said) or (re.search(r"[’']", said) and _fits(said, enumeration)):
                        said = said.replace("’", "'").upper()
                        if said not in out:
                            out.append(said)
                    break
                if not ans.startswith(run):
                    break
    return out


def spelling_unsaid(ann, answer, enumeration=None):
    """The answer with the apostrophe or accent it takes, when the annotation has
    no `spelling` and either its own prose writes the answer so or another
    annotation gave this answer that spelling; else None."""
    if ann.get("spelling") or not answer:
        return None
    ans = letters(answer)
    if len(ans) < 4:
        return None
    said = known_spellings().get(ans)
    if said:
        # Another clue's spelling (I'M PATIENT) is not this one's when the
        # printed enumeration counts a different number of words (IMPATIENT, 9).
        groups = re.fullmatch(r"[\d,\-\s]+", enumeration or "")
        if groups and len(re.findall(r"\d+", enumeration)) != len(said.split()):
            return None
        return said
    return next(iter(prose_spellings(ann, answer, enumeration)), None)
