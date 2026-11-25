"""One place for how this repo talks to other people's web servers.

Every fetcher used to carry its own User-Agent, timeout, sleep between
requests and retry loop, and they disagreed (Wayback was paced at 3 s in one
and 10 s in another). The HOSTS table below is the single source: a host's
User-Agent, request timeout, least gap between requests and the waits between
retries. polite_reply / polite_get / polite_bytes read it, so a fetcher that
goes through them neither sleeps between requests nor retries by hand.

Fetchers that must keep their own transport (Trove's cookie opener, the
archive.org loan session, the editions walker's threaded opener) call
policy_for(url) for the numbers and pace(url) for the gap.

Retrying: a throttled request and a missing page look the same to a walker
(both are an exception where a page should have been), and a walker reads that
as "never published". So the statuses that mean "not now" (RETRY_STATUSES), a
dropped connection, a timeout and a body that `parse` rejects with ValueError
are asked again after the host's backoff waits, Retry-After winning when the
server sends one (capped, so a silly value cannot park a run for an afternoon).
Once the waits are spent the last error propagates unchanged: HTTPError,
URLError, TimeoutError and ConnectionError reach the caller as urllib raises
them.

Adding a host: one row in HOSTS. A subdomain uses its parent's row unless it
has its own (web.archive.org beats archive.org).
"""

import http.client
import threading
import time
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit

#: Says what we are. The default, and what a host that is happy with it gets.
IDENTIFYING_UA = "Mozilla/5.0 (cryptic-teacher; personal educational use)"
#: Identifies us with a contact address; archive.org asks for one.
CONTACT_UA = "cryptic-teacher-fetcher/1.0 (cryptic-teacher@paulisageek.com)"
TIMES_FEED_UA = "Mozilla/5.0 (cryptic-teacher; +https://github.com/ptarjan/cryptic-teacher)"
#: Browser strings for the hosts that refuse an identifying one (a 403 with
#: nothing in the error naming the header). Kept at the Chrome version each
#: host has always been sent.
BROWSER_120_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
BROWSER_124_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BROWSER_128_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

RETRY_STATUSES = (429, 500, 502, 503, 504)
#: Waits between a host's attempts: one more attempt than there are waits.
DEFAULT_BACKOFF = (5, 20, 60, 180)
#: A WordPress API that is slow to recover: 30 s doubling.
SLOW_BACKOFF = (30, 60, 120)
MAX_RETRY_AFTER = 600

#: What a host with no row gets.
DEFAULTS = {"ua": IDENTIFYING_UA, "timeout": 30, "delay": 0.0, "backoff": DEFAULT_BACKOFF}

#: host -> overrides of DEFAULTS. `delay` is the least seconds between one
#: request finishing and the next starting, across every fetcher in the process.
HOSTS = {
    "thenation.com": {"ua": BROWSER_120_UA, "timeout": 40, "delay": 1.5, "backoff": (10, 30)},
    # Their robots.txt Crawl-delay: not a tuning knob.
    "fifteensquared.net": {"ua": BROWSER_128_UA, "timeout": 60, "delay": 20, "backoff": SLOW_BACKOFF},
    # Their robots.txt.
    "timesforthetimes.co.uk": {"ua": BROWSER_124_UA, "timeout": 60, "delay": 10, "backoff": SLOW_BACKOFF},
    # robots.txt sets no delay; 3 s keeps a full walk to minutes.
    "bigdave44.com": {"ua": BROWSER_124_UA, "timeout": 60, "delay": 3, "backoff": SLOW_BACKOFF},
    "puzzlesdata.telegraph.co.uk": {"ua": BROWSER_128_UA, "delay": 2.0},
    "feeds.thetimes.co.uk": {"ua": TIMES_FEED_UA, "timeout": 40, "delay": 0.5},
    "times.xwdsnitch.link": {"ua": BROWSER_128_UA, "timeout": 60, "delay": 5},
    # The Anubis cookie is tied to the User-Agent and IP: this UA must never
    # change. The cross-process gap lives in fetch_trove.Trove.pace; delay here
    # is its default.
    "trove.nla.gov.au": {"ua": BROWSER_128_UA, "timeout": 60, "delay": 1.0},
    # Somebody else's CDN (the Globe's puzzle host): a ban would take the
    # puzzle away from every future run.
    "cdn-us.amuselabs.com": {"delay": 1.0},
    "archive.org": {"ua": CONTACT_UA, "timeout": 120, "delay": 0.3},
    # Wayback throttles by IP at about 15 requests a minute.
    "web.archive.org": {"timeout": 90, "delay": 4.0},
}


class Policy(NamedTuple):
    key: str  # the HOSTS row it came from; "" for the defaults
    ua: str
    timeout: float
    delay: float
    backoff: tuple


def policy_for(url):
    """The Policy for a URL's host: its row (or its nearest parent's) over DEFAULTS."""
    labels = (urlsplit(url).hostname or "").split(".")
    for i in range(len(labels)):
        key = ".".join(labels[i:])
        if key in HOSTS:
            return Policy(key, **{**DEFAULTS, **HOSTS[key]})
    return Policy("", **DEFAULTS)


_lock = threading.Lock()
_free_at = {}  # row key -> time.monotonic() before which the host is not asked again


def pace(url):
    """Block until the host's delay since its last request is up, and claim the slot."""
    p = policy_for(url)
    with _lock:
        now = time.monotonic()
        start = max(now, _free_at.get(p.key, 0.0))
        _free_at[p.key] = start + p.delay
    if start > now:
        time.sleep(start - now)


def _done(url):
    p = policy_for(url)
    with _lock:
        _free_at[p.key] = time.monotonic() + p.delay


class Reply(NamedTuple):
    url: str  # after redirects
    headers: object
    body: bytes
    value: object  # parse(body) when a parse was given, else None


def polite_reply(url, *, parse=None, ua=None, timeout=None, backoff=None):
    """One GET as a Reply, paced and retried as the module docstring says.
    `parse(body)` runs inside the retry: a ValueError from it asks again."""
    p = policy_for(url)
    ua, timeout = ua or p.ua, timeout or p.timeout
    for wait in (p.backoff if backoff is None else backoff) + (None,):
        pace(url)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                final, headers, body = r.geturl(), r.headers, r.read()
            value = parse(body) if parse else None
            return Reply(final, headers, body, value)
        except urllib.error.HTTPError as err:
            if wait is None or err.code not in RETRY_STATUSES:
                raise
            try:
                wait = max(wait, min(float(err.headers.get("Retry-After")), MAX_RETRY_AFTER))
            except (AttributeError, TypeError, ValueError):
                pass
            print(f"  HTTP {err.code} on {url} — waiting {wait:.0f}s")
        except urllib.error.URLError as err:
            if wait is None:
                raise
            print(f"  {err.reason} on {url} — waiting {wait}s")
        except (http.client.HTTPException, ConnectionError, TimeoutError, ValueError) as err:
            # A ValueError is only a bad body when a parse was given; otherwise
            # it is a defect (a malformed URL) that asking again cannot fix.
            if wait is None or (isinstance(err, ValueError) and not parse):
                raise
            print(f"  {type(err).__name__} on {url} — waiting {wait}s")
        finally:
            _done(url)
        time.sleep(wait)


def polite_bytes(url, **kw):
    return polite_reply(url, **kw).body


def polite_get(url, *, parse=None, **kw):
    """The body as text (UTF-8), or parse(body) when `parse` is given."""
    reply = polite_reply(url, parse=parse, **kw)
    return reply.value if parse else reply.body.decode("utf-8")
