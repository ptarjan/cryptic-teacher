#!/bin/bash
# Does tools/fetch_ia_book.py still tell "needs no loan" apart from
# "every copy is checked out"?
#
#     bash tools/test_ia_borrow.sh
#
# archive.org answers browse_book with ONE byte-identical HTTP 400 body for
# both conditions (recorded live 2026-09-18 from sketchbookofgeof00irvi and
# dailytelegraphcr0000dail — see AMBIGUOUS_BODY below, used for both fixtures
# here precisely so they cannot drift apart and let a string test look like it
# works). Anything that decides between them from that body alone is guessing,
# and guessing "public domain" sends a temporarily-unavailable book down the
# no-loan path to die at create_token with "You do not currently have this
# book borrowed" — a true sentence naming the wrong cause, an hour of retries
# spent on the wrong problem.
#
# So this gates the behaviour, not the wording of any one message: the
# discriminator must be the action=availability call, the all-copies-out case
# must name itself and must not reach create_token, and the no-loan case must
# not take or return a loan it never had.
#
# Offline by construction: a stub session answers from the recorded payloads,
# so it runs in CI and costs archive.org nothing.
set -u
cd "$(dirname "$0")/.."

# Every check below reads or writes the loan ledger. Point it at a scratch
# file: a test that cleaned up the machine's real outstanding loans would be
# returning books somebody is reading.
LEDGER_DIR=$(mktemp -d)
trap 'rm -rf "$LEDGER_DIR"' EXIT
export IA_LOAN_LEDGER="$LEDGER_DIR/ia-loans.json"

python3 - <<'PYEOF'
import json
import sys
import types

sys.path.insert(0, "tools")
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    # fetch_ia_book.py needs requests only to BUILD a session. Every session
    # in this file is a stub, so a placeholder import keeps these checks
    # RUNNING on a runner with no third-party packages — CI installs none —
    # rather than skipping, which is the same as not having them.
    sys.modules["requests"] = types.ModuleType("requests")
import fetch_ia_book as F

failures = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL {msg}")


def ok(msg):
    print(f"  ok   {msg}")


def check(label, got, want):
    if got == want:
        ok(f"{label}: {got!r}")
    else:
        fail(f"{label}: got {got!r}, wanted {want!r}")


# The one string archive.org sends for both conditions, recorded live.
AMBIGUOUS_BODY = json.dumps(
    {"error": "This book is not available to borrow at this time. "
              "Please try again later."})

# lending_status payloads as archive.org actually returned them, trimmed to
# the keys this code reads.
ALL_COPIES_OUT = {           # dailytelegraphcr0000dail, 2026-09-18
    "is_lendable": True, "is_readable": False,
    "max_lendable_copies": 1, "available_lendable_copies": 0,
    "max_browsable_copies": 1, "available_browsable_copies": 0,
    "active_browses": 1, "next_browse_expiration": "2026-09-19 04:37:46",
    "available_to_browse": False,
}
NO_LOAN_NEEDED = {           # sketchbookofgeof00irvi, 2026-09-18
    "is_lendable": False, "is_readable": True,
    "max_lendable_copies": 0, "available_lendable_copies": 0,
    "max_browsable_copies": 0, "available_browsable_copies": 0,
    "active_browses": 0, "next_browse_expiration": None,
    "available_to_browse": False,
}
NOT_READABLE_EITHER = dict(NO_LOAN_NEEDED, is_readable=False)
COPY_FREED_BETWEEN_CALLS = dict(ALL_COPIES_OUT, available_browsable_copies=1)


class Response:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.ok = 200 <= status_code < 300

    def json(self):
        return json.loads(self.text)


class StubSession:
    """Answers the loan endpoint from a per-action script and records the
    order of actions, which is itself part of what is under test."""

    def __init__(self, browse, availability=None, create_token=None):
        self.browse = browse
        self.availability = availability
        self.create_token = create_token or Response(
            200, json.dumps({"token": "stub-token"}))
        self.calls = []

    def post(self, url, data=None, timeout=None):
        action = data["action"]
        self.calls.append(action)
        if action == "browse_book":
            return self.browse
        if action == "availability":
            if self.availability is None:
                raise AssertionError("availability not scripted for this case")
            return self.availability
        if action == "create_token":
            return self.create_token
        if action == "return_loan":
            return Response(200, json.dumps({"success": True}))
        raise AssertionError(f"unexpected action {action!r}")


def availability_response(status):
    return Response(200, json.dumps({"status": "OK", "lending_status": status}))


refused = Response(400, AMBIGUOUS_BODY)

# --------------------------------------------------------------- case 1
# All copies out. The regression: this used to be read as public domain.
print("case 1: every copy checked out")
s = StubSession(browse=refused, availability=availability_response(ALL_COPIES_OUT))
try:
    result = F.borrow(s, "dailytelegraphcr0000dail")
    fail(f"borrow() returned {result!r} instead of refusing — a book whose "
         f"copies are all out was read as freely readable")
except SystemExit as e:
    msg = str(e)
    if "all copies checked out, retry later" not in msg:
        fail(f"the error does not name the real condition: {msg!r}")
    elif "2026-09-19 04:37:46" not in msg:
        fail("the error does not say when a copy frees up, which is the only "
             f"thing the caller can act on: {msg!r}")
    else:
        ok("refuses, names 'all copies checked out, retry later', says when")
    if "see the log" in msg.lower():
        fail(f"the error defers to a log instead of saying it: {msg!r}")
    # The two diagnoses an operator would otherwise waste the hour on are
    # ruled out in the message itself, not merely left unmentioned.
    for ruled_out in ("NOT a public-domain item", "NOT a credentials problem"):
        if ruled_out not in msg:
            fail(f"the error does not rule out the wrong diagnosis "
                 f"{ruled_out!r}: {msg!r}")
    if "create_token" in s.calls:
        fail("reached create_token without a loan — that is where the old bug "
             "surfaced as 'You do not currently have this book borrowed'")
    else:
        ok("stops before create_token")
    if "availability" not in s.calls:
        fail("decided without calling action=availability — the refusal body "
             "alone cannot tell the two cases apart")
    else:
        ok("decided from action=availability, not from the refusal string")

# --------------------------------------------------------------- case 2
# Genuinely no loan required. Same body, opposite outcome.
print("case 2: item needs no loan")
s = StubSession(browse=Response(400, AMBIGUOUS_BODY),
                availability=availability_response(NO_LOAN_NEEDED))
try:
    result = F.borrow(s, "sketchbookofgeof00irvi")
    if result is not False:
        fail(f"borrow() returned {result!r}; a no-loan item must report False "
             "so the caller does not try to return a loan it never took")
    elif "create_token" in s.calls or "return_loan" in s.calls:
        fail(f"took loan actions for an item needing none: {s.calls}")
    else:
        ok("proceeds without a loan, returns False, no create_token")
except SystemExit as e:
    fail(f"refused an item that needs no loan: {e}")

# --------------------------------------------------------------- case 3
# The two fixtures above must stay indistinguishable by their body alone,
# or this test would pass while the code went back to sniffing the string.
print("case 3: the refusal body really is identical in both cases")
if AMBIGUOUS_BODY != json.dumps(
        {"error": "This book is not available to borrow at this time. "
                  "Please try again later."}):
    fail("the recorded body drifted")
else:
    ok("one recorded body drives both cases; only availability separates them")

# --------------------------------------------------------------- case 4
# A normal, granted loan still works and reports itself as held.
print("case 4: a loan is granted")
s = StubSession(browse=Response(200, json.dumps({"success": True})))
if F.borrow(s, "newpenguinbkguar0000perk") is not True:
    fail("a granted loan must report True so main() returns it on the way out")
elif s.calls != ["browse_book", "create_token"]:
    fail(f"unexpected call sequence for a granted loan: {s.calls}")
else:
    ok("browse_book then create_token, reports the loan held")

# --------------------------------------------------------------- case 5
# Availability won't say. Honest ambiguity beats a friendly guess.
print("case 5: availability returns no lending_status")
for label, payload in (("no lending_status key", Response(200, json.dumps({"status": "OK"}))),
                       ("not JSON at all", Response(200, "<html>503</html>"))):
    s = StubSession(browse=Response(400, AMBIGUOUS_BODY), availability=payload)
    try:
        result = F.borrow(s, "someidentifier0000xxxx")
        fail(f"{label}: returned {result!r} — with nothing to decide on, "
             "proceeding is a guess")
    except SystemExit as e:
        msg = str(e)
        if "all copies checked out" in msg:
            fail(f"{label}: claimed copies are out without evidence: {msg!r}")
        elif "cannot be determined" not in msg:
            fail(f"{label}: does not admit the ambiguity: {msg!r}")
        else:
            ok(f"{label}: says it cannot tell, picks neither side")

# --------------------------------------------------------------- case 6
# Neither lendable nor readable: a third condition, not "free to read".
print("case 6: not lendable and not readable either")
s = StubSession(browse=Response(400, AMBIGUOUS_BODY),
                availability=availability_response(NOT_READABLE_EITHER))
try:
    result = F.borrow(s, "restricted0000xxxx")
    fail(f"returned {result!r} for an item this account cannot read")
except SystemExit as e:
    if "is_readable=false" not in str(e):
        fail(f"does not name the restriction: {e}")
    else:
        ok("names the restriction instead of promising a retry will fix it")

# --------------------------------------------------------------- case 7
# A copy freed up between the two calls: transient, and said so.
print("case 7: a copy shows free after the refusal")
s = StubSession(browse=Response(400, AMBIGUOUS_BODY),
                availability=availability_response(COPY_FREED_BETWEEN_CALLS))
try:
    result = F.borrow(s, "dailytelegraphcr0000dail")
    fail(f"returned {result!r} without a loan on a lendable item")
except SystemExit as e:
    if "Retry in a minute" not in str(e):
        fail(f"does not report the race as transient: {e}")
    else:
        ok("reports the race, does not call it public domain")

# --------------------------------------------------------------- case 8
# A refusal that is NOT the ambiguous one is still a plain failure.
print("case 8: some other browse_book error")
s = StubSession(browse=Response(400, json.dumps({"error": "Item is dark."})))
try:
    F.borrow(s, "darkitem0000xxxx")
    fail("a non-ambiguous browse_book error was swallowed")
except SystemExit as e:
    if "Item is dark." not in str(e):
        fail(f"lost the server's own reason: {e}")
    elif "availability" in s.calls:
        fail("spent an availability call on an error that was never ambiguous")
    else:
        ok("passes the server's reason straight through")

# --------------------------------------------------------------- case 9
# The loan comes back however the block ends. This is the property that
# matters most: these are one-hour, single-copy, no-waitlist loans, so a path
# that skips the return locks the book out for the next hour, and every
# caller now gets the loan through this one context manager.
print("case 9: borrowed() returns the loan on every way out")
returned = []
real = (F.load_credentials, F.login, F.borrow, F.return_loan, F.requests)
F.load_credentials = lambda path: ("someone@example.com", "hunter2")
F.login = lambda *a, **k: None
F.return_loan = lambda session, identifier: returned.append(identifier)
F.requests = types.SimpleNamespace(
    Session=lambda: types.SimpleNamespace(headers={}, post=None))
try:
    F.borrow = lambda session, identifier: True

    with F.borrowed("normalexit0000xxxx"):
        pass
    check("normal exit returns the loan", returned, ["normalexit0000xxxx"])

    returned.clear()
    try:
        with F.borrowed("raised0000xxxx"):
            raise RuntimeError("the read blew up half way through")
    except RuntimeError:
        pass
    check("an exception still returns the loan", returned, ["raised0000xxxx"])

    returned.clear()
    try:
        with F.borrowed("interrupted0000xxxx"):
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    check("a Ctrl-C still returns the loan", returned, ["interrupted0000xxxx"])

    returned.clear()
    with F.borrowed("keptloan0000xxxx", keep_loan=True):
        pass
    check("--keep-loan keeps it", returned, [])

    # An item needing no loan must not have one "returned": archive.org
    # answers {"success": true} to a return for a book you never had, so a
    # spurious call looks like it worked and teaches nobody anything.
    returned.clear()
    F.borrow = lambda session, identifier: False
    with F.borrowed("noloanneeded0000xxxx"):
        pass
    check("no loan taken, none returned", returned, [])
finally:
    (F.load_credentials, F.login, F.borrow, F.return_loan, F.requests) = real

# -------------------------------------------------------------- case 10
# tools/acquire_book.py runs the borrow for the whole pipeline, so the two
# files have to agree about where borrowed text lands, and acquire_book has
# to stay importable on a runner with no third-party packages — which is the
# runner CI uses, and tools/test_acquire_book.sh imports it there.
print("case 10: acquire_book's borrow wiring")
import acquire_book as A

check("both files agree where borrowed text is cached",
      A.FETCHED_TEXT_DIR, F.DEFAULT_OUT)

path, how, status = A.fetch_text("someidentifier0000xxxx", override="/nonexistent/x.txt")
check("a missing --text is a stop, not a borrow", status, "text-not-public")

real_restriction = A.item_restriction
A.item_restriction = lambda identifier: ("lending", "; a lending item")
try:
    path, how, status = A.fetch_text("lending0000xxxx", allow_borrow=False)
    if status != "text-not-public" or "no loan was taken" not in how:
        fail(f"--no-borrow must stop rather than borrow: {status} / {how}")
    else:
        ok("--no-borrow stops on a lending item without taking a loan")
finally:
    A.item_restriction = real_restriction

# -------------------------------------------------------------- case 11
# The account-level refusal. It is not about the identifier, so it must not
# arrive as the same exception every per-book refusal uses: a driver looping
# over a book list has to be able to tell "this book failed" from "every
# remaining book will fail", which is the difference between one refusal and
# twenty-four identical ones.
print("case 11: the account has hit its lending limit")
LENDING_LIMIT_BODY = json.dumps(
    {"error": "Your account has hit a lending limit. Please try again later "
              "or contact info@archive.org."})
LIMIT_AVAILABILITY = {           # live shape 2026-09-19: a free copy, still refused
    "is_lendable": True, "is_readable": False,
    "max_browsable_copies": 1, "available_browsable_copies": 1,
    "active_browses": 0, "available_to_browse": True,
    "user_loan_count": 0, "user_at_max_loans": False,
    "user_has_browsed": False, "user_loan_record": [],
}
s = StubSession(browse=Response(400, LENDING_LIMIT_BODY),
                availability=availability_response(LIMIT_AVAILABILITY))
try:
    result = F.borrow(s, "isbn_9780330451789")
    fail(f"returned {result!r} for a lending-limit refusal")
except F.LendingLimitReached as e:
    msg = str(e)
    ok("raises LendingLimitReached, not the generic per-book refusal")
    if "create_token" in s.calls:
        fail("reached create_token without a loan")
    for wanted, why in (
            ("user_loan_count=0", "does not report how many loans the account holds"),
            ("user_at_max_loans=False", "does not report whether the concurrency cap is the binding one"),
            ("loans this machine took and has not returned: none",
             "does not report this machine's own outstanding loans"),
            ("not loans HELD", "does not say that returning loans need not clear it"),
            ("stop here", "does not tell the caller to stop rather than try the next book")):
        if wanted not in msg:
            fail(f"{why}: {msg!r}")
    else:
        ok("names the live counters, the outstanding loans, and says stop")
except SystemExit as e:
    fail(f"raised a plain SystemExit, indistinguishable from a per-book "
         f"refusal: {e}")

# The generic refusal must NOT be upgraded: only the lending-limit string is.
s = StubSession(browse=Response(400, json.dumps({"error": "Item is dark."})))
try:
    F.borrow(s, "darkitem0000xxxx")
    fail("a plain error was swallowed")
except F.LendingLimitReached:
    fail("an unrelated refusal was reported as a lending limit")
except SystemExit:
    ok("an unrelated refusal stays a plain per-book refusal")

# -------------------------------------------------------------- case 12
# The startup reconcile. borrowed()'s finally clause cannot run when the
# process is killed by a signal, so the loan is returned by the NEXT run
# instead — but only after archive.org confirms the account still holds it,
# because return_loan answers {"success": true} for a book never borrowed and
# would otherwise let the reconcile report returns it never made.
print("case 12: the startup reconcile returns what a killed run left out")


class ReconcileSession:
    def __init__(self, held, refuse_return=()):
        self.held = set(held)
        self.refuse_return = set(refuse_return)
        self.returned = []
        self.asked = []

    def post(self, url, data=None, timeout=None):
        action, ident = data["action"], data["identifier"]
        if action == "availability":
            self.asked.append(ident)
            return availability_response(
                {"user_has_browsed": ident in self.held, "user_loan_record": []})
        if action == "return_loan":
            if ident in self.refuse_return:
                return Response(500, "nope")
            self.returned.append(ident)
            return Response(200, json.dumps({"success": True}))
        raise AssertionError(f"unexpected action {action!r}")


F._write_ledger({"leaked0000xxxx": "2026-09-19T14:55:00Z",
                 "expired0000xxxx": "2026-09-19T09:00:00Z",
                 "working0000xxxx": "2026-09-19T20:00:00Z"})
s = ReconcileSession(held={"leaked0000xxxx", "working0000xxxx"})
got = F.reconcile_loans(s, keep=("working0000xxxx",), log=lambda m: None)
check("returns the loan a killed run left out", got, ["leaked0000xxxx"])
check("never touches the book this run is working on",
      "working0000xxxx" in s.asked or "working0000xxxx" in s.returned, False)
check("drops an entry whose loan already expired, without claiming a return",
      "expired0000xxxx" in s.returned, False)
check("the ledger is left holding only the in-flight book",
      sorted(F.read_ledger()), ["working0000xxxx"])

# A return archive.org refuses must leave the entry, or the next run forgets
# the one loan still out there.
F._write_ledger({"stubborn0000xxxx": "2026-09-19T14:55:00Z"})
s = ReconcileSession(held={"stubborn0000xxxx"}, refuse_return={"stubborn0000xxxx"})
got = F.reconcile_loans(s, log=lambda m: None)
check("a refused return is not reported as returned", got, [])
check("a refused return keeps its ledger entry for the next run",
      sorted(F.read_ledger()), ["stubborn0000xxxx"])
F._write_ledger({})

# -------------------------------------------------------------- case 13
# The ledger entry has to exist BEFORE the caller can be killed holding the
# loan, and has to survive being killed: written whole, never half.
print("case 13: the ledger records the loan before the block runs")
seen_during_block = []
real = (F.load_credentials, F.login, F.borrow, F.return_loan, F.requests,
        F.reconcile_loans)
F.load_credentials = lambda path: ("someone@example.com", "hunter2")
F.login = lambda *a, **k: None
F.return_loan = lambda session, identifier: None
F.reconcile_loans = lambda *a, **k: []
F.requests = types.SimpleNamespace(
    Session=lambda: types.SimpleNamespace(headers={}, post=None))
try:
    F.borrow = lambda session, identifier: True
    with F.borrowed("inflight0000xxxx"):
        seen_during_block.append(sorted(F.read_ledger()))
    check("the loan is on disk while the block runs",
          seen_during_block, [["inflight0000xxxx"]])
    check("and gone once it is confirmed returned", sorted(F.read_ledger()), [])

    # --keep-loan hands ownership of the return to the caller, so it must not
    # be ledgered: a later run would otherwise reconcile away a loan somebody
    # is deliberately holding open.
    with F.borrowed("kept0000xxxx", keep_loan=True):
        seen_during_block.append(sorted(F.read_ledger()))
    check("--keep-loan is not ledgered", sorted(F.read_ledger()), [])
finally:
    (F.load_credentials, F.login, F.borrow, F.return_loan, F.requests,
     F.reconcile_loans) = real

# -------------------------------------------------------------- case 14
# acquire_book.py is what the 24-book driver runs, so the account-level
# refusal has to survive the trip through it as its own status and its own
# exit code. Sharing exit 1 with every per-book failure is what let a driver
# burn 24 books in 18 minutes on one refusal.
print("case 14: acquire_book reports the lending limit apart")
check("acquire_book has a dedicated exit code", A.EXIT_LENDING_LIMIT, 3)


class LimitModule:
    LendingLimitReached = F.LendingLimitReached
    DEFAULT_CREDS = F.DEFAULT_CREDS

    @staticmethod
    def load_credentials(path):
        return ("someone@example.com", "hunter2")

    @staticmethod
    def borrowed(identifier):
        raise F.LendingLimitReached(f"{identifier}: the account is over its "
                                     f"lending limit, stop here")


sys.modules["fetch_ia_book"] = LimitModule
try:
    path, how, status = A.borrow_text("isbn_9780330451789")
    check("status is its own, not borrow-refused", status, "lending-limit")
    if "stop here" not in how:
        fail(f"the account-level reason was lost on the way through: {how!r}")
    else:
        ok("carries the reason through to the report")
finally:
    sys.modules["fetch_ia_book"] = F

print()
if failures:
    print(f"FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("PASSED")
PYEOF
