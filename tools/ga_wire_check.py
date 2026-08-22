#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Do the GA hits actually leave the browser, and under which names?

tools/e2e_analytics.py stops at the dataLayer queue on purpose: whether gtag.js
loads is a fact about the visitor, not about the site, and a test that fails
because Google was slow is a test nobody trusts. This is the other half, run by
hand — it watches the wire and prints the event name out of each collect hit, so
"wired up" and "arriving" are two answers rather than one assumption.

    tools/ga_wire_check.py
"""
import re
import sys
from urllib.parse import parse_qs, urlparse

SITE = "https://paultarjan.com/cryptic-teacher/?p=quiptic-1394"


def main():
    from playwright.sync_api import sync_playwright
    hits = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("request", lambda r: hits.append((r.url, r.post_data))
                if re.search(r"google-analytics\.com|analytics\.google\.com", r.url) else None)
        page.goto(SITE, wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.locator("#clues-across li").first.click()
        page.wait_for_timeout(500)
        btn = page.locator("#hint-next button").first
        if btn.is_visible() and btn.is_enabled():
            btn.click()
        page.locator("#chk-letter").click()
        # gtag.js sends page_view at once and BATCHES what follows, flushing on a
        # timer or when the page goes away. Closing the tab straight after a
        # click therefore shows an empty wire and proves nothing, so the page is
        # navigated away from and given time to flush.
        page.wait_for_timeout(6000)
        page.goto("about:blank")
        page.wait_for_timeout(3000)
        browser.close()

    if not hits:
        raise SystemExit("no request reached Google at all — the tag is not loading")
    # A single event rides in the query string; a batch of them is POSTed, one
    # `en=` per line in the body. Reading only the query finds the page_view and
    # calls everything after it missing.
    names = []
    for url, body in hits:
        names += parse_qs(urlparse(url).query).get("en", [])
        for line in (body or "").splitlines():
            names += parse_qs(line).get("en", [])
    print(f"{len(hits)} request(s) to Google, carrying {len(names)} event(s):")
    for n in names:
        print("  ", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
