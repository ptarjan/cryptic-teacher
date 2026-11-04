#!/usr/bin/env python3
# Does tools/blog_prefetch.py find a puzzle's post by title, cache it for blog_post, remember a miss,
# and never raise? Network mocked.
#
#     python3 tests/test_blog_prefetch.py
import os
import sys
import tempfile
import urllib.error
from datetime import date

os.environ["CT_BLOG_PREFETCH"] = tempfile.mkdtemp()
import _path  # puts tools/ on sys.path
import blog_prefetch as bp

fails = 0


def check(what, want, got):
    global fails
    print(("ok   " if want == got else "FAIL ") + what + ("" if want == got else f": expected {want!r}, got {got!r}"))
    fails += want != got


def post(pid, title, day="2026-10-01"):
    return {"id": pid, "date": day + "T06:00:00", "link": f"https://bigdave44.com/{pid}/", "title": {"rendered": title}}


calls = []


def fake(url):
    calls.append(url)
    if "/comments?" in url:
        return [{"id": 1, "content": {"rendered": "<p>Nice</p>"}, "author_name": "x"}]
    return [post(1, "Toughie 3148", "2026-10-01"), post(2, "DT 31018", "2026-10-01"),
            post(3, "DT 31018 (old)", "2019-01-01"), post(4, "DT 310180")]


pz = {"id": "telegraph-31018", "number": 31018, "date": "2026-10-01"}
check("title picks series and number", True, bp.titled(post(2, "DT 31,018"), "telegraph", "31018"))
check("toughie is not a telegraph cryptic", False, bp.titled(post(1, "Toughie 31018"), "telegraph", "31018"))
check("prefix number is not a match", False, bp.titled(post(4, "DT 310180"), "telegraph", "31018"))
check("fetched", "fetched", bp.prefetch(pz, fake, date(2026, 11, 3)))
host, url, p, comments = bp.load("telegraph-31018")
check("stored post url", "https://bigdave44.com/2/", url)
check("stored comments", 1, len(comments))
check("one search, one comments request", 2, len(calls))
check("second call has it", "have", bp.prefetch(pz, fake, date(2026, 11, 3)))
check("no more requests", 2, len(calls))


def boom(url):
    calls.append(url)
    raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)


other = {"id": "toughie-2875", "number": 2875, "date": "2026-10-02"}
n = len(calls)
check("403 is a miss, not a raise", "miss", bp.prefetch(other, boom, date(2026, 11, 3)))
check("retry the same day skips the network", "recent miss", bp.prefetch(other, boom, date(2026, 11, 4)))
check("no request on retry", n + 1, len(calls))
check("asks again after the miss ages", "miss", bp.prefetch(other, boom, date(2026, 11, 20)))
check("series with no blog", None, bp.host_of({"id": "metro-1", "number": 1}))
sys.exit(1 if fails else 0)
