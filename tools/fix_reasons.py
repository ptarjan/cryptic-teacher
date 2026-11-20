"""The registry of reread "fix reasons": add one by creating ONE new file, touching no shared list.

A fix reason (a reader fix landed, so some pages are read again for it) used to be spread over a
dozen shared lines: file_archive_org_puzzles.RANKS, BLANKET_PASSES / SOLUTION_FIXES, the fix_reason()
chain, and edition_queue's UNFILED_FIRST, NEWEST_LANDED, FIX_LANDED and evidence_reason. Two fix
branches always conflicted there. Those lists now end `+ fix_reasons.of("...")` (RANKS
`| fix_reasons.ranks()`), so a registered reason is appended after the existing ones, in file order.

How to add a new fix reason: create tools/reasons/<YYYYMMDD_HHMM>_<name>.py (the name sorts the
registry: a later name is a newer fix, so it lands last in UNFILED_FIRST, which is the newest-first
end) holding:

    from fix_reasons import Reason

    def due(row):                      # True when ledger `row` is due this reread
        import file_archive_org_puzzles as fa     # import inside: fa loads this registry first
        return fa.some_due(row)

    REASON = Reason("my fix text", rank=2, unfiled_first=True, solution_fix=True, due=due)

`rank` is its RANKS entry. The flags put its text on a list: unfiled_first (edition_queue.UNFILED_FIRST,
which evidence_reason keeps too), newest_landed (NEWEST_LANDED), fix_landed (FIX_LANDED), blanket
(BLANKET_PASSES), solution_fix (SOLUTION_FIXES, an answers-only reread), kept (evidence_reason keeps
it though it is on no other list; implied by unfiled_first). `due` is asked by fix_reason() first of
all, in file order; leave it None for a reason another function names. tests/test_fix_reasons.py
checks the lists against a frozen copy of the pre-registry values, and each registered reason's list
membership. Keys: a registered module is not reached by a scan, so no scan or solution key moves
(tools/prepush_check.py checks).
"""
import functools
import importlib.util
from pathlib import Path
from typing import Callable, NamedTuple, Optional

DIR = Path(__file__).resolve().parent / "reasons"
FLAGS = ("unfiled_first", "newest_landed", "fix_landed", "blanket", "solution_fix", "kept")


class Reason(NamedTuple):
    text: str
    rank: int
    unfiled_first: bool = False
    newest_landed: bool = False
    fix_landed: bool = False
    blanket: bool = False
    solution_fix: bool = False
    kept: bool = False
    due: Optional[Callable] = None


@functools.lru_cache(maxsize=None)
def registered():
    """{file stem: Reason} of tools/reasons/*.py in name order."""
    out = {}
    for path in sorted(DIR.glob("*.py")):
        spec = importlib.util.spec_from_file_location(f"reasons_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out[path.stem] = mod.REASON
    return out


def of(flag):
    """The texts of the registered reasons with `flag` set (one of FLAGS), in order."""
    if flag not in FLAGS:
        raise KeyError(flag)
    return tuple(r.text for r in registered().values() if getattr(r, flag) or (flag == "kept" and r.unfiled_first))


def ranks():
    """{text: rank} of every registered reason."""
    return {r.text: r.rank for r in registered().values()}


def due(row):
    """The text of the first registered reason whose `due(row)` holds, or None."""
    for r in registered().values():
        if r.due is not None and r.due(row):
            return r.text
    return None
