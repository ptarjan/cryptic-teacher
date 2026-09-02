#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["google-analytics-data"]
# ///
"""What Google Analytics saw, next to what KV saw.

tools/usage_report.py counts the copy we store ourselves; this reads the copy
Google stores. They measure the same milestones (app.js hands every name in
sync/events.js to both), so the gap between them is the interesting number: GA
loses every visitor running a blocker, KV loses nobody, and neither can tell you
that on its own.

Realtime is asked first and printed first, because the batch tables lag 24-48h —
a tag wired up this morning shows zero all day in the report and a row within
the minute in realtime, and only one of those means it is broken.

    tools/ga_report.py                 # last 28 days, plus realtime
    tools/ga_report.py --days 7
    tools/ga_report.py --realtime      # just the last 30 minutes

Credentials, neither of them in this repo:
  ~/.config/ga4/cryptic-teacher.json   service-account key, chmod 600
  ~/.config/ga4/property             the 9-digit property id (or $GA4_PROPERTY_ID)

Reads only. Nothing here writes to GA, to the site or to KV.
"""
import argparse
import os
import sys
from pathlib import Path

PREFIX = "/cryptic-teacher"
CONF = Path.home() / ".config" / "ga4"
KEY = CONF / "cryptic-teacher.json"
PROP = CONF / "property"


def credentials():
    """The key file and the property id, or a message that says how to get them.

    Both halves are set up by hand once, months before anyone runs this again,
    so the failure has to name the missing thing and where it comes from — "file
    not found" would send you back to the transcript.
    """
    if not KEY.exists():
        raise SystemExit(
            f"no service-account key at {KEY}\n"
            "  Google Cloud console -> IAM & Admin -> Service Accounts -> Keys -> Add key\n"
            f"  then: mkdir -p {CONF} && mv ~/Downloads/<that>.json {KEY} && chmod 600 {KEY}\n"
            "  and grant its email Viewer under GA4 Admin -> Property access management.")
    if KEY.stat().st_mode & 0o077:
        print(f"warning: {KEY} is readable by other accounts (chmod 600 it)", file=sys.stderr)

    prop = os.environ.get("GA4_PROPERTY_ID") or (
        PROP.read_text(encoding="utf-8").strip() if PROP.exists() else "")
    if not prop.isdigit():
        raise SystemExit(
            f"no property id in $GA4_PROPERTY_ID or {PROP}\n"
            "  GA4 Admin -> Property Settings -> Property ID: nine digits, NOT the\n"
            f"  G-XXXXXXX measurement id. Then: echo <digits> > {PROP}")
    return str(KEY), prop


def client(key):
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    return BetaAnalyticsDataClient.from_service_account_file(key)


def rows(resp):
    """(dimension values, first metric) per row, as plain strings and ints."""
    return [(tuple(d.value for d in r.dimension_values), int(r.metric_values[0].value))
            for r in resp.rows]


def table(title, pairs, note=""):
    if not pairs:
        print(f"\n{title}: nothing" + (f" — {note}" if note else ""))
        return
    top = max(n for _, n in pairs)
    print(f"\n{title}")
    for label, n in pairs:
        print(f"  {label:<24} {n:>6}  {'#' * (round(24 * n / top) if top else 0)}")


def page_label(path, width=24):
    """A page path shortened from the LEFT, so the tail survives.

    Every path here starts /cryptic-teacher/ and the part that says which page it
    is sits at the end, so cutting the tail to fit printed fifteen rows all
    reading "/cryptic-teacher/puzzles". Drop the shared prefix, then keep the end.
    """
    if path.startswith(PREFIX):
        path = path[len(PREFIX):] or "/"
    return path if len(path) <= width else "…" + path[-(width - 1):]


def realtime(cl, prop):
    """The last 30 minutes. This is the one that answers "is it working".

    Realtime keeps only a handful of dimensions and no date, so it can say what
    is arriving and never what arrived on Tuesday.

    Test the site with a headed browser or this stays empty however hard you
    drive it: GA4 drops headless traffic as bots without saying so, which reads
    exactly like a broken tag. tools/e2e_analytics.py is headless on purpose and
    stops its evidence at the gtag handoff for that reason.
    """
    from google.analytics.data_v1beta.types import (Dimension, Metric,
                                                    RunRealtimeReportRequest)
    resp = cl.run_realtime_report(RunRealtimeReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")]))
    table("last 30 minutes", sorted(((d[0], n) for d, n in rows(resp)),
                                    key=lambda kv: -kv[1]),
          "nobody is on the site right now, which is not the same as a broken tag")


def batch(cl, prop, days):
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                    RunReportRequest)
    rng = [DateRange(start_date=f"{days}daysAgo", end_date="today")]

    totals = cl.run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=rng,
        metrics=[Metric(name="activeUsers"), Metric(name="sessions"),
                 Metric(name="screenPageViews")]))
    if totals.rows:
        m = [v.value for v in totals.rows[0].metric_values]
        print(f"\nlast {days} days: {m[0]} users, {m[1]} sessions, {m[2]} page views")

    ev = cl.run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=rng,
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")]))
    table("events", sorted(((d[0], n) for d, n in rows(ev)), key=lambda kv: -kv[1]),
          "GA reports lag 24-48h, so a tag added today is expected to be empty here")

    pages = cl.run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=rng,
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="screenPageViews")],
        limit=15))
    table("top pages", [(page_label(d[0]), n) for d, n in rows(pages)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--realtime", action="store_true", help="skip the lagging tables")
    args = ap.parse_args()

    key, prop = credentials()
    cl = client(key)
    print(f"GA4 property {prop}")
    realtime(cl, prop)
    if not args.realtime:
        batch(cl, prop, args.days)
    print("\nThe same milestones, counted our own way: python3 tools/usage_report.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
