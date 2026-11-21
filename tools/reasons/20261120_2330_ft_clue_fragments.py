"""FT_CUT_RESTORED (fa.ft_cut_restored): a Gale FT clue filed cut by FT_LEAD_ONE's old lead window ("Fool pickpockets
ment (8)", "Affectionate feeling rection", "Intend one entering receive care") stayed cut through the FT_LEAD_ONE
reread: the reread's whole clue went through corrected_clues -> corrects(), which takes one gained dictionary word at
most, and the cut clue lacked two or three. 2006-10-14 (ftcryptic-12280) was read again at 19:51 with clean reader
and VLM text ("1 Fool pickpockets with deferred pay-/ment (8)") and its file kept all 28 cut clues. ft_cut_restored takes
the whole clue for a held Financial Times clue whose words all stand in it in order, a fragment ("ment") as the end
of one, the gain a middle run of dictionary words. Held files of such shape (a fragment token: ~700 of 3,630 Gale FT
files hold a lowercase non-word, most of them lexicon gaps) are not told apart by the ledger row, so due is: a Gale FT
row with a written verdict that parsed the cut text (the old across 'cannot find a clue number' stop) or kept a
held clue by `mended`, read before the cutoff."""
import re
from fix_reasons import Reason

TEXT = "a Gale FT clue cut in its middle (first line's tail lost) kept over the reread's whole clue"
REREAD = "2026-11-21T05:17:00+00:00"
HEAD = "across clues do not parse: cannot find a clue number"


def shaped(v):
    """Whether verdict `v` is a written one of the cut-clue shape: every reader's across list stopped at a
    clue number it could not find, or the reread mended held clues by the corrected_clues route."""
    un = v.get("unparsed")
    if not (v.get("wrote") and v.get("id")):
        return False
    return bool(v.get("mended")) or bool(isinstance(un, dict) and un and any(HEAD in str(x) for x in un.values()))


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleFT(?:19|20)\d\d" r"UKEnglish/", rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    return any(shaped(v) for v in row.get("verdicts", ()))


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
