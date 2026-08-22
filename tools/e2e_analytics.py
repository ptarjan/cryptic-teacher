#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Drive a real browser through a whole solve and prove every event arrives.

The unit tests can only show that app.js *calls* the beacon. Between that call
and a row in the report sit sendBeacon, CORS, the Worker's enum check and a KV
write, and every one of them fails silently by design — a rejected event is a
204 with no key, which looks exactly like nobody having solved anything. So the
only test worth trusting drives the live site and then looks in KV.

    tools/e2e_analytics.py            # live site, cleans up after itself
    tools/e2e_analytics.py --keep     # leave the keys it wrote

Exit 0 when every event in sync/events.js was both sent and stored.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://paultarjan.com/cryptic-teacher/"
PUZZLE = "quiptic-1394"
NS = "85f9de552ea64b229c113df624fb6ca0"


def enum_names():
    """The event names the app and Worker share, read from the one source.

    Only the frozen array counts: the prose above it names events too, and a
    test that scraped those would demand keys for words like "arrived".
    """
    src = open(os.path.join(ROOT, "sync/events.js"), encoding="utf-8").read()
    m = re.search(r"Object\.freeze\(\[(.*?)\]\)", src, re.S)
    if not m:
        raise SystemExit("sync/events.js no longer ends in Object.freeze([...])")
    return sorted(set(re.findall(r'"([a-z][a-z-]*)"', m.group(1))))


def kv_keys():
    out = subprocess.run(
        ["npx", "wrangler", "kv", "key", "list", "--namespace-id", NS, "--remote"],
        capture_output=True, text=True, cwd=os.path.join(ROOT, "sync"), timeout=180)
    if "[" not in out.stdout:
        raise SystemExit(f"wrangler gave no key list: {out.stderr[-500:]}")
    body = out.stdout[out.stdout.index("["):out.stdout.rindex("]") + 1]
    return {k["name"] for k in json.loads(body) if k["name"].startswith("e:")}


def kv_delete(names):
    """Remove the keys this run wrote, and name any it could not.

    Every key is attempted even after one fails — wrangler's token can expire
    part way through a run, and stopping at the first refusal leaves the rest
    behind with nothing but a count to find them by. A key left in KV is a solve
    that never happened, so the names go in the message, not in a log.
    """
    stuck, why = [], ""
    for n in sorted(names):
        out = subprocess.run(["npx", "wrangler", "kv", "key", "delete", n,
                             "--namespace-id", NS, "--remote"],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             cwd=os.path.join(ROOT, "sync"), timeout=120)
        if out.returncode:
            stuck.append(n)
            why = (out.stderr or out.stdout)[-400:]
    if stuck:
        raise SystemExit(f"{len(stuck)} of this test's keys are still in your numbers "
                         f"(delete them by hand, or run `npx wrangler login` and "
                         f"re-run):\n  " + "\n  ".join(stuck) + f"\n{why}")


# Wrapped before app.js runs. It calls through, so the real beacon still goes
# out; it only remembers the name and whether the browser agreed to queue it.
TAP = """
window.__ctBeacons = [];
if (navigator.sendBeacon) {
  const orig = navigator.sendBeacon.bind(navigator);
  navigator.sendBeacon = (url, data) => {
    const ok = orig(url, data);
    if (String(url).endsWith('/e')) {
      const text = typeof data === 'string' ? Promise.resolve(data) : data.text();
      window.__ctBeacons.push(text.then((name) => ({ name, ok })));
    }
    return ok;
  };
}
"""


def sent_names(page):
    return {b["name"] for b in page.evaluate("() => Promise.all(window.__ctBeacons || [])")}


def walk_ladder(page):
    """Take every rung the current clue will give up.

    A locked rung is a rendered-but-disabled button, and the spotting rungs stay
    locked until their question is answered — so answering it comes first ("tell
    me" is a legitimate answer and costs what the rung costs), and only enabled
    buttons are ever clicked.
    """
    for _ in range(16):
        tell = page.locator("#guess-tell")
        if tell.count() and tell.first.is_visible():
            tell.first.click()
            page.wait_for_timeout(250)
            continue
        btns = page.locator("#hint-next button")
        for i in range(btns.count()):
            b = btns.nth(i)
            if b.is_visible() and b.is_enabled():
                b.click()
                page.wait_for_timeout(250)
                break
        else:
            return


def solve(page):
    """Open a puzzle, work the hint ladder, then fill the grid from the answers."""
    page.goto(SITE + "?p=" + PUZZLE, wait_until="networkidle")
    page.wait_for_function("window.CRYPTIC_PUZZLES && window.CRYPTIC_PUZZLES['%s']" % PUZZLE,
                           timeout=30000)

    # Every rung, taken in whatever order the tiers allow. One clue usually
    # offers all six, but a clue whose ladder skips a rung would silently leave
    # that event unproven, so keep opening clues until all six have fired.
    hints = {n for n in enum_names() if n.startswith("hint-")}
    for i in range(4):
        page.locator("#clues-across li").nth(i).click()
        page.wait_for_timeout(400)
        walk_ladder(page)
        if hints <= sent_names(page):
            break

    for b in ("#chk-letter", "#chk-entry", "#chk-grid"):
        page.locator(b).click()
        page.wait_for_timeout(150)

    # One square at a time, each one selected by clicking it. Typing whole
    # answers into the clue list does not work as a test: the cursor skips
    # squares a crossing clue already filled, so the letters land one square
    # late, and clearing an entry first punches holes in the crossings. Either
    # way the grid ends up not-quite-right, which is indistinguishable from the
    # completion event being broken. A square is unambiguous.
    p = page.evaluate("window.CRYPTIC_PUZZLES['%s']" % PUZZLE)
    cols = p["dimensions"]["cols"]
    want = {}
    for e in p["entries"]:
        sol = (e.get("solution") or "").upper()
        for i, ch in enumerate(sol):
            x, y = e["position"]["x"], e["position"]["y"]
            want[(x + i, y) if e["direction"] == "across" else (x, y + i)] = ch
    squares = page.locator("#grid .cell")
    for (x, y), ch in sorted(want.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        squares.nth(y * cols + x).click()
        page.keyboard.type(ch)
    page.wait_for_timeout(1500)

    # half and done are the only events that need the grid to actually fill, so
    # a typing failure has to report itself here rather than as a missing key.
    return page.evaluate("""(want) => {
        const cells = [...document.querySelectorAll('#grid .cell')];
        const got = cells.map((d) => d.classList.contains('block') ? null
                                   : ((d.querySelector('.letter') || {}).textContent || ""));
        const wrong = want.filter(([i, ch]) => got[i] !== ch).map(([i, ch]) => i);
        return [want.length - wrong.length, want.length, wrong.slice(0, 8)];
    }""", [[y * cols + x, ch] for (x, y), ch in want.items()])


def visit_buckets(browser, sent):
    """The returning buckets need a browser that remembers an earlier day.

    Which bucket goes is decided entirely by the browser's own tally, so seeding
    that tally is the whole test. The solve above runs in a fresh context and so
    proves visit-new; these two prove the other arms are reachable rather than
    names nothing can ever send.
    """
    for days, expect in ((1, "visit-return"), (9, "visit-regular")):
        page = browser.new_page()          # a new context, so a fresh store
        page.add_init_script(TAP)
        page.add_init_script(
            "try { localStorage.setItem('ct:seen', JSON.stringify("
            "{last: '2020-01-01', days: %d})); } catch (e) {}" % days)
        page.goto(SITE + "?p=" + PUZZLE, wait_until="networkidle")
        page.wait_for_timeout(1500)
        got = page.evaluate("() => Promise.all(window.__ctBeacons || [])")
        sent += got
        page.close()
        if expect not in {b["name"] for b in got}:
            print(f"  a browser {days + 1} days old sent "
                  f"{sorted({b['name'] for b in got})}, not {expect}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="leave the keys behind")
    args = ap.parse_args()

    want = set(enum_names())
    print(f"events in sync/events.js ({len(want)}): {', '.join(sorted(want))}")

    before = kv_keys()
    print(f"KV already holds {len(before)} event key(s) — those are not mine")

    sent, posts = [], []
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.add_init_script(TAP)
        # The POST is what proves the beacon left the browser; its body is not
        # readable from here (a Blob reads back empty), so the name comes from
        # the tap and the wire only has to agree on the count.
        page.on("request", lambda r: posts.append(r.url)
                if r.method == "POST" and r.url.endswith("/e") else None)
        page.on("console", lambda m: print("  browser error:", m.text)
                if m.type == "error" else None)
        try:
            right, total, wrong = solve(page)
            print(f"grid correct in {right}/{total} squares"
                  + (f" — wrong at grid index {wrong}" if wrong else ""))
            sent += page.evaluate("() => Promise.all(window.__ctBeacons || [])")
            visit_buckets(browser, sent)
        finally:
            browser.close()

    refused = [b["name"] for b in sent if not b["ok"]]
    sent_set = {b["name"] for b in sent}
    print(f"\nbeacons the browser sent ({len(sent)} calls, {len(posts)} POSTs on the wire, "
          f"{len(sent_set)} distinct):")
    for s in sorted(sent_set):
        print("  sent    ", s)
    if refused:
        print("  REFUSED by sendBeacon (never left the browser):", ", ".join(sorted(set(refused))))

    after = kv_keys()
    mine = after - before
    stored = {n.split(":")[2] for n in mine if len(n.split(":")) > 2}
    for s in sorted(stored):
        print("  stored  ", s)

    missing_sent = want - sent_set
    missing_stored = sent_set - stored
    print()
    if missing_sent:
        print("NOT SENT by the browser:", ", ".join(sorted(missing_sent)))
    if missing_stored:
        print("SENT BUT NOT STORED (Worker dropped it):", ", ".join(sorted(missing_stored)))

    if not args.keep and mine:
        print(f"\ncleaning up {len(mine)} key(s) this test wrote")
        kv_delete(mine)
        left = kv_keys()
        print("KV back to", len(left), "key(s)" if len(left) != 1 else "key")

    if missing_sent or missing_stored:
        return 1
    print("\nEND TO END OK: every event was sent by the browser and stored by the Worker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
