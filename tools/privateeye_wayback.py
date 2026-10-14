#!/usr/bin/env python3
"""Private Eye Cyclops crosswords the Eye no longer serves, from the Wayback Machine.

Usage:
  python3 tools/privateeye_wayback.py fetch        # list and download every capture
  python3 tools/privateeye_wayback.py index        # print number -> what the captures hold

The Eye's own .puz downloads (tools/fetch_privateeye.py) start at No 300
(Nov 2005) and fifteensquared's posts at Dec 2006. Before that the Eye's site
printed the current crossword as HTML text, and the Wayback Machine kept it:

  1998-2005  private-eye.co.uk/xword.htm (and /noframe/xword.htm): "EYE
             CROSSWORD 105 by Cyclops" / "No. 249", the clues, then
             "Solution to Crossword No. 104" (or "Crossword 248 winner") and
             that puzzle's answers. From about 2003 it links
             download/cyclops<N>.puz and images/grid<issue>.gif.
  2005-2012  sections.php?section_link=crossword[&issue=<issue>]: "No. 307 by
             Cyclops", the clues, then "Previous Crossword Solution".

So each capture gives one puzzle's clues and the one before's answers. The
crossword number is the issue number - 845 throughout (No 105 = issue 950,
May 1998; No 249 = issue 1094; No 307 = issue 1152).

Captures go to downloads.PRIVATE_EYE_WAYBACK/<timestamp>.html (one per
distinct digest), the CDX listing to cdx.txt beside them. They are untrusted
downloads: this only reads them as text.
"""
import argparse
import datetime
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import downloads
import provenance

TOOL = "tools/privateeye_wayback.py"
DIR = downloads.PRIVATE_EYE_WAYBACK
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
ISSUE_OFFSET = 845
MAX_NODES = 4_000_000
# (url, matchType) of every page that printed the crossword, and the .puz/.gif
# files the 2003-2005 page linked.
# The CDX key sorts a query's arguments ("issue=1165&section_link=crossword"),
# so sections.php is listed whole and filtered on the original URL.
PAGES = [("private-eye.co.uk/xword.htm", "exact", None),
         ("private-eye.co.uk/noframe/xword.htm", "exact", None),
         ("private-eye.co.uk/frames/xword.htm", "exact", None),
         ("private-eye.co.uk/sections.php", "prefix", "original:.*section_link=crossword.*")]
FILES = [("private-eye.co.uk/download/", "prefix", "original:.*puz"),
         ("private-eye.co.uk/images/grid", "prefix", None)]


def get(url, tries=4):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=120).read()
        except Exception as e:  # Wayback drops connections under load
            err = e
            time.sleep(5 * (i + 1))
    raise err


def cdx(url, match, flt=None, to="2013"):
    # No collapse=digest: on these urlkeys it dropped most captures (sections.php:
    # 4 of 132); listing() dedupes by digest instead.
    q = urllib.parse.urlencode({"url": url, "matchType": match, "to": to, "filter": "statuscode:200",
                                "fl": "timestamp,original,digest"})
    if flt:
        q += "&" + urllib.parse.urlencode({"filter": flt})
    return [line.split() for line in get("http://web.archive.org/cdx/search/cdx?" + q).decode().splitlines()]


def listing():
    rows = []
    for url, match, flt in PAGES + FILES:
        rows += [r for r in cdx(url, match, flt) if len(r) == 3]
    seen, out = set(), []
    for ts, orig, digest in rows:
        if digest not in seen:
            seen.add(digest)
            out.append((ts, orig, digest))
    return out


def local_name(ts, orig):
    tail = orig.rsplit("/", 1)[-1]
    if tail.endswith((".puz", ".gif")):
        return f"files/{ts}_{tail}"
    return f"{ts}.html"


def fetch():
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "files").mkdir(exist_ok=True)
    rows = listing()
    (DIR / "cdx.txt").write_text("".join(" ".join(r) + "\n" for r in rows))
    got = 0
    for ts, orig, _digest in rows:
        path = DIR / local_name(ts, orig)
        if path.exists():
            continue
        try:
            path.write_bytes(get(f"http://web.archive.org/web/{ts}id_/{orig}"))
            got += 1
        except Exception as e:
            print(f"{ts} {orig}: {e}", file=sys.stderr)
        time.sleep(1)
    print(f"{len(rows)} captures listed, {got} downloaded to {DIR}")


# ---------- reading a capture ----------

NUMBER = re.compile(r"EYE CROSSWORD\s+(\d{1,3})\b|\bNo\.\s*(\d{1,3})\s+(?=by Cyclops|'|ACROSS)", re.I)
SOLUTION = re.compile(r"Solution to Crossword No\.?\s*(\d{1,3})|Crossword\s+(\d{1,3})\s+winner"
                      r"|(Previous Crossword Solution)", re.I)
TAIL = re.compile(r"\bEntries to\b|Back to Private Eye|£\s?\d|\bThis site features\b"
                  r"|Arrived here unexpectedly|Send your entries", re.I)
ENUM = r"\((?:\d[\d,\-\s'.]*|see \d{1,2}[^)]{0,12})\)"
SEE_TAIL = r"See \d{1,2}\s*(?:ac|dn|across|down)?\.?"
CLUE = re.compile(r"(?:^|(?<=\s))(\d{1,2}(?:\s*/\s*\d{1,2}(?:\s*(?:ac|dn)\.?)?)*)\s+(.*?)\s*(" + ENUM + "|"
                  + SEE_TAIL + r")(?=\s+\d{1,2}\s*[/\s(A-Za-z\"'£]|\s*$)", re.I)
ANSWER = re.compile(r"(\d{1,2}(?:/\d{1,2})*)\s+([^\d]+?)(?=\s+\d{1,2}[\s/]|\s*\.?\s*$)")


def text_of(raw):
    t = raw.decode("cp1252", "replace")
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def split_dirs(part):
    """'ACROSS ... DOWN ...' -> (across text, down text) or None."""
    m = re.search(r"\bACROSS\b:?(.*?)\bDOWN\b:?(.*)$", part, re.I | re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else None


def clue_rows(part):
    """light_spec rows ({"number", "clue", "enumeration"}) of one direction's
    text, or None if any text is left between or after the clues."""
    rows, pos = [], 0
    for m in CLUE.finditer(part):
        if part[pos:m.start()].strip():
            return None
        pos = m.end()
        nums = re.findall(r"\d{1,2}", m.group(1))
        text, tail = m.group(2).strip(), m.group(3)
        see = re.match(r"\(?\s*see (\d{1,2})", tail, re.I)
        if see and not text:
            rows.append({"number": nums[0], "clue": f"See {see.group(1)}", "enumeration": None})
            continue
        if see:
            return None
        rows.append({"number": ",".join(nums), "clue": text,
                     "enumeration": re.sub(r"\s+", "", tail[1:-1]).replace("–", "-")})
    if part[pos:].strip() or not rows:
        return None
    return rows


def answer_rows(part, direction):
    """fetch_privateeye.solve_from_rows rows [(key, direction, LETTERS)]."""
    out = []
    for key, words in ANSWER.findall(part):
        if re.match(r"\s*\(?see\b", words, re.I):
            continue
        letters = re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", words).upper())
        if letters:
            out.append((key, direction, letters))
    return out


def read_capture(raw):
    """{"number", "rows": {"across", "down"} | None, "prev", "answers": [...] | None}."""
    t = text_of(raw)
    m = NUMBER.search(t)
    if not m:
        return None
    num = int(m.group(1) or m.group(2))
    body = t[m.end():]
    sol = SOLUTION.search(body)
    clues = body[:sol.start()] if sol else (TAIL.split(body)[0])
    out = {"number": num, "rows": None, "prev": None, "answers": None}
    dirs = split_dirs(clues)
    if dirs:
        a, d = clue_rows(dirs[0]), clue_rows(dirs[1])
        if a and d:
            out["rows"] = {"across": a, "down": d}
    if sol:
        out["prev"] = int(sol.group(1) or sol.group(2)) if not sol.group(3) else num - 1
        rest = body[sol.end():]
        rest = re.sub(r"^\s*Winner:?\s*[^A-Z]*[A-Z.\s'\-]+?(?=ACROSS)", "", rest)
        rest = TAIL.split(rest)[0]
        dirs = split_dirs(rest)
        if dirs:
            out["answers"] = answer_rows(dirs[0], "across") + answer_rows(dirs[1], "down")
    return out


def index():
    """{number: {"clues": [(ts, rows)], "answers": [(ts, rows)], "puz": path|None}}."""
    got = {}
    for path in sorted(DIR.glob("*.html")):
        try:
            cap = read_capture(path.read_bytes())
        except Exception as e:  # one odd capture never stops the rest
            print(f"{path.name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if not cap:
            continue
        ts = path.stem
        if cap["rows"]:
            got.setdefault(cap["number"], {}).setdefault("clues", []).append((ts, cap["rows"]))
        if cap["answers"]:
            got.setdefault(cap["prev"], {}).setdefault("answers", []).append((ts, cap["answers"]))
    for path in sorted((DIR / "files").glob("*_cyclops*.puz")):
        n = int(re.search(r"cyclops(\d+)\.puz", path.name).group(1))
        got.setdefault(n, {})["puz"] = str(path)
    return got


def capture_url(ts):
    """The Wayback URL a capture was read from."""
    for line in (DIR / "cdx.txt").read_text().splitlines():
        t, orig, _ = line.split()
        if t == ts:
            return f"https://web.archive.org/web/{ts}/{orig}"
    return f"https://web.archive.org/web/{ts}/http://www.private-eye.co.uk/xword.htm"


# ---------- building a puzzle ----------

def build(num, held):
    """(puzzle, None) or (None, why not) for Cyclops `num` from its captures."""
    import fetch_privateeye as fp
    clues = held.get("clues") or []
    if held.get("puz") and clues:
        try:  # a truncated capture of the .puz (184) leaves the page's clues
            fp.parse_puz(Path(held["puz"]).read_bytes())
        except ValueError as e:
            print(f"  cyclops-{num}: the .puz does not read ({e}); using the page")
            held = {**held, "puz": None}
    if held.get("puz"):
        puz = fp.parse_puz(Path(held["puz"]).read_bytes())
        puzzle = fp.convert(num, puz)
        url = capture_url(Path(held["puz"]).name.split("_")[0])
        how = "the Eye's own .puz, from the Wayback Machine"
    elif clues:
        ts, rows = clues[-1]
        puzzle, why = from_rows(num, rows)
        if puzzle is None:
            return None, why
        url = capture_url(ts)
        how = "the Eye's crossword page, from the Wayback Machine"
    else:
        return None, "no capture prints its clues"
    puzzle["source"] = {"publisher": "Private Eye", "url": url, "retrievedFrom": "web.archive.org",
                        "acquiredBy": TOOL, "acquiredOn": datetime.date.today().isoformat(),
                        **({} if held.get("puz") else {"gridOrigin": "reconstructed"})}
    if not puzzle.get("date"):
        day = fp.fetch_cover_date(num + ISSUE_OFFSET)
        puzzle["date"] = day.isoformat() if day else None
    for ts, rows in held.get("answers") or []:
        solutions, problem = fp.solve_from_rows(puzzle, rows)
        if solutions:
            for e in puzzle["entries"]:
                e["solution"] = solutions[f"{e['number']}-{e['direction']}"]
            # The Eye's own printed solution: the published origin, no detail.
            puzzle = provenance.drop_solution_detail(puzzle)
            print(f"  cyclops-{num}: answers from the solution printed in capture {ts}")
            break
        print(f"  cyclops-{num}: the answers in capture {ts} do not fit: {problem}")
    print(f"  cyclops-{num}: {how}")
    return puzzle, None


def from_rows(num, rows):
    """A puzzle with no answers from light_spec rows, its grid rebuilt from
    the clue numbers and enumerations (as tools/fetch_nation.py does)."""
    import light_spec
    from clues_only import entries_from_grid
    import reconstruct_grid as rg
    from fetch_nation import linked_groups
    from fetch_puzzle import has_words
    from file_penguin_puzzle import separators
    from groups import entry_id
    from normalise_linked_enumerations import normalise_record, resolve_groups
    import enumeration
    across, down, _notes, damage = light_spec.build_spec(rows)
    if damage:
        return None, "clue list damaged: " + "; ".join(damage)
    for lg in across + down:
        if lg[2].startswith("linked"):
            lg[1] = None
    groups = linked_groups(rows, across, down)
    spec = [(lg[0], d, lg[1]) for d, lights in (("across", across), ("down", down)) for lg in lights]
    # Every Cyclops is 15x15; the linked lights' free lengths need more search
    # than the Nation's budget.
    grid, why = rg.unique_grid(spec, cols=15, rows=15, max_nodes=MAX_NODES, groups=groups)
    if grid is None:
        return None, f"grid did not rebuild: {why}"
    entries, problems = entries_from_grid(grid, across, down)
    if problems:
        return None, "; ".join(problems)
    for e in entries:
        e["clue"] = (e["clue"] or "").strip()
    normalise_record({"puzzle": {"entries": entries}, "fill": {}})
    grouped = resolve_groups(entries)
    by_id = {entry_id(e): e for e in entries}
    seps = {}
    for e in entries:
        if not e.get("enumeration"):
            continue
        ids = grouped.get(entry_id(e), [entry_id(e)])
        if ids[0] != entry_id(e):
            return None, f"{entry_id(e)} carries an enumeration but is a continuation"
        try:
            seps.update(separators(ids, by_id, e["enumeration"]))
        except SystemExit as err:
            return None, str(err)
    out = []
    for e in entries:
        printed = e.pop("enumeration", None)
        line = f"{e['clue']} ({printed})" if printed else e["clue"]
        e["clue"] = enumeration.clue(line, separators=seps.get(entry_id(e)),
                                     missing=not has_words(enumeration.split(line)[0]))
        if grouped.get(entry_id(e), [None])[0] == entry_id(e):
            e["group"] = list(grouped[entry_id(e)])
        e["solution"] = None
        out.append(e)
    return {"id": f"cyclops-{num}", "number": num, "series": "cyclops",
            "name": f"Private Eye Cyclops crossword No {num}", "setter": "Cyclops",
            "date": None, "dimensions": {"cols": len(grid[0]), "rows": len(grid)},
            "entries": out}, None


def file(numbers=None, dry_run=False):
    from fetch_puzzle import puzzle_path, write_puzzle_file
    import puzzle_paths
    got = index()
    filed, why = [], {}
    for num in sorted(numbers or got):
        if num not in got or (not numbers and puzzle_paths.find(f"cyclops-{num}")):
            continue
        try:
            puzzle, reason = build(num, got[num])
        except Exception as e:
            puzzle, reason = None, f"{type(e).__name__}: {e}"
        if puzzle is None:
            why[num] = reason
            print(f"  cyclops-{num}: refused: {reason}")
            continue
        if dry_run:
            print(json.dumps(puzzle)[:400])
        else:
            try:
                write_puzzle_file(puzzle_path("cyclops", num), puzzle, generator=TOOL)
            except Exception as e:
                why[num] = f"write refused: {type(e).__name__}: {e}"
                print(f"  cyclops-{num}: {why[num]}")
                continue
        filed.append(num)
    print(f"filed {len(filed)}: {filed}")
    if not dry_run:
        refused = json.loads(REFUSED.read_text()) if REFUSED.exists() else {}
        for n in filed:
            refused.pop(str(n), None)
        refused.update({str(n): r for n, r in why.items()})
        REFUSED.write_text(json.dumps(refused, indent=1, sort_keys=True) + "\n")
    return filed, why


# ---------- coverage (tools/coverage.py) ----------

REFUSED = DIR / "refused.json"
# The numbers below the Eye's own .puz downloads (No 300) and the gaps after it,
# checked 2026-10-13 against every Wayback capture of xword.htm, noframe/ and
# frames/xword.htm, sections.php?section_link=crossword[&issue=N], download/*.puz
# and images/grid*.gif up to 2013, and against fifteensquared (Dec 2006 on).
LOST_CAUSES = {
    "no-capture": "the Wayback Machine holds no capture of the Eye's crossword page "
                  "or .puz while it was current, and no blog posted it: only a print "
                  "copy (or the Eye's paid archive) files it",
    "answers-only": "a capture holds only the solution printed in the next issue, "
                    "not the clues: only a print copy files it",
    "not-read": "a capture prints its clues and no filing run has tried it: "
                "privateeye_wayback.py file N",
    "refused": "a capture prints its clues and the filer refused it "
               "(privateeye_wayback/refused.json says why)",
}
LOST_FIRST, LOST_LAST = 1, 459


def lost():
    """{number: LOST_CAUSES key} for every Cyclops 1-459 this source could speak to.
    Filed numbers are the ledger's to skip."""
    got = index() if DIR.exists() else {}
    refused = json.loads(REFUSED.read_text()) if REFUSED.exists() else {}
    out = {}
    for n in range(LOST_FIRST, LOST_LAST + 1):
        h = got.get(n, {})
        if h.get("clues") or h.get("puz"):
            out[n] = "refused" if str(n) in refused else "not-read"
        elif h.get("answers"):
            out[n] = "answers-only"
        else:
            out[n] = "no-capture"
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["fetch", "index", "file"])
    ap.add_argument("numbers", nargs="*", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "fetch":
        fetch()
    elif args.cmd == "file":
        file(args.numbers, args.dry_run)
    else:
        for n, h in sorted(index().items()):
            print(n, "clues" if h.get("clues") else "-", "answers" if h.get("answers") else "-",
                  "puz" if h.get("puz") else "-")


if __name__ == "__main__":
    main(sys.argv[1:])
