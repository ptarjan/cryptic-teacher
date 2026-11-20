#!/usr/bin/env python3
"""The daily burn review, as a script and a ledger instead of a room's prose.

    python3 tools/burn_review.py                 # review the last 24h, append the row, wake on a trip
    python3 tools/burn_review.py --dry-run       # print the row and the digest, write and send nothing
    python3 tools/burn_review.py --backfill      # load tools/data/burn_review_backfill.jsonl (rows missing only)

One JSON row a day goes to ~/.cache/cryptic-burn-review.jsonl (BURN_REVIEW_LEDGER
overrides). A rerun on the same date replaces that day's row. A row is written
even when the burn did no work or the review itself broke: `status` is "ok",
"no-work" or "error" (with `error`).

A row holds, for the 24h ending now:
  puzzles, clues, usd, usd_per_clue, usd_per_puzzle   from the annotate cost ledger
  width_hours      {width: hours}                     from .prereset.log status lines
  cap_hours        {cap: hours}  memory, pressure, overnight, quota, load, cpu,
                   waiting (nothing may start), idle, none (unconstrained)
  free_rate        puzzles/h the log reports at width 8+ (what width 1 loses against)
  top_causes       retry causes with sessions and post_fail_usd (the cost after a
                   first-check fail), no-lever causes dropped
  ranked           ONE list in "puzzles lost per day", biggest first:
                     width loss  = hours at width 1 x (free_rate - the done/h reported
                                   at width 1), split by the cap named at the time
                     retry loss  = post_fail_usd / usd_per_puzzle
                   causes in tools/data/annotate_no_lever.json are not in it
  resets_left      "N of M manual resets left" from the last status line

The log carries HH:MM only (Alberta time); dates are recovered by walking back from
the file's mtime and counting each time the clock wraps. A status line holds until the
next one, at most GAP_CAP_MIN (a heartbeat is every 5 minutes), so a dead burn shows
as unlogged hours rather than as width.

The wake (wake.sh -q, no inference unless the room is already running) fires only when
the new row, against the previous ok row, shows: a new top item in `ranked`, $/clue up
more than COST_RISE, width-1 hours over WIDTH1_MAX, or status error/no-work. The digest
names the single top ranked item. Quiet otherwise: the row is the record.
"""
import argparse
import collections
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import traceback
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

REPO = HERE.parent
ABT = ZoneInfo("America/Edmonton")
CHICAGO = ZoneInfo("America/Chicago")
LEDGER = pathlib.Path(os.environ.get("BURN_REVIEW_LEDGER") or pathlib.Path.home() / ".cache" / "cryptic-burn-review.jsonl")
BACKFILL = HERE / "data" / "burn_review_backfill.jsonl"
NO_LEVER = HERE / "data" / "annotate_no_lever.json"
ROOM = os.environ.get("BURN_REVIEW_ROOM", "web.cryptic-crosswords")
WINDOW_H = 24
GAP_CAP_MIN = 20          # a status line is trusted this long without a newer one
COST_RISE = 0.25          # $/clue up more than this vs the previous ok row
WIDTH1_MAX = 6.0          # hours at width 1 above this trips
FREE_WIDTH = 8            # "unconstrained": the done/h reported at this width or wider
KEEP_CAUSES = 5
KEEP_RANKED = 10

STATUS = re.compile(r"^(\d\d):(\d\d) ── (.*)$")
AT_ONCE = re.compile(r"^(\d+) at once(?: \(([^)]*)\))?")
DONE_H = re.compile(r"(\d+) done(?:/h| last hour)")
RESETS = re.compile(r"(\d+) of (\d+) manual resets left")
CAP_WORDS = (("overnight", "overnight"), ("pressure", "pressure"), ("memory", "memory"),
             ("usage pace", "quota"), ("load", "load"), ("cpu", "cpu"))


def cap_of(paren):
    """The binding cap a status line names, as one of CAP_WORDS' labels ('none' for no limit)."""
    for word, label in CAP_WORDS:
        if paren and word in paren:
            return label
    return "none"


def main_checkout():
    env = os.environ.get("CT_MAIN_CHECKOUT")
    if env:
        return pathlib.Path(env)
    try:
        common = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True, timeout=20).stdout.strip()
        return pathlib.Path(common).parent
    except (OSError, subprocess.SubprocessError):
        return REPO


# ---- the burn log --------------------------------------------------------

def dated_lines(text, mtime):
    """[(datetime ABT, text after the time)] for every line starting HH:MM, oldest first.
    The last line takes mtime's date (or the day before when its clock is later than the
    file's); going backward, a clock that jumps up by over 6h is the previous day."""
    stamped = []
    for line in text.splitlines():
        if len(line) > 6 and line[2] == ":" and line[:2].isdigit() and line[3:5].isdigit() and line[5] == " ":
            stamped.append((int(line[:2]), int(line[3:5]), line[6:]))
    out, day, nxt = [], mtime.astimezone(ABT).date(), None
    for h, m, rest in reversed(stamped):
        minutes = h * 60 + m
        if nxt is None:
            if minutes > mtime.astimezone(ABT).hour * 60 + mtime.astimezone(ABT).minute + 60:
                day -= datetime.timedelta(days=1)
        elif minutes > nxt + 360:
            day -= datetime.timedelta(days=1)
        nxt = minutes
        out.append((datetime.datetime.combine(day, datetime.time(h, m), tzinfo=ABT), rest))
    out.reverse()
    return out


def segments(lines, start, end):
    """Status-line segments clipped to [start, end): [{width, cap, hours, done_h}].
    width 0 covers waiting/idle/stopped, with cap waiting/quota/idle/stopped."""
    marks = []
    for ts, rest in lines:
        if not rest.startswith("── "):
            continue
        body = rest[3:]
        m = AT_ONCE.match(body)
        done = DONE_H.search(body)
        done_h = int(done.group(1)) if done else None
        if m:
            marks.append((ts, int(m.group(1)), cap_of(m.group(2)), done_h))
        elif body.startswith("waiting:"):
            marks.append((ts, 0, "quota" if "usage pace" in body else "waiting", None))
        elif body.startswith("idle:"):
            marks.append((ts, 0, "idle", None))
        elif body.startswith("stopping:"):
            marks.append((ts, 0, "stopped", None))
    cap = datetime.timedelta(minutes=GAP_CAP_MIN)
    segs = []
    for i, (ts, width, label, done_h) in enumerate(marks):
        stop = ts + cap
        if i + 1 < len(marks):
            stop = min(stop, marks[i + 1][0])
        a, b = max(ts, start), min(stop, end)
        if b > a:
            segs.append({"width": width, "cap": label, "hours": (b - a).total_seconds() / 3600, "done_h": done_h})
    return segs


def last_resets(lines, start):
    found = None
    for ts, rest in lines:
        if ts >= start:
            m = RESETS.search(rest)
            if m:
                found = int(m.group(1))
    return found


def summarise_log(segs):
    width_hours, cap_hours = collections.Counter(), collections.Counter()
    for s in segs:
        width_hours[str(s["width"])] += s["hours"]
        cap_hours[s["cap"]] += s["hours"]

    def mean_rate(pick):
        use = [s for s in segs if pick(s) and s["done_h"] is not None]
        h = sum(s["hours"] for s in use)
        return sum(s["done_h"] * s["hours"] for s in use) / h if h else None

    w1 = {}
    for s in segs:
        if s["width"] == 1:
            w1[s["cap"]] = w1.get(s["cap"], 0) + s["hours"]
    return {
        "width_hours": {k: round(v, 2) for k, v in sorted(width_hours.items(), key=lambda kv: int(kv[0]))},
        "cap_hours": {k: round(v, 2) for k, v in sorted(cap_hours.items())},
        "width1_cap_hours": {k: round(v, 2) for k, v in sorted(w1.items())},
        "free_rate": mean_rate(lambda s: s["width"] >= FREE_WIDTH),
        "width1_rate": mean_rate(lambda s: s["width"] == 1),
        "logged_hours": round(sum(s["hours"] for s in segs), 2),
    }


# ---- ranking -------------------------------------------------------------

def width_losses(log):
    """Items for the ranked list: width-1 hours x the rate gap, split by cap."""
    free, w1 = log["free_rate"], log["width1_rate"]
    if free is None or w1 is None:
        return []
    gap = max(free - w1, 0)
    return [{"kind": "width", "key": f"width1:{cap}", "label": f"width 1 held by {cap}: {h:.1f}h at {w1:.0f} done/h vs {free:.0f} unconstrained",
             "puzzles_lost": round(h * gap, 1)}
            for cap, h in log["width1_cap_hours"].items() if h * gap > 0]


def retry_losses(causes, usd_per_puzzle, no_lever):
    """(actionable items, dropped no-lever keys). Loss = post-fail $ / the day's $/puzzle."""
    items, dropped = [], []
    for c in causes:
        if c["key"] in no_lever:
            dropped.append(c["key"])
        elif usd_per_puzzle:
            items.append({"kind": "retry", "key": c["key"], "label": f"{c['label']}: {c['sessions']} sessions, ${c['post_fail_usd']:.2f} after the fail",
                          "puzzles_lost": round(c["post_fail_usd"] / usd_per_puzzle, 1)})
    return items, dropped


def rank(items):
    return sorted(items, key=lambda i: (-i["puzzles_lost"], i["key"]))


def read_no_lever():
    try:
        return json.loads(NO_LEVER.read_text())
    except (OSError, ValueError):
        return {}


# ---- the day's money and causes (from the existing ledgers) -----------------

def money(start, end):
    import annotate_ledger as led
    rows = [r for r in led.read_all() if start <= led.parse(r["end"]) <= end]
    p = sum(r.get("puzzles") or 0 for r in rows)
    c = sum(r.get("clues") or 0 for r in rows)
    usd = sum(r.get("cost") or 0 for r in rows)
    return {"puzzles": p, "clues": c, "usd": round(usd, 2),
            "usd_per_clue": round(usd / c, 5) if c else None,
            "usd_per_puzzle": round(usd / p, 4) if p else None}


def retry_causes(start, end):
    import annotate_audit as audit
    import annotate_ledger as led
    merged = {}
    for kind in ("annotate", led.HINT):
        res = audit.window_audit(start, end, kind)
        for c in res["causes"]:
            m = merged.setdefault(c["key"], {"key": c["key"], "label": c["label"], "sessions": 0, "post_fail_usd": 0.0})
            m["sessions"] += c["sessions"]
            m["post_fail_usd"] += c["cost_after_check"]
    out = [dict(c, post_fail_usd=round(c["post_fail_usd"], 2)) for c in merged.values() if c["post_fail_usd"] > 0]
    return sorted(out, key=lambda c: (-c["post_fail_usd"], c["key"]))


# ---- the row -------------------------------------------------------------

def build_row(now, log_path):
    start = now - datetime.timedelta(hours=WINDOW_H)
    row = {"date": now.astimezone(CHICAGO).date().isoformat(), "source": "script",
           "window_start": start.isoformat(), "window_end": now.isoformat(), "status": "ok"}
    stat = log_path.stat()
    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
    lines = dated_lines(log_path.read_text(errors="replace"), mtime)
    log = summarise_log(segments(lines, start, now))
    row.update(width_hours=log["width_hours"], cap_hours=log["cap_hours"], width1_hours=log["width_hours"].get("1", 0),
               free_rate=log["free_rate"], width1_rate=log["width1_rate"], logged_hours=log["logged_hours"],
               resets_left=last_resets(lines, start))
    row.update(money(start, now))
    causes = retry_causes(start, now)
    items, dropped = retry_losses(causes, row["usd_per_puzzle"], read_no_lever())
    row["top_causes"] = causes[:KEEP_CAUSES]
    row["no_lever_dropped"] = dropped
    row["ranked"] = rank(width_losses(log) + items)[:KEEP_RANKED]
    row["top_key"] = row["ranked"][0]["key"] if row["ranked"] else None
    if not row["puzzles"]:
        row["status"] = "no-work"
    return row


def error_row(now, exc):
    return {"date": now.astimezone(CHICAGO).date().isoformat(), "source": "script", "window_end": now.isoformat(),
            "status": "error", "error": "".join(traceback.format_exception_only(type(exc), exc)).strip()[:500],
            "puzzles": None, "clues": None, "usd": None, "usd_per_clue": None, "ranked": [], "top_key": None}


# ---- ledger and trips ----------------------------------------------------

def read_rows(path=None):
    rows = []
    try:
        for line in (path or LEDGER).read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except OSError:
        pass
    return sorted(rows, key=lambda r: r["date"])


def write_rows(rows, path=None):
    path = path or LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in sorted(rows, key=lambda r: r["date"])))
    os.replace(tmp, path)


def trips(row, prev):
    """Reasons to wake the room, from the new row and the previous ok row (None if none)."""
    out = []
    if row["status"] != "ok":
        out.append(f"status {row['status']}" + (f" ({row['error']})" if row.get("error") else ""))
        return out
    if row.get("top_key") and prev and prev.get("top_key") and row["top_key"] != prev["top_key"]:
        out.append("new top item")
    if prev and prev.get("usd_per_clue") and row.get("usd_per_clue") and row["usd_per_clue"] > prev["usd_per_clue"] * (1 + COST_RISE):
        out.append(f"$/clue {prev['usd_per_clue']:.4f} -> {row['usd_per_clue']:.4f} (+{row['usd_per_clue'] / prev['usd_per_clue'] - 1:.0%})")
    if (row.get("width1_hours") or 0) > WIDTH1_MAX:
        out.append(f"{row['width1_hours']:.1f}h at width 1 (limit {WIDTH1_MAX:g}h)")
    return out


def digest(row, reasons):
    top = row["ranked"][0] if row.get("ranked") else None
    head = f"Burn review {row['date']}: {'; '.join(reasons)}."
    if row["status"] != "ok":
        tail = " The burn log and cost ledger gave no usable day; check .prereset.log and the plugin's log."
    else:
        tail = (f" {row['puzzles']} puzzles, {row['clues']} clues, ${row['usd']:.2f} (${row['usd_per_clue']:.4f}/clue), "
                f"{row['width1_hours']:.1f}h at width 1.")
        tail += (f" Top of the ranked list: {top['label']} = {top['puzzles_lost']:g} puzzles lost/day."
                 if top else " Nothing ranked.")
    return head + tail + f" Full row in {LEDGER}."


def wake(text):
    wake_sh = os.environ.get("WAKE_SH") or __import__("local_config").path("household_dir") + "/tools/wake.sh"
    return subprocess.run([wake_sh, "-q", "-c", ROOM, text], check=False, timeout=120).returncode


def backfill(dry_run):
    have = {r["date"] for r in read_rows()}
    new = [json.loads(line) for line in BACKFILL.read_text().splitlines() if line.strip()]
    new = [r for r in new if r["date"] not in have]
    print(f"burn review: backfilling {len(new)} rows")
    if new and not dry_run:
        write_rows(read_rows() + new)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--log", help="burn log (default: .prereset.log in the main checkout)")
    args = ap.parse_args(argv)
    if args.backfill:
        return backfill(args.dry_run)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        row = build_row(now, pathlib.Path(args.log) if args.log else main_checkout() / ".prereset.log")
    except Exception as exc:  # a broken review still writes its row and tells the room
        traceback.print_exc()
        row = error_row(now, exc)
    rows = [r for r in read_rows() if r["date"] != row["date"]]
    prev = next((r for r in reversed(rows) if r["status"] == "ok"), None)
    reasons = trips(row, prev)
    print(json.dumps(row))
    text = digest(row, reasons) if reasons else None
    print(f"burn review: {'WAKE: ' + text if text else 'quiet'}")
    if args.dry_run:
        return 0
    write_rows(rows + [row])
    if text:
        rc = wake(text)
        if rc:
            print(f"burn review: wake.sh exited {rc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
