"""vlm_asks.log read once and then by its appended bytes, for the queue's plan.

file_archive_org_puzzles.ask_replies() and asked_lights() each parse the whole log (~20 MB, and it grows
every few seconds while the drainer works) whenever its stat has moved: a plan pass read it ~45 times
(~900 MB, a pass measured under /proc/self/io), and every plan runs in a fresh forked child whose memos die
with it. install() swaps both for the same answers folded by dir_cache.appended, which carries the fold
between calls and, for the default log, between processes (the ledger_folds dir, like the ledger folds), so
a call reads only the whole lines appended since. The readers' own code (and so every scan key) is
untouched; they are only rebound in the queue process."""

import os
import re

import dir_cache

_REPLIES = re.compile(r"\S+ vlm ask (\S+) \S+ (\w+) why=solution:(\S+)")
_ASKED = re.compile(r"\S+ vlm ask (\S+) \S+ \w+ why=(solution|candidates|wide):(\S+)")
_DEFAULT = "~/.cache/corpus_queue/vlm_asks.log"


def _fold_replies(acc, raw):
    m = _REPLIES.match(raw.decode("utf-8", "replace"))
    if m:
        ed = m.group(1)
        if ed.split("/", 1)[0] in ("gale", "archive"):
            ed = ed.split("/", 1)[1]
        acc.setdefault(ed, {}).setdefault(m.group(3), []).append(m.group(2))


def _fold_asked(acc, raw):
    m = _ASKED.match(raw.decode("utf-8", "replace"))
    if m:
        acc.setdefault(m.group(1).split("/", 1)[-1], {}).setdefault(m.group(3), set()).add(m.group(2))


def _keep(fa, fold):
    """dir_cache.appended's `keep` for the default log only (a test's CT_VLM_ASK_LOG stays in memory)."""
    if os.environ.get("CT_VLM_ASK_LOG") or not getattr(fa, "HELD_SERIES_CACHE", None):
        return None
    import inspect
    return fa.LEDGER_FOLDS, inspect.getsource(fold) + _REPLIES.pattern + _ASKED.pattern


def _log():
    return os.path.expanduser(os.environ.get("CT_VLM_ASK_LOG") or _DEFAULT)


def install(fa):
    """Rebind fa.ask_replies and fa.asked_lights to the appended-fold versions."""
    def ask_replies():
        return dir_cache.appended(_log(), dict, _fold_replies, keep=_keep(fa, _fold_replies))

    def asked_lights():
        return dir_cache.appended(_log(), dict, _fold_asked, keep=_keep(fa, _fold_asked))

    ask_replies.__doc__ = "fa.ask_replies' answer, folded from the log's appended lines (ask_log_fold)."
    asked_lights.__doc__ = "fa.asked_lights' answer, folded from the log's appended lines (ask_log_fold)."
    fa.ask_replies = ask_replies
    fa.asked_lights = asked_lights
