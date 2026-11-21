"""FT_LEAD_ONE (fa.ft_lead_split): a Gale FT page's lead window (the column left of the grid) was split in two where
10-13 words of each reading cross, though the page prints one ACROSS column there, so the first line of every
two-line across clue was lost (its tail past the cut), its second line kept: 2006-10-14's "Fool pickpockets ment (8)"
for "Fool pickpockets with deferred payment", filed by the VLM's merge from the cut text. Every reader's across list then
read "cannot find a clue number at: 'ment (8) respectively? (6,6) ...'", all of them, and that verdict is what is due:
a Gale FT row with a written verdict whose every reader's across clues do not parse that way. (Some such rows
lost their lines to another cause and read the same text again: a reread rewrites the file with the same clues.)
check_rewrite does not refuse the longer clue over the cut one: it guards only a clue's words blanked."""
import re
from fix_reasons import Reason

TEXT = "a Gale FT page's lead column split through its middle, the first line of its two-line clues lost"
REREAD = "2026-11-20T23:25:00+00:00"
HEAD = "across clues do not parse: cannot find a clue number"


def cut(v):
    """Whether verdict `v` is a written one whose every reader's across list stopped at a clue number it could not find."""
    un = v.get("unparsed")
    return bool(v.get("wrote") and v.get("id") and isinstance(un, dict) and un
                and all(HEAD in str(x) for x in un.values()))


def due(row):
    import file_archive_org_puzzles as fa
    rel = row.get("edition") or ""
    if not re.match(r"GaleFT(?:19|20)\d\d UKEnglish/".replace(" ", ""), rel) \
            or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    return any(cut(v) for v in row.get("verdicts", ()))


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
