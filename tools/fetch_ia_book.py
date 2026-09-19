#!/usr/bin/env python3
"""Borrow a lending-restricted archive.org book, save its OCR text, return the loan.

Usage:
  python3 tools/fetch_ia_book.py newpenguinbkguar0000perk
  python3 tools/fetch_ia_book.py cluetoourlives800000balf --out /tmp/somewhere
  python3 tools/fetch_ia_book.py newpenguinbkguar0000perk --keep-loan

Writes <out>/<identifier>.txt (default: DEFAULT_OUT below, never the repo —
this is a fetched artifact, reproducible on demand, not something to commit).

CREDENTIALS. Read from the file at $IA_CREDS (default ~/.config/ia/creds),
never hardcoded and never printed. Either shape works:
    someone@example.com
    hunter2
or:
    {"email": "someone@example.com", "password": "hunter2"}
A missing file is a hard stop naming the exact path it looked at, because
"see the log" doesn't tell you which of $IA_CREDS or the default you need to
fix.

WHY A LOAN AT ALL, AND WHY NOT _djvu.txt. <id>_djvu.txt at
https://archive.org/download/<id>/<id>_djvu.txt is the plain-text OCR dump
you'd want, and it's what a public-domain item serves — but for a lending
book it stays HTTP 401 even with an active loan held (verified live
2026-09-18: logged in, browse_book + create_token both succeeded, loan
cookies present, and the request still 401'd). archive.org simply does not
generate/serve that whole-book text file for lending items; a loan does not
unlock it. What a loan *does* unlock is the BookReader's own per-page OCR
endpoint (see FULL-TEXT ENDPOINT below), which is loan-gated (HTTP 403
"Item not available" with no session/loan, HTTP 200 with hidden text once
logged in and holding the loan) and is the only route this script found
that returns real text for a book you don't own outright.

ENDPOINT SEQUENCE (verified against archive.org live 2026-09-18, and cross-
checked against github.com/MiniGlome/Archive.org-Downloader, a working
downloader that exercises the same login/loan flow):

  1. GET  https://archive.org/services/csrf-token
     -> {"success": true, "value": {"token": "..."}} — token feeds both the
     header and the body of the next request.
  2. POST https://archive.org/services/account/login/
     headers: Content-Type: application/x-www-form-urlencoded,
              X-Csrf-Token: <token>
     body (JSON-encoded despite the content-type above — that's what the
     reference implementation sends and archive.org accepts):
       {"username": <email>, "password": <password>, "t": <token>}
     Success: {"success": true, ...}. Bad credentials: HTTP 400,
     {"success": false, "value": "bad_login", "error": "..."} — confirmed
     live with a throwaway bad login 2026-09-18. Session cookies from here
     carry the login through every later request.
  3. POST https://archive.org/services/loans/loan/  data: action=browse_book,
     identifier=<id>
     HTTP 400 {"error": "This book is not available to borrow at this time.
     Please try again later."} is AMBIGUOUS and must never be read as
     "public domain, no loan needed" on its own — see THE BORROW TRAP below.
     Any other non-2xx here is real.
  3b. THE BORROW TRAP. archive.org returns that one byte-identical 400 body
     for two different conditions: (a) an item that needs no loan at all, and
     (b) a lending item whose every copy is checked out right now. Verified
     live 2026-09-18 with one logged-in session: sketchbookofgeof00irvi (no
     loan needed) and dailytelegraphcr0000dail (single copy out until
     04:37 UTC) both answered with exactly
     {"error":"This book is not available to borrow at this time. Please try
     again later."} — same status, same string, nothing in the response
     separating them. Reading it as (a) sends a temporarily-unavailable book
     down the no-loan path, where it dies two steps later at create_token
     with {"error":"You do not currently have this book borrowed."}: a true
     sentence about a cause that is not the real one.
     WHAT ACTUALLY SEPARATES THEM is a second, cheap, login-free call to the
     same endpoint: action=availability, whose "lending_status" object says
     it outright —
         no loan needed : is_lendable=false, is_readable=true,
                          max_lendable_copies=0
         all copies out : is_lendable=true, is_readable=false,
                          max_browsable_copies=1, available_browsable_copies=0,
                          active_browses=1, next_browse_expiration=<when a
                          copy frees up>
     is_lendable is the discriminator; the copy counts and
     next_browse_expiration are what make the "retry later" message say WHEN.
     lending_status() makes that call and _classify_refused_browse() turns it
     into one of: proceed without a loan, or a SystemExit naming the real
     condition. If the availability call itself gives no lending_status, the
     code says it cannot tell rather than picking the friendlier side.
  4. POST same URL, data: action=create_token, identifier=<id>
     ONLY when a loan was actually granted. Without one it answers HTTP 400
     "You do not currently have this book borrowed." — which is how the
     borrow trap used to surface.
     Success has the literal substring "token" in the response body (the
     reference implementation's own success check; the response isn't a
     clean {"success": true} shape here). This sets loan-<id> and
     br-loan-<id> cookies on the session — those, not the token value
     itself, are what later requests need.
  5. FULL-TEXT ENDPOINT (this is the part that took experimentation — see
     fetch_full_text()'s docstring for the full story):
     a. GET https://archive.org/metadata/<id> (public, no login needed) for
        "server", "dir", and metadata.imagecount — dir + "/" + <id> +
        "_djvu.xml" is the page path the next call wants, and imagecount
        is how many pages to walk.
     b. For page in 1..imagecount: GET
        https://<server>/BookReader/BookReaderGetTextWrapper.php
          ?path=<urlencoded page path>&mode=djvu_xml&page=<page>
        -> djvu.xml for that one page: an <OBJECT><HIDDENTEXT>...</OBJECT>
        tree of PAGECOLUMN/REGION/PARAGRAPH/LINE/WORD elements, each WORD
        carrying its OCR text plus pixel coordinates and a confidence
        score. Cover/blank pages have no <HIDDENTEXT> at all — normal, not
        an error. This is the same per-page endpoint the in-browser reader
        uses for text selection (found via the "textSelection" plugin URL
        template in BookReaderJSIA.php's response, which is where this
        endpoint was discovered — see fetch_full_text() docstring).
     Concatenated per-page text, pages joined with form-feed (\x0c), is
     what this script writes.
  6. POST loan URL, data: action=return_loan, identifier=<id>, but only when
     step 3 actually granted a loan. Success: HTTP 200, {"success": true}.
     (It answers {"success": true} for an item you never borrowed as well, so
     its reply is no evidence a loan existed — borrow()'s return value is.)

Every step above, including the full-text route, was run for real against
archive.org for newpenguinbkguar0000perk (150 pages) on 2026-09-18: login,
browse_book, create_token, all 150 pages of BookReaderGetTextWrapper.php,
and return_loan all succeeded, and the output file contains real book text.

The loan is always returned on the way out, success or exception, unless
--keep-loan is given — these are one-hour, one-copy, no-waitlist loans on
both target books, so a crash that leaves one held locks the next borrow
out for the full hour.
"""

import argparse
import contextlib
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
CSRF_URL = "https://archive.org/services/csrf-token"
LOGIN_URL = "https://archive.org/services/account/login/"
LOAN_URL = "https://archive.org/services/loans/loan/"
METADATA_URL = "https://archive.org/metadata/{id}"
PAGE_TEXT_URL = "https://{server}/BookReader/BookReaderGetTextWrapper.php"
DEFAULT_CREDS = "~/.config/ia/creds"
DEFAULT_OUT = Path("/tmp/cryptic-teacher-ia-books")
# The one refusal string archive.org sends for two unrelated conditions; on
# its own it means only "no loan for you right now", never "no loan needed".
AMBIGUOUS_BORROW_ERROR = "not available to borrow"
PAGE_FETCH_DELAY_SECONDS = 0.3


def load_credentials(path):
    """(email, password) from a two-line file or a JSON object with those
    keys. Raises SystemExit naming the exact path on anything wrong, because
    the fix is always "put credentials there", never "check the log"."""
    if not path.exists():
        raise SystemExit(
            f"No archive.org credentials at {path} (from $IA_CREDS or its "
            f"default ~/.config/ia/creds). Create it as `email\\npassword` "
            f'or {{"email": ..., "password": ...}} and try again.'
        )
    raw = path.read_text().strip()
    try:
        obj = json.loads(raw)
        return obj["email"], obj["password"]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    lines = raw.splitlines()
    if len(lines) >= 2 and lines[0].strip() and lines[1].strip():
        return lines[0].strip(), lines[1].strip()
    raise SystemExit(
        f"{path} isn't `email\\npassword` or a JSON object with "
        '"email"/"password" keys — fix its contents.'
    )


def login(session, email, password, creds_path):
    """Raises SystemExit (never leaking the password into it) on bad
    credentials or any response shape this hasn't seen before."""
    r = session.get(CSRF_URL, timeout=30)
    r.raise_for_status()
    token = r.json()["value"]["token"]
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Csrf-Token": token}
    body = {"username": email, "password": password, "t": token}
    r = session.post(LOGIN_URL, headers=headers, data=json.dumps(body), timeout=30)
    try:
        result = r.json()
    except ValueError:
        raise SystemExit(f"archive.org login returned no JSON (HTTP {r.status_code}) — "
                          f"endpoint or response shape may have changed: {r.text[:300]}")
    if result.get("success"):
        return
    if result.get("value") == "bad_login":
        raise SystemExit(f"archive.org rejected the credentials in {creds_path} — "
                          "check the email/password there.")
    raise SystemExit(f"archive.org login failed: {result}")


def lending_status(session, identifier):
    """The "lending_status" object from action=availability, or None if the
    response carries no usable one. This is the only call that tells a book
    needing no loan apart from a lending book with every copy out — the
    browse_book refusal cannot (module docstring, THE BORROW TRAP). It needs
    no login and takes no loan."""
    r = session.post(LOAN_URL,
                     data={"action": "availability", "identifier": identifier},
                     timeout=30)
    try:
        status = r.json()["lending_status"]
    except (ValueError, KeyError, TypeError):
        return None
    return status if isinstance(status, dict) else None


def _classify_refused_browse(session, identifier):
    """browse_book refused with the ambiguous string. Return normally if the
    item genuinely needs no loan; otherwise raise SystemExit naming the real
    condition. Never resolves the ambiguity by assuming: when availability
    won't say, this says it won't say."""
    status = lending_status(session, identifier)
    if status is None:
        raise SystemExit(
            f"{identifier}: archive.org refused the loan with the message it "
            f'sends BOTH for "this book needs no loan" and for "every copy is '
            f'checked out" ("{AMBIGUOUS_BORROW_ERROR}"), and its availability '
            f"endpoint returned no lending_status to tell the two apart — so "
            f"which one this is cannot be determined, and guessing either way "
            f"would be wrong. Retry in a few minutes; if it persists, the "
            f"availability API has changed shape and lending_status() needs "
            f"updating."
        )

    if not status.get("is_lendable"):
        if status.get("is_readable"):
            return  # genuinely no loan required: read it straight through
        raise SystemExit(
            f"{identifier}: archive.org lends no copies of this item "
            f"(is_lendable=false) and will not let this account read it "
            f"either (is_readable=false), so there is no loan to wait for — "
            f"it needs different access, not a retry."
        )

    free = status.get("available_browsable_copies")
    if free:
        raise SystemExit(
            f"{identifier}: archive.org refused the loan yet reports {free} "
            f"browsable copy/copies free — a copy was almost certainly taken "
            f"between the two calls. Retry in a minute."
        )
    until = status.get("next_browse_expiration")
    raise SystemExit(
        f"{identifier}: all copies checked out, retry later — archive.org "
        f"lends {status.get('max_browsable_copies')} copy/copies of this book "
        f"and {status.get('active_browses')} are on loan right now"
        + (f", the next one free at {until} UTC" if until else "")
        + ". This is NOT a public-domain item and NOT a credentials problem; "
        "nothing here will work until a copy comes back."
    )


def borrow(session, identifier):
    """browse_book then create_token. Returns True if a loan is now held (and
    must be returned), False if the item needs none. A refusal is never read
    as "needs no loan" on its own — see the module docstring, THE BORROW
    TRAP."""
    data = {"action": "browse_book", "identifier": identifier}
    r = session.post(LOAN_URL, data=data, timeout=30)
    if r.status_code == 400:
        try:
            err = r.json().get("error", "")
        except ValueError:
            err = r.text
        if AMBIGUOUS_BORROW_ERROR not in err:
            raise SystemExit(f"browse_book failed for {identifier}: {err}")
        _classify_refused_browse(session, identifier)  # raises unless free
        # No loan needed, so create_token has nothing to sign and would answer
        # "You do not currently have this book borrowed."
        return False
    elif not r.ok:
        raise SystemExit(f"browse_book failed for {identifier}: "
                          f"HTTP {r.status_code} {r.text[:300]}")

    data["action"] = "create_token"
    r = session.post(LOAN_URL, data=data, timeout=30)
    if "token" not in r.text:
        raise SystemExit(f"create_token failed for {identifier}: "
                          f"HTTP {r.status_code} {r.text[:300]}")
    return True


@contextlib.contextmanager
def borrowed(identifier, creds_path=None, keep_loan=False):
    """A logged-in session with the loan already taken, yielded to the caller,
    and RETURNED ON THE WAY OUT however the block ends — normally, by
    exception, or by KeyboardInterrupt. That is why this is a context manager
    and not a pair of calls: these are one-hour, one-copy, no-waitlist loans,
    so a path that forgets the return locks the book for the next hour, and
    "remember to call return_loan" is not a guarantee. Any caller that wants
    text out of a lending item goes through here.

    Yields the session whether or not a loan was needed: an item that needs
    none is not an error (borrow() says which), and its text is fetched the
    same way. Only a loan actually taken is returned.
    """
    creds_path = creds_path or Path(
        os.environ.get("IA_CREDS", DEFAULT_CREDS)).expanduser()
    email, password = load_credentials(creds_path)
    session = requests.Session()
    session.headers.update(UA)
    login(session, email, password, creds_path)
    loan_held = False
    try:
        loan_held = borrow(session, identifier)
        yield session
    finally:
        if loan_held and not keep_loan:
            try:
                return_loan(session, identifier)
            except Exception as err:
                print(f"warning: could not return loan for {identifier}: {err}",
                      file=sys.stderr)


def return_loan(session, identifier):
    """Best-effort: called from a finally block, so a failure here is
    reported, not raised past cleanup."""
    data = {"action": "return_loan", "identifier": identifier}
    r = session.post(LOAN_URL, data=data, timeout=30)
    try:
        ok = r.status_code == 200 and r.json().get("success")
    except ValueError:
        ok = False
    if not ok:
        raise RuntimeError(f"return_loan for {identifier}: HTTP {r.status_code} {r.text[:300]}")
    print(f"returned loan for {identifier}")


def _page_text_from_djvu_xml(xml_bytes):
    """<HIDDENTEXT> holds nested PAGECOLUMN/REGION/PARAGRAPH/LINE/WORD
    elements with per-word OCR + coordinates. Pages with no text layer
    (covers, blanks) simply have no HIDDENTEXT and yield ''. The last few
    leaves of newpenguinbkguar0000perk (148-150 of 150) come back HTTP 200
    with a genuinely empty body rather than an XML shell — same "no text
    here" case, not an error, so an empty/unparseable body yields '' too
    instead of raising."""
    if not xml_bytes.strip():
        return ""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    hidden = root.find("HIDDENTEXT")
    if hidden is None:
        return ""
    paragraphs = []
    for region in hidden.iter("REGION"):
        for para in region.findall("PARAGRAPH"):
            lines = [
                " ".join(word.text or "" for word in line.findall("WORD"))
                for line in para.findall("LINE")
            ]
            text = "\n".join(line for line in lines if line)
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)


def fetch_full_text(session, identifier, max_pages=None):
    """djvu.txt (see module docstring) stays HTTP 401 even with an active
    loan — archive.org doesn't serve the plain-text dump for lending books
    at all. What the loan *does* unlock is BookReaderGetTextWrapper.php,
    the same per-page OCR (djvu.xml with word coordinates) the in-browser
    reader uses for text selection: confirmed HTTP 403 "Item not available"
    with no session, HTTP 200 with hidden text once logged in and holding
    the loan (verified live 2026-09-18). There is no whole-book endpoint,
    so this walks every page and concatenates.
    """
    meta = session.get(METADATA_URL.format(id=identifier), timeout=30)
    meta.raise_for_status()
    meta_json = meta.json()
    server = meta_json.get("server")
    item_dir = meta_json.get("dir")
    page_count = meta_json.get("metadata", {}).get("imagecount")
    if not server or not item_dir or not page_count:
        raise SystemExit(
            f"metadata for {identifier} is missing server/dir/imagecount "
            f"(got server={server!r} dir={item_dir!r} imagecount={page_count!r}) "
            "— can't locate per-page OCR without them"
        )
    page_count = int(page_count)
    if max_pages is not None:
        # A sample, for checking that the route works without walking 150
        # pages of somebody else's server to prove it.
        page_count = min(page_count, max_pages)
    book_path = f"{item_dir}/{identifier}_djvu.xml"
    url = PAGE_TEXT_URL.format(server=server)

    pages = []
    for page in range(1, page_count + 1):
        # book_path must be passed raw, NOT pre-urlencoded: requests'
        # params= urlencodes values itself, so pre-quoting here would
        # double-encode the slashes (%2F -> %252F) and archive.org 403s
        # the mangled path as "Item not available" — indistinguishable
        # from a real auth failure without diffing the outgoing r.url.
        r = session.get(url, params={"path": book_path, "mode": "djvu_xml", "page": page},
                         timeout=30)
        if not r.ok:
            raise SystemExit(
                f"page {page}/{page_count} of {identifier} failed: "
                f"HTTP {r.status_code} {r.text[:300]} — the loan may have expired "
                "mid-fetch, or archive.org is rate-limiting; rerun once the loan "
                "cools down rather than retrying immediately"
            )
        pages.append(_page_text_from_djvu_xml(r.content))
        if page < page_count:
            time.sleep(PAGE_FETCH_DELAY_SECONDS)

    return "\x0c".join(pages)


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("identifier", help="archive.org item id, e.g. newpenguinbkguar0000perk")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"output directory (default: {DEFAULT_OUT})")
    p.add_argument("--max-pages", type=int,
                    help="stop after N pages. A SAMPLE, for checking the route "
                         "works without walking the whole book; it is written "
                         "under a .sample-Np.txt name so nothing mistakes it "
                         "for the complete text")
    p.add_argument("--keep-loan", action="store_true",
                    help="don't return the loan on exit (default: always return it)")
    args = p.parse_args(argv)

    creds_path = Path(os.environ.get("IA_CREDS", DEFAULT_CREDS)).expanduser()

    args.out.mkdir(parents=True, exist_ok=True)

    # The return is the context manager's job, on every path out of the block.
    with borrowed(args.identifier, creds_path, args.keep_loan) as session:
        text = fetch_full_text(session, args.identifier, args.max_pages)

    # A sample is never written under the whole-book name. Everything
    # downstream — tools/acquire_book.py most of all — treats
    # <out>/<id>.txt as THE book, and a truncated file sitting there would
    # be read as a complete one and silently acquire half a book.
    if args.max_pages is None:
        out_path = args.out / f"{args.identifier}.txt"
        note = ""
    else:
        out_path = args.out / f"{args.identifier}.sample-{args.max_pages}p.txt"
        note = f" — SAMPLE of the first {args.max_pages} pages, not the book"
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path} ({len(text)} chars){note}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
