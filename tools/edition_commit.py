"""What an archive.org or Gale edition's read leaves on the Mac: its files and its ledger row.

    (no command line: tools/edition_queue.py runs main() as a read unit's process when it prepared the read)

A read the edition queue prepared (file_archive_org_puzzles.brief: the
desktop's request and what the row needs, made from the queue's own ledger,
scans and corpus, already loaded) runs here as its unit, without the reader's
code: it sends the request to the desktop (tools/ocr_remote.py), waits,
answering the desktop's VLM asks, writes what the desktop decided
(scan_queue.file_puzzle) and appends the edition's ledger row. Anything
else, the whole unit runs as before (`edition_queue.py unit`, exec'd in this
process): the desktop unavailable (unset, or gone LONG_GONE: a desktop lost
for less is tried again, then the unit ends deferred) or failing the read, a
title it left to the Mac to decide (decided here from the desktop's
readings, CT_EDITION_ANSWER), the edition read by another unit since it was
prepared, or a run holding the ledger.

file_archive_org_puzzles imports the parts both paths share from here.
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

import dir_cache
import media_manifest

#: The filer whose files these are: a held file it wrote names it (source.acquiredBy).
TOOL = "tools/file_archive_org_puzzles.py"
#: A unit's exit status: what read_unit/scan_unit/a fetcher's unit returned;
#: "deferred", its desktop reads met a busy desktop (ocr_remote.DesktopBusy);
#: "lost", the desktop stopped answering it (ocr_remote.DesktopLost); "vlm",
#: its read needed the VLM and it was down or went down (vlm_reader.Down):
#: nothing written, the read waits for the VLM.
EXITS = {"read": 0, "scanned": 0, "current": 0, "fetched": 0, "busy": 3, "held": 4, "outage": 5,
         "throttled": 6, "disk": 7, "deferred": 8, "lost": 9, "vlm": 10,
         # The media share did not answer (downloads.media_down): deferred, the queue waits for it.
         "media": 11}
#: The tools modules main() runs, loaded as the unit starts (under the
#: queue's code lock, edition_queue.snapshot): none of them is loaded later
#: from a tree that moved meanwhile (test_edition_commit.py checks a commit
#: loads nothing past these).
MODULES = ("annotation", "blog_store", "clue_repair", "desktop_busy", "dir_cache", "fetch_puzzle", "find_answer_leaks", "groups", "hidden_messages",
           "ocr_clues", "ocr_remote", "puzzle_integrity", "puzzle_paths", "repair_fetched", "reprints", "scan_queue",
           "shape_queue", "trove_solution_ocr", "validate_annotations", "vlm_reader", "wordplay")


def filer_path(where, series, puzzles, root=None):
    """The file a decide() write names: ("held", number), the corpus file of
    `series`-`number` (puzzle_path), or ("out", id), `puzzles`' copy of it
    (destination). `root` (the desktop's copy of those files) puts both
    under it."""
    from fetch_puzzle import puzzle_path
    kind, key = where
    if root is not None:
        return Path(root) / kind / f"{key}.json"
    return puzzle_path(series, key) if kind == "held" else Path(puzzles) / f"{key}.json"


def writer(source, series, puzzles):
    """commit(where, puzzle, verdict) for decide(): writes `puzzle` where
    `where` names (filer_path), True when written; where None is the raw
    reading's copy under `source`."""
    import scan_queue
    from fetch_puzzle import write_puzzle_file

    def commit(where, puzzle, verdict):
        if where is None:
            Path(source).mkdir(parents=True, exist_ok=True)
            raw = Path(source) / f"{puzzle['id']}.json"
            part = raw.with_name(f"{raw.name}.{os.getpid()}.part")
            part.write_text(json.dumps(puzzle, indent=1))
            part.replace(raw)
            # cross_validate.ArchiveOrg.ids reads this, not a listing of the media disk.
            media_manifest.record_file("archiveorg-source", Path(source) / f"{puzzle['id']}.json")
            return True
        return scan_queue.file_puzzle(write_puzzle_file, TOOL, filer_path(where, series, puzzles), puzzle, verdict)
    return commit


def commit_decided(decided, commit):
    """The verdicts of the titles the desktop decided ([(verdict, [(where,
    puzzle)])]), each write made through `commit` (None: none made)."""
    verdicts = []
    for verdict, writes in decided:
        for where, puzzle in writes:
            if commit is not None:
                commit(where and tuple(where), puzzle, verdict)
        verdicts.append(verdict)
    return verdicts


def strayed(puzzle, spaces=True):
    """The lights of a puzzle whose clue ocr_clues.stray flags (a doubled
    word, a stray letter), and with `spaces` those whose clue holds a run
    of spaces (spaced) or breaks a punctuation rule (punctuation.faulted):
    any makes the edition due (inputs)."""
    import ocr_clues
    import punctuation
    from groups import entry_id
    return {entry_id(e) for e in puzzle.get("entries") or ()
            if ocr_clues.stray((e.get("clue") or {}).get("text") or "")} | (
                spaced(puzzle) | punctuation.faulted(puzzle) if spaces else set())


def spaced(puzzle):
    """The lights of a puzzle whose clue text holds a run of spaces ("Toe
    so"), which enumeration.collapse_spaces cuts to one."""
    from groups import entry_id
    return {entry_id(e) for e in puzzle.get("entries") or ()
            if "  " in ((e.get("clue") if isinstance(e.get("clue"), dict) else None) or {}).get("text", "")}


def held_paths(series, numbers):
    """The corpus files this tool filed for puzzles `numbers` of `series`."""
    import puzzle_paths
    import series as series_meta
    out = []
    for n in numbers:
        path = puzzle_paths.find_listed(series_meta.puzzle_id(series, n))
        if path is None:
            continue
        try:
            held = dir_cache.derived(path, acquired_by) == TOOL
        except FileNotFoundError:
            continue  # listed, then gone (the tree moved under us): not held
        if held:
            out.append(path)
    return out


def acquired_by(puzzle):
    return (puzzle.get("source") or {}).get("acquiredBy")


def any_strayed(puzzle):
    return bool(strayed(puzzle))


def inputs(files_hash, reprints, series, numbers):
    """An edition's inputs (file_archive_org_puzzles.inputs_of): its files'
    hash, its reprints' (reprint_key), and "+strayed" when a held file of
    its `numbers` holds a stray clue."""
    extra = reprints
    for path in held_paths(series, numbers):
        try:
            strayed_here = dir_cache.derived(path, any_strayed)
        except FileNotFoundError:
            continue
        if strayed_here:
            extra = (extra or "") + "+strayed"
            break
    return f"{files_hash}+{extra}" if extra else files_hash


def row(rel, inputs_key, found, files_hash, scan_key, sol_seen, verdicts, vlm=None, solution_key=None,
        sol_only=None):
    """An edition's ledger row after a read; `vlm` the VLM version it was
    read with, `solution_key` its solution reader's code (solution_key()),
    `sol_only` the row's solutions_only read ("solOnly") before it, kept: a
    host's own reread dropped the headings only that read found (fa.scan_of
    takes them while it is current). 10-26: 41 links over 240 Gale Times
    hosts lost so, 7 of them to unanswered puzzles."""
    import scan_queue
    out = {"edition": rel, "inputs": inputs_key, "scan": found, "filesHash": files_hash, "scanKey": scan_key,
           "solutionKey": solution_key, "solutionsSeen": sol_seen, "verdicts": verdicts,
           "readAt": scan_queue.now()}
    if sol_only:
        out["solOnly"] = sol_only
    if vlm:
        out["vlm"] = vlm
    else:
        import vlm_reader
        if vlm_reader.unconfigured():
            out["vlmUnset"] = True  # read with no VLM address configured: due again (fa.UNCONFIGURED_READ)
    return out


def read_line(rel, verdicts):
    """The log line of an edition's read, ending with its VLM asks (vlm_reader.vlm_note)."""
    import vlm_reader
    return f"read {rel}: " + ("; ".join(
        f"{v['number']} " + ("wrote " + v["id"] + (f" (incomplete: {v['unfiled']} blank, unfiled)" if v.get("unfiled") is not None else "")
                             if v.get("wrote") else
                             v.get("skip") or v.get("refused") or v.get("refusedWrite")
                             or ("write failed: " + v["writeFailed"] if v.get("writeFailed") else None)
                             or v.get("id") or "read")[:60]
        for v in verdicts) or "nothing filed") + f" ({vlm_reader.vlm_note()})"


def progress(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)


# ------------------------------------------------------------ the unit


def save_brief(path, head, tar, ctx):
    """Write a prepared read to `path`: a JSON line {head, ctx}, then the tar."""
    tmp = Path(f"{path}.part")
    tmp.write_bytes(json.dumps({"head": head, "ctx": ctx}).encode() + b"\n" + tar)
    tmp.replace(path)


def load_brief(path):
    """(head, tar, ctx) of a prepared read, its file removed."""
    data = Path(path).read_bytes()
    Path(path).unlink()
    line, _, tar = data.partition(b"\n")
    got = json.loads(line)
    return got["head"], tar, got["ctx"]


def load():
    """Load MODULES (the unit's start, under the code lock)."""
    import importlib
    for name in MODULES:
        importlib.import_module(name)


def read_since(ledger, size, rel):
    """Whether `ledger` holds a row for `rel` past byte `size` (or shrank:
    compacted since)."""
    with open(ledger, "rb") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() < size:
            return True
        f.seek(size)
        tail = f.read()
    for line in tail.split(b"\n"):
        if line.strip():
            try:
                if json.loads(line).get("edition") == rel:
                    return True
            except ValueError:
                return True  # a line still being appended: its edition is unknown
    return False


def whole_unit(spec, why, env=None):
    """Become the whole unit (edition_queue.py unit, as started), `why` logged."""
    progress(f"{spec['unit']['rel']}: {why}; the whole unit runs")
    sys.stdout.flush()
    rest = {k: v for k, v in spec.items() if k != "brief"}
    os.execve(sys.executable, [sys.executable, *sys.argv],
              {**os.environ, **(env or {}), "CT_EDITION_UNIT": json.dumps(rest)})


def main(spec):
    """Run the prepared read `spec["brief"]` names; its exit status (EXITS)."""
    import io
    import tarfile

    import ocr_remote
    import scan_queue
    import vlm_reader
    head, tar, ctx = load_brief(spec["brief"])
    rel, ledger = ctx["rel"], Path(ctx["ledger"])
    if scan_queue.held(ledger, scan_queue.UNIT_HOLD_WAIT):
        return EXITS["held"]
    with scan_queue.source_lock(ledger, rel) as mine:
        if not mine:
            return EXITS["busy"]
        if read_since(ledger, ctx["ledgerSize"], rel):
            whole_unit(spec, "its ledger row moved since it was prepared")
        # The VLM down: vlm_reader.Down, the unit ends deferred (EXITS["vlm"]) before the desktop reads a page.
        vlm_up = vlm_reader.wanted()
        head = {**head, "vlm": vlm_up}
        # A desktop lost mid-read is tried again (ocr_remote.there), then the
        # unit ends deferred (DesktopLost) unless it has been gone LONG_GONE.
        got = ocr_remote.there(lambda s, tar=tar: s.edition(head, tar))
        if got is None:
            whole_unit(spec, "the desktop is not reading", {"OCR_REMOTE": ""})
        got, back = got
        del tar
        if "error" in got:
            whole_unit(spec, f"the read failed there ({got['error']})")
        if vlm_up and not got["vlm"]:
            vlm_reader.went_without(f"{rel}'s read")  # lost mid-edition: Down, nothing committed
        with tarfile.open(fileobj=io.BytesIO(back)) as t:
            t.extractall(ctx["crops"], filter="data")
        if got.get("decided") is None:
            answer = Path(f"{spec['brief']}.answer")
            answer.write_text(json.dumps({"edition": rel, "results": got["results"], "vlm": got["vlm"]}))
            whole_unit(spec, "a title there looked up a file it was not sent, so its filing is decided here",
                       {"CT_EDITION_ANSWER": str(answer)})
        found, series = ctx["found"], ctx["series"]
        # The writes and the ledger row are a few local file writes: a TERM (the queue stopping its
        # units for a game, or a stop) waits until they are all made, so none is left half done
        # (a puzzle filed with no ledger row). It then takes effect, the read being done.
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            verdicts = commit_decided(got["decided"], writer(ctx["source"], series, ctx["puzzles"]))
            # Keyed by the inputs after this read's writes: a stray clue it
            # mended no longer makes the edition due.
            key = inputs(ctx["filesHash"], ctx["reprints"], series, [p["number"] for p in found["puzzles"]])
            seen_by = ctx["vlmVersion"] if vlm_up and got["vlm"] else None
            scan_queue.append(ledger, [row(rel, key, found, ctx["filesHash"], ctx["scanKey"], ctx["solutionsSeen"],
                                           verdicts, seen_by, ctx.get("solutionKey"), ctx.get("solOnly"))])
        finally:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
        progress(read_line(rel, verdicts))
    return EXITS["read"]
