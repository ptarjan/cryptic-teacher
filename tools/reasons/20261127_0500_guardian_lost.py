"""GUARDIAN_LOST (fa.lost_writes): archive.org Guardian editions read 11-17/11-18 whose verdict says "wrote" (a cryptic-N
id, complete or not) while no puzzle file holds that id: ~226 rows (24 labelled "other: complete" in census r315, 1997-98),
all Guardian, none of any other paper. REREAD_LOST (10-25) had already passed, so LOST_WRITE stood no more, and a non-Times
row keeps the blanket reason anyway. What is due: any archive.org row with a lost write (LOST_WRITE's own test), read before REREAD; no paper gate, the rule
is the measured loss, which today only Guardian rows show."""
from fix_reasons import Reason

TEXT = "an archive.org page read as written whose puzzle file is gone, read again since"
REREAD = "2026-11-19T23:59:00+00:00"


def due(row):
    import file_archive_org_puzzles as fa
    if "inputs" not in row or not fa.scan_queue.read_before(row, fa.scan_queue.when(REREAD)):
        return False
    return bool(fa.lost_writes(row))


REASON = Reason(TEXT, rank=2, fix_landed=True, kept=True, due=due)
