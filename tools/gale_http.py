"""The Chrome-like browsing of Gale and its portal, shared by gale_fetch.py
(downloads) and gale_docs.py (lookups): curl_cffi's Chrome impersonation when
installed, else urllib with Chrome's headers; one cookie jar per Chrome."""

import http.cookiejar
import ssl
import urllib.error
import urllib.parse
import urllib.request

#: A current Chrome on a Mac (the one curl_cffi's impersonate="chrome" sends).
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/150.0.0.0 Safari/537.36")

#: Chrome's headers for a script's fetch() of data (an XHR), over the page ones.
XHR_HEADERS = {"Accept": "*/*", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty", "Priority": "u=1, i",
               "X-Requested-With": "XMLHttpRequest"}


#: A current Chrome's headers for a click that loads a page (what
#: curl_cffi's impersonate="chrome" sends), for the urllib stand-in.
CHROME_HEADERS = {
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
              "application/signed-exchange;v=b3;q=0.7",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Encoding": "gzip, deflate",  # urllib cannot undo br or zstd
    "Accept-Language": "en-US,en;q=0.9",
    "Priority": "u=0, i",
}


class Chrome:
    """GET as Chrome does: curl_cffi's impersonation (Chrome's TLS and HTTP/2
    fingerprint and headers) when it is installed, else urllib with Chrome's
    headers. One cookie jar. Called (url, extra headers, verify) ->
    (status, body, final url)."""

    def __init__(self, timeout=120):
        self.timeout = timeout
        try:
            from curl_cffi import requests as cffi
        except ImportError:
            cffi = None
        if cffi:
            self.cffi = cffi.Session(impersonate="chrome")
            return
        self.cffi = None
        jar = http.cookiejar.CookieJar()
        self.ops = {}
        for verify in (True, False):
            ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),
                                             urllib.request.HTTPSHandler(context=ctx))
            op.addheaders = []
            self.ops[verify] = op

    def __call__(self, url, headers, verify, timeout=None):
        timeout = timeout or self.timeout
        if self.cffi:
            # curl_cffi's errors are OSErrors, so run() counts them as errors.
            r = self.cffi.get(url, headers=headers, verify=verify, timeout=timeout)
            return r.status_code, r.content, r.url
        req = urllib.request.Request(url, headers={**CHROME_HEADERS, **headers})
        try:
            with self.ops[verify].open(req, timeout=timeout) as r:
                return r.status, unzip(r.read(), r.headers.get("Content-Encoding")), r.geturl()
        except urllib.error.HTTPError as e:
            return e.code, unzip(e.read(), e.headers.get("Content-Encoding")), url


def unzip(body, encoding):
    import zlib
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompress(body, 16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def fetch_site(referer, url):
    """Chrome's Sec-Fetch-Site for following a link on `referer` to `url`."""
    a, b = urllib.parse.urlsplit(referer), urllib.parse.urlsplit(url)
    if (a.scheme, a.netloc) == (b.scheme, b.netloc):
        return "same-origin"
    return "same-site" if _site(a.hostname) == _site(b.hostname) else "cross-site"


def _site(host):
    """The registrable part of `host`: gale.com, abresearchportal.ca."""
    return ".".join((host or "").split(".")[-2:])


def verifies(url, portal):
    """Whether to verify `url`'s certificate. The portal's chain lacks its
    intermediate (Chrome fetches it; Python cannot), so only it goes unverified."""
    return urllib.parse.urlsplit(url).hostname != urllib.parse.urlsplit(portal).hostname


def click_headers(referer, url, xhr=False):
    """The headers of following a link (or, `xhr`, a script's fetch) on page
    `referer` to `url`."""
    if not referer:
        return dict(XHR_HEADERS) if xhr else {}
    return {"Referer": referer, "Sec-Fetch-Site": fetch_site(referer, url), **(XHR_HEADERS if xhr else {})}
