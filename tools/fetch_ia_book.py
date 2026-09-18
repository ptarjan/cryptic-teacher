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
     A book that needs no loan (public domain) answers HTTP 400 with
     {"error": "This book is not available to borrow at this time...money"}
     wording containing "not available to borrow" — not a failure, just skip
     the loan and read straight through. Any other non-2xx here is real.
  4. POST same URL, data: action=create_token, identifier=<id>
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
  6. POST loan URL, data: action=return_loan, identifier=<id>
     Success: HTTP 200, {"success": true}.

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


def borrow(session, identifier):
    """browse_book then create_token. A book needing no loan (public domain)
    is left alone, not treated as a failure — see the module docstring."""
    data = {"action": "browse_book", "identifier": identifier}
    r = session.post(LOAN_URL, data=data, timeout=30)
    if r.status_code == 400:
        try:
            err = r.json().get("error", "")
        except ValueError:
            err = r.text
        if "not available to borrow" not in err:
            raise SystemExit(f"browse_book failed for {identifier}: {err}")
    elif not r.ok:
        raise SystemExit(f"browse_book failed for {identifier}: "
                          f"HTTP {r.status_code} {r.text[:300]}")

    data["action"] = "create_token"
    r = session.post(LOAN_URL, data=data, timeout=30)
    if "token" not in r.text:
        raise SystemExit(f"create_token failed for {identifier}: "
                          f"HTTP {r.status_code} {r.text[:300]}")


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


def fetch_full_text(session, identifier):
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
    p.add_argument("--keep-loan", action="store_true",
                    help="don't return the loan on exit (default: always return it)")
    args = p.parse_args(argv)

    creds_path = Path(os.environ.get("IA_CREDS", DEFAULT_CREDS)).expanduser()
    email, password = load_credentials(creds_path)

    args.out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(UA)

    logged_in = False
    try:
        login(session, email, password, creds_path)
        logged_in = True
        borrow(session, args.identifier)
        text = fetch_full_text(session, args.identifier)
    finally:
        # Runs on success AND on exception — a crash must not strand a
        # one-hour lock on a single-copy, no-waitlist book. Only skipped
        # when login itself never succeeded (nothing was borrowed) or the
        # caller explicitly asked to keep the loan.
        if logged_in and not args.keep_loan:
            try:
                return_loan(session, args.identifier)
            except Exception as err:
                print(f"warning: could not return loan for {args.identifier}: {err}",
                      file=sys.stderr)

    out_path = args.out / f"{args.identifier}.txt"
    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
