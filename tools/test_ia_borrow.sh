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

python3 - <<'PYEOF'
import json
import sys

sys.path.insert(0, "tools")
import fetch_ia_book as F

failures = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL {msg}")


def ok(msg):
    print(f"  ok   {msg}")


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

print()
if failures:
    print(f"FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("PASSED")
PYEOF
