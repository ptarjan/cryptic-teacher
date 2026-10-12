"""A unit's one signal back to tools/unit_queue.py: it stopped with backlog
left. Its own module, imported by the units that drain a backlog, so a unit
loads none of the queue runner (mem_gate and the rest) to say so."""
import os
from pathlib import Path


def backlog_left():
    """Say, from inside a unit, that it stopped with backlog left: it is due
    again at the next tick rather than after its `every`. A no-op outside a
    unit (run by hand)."""
    path = os.environ.get("UNIT_MORE")
    if path:
        Path(path).touch()
