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

WHY A LOAN AT ALL. <id>_djvu.txt at
https://archive.org/download/<id>/<id>_djvu.txt is the OCR text we want. On
both target identifiers, unborrowed, it returns HTTP 401 (verified
2026-09-18 — not the 403 first guessed; archive.org's real answer for "this
book is lending-restricted and you don't hold a loan" is 401). Borrowing is
the only way to flip that to 200.

ENDPOINT SEQUENCE (verified against archive.org live 2026-09-18, and cross-
checked against github.com/MiniGlome/Archive.org-Downloader, a working
downloader that exercises the same flow):

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
     clean {"success": true} shape here).
  5. GET the _djvu.txt URL with the now-authenticated, now-loaned session.
  6. POST same loan URL, data: action=return_loan, identifier=<id>
     Success: HTTP 200, {"success": true}.

Steps 1-2 (csrf + login, including the bad-credentials error shape) and the
401-before-loan fact were run for real against archive.org while writing
this. Steps 3-5 (borrow, token, fetch) and step 6 (return) are UNTESTED —
there was no working account yet — implemented from the reference source
above and archive.org's documented response shapes, not from a live run.
Run this for real the moment credentials land and fix whatever step 3-6
actually does differently.

The loan is always returned on the way out, success or exception, unless
--keep-loan is given — these are one-hour, one-copy, no-waitlist loans on
both target books, so a crash that leaves one held locks the next borrow
out for the full hour.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

UA = {"User-Agent": "Mozilla/5.0 (cryptic-teacher; personal educational use)"}
CSRF_URL = "https://archive.org/services/csrf-token"
LOGIN_URL = "https://archive.org/services/account/login/"
LOAN_URL = "https://archive.org/services/loans/loan/"
DJVU_URL = "https://archive.org/download/{id}/{id}_djvu.txt"
DEFAULT_CREDS = "~/.config/ia/creds"
DEFAULT_OUT = Path("/tmp/cryptic-teacher-ia-books")


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


def fetch_djvu_text(session, identifier):
    url = DJVU_URL.format(id=identifier)
    r = session.get(url, timeout=60)
    if not r.ok:
        raise SystemExit(f"{identifier}_djvu.txt still HTTP {r.status_code} after "
                          "borrowing — the loan may not have granted full-text access")
    return r.text


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
        text = fetch_djvu_text(session, args.identifier)
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
